"""Bundle 可靠批次的创建、恢复与完成。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...domain.entities.bundle import Bundle
from ...domain.entities.content_types import LayoutFragment
from ...domain.entities.delivery import DeliveryBatchDraft, DeliveryOwner
from ...domain.entities.push_history import PushHistory
from ...domain.repositories.bundle_repository import BundleRepository
from ...domain.repositories.delivery_repository import DeliveryRepository
from ...domain.repositories.feed_repository import FeedRepository
from ...domain.repositories.user_repository import UserRepository
from ...infrastructure.templates.rendering import CardTemplateService
from ...infrastructure.utils import get_logger
from .bundle_document_service import BundleDocumentHandlerResult, BundleDocumentService
from .content_handlers import EntryContentContext
from .notification_dispatcher import NotificationDispatcher
from .output_orchestrator import OutputOrchestrator

logger = get_logger()


class BundleBatchDeliveryError(RuntimeError):
    """Bundle 无法创建可靠投递批次。"""


@dataclass(frozen=True, slots=True)
class BundleBatchDeliveryResult:
    """一次 Bundle owner 投递推进的结果。"""

    batch_id: int | None
    ready_to_confirm: bool


@dataclass(frozen=True, slots=True)
class BundleSendPayload:
    """Bundle 标准输出在批次创建时固化的有效发送参数。"""

    content: str
    media_urls: list[str] | None
    media_items: list[tuple[str, str]] | None
    layout: list[LayoutFragment] | None
    send_mode: int | None
    style: int
    notify: bool


class BundleBatchDeliveryService:
    """把 Bundle inbox 固化成唯一批次，再交给公共输出编排器。"""

    def __init__(
        self,
        *,
        delivery_repository: DeliveryRepository,
        bundle_repository: BundleRepository,
        feed_repository: FeedRepository,
        template_repository: Any,
        template_service: CardTemplateService,
        document_service: BundleDocumentService,
        output_orchestrator: OutputOrchestrator,
        notification_dispatcher: NotificationDispatcher | None = None,
        user_repository: UserRepository | None = None,
        history_entry_limit: int = 0,
        max_retries: int = 3,
    ) -> None:
        self._delivery_repository = delivery_repository
        self._bundle_repository = bundle_repository
        self._feed_repository = feed_repository
        self._template_repository = template_repository
        self._template_service = template_service
        self._document_service = document_service
        self._output_orchestrator = output_orchestrator
        self._notification_dispatcher = notification_dispatcher
        self._user_repository = user_repository
        self._history_entry_limit = max(0, history_entry_limit)
        self._max_retries = max(0, max_retries)
        self._owner_locks: dict[int, asyncio.Lock] = {}

    async def deliver(
        self,
        bundle_id: int,
        *,
        retry_failed: bool = False,
        force_retry: bool = False,
    ) -> BundleBatchDeliveryResult:
        """创建或恢复一个 Bundle 批次，并推进当前可执行输出。"""
        lock = self._owner_locks.setdefault(bundle_id, asyncio.Lock())
        async with lock:
            owner = DeliveryOwner(owner_type="bundle", owner_id=bundle_id)
            batch = await self._delivery_repository.get_pending_batch(owner)
            if batch is not None:
                batch = await self._delivery_repository.reconcile_batch(batch.id)
                if batch.status in {"confirmed", "discarded"}:
                    return BundleBatchDeliveryResult(
                        batch_id=batch.id,
                        ready_to_confirm=batch.status == "confirmed",
                    )
            else:
                batch = await self._create_batch(owner)
                if batch is None:
                    return BundleBatchDeliveryResult(None, False)

            if force_retry:
                orchestration = await self._output_orchestrator.run(
                    batch,
                    retry_failed=retry_failed,
                    force_retry=True,
                )
            else:
                orchestration = await self._output_orchestrator.run(
                    batch,
                    retry_failed=retry_failed,
                )
            if orchestration.ready_to_confirm:
                await self._delivery_repository.confirm_batch(batch.id)
            return BundleBatchDeliveryResult(
                batch_id=batch.id,
                ready_to_confirm=orchestration.ready_to_confirm,
            )

    async def retry(self, bundle_id: int) -> BundleBatchDeliveryResult:
        """人工重试当前 Bundle 批次，允许重试次数已耗尽的失败输出。"""
        return await self.deliver(
            bundle_id,
            retry_failed=True,
            force_retry=True,
        )

    async def retry_active_batches(self) -> None:
        """推进所有启用 Bundle 的 pending 批次或未认领 backlog。"""
        bundles = await self._bundle_repository.get_all_active()
        for bundle in bundles:
            if bundle.id is None:
                continue
            try:
                await self.deliver(bundle.id, retry_failed=True)
            except Exception:
                # owner 级边界必须隔离，异常仍保留在日志中供排查。
                logger.exception("推进 Bundle 批次失败: bundle=%s", bundle.id)

    async def discard(
        self,
        bundle_id: int,
        *,
        reason: str = "Bundle 批次已显式丢弃",
    ) -> Any | None:
        """显式丢弃当前 pending 批次，并释放其已认领 inbox。"""
        lock = self._owner_locks.setdefault(bundle_id, asyncio.Lock())
        async with lock:
            owner = DeliveryOwner(owner_type="bundle", owner_id=bundle_id)
            batch = await self._delivery_repository.get_pending_batch(owner)
            if batch is None:
                return None
            return await self._output_orchestrator.discard(batch, reason=reason)

    async def _create_batch(self, owner: DeliveryOwner) -> Any | None:
        bundle = await self._bundle_repository.get_by_id(owner.owner_id)
        if bundle is None or bundle.id is None:
            raise BundleBatchDeliveryError("Bundle 不存在")
        if bundle.state != 1:
            raise BundleBatchDeliveryError("Bundle 未启用")
        if not bundle.target_sessions:
            raise BundleBatchDeliveryError("Bundle 缺少目标会话")

        inbox = await self._delivery_repository.list_inbox_items(
            owner,
            claimed=False,
        )
        if not inbox:
            return None

        members = await self._bundle_repository.list_members(bundle.id)
        if not members:
            raise BundleBatchDeliveryError("Bundle 缺少成员")
        feeds: dict[int, Any] = {}
        for member in members:
            feed = await self._feed_repository.get_by_id(member.feed_id)
            if feed is None or feed.id is None:
                raise BundleBatchDeliveryError(
                    f"Bundle 成员 Feed 不存在: {member.feed_id}"
                )
            feeds[member.feed_id] = feed

        template_snapshot: dict[str, Any] | None = None
        if bundle.send_card:
            template_snapshot = await self._load_template_snapshot(bundle, feeds)

        document_result = await self._document_service.build_and_process(
            bundle=bundle,
            members=members,
            feeds=feeds,
            inbox_items=inbox,
            history_entry_limit=self._history_entry_limit,
            session_id=bundle.target_sessions[0],
        )
        consumption_keys = set(document_result.document.consumption_item_keys)
        claimed_item_ids = [
            item.id for item in inbox if item.item_key in consumption_keys
        ]
        if not claimed_item_ids:
            raise BundleBatchDeliveryError("Bundle 文档没有可消费的 inbox 条目")
        document_snapshot = self._document_snapshot(document_result)
        send_payload = await self._prepare_send_payload(
            bundle=bundle,
            members=members,
            feeds=feeds,
            document_result=document_result,
            document_snapshot=document_snapshot,
        )
        outputs = self._build_outputs(
            bundle=bundle,
            members=members,
            document_result=document_result,
            document_snapshot=document_snapshot,
            template_snapshot=template_snapshot,
            feeds=feeds,
            send_payload=send_payload,
        )
        draft = DeliveryBatchDraft(
            target_sessions=list(bundle.target_sessions),
            config_snapshot={
                "send_card": bundle.send_card,
                "card_send_original_content": bundle.card_send_original_content,
                "history_entry_limit": self._history_entry_limit,
                "send_mode": bundle.send_mode,
                "style": bundle.style,
                "effective_send_mode": send_payload.send_mode,
                "effective_style": send_payload.style,
                "notify": send_payload.notify,
            },
            template_snapshot=template_snapshot,
            document_snapshot=document_snapshot,
        )
        return await self._delivery_repository.claim_batch(
            owner,
            draft,
            outputs,
            item_ids=claimed_item_ids,
        )

    async def _load_template_snapshot(
        self,
        bundle: Bundle,
        feeds: dict[int, Any],
    ) -> dict[str, Any]:
        if not bundle.template_id:
            raise BundleBatchDeliveryError("Bundle 卡片缺少模板")
        package = await asyncio.to_thread(
            self._template_repository.get,
            bundle.template_id,
        )
        if package is None:
            raise BundleBatchDeliveryError("Bundle 卡片模板不存在")
        feed_urls = [feeds[feed_id].link for feed_id in feeds]
        if (
            package.metadata.id != bundle.template_id
            or not package.metadata.matches_owner(
                owner_type="bundle",
                feed_urls=feed_urls,
            )
        ):
            raise BundleBatchDeliveryError("卡片模板与 Bundle 不匹配")
        snapshot = await asyncio.to_thread(
            self._template_service.snapshot,
            package,
        )
        return snapshot.model_dump(mode="json")

    @staticmethod
    def _document_snapshot(result: BundleDocumentHandlerResult) -> dict[str, Any]:
        snapshot = result.to_snapshot()
        snapshot["rendered_at"] = datetime.now(timezone.utc).isoformat()
        return snapshot

    def _build_outputs(
        self,
        *,
        bundle: Bundle,
        members: list[Any],
        document_result: BundleDocumentHandlerResult,
        document_snapshot: dict[str, Any],
        template_snapshot: dict[str, Any] | None,
        feeds: dict[int, Any],
        send_payload: BundleSendPayload,
    ) -> list[PushHistory]:
        outputs: list[PushHistory] = []
        allowed = document_result.allowed and send_payload.notify
        reason = document_result.reason
        if document_result.allowed and not send_payload.notify:
            reason = "notify disabled"
        for target_session in bundle.target_sessions:
            if bundle.send_card:
                outputs.append(
                    self._history(
                        bundle=bundle,
                        members=members,
                        target_session=target_session,
                        output_kind="card",
                        output_order=0,
                        status="waiting" if allowed else "skipped",
                        document_snapshot=document_snapshot,
                        template_snapshot=template_snapshot,
                        feeds=feeds,
                        handler_trace=document_result.trace,
                        send_payload=send_payload,
                        reason=reason,
                    )
                )
                if bundle.card_send_original_content:
                    outputs.append(
                        self._history(
                            bundle=bundle,
                            members=members,
                            target_session=target_session,
                            output_kind="standard",
                            output_order=1,
                            status="waiting" if allowed else "skipped",
                            document_snapshot=document_snapshot,
                            template_snapshot=None,
                            feeds=feeds,
                            handler_trace=document_result.trace,
                            send_payload=send_payload,
                            reason=reason,
                        )
                    )
            else:
                outputs.append(
                    self._history(
                        bundle=bundle,
                        members=members,
                        target_session=target_session,
                        output_kind="standard",
                        output_order=0,
                        status="waiting" if allowed else "skipped",
                        document_snapshot=document_snapshot,
                        template_snapshot=None,
                        feeds=feeds,
                        handler_trace=document_result.trace,
                        send_payload=send_payload,
                        reason=reason,
                    )
                )
        return outputs

    def _history(
        self,
        *,
        bundle: Bundle,
        members: list[Any],
        target_session: str,
        output_kind: str,
        output_order: int,
        status: str,
        document_snapshot: dict[str, Any],
        template_snapshot: dict[str, Any] | None,
        feeds: dict[int, Any],
        handler_trace: tuple[dict[str, Any], ...],
        send_payload: BundleSendPayload,
        reason: str,
    ) -> PushHistory:
        document = document_snapshot.get("document") or {}
        rss_xml = str(document.get("rss_xml") or "")
        source_context: dict[str, Any] = {
            "document_snapshot": document_snapshot,
            "bundle": {"id": bundle.id, "name": bundle.name},
            "feeds": [
                {
                    "id": feed.id,
                    "title": feed.title,
                    "link": feed.link,
                    "position": member.position,
                }
                for member in sorted(members, key=lambda item: item.position)
                for feed in [feeds[member.feed_id]]
            ],
            "send": {
                "content": send_payload.content,
                "media_urls": list(send_payload.media_urls or []) or None,
                "media_items": self._media_snapshot(send_payload.media_items),
                "layout": self._layout_snapshot(send_payload.layout),
                "send_mode": send_payload.send_mode,
                "style": send_payload.style,
            },
        }
        if template_snapshot is not None:
            source_context["template_snapshot"] = template_snapshot
        history = PushHistory(
            bundle_id=bundle.id,
            user_id=bundle.user_id,
            source_type="bundle",
            source_key=f"bundle:{bundle.id}",
            content=send_payload.content,
            raw_xml=rss_xml or None,
            media_urls=list(send_payload.media_urls or []) or None,
            handler_trace=[dict(item) for item in handler_trace] or None,
            output_kind=output_kind,
            output_order=output_order,
            source_context=source_context,
            feed_title=bundle.name,
            feed_link=self._feed_link(members, feeds),
            platform_name=self._platform_name(target_session),
            target_session=target_session,
            status=status,
            max_retries=0 if status == "skipped" else self._max_retries,
            fail_reason=reason if status == "skipped" else None,
        )
        if status == "skipped":
            history.mark_skipped(reason)
        return history

    async def _prepare_send_payload(
        self,
        *,
        bundle: Bundle,
        members: list[Any],
        feeds: dict[int, Any],
        document_result: BundleDocumentHandlerResult,
        document_snapshot: dict[str, Any],
    ) -> BundleSendPayload:
        document = document_snapshot.get("document") or {}
        text = str(document.get("text") or "")
        rss_xml = str(document.get("rss_xml") or "")
        media_items = self._media_items(document_snapshot)
        feed_link = self._feed_link(members, feeds)
        if self._notification_dispatcher is None:
            return BundleSendPayload(
                content=text,
                media_urls=[url for _kind, url in media_items] or None,
                media_items=media_items or None,
                layout=[],
                send_mode=bundle.send_mode,
                style=bundle.style,
                notify=True,
            )

        user = (
            await self._user_repository.get_by_id(bundle.user_id)
            if self._user_repository is not None
            else None
        )
        prepared = await self._notification_dispatcher.prepare_subscription_entry(
            subscription=bundle,
            user=user,
            entry=EntryContentContext(
                title=bundle.name,
                summary=text,
                content=text,
                link=feed_link,
                author="",
                feed_title=bundle.name,
                feed_link=feed_link,
                raw_xml=rss_xml,
                media_urls=tuple(url for _kind, url in media_items),
                media_items=tuple(media_items),
            ),
            handler_trace=[dict(item) for item in document_result.trace] or None,
        )
        effective_options = (
            self._notification_dispatcher._resolve_effective_push_options(
                bundle,
                user,
            )
        )
        return BundleSendPayload(
            content=prepared.effective_content,
            media_urls=prepared.effective_media_urls,
            media_items=prepared.effective_media_items,
            layout=prepared.effective_layout,
            send_mode=prepared.effective_send_mode,
            style=prepared.effective_style,
            notify=bool(effective_options.notify),
        )

    @staticmethod
    def _media_items(document_snapshot: dict[str, Any]) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for entry in document_snapshot.get("entries") or []:
            for media in entry.get("media_items") or []:
                if not isinstance(media, dict):
                    continue
                url = str(media.get("url") or "").strip()
                if not url:
                    continue
                media_type = str(media.get("type") or "file").strip() or "file"
                identity = (media_type, url)
                if identity not in seen:
                    seen.add(identity)
                    items.append(identity)
        return items

    @staticmethod
    def _media_snapshot(
        media_items: list[tuple[str, str]] | None,
    ) -> list[list[str]]:
        return [[media_type, url] for media_type, url in (media_items or [])]

    @staticmethod
    def _layout_snapshot(
        layout: list[LayoutFragment] | None,
    ) -> list[dict[str, Any] | LayoutFragment]:
        return [
            fragment.model_dump(mode="json")
            if hasattr(fragment, "model_dump")
            else fragment
            for fragment in (layout or [])
        ]

    @staticmethod
    def _feed_link(members: list[Any], feeds: dict[int, Any]) -> str:
        if not members:
            return ""
        first_member = min(members, key=lambda item: item.position)
        feed = feeds.get(first_member.feed_id)
        return str(getattr(feed, "link", "") or "")

    @staticmethod
    def _platform_name(target_session: str) -> str:
        return str(target_session).split(":", 1)[0].strip()
