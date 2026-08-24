"""卡片 Subscription 的可靠批次创建与投递。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...domain.entities.delivery import DeliveryBatchDraft, DeliveryOwner
from ...domain.entities.push_history import PushHistory
from ...domain.repositories.delivery_repository import DeliveryRepository
from ...domain.repositories.feed_repository import FeedRepository
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ...domain.repositories.user_repository import UserRepository
from ...infrastructure.templates.rendering import CardTemplateService
from ...infrastructure.utils import get_logger
from ..services.content_handlers import ContentHandlerRuntime, EntryContentContext
from ..services.notification_dispatcher import NotificationDispatcher
from ..services.output_orchestrator import OutputOrchestrator

logger = get_logger()


class SubscriptionBatchDeliveryError(RuntimeError):
    """卡片 Subscription 无法创建可靠批次。"""


@dataclass(frozen=True, slots=True)
class SubscriptionBatchDeliveryResult:
    """一次 owner 投递推进的结果。"""

    batch_id: int | None
    ready_to_confirm: bool


class SubscriptionBatchDeliveryService:
    """固化 handler 后输入，再交给公共输出编排器。"""

    def __init__(
        self,
        *,
        delivery_repository: DeliveryRepository,
        subscription_repository: SubscriptionRepository,
        feed_repository: FeedRepository,
        user_repository: UserRepository,
        template_repository: Any,
        template_service: CardTemplateService,
        content_handler_runtime: ContentHandlerRuntime,
        notification_dispatcher: NotificationDispatcher,
        output_orchestrator: OutputOrchestrator,
        history_entry_limit: int = 0,
        max_retries: int = 3,
    ) -> None:
        self._delivery_repository = delivery_repository
        self._subscription_repository = subscription_repository
        self._feed_repository = feed_repository
        self._user_repository = user_repository
        self._template_repository = template_repository
        self._template_service = template_service
        self._content_handler_runtime = content_handler_runtime
        self._notification_dispatcher = notification_dispatcher
        self._output_orchestrator = output_orchestrator
        self._history_entry_limit = max(0, history_entry_limit)
        self._max_retries = max(0, max_retries)
        self._owner_locks: dict[int, asyncio.Lock] = {}

    async def deliver(
        self,
        subscription_id: int,
        *,
        retry_failed: bool = False,
    ) -> SubscriptionBatchDeliveryResult:
        """创建或恢复一个批次，并推进当前可执行输出。"""
        lock = self._owner_locks.setdefault(subscription_id, asyncio.Lock())
        async with lock:
            return await self._deliver_locked(
                subscription_id,
                retry_failed=retry_failed,
            )

    async def retry_active_batches(self) -> None:
        """按现有调度周期推进所有启用卡片 Subscription 的批次或 backlog。"""
        subscriptions = await self._subscription_repository.get_all_active()
        for subscription in subscriptions:
            if subscription.send_card and subscription.id is not None:
                try:
                    await self.deliver(subscription.id, retry_failed=True)
                except Exception:
                    # owner 级调度边界必须隔离，同时保留真实异常供定位。
                    logger.exception(
                        "推进卡片 Subscription 批次失败: subscription=%s",
                        subscription.id,
                    )

    async def _deliver_locked(
        self,
        subscription_id: int,
        *,
        retry_failed: bool,
    ) -> SubscriptionBatchDeliveryResult:
        owner = DeliveryOwner(owner_type="subscription", owner_id=subscription_id)
        batch = await self._delivery_repository.get_pending_batch(owner)
        if batch is None:
            batch = await self._create_batch(owner)
            if batch is None:
                return SubscriptionBatchDeliveryResult(None, False)

        orchestration = await self._output_orchestrator.run(
            batch,
            retry_failed=retry_failed,
        )
        if orchestration.ready_to_confirm:
            await self._delivery_repository.confirm_batch(batch.id)
        return SubscriptionBatchDeliveryResult(
            batch_id=batch.id,
            ready_to_confirm=orchestration.ready_to_confirm,
        )

    async def _create_batch(self, owner: DeliveryOwner) -> Any | None:
        subscription = await self._subscription_repository.get_by_id(owner.owner_id)
        if subscription is None or not subscription.send_card:
            raise SubscriptionBatchDeliveryError("Subscription 不存在或未启用卡片")
        if not subscription.template_id:
            raise SubscriptionBatchDeliveryError("卡片 Subscription 缺少模板")
        if not subscription.target_session:
            raise SubscriptionBatchDeliveryError("卡片 Subscription 缺少目标会话")

        inbox = await self._delivery_repository.list_inbox_items(
            owner,
            claimed=False,
        )
        if not inbox:
            return None
        discovery_key = inbox[0].discovery_key
        inbox = [item for item in inbox if item.discovery_key == discovery_key]
        feed = await self._feed_repository.get_by_id(subscription.feed_id)
        if feed is None or feed.id is None:
            raise SubscriptionBatchDeliveryError("卡片 Subscription 的 Feed 不存在")
        package = await asyncio.to_thread(
            self._template_repository.get,
            subscription.template_id,
        )
        if package is None:
            raise SubscriptionBatchDeliveryError("卡片模板不存在")
        if (
            package.metadata.id != subscription.template_id
            or not package.metadata.matches_owner(
                owner_type="subscription",
                feed_urls=[feed.link],
            )
        ):
            raise SubscriptionBatchDeliveryError("卡片模板与 Subscription 不匹配")
        template_snapshot = await asyncio.to_thread(
            self._template_service.snapshot,
            package,
        )
        user = await self._user_repository.get_by_id(subscription.user_id)

        entries: list[dict[str, Any]] = []
        handler_traces: list[list[dict[str, Any]]] = []
        allowed_entries: list[
            tuple[Any, EntryContentContext, list[dict[str, Any]]]
        ] = []
        for item in inbox:
            raw_entry = self._entry_context(
                item.entry_payload,
                feed,
                item.raw_xml,
                item.media_items,
            )
            handled = await self._content_handler_runtime.process_entry_with_trace(
                subscription=subscription,
                user=user,
                entry=raw_entry,
                session_id=subscription.target_session,
                target_session=subscription.target_session,
                platform_name=subscription.platform_name,
                user_id=subscription.user_id,
            )
            trace = list(handled.trace)
            handler_traces.append(trace)
            if handled.allow:
                entries.append(self._entry_snapshot(item, handled.entry))
                allowed_entries.append((item, handled.entry, trace))

        document_snapshot = {
            "input_entries": [
                {
                    "item_key": item.item_key,
                    "raw_xml": item.raw_xml,
                }
                for item in inbox
            ],
            "entries": entries,
            "handler_traces": handler_traces,
            "document": {
                "text": "\n\n".join(
                    entry.content or entry.summary
                    for _item, entry, _trace in allowed_entries
                ),
                "rss_xml": "",
            },
            "rendered_at": datetime.now(timezone.utc).isoformat(),
        }
        outputs = [
            PushHistory(
                sub_id=subscription.id,
                user_id=subscription.user_id,
                feed_id=feed.id,
                source_type="feed",
                source_key=f"feed:{feed.id}:sub:{subscription.id}",
                output_kind="card",
                output_order=0,
                target_session=subscription.target_session,
                platform_name=subscription.platform_name,
                feed_title=feed.title,
                feed_link=feed.link,
                status="waiting" if allowed_entries else "skipped",
                max_retries=0 if not allowed_entries else self._max_retries,
                source_context={
                    "template_snapshot": template_snapshot.model_dump(mode="json"),
                    "document_snapshot": document_snapshot,
                },
            )
        ]
        if not allowed_entries:
            outputs[0].mark_skipped("全部条目被 handler 过滤")
        elif subscription.card_send_original_content:
            selected_entries = sorted(
                allowed_entries,
                key=lambda value: (
                    value[0].published_at
                    or value[0].entry_updated_at
                    or value[0].discovered_at
                ),
                reverse=True,
            )
            if self._history_entry_limit > 0:
                selected_entries = selected_entries[: self._history_entry_limit]
            for order, (item, entry, trace) in enumerate(selected_entries, start=1):
                prepared = (
                    await self._notification_dispatcher.prepare_subscription_entry(
                        subscription=subscription,
                        user=user,
                        entry=entry,
                        handler_trace=trace or None,
                    )
                )
                standard = self._standard_history(
                    subscription=subscription,
                    feed=feed,
                    item=item,
                    prepared=prepared,
                    output_order=order,
                )
                standard.max_retries = self._max_retries
                outputs.append(standard)

        draft = DeliveryBatchDraft(
            target_sessions=[subscription.target_session],
            config_snapshot={
                "send_card": True,
                "card_send_original_content": subscription.card_send_original_content,
                "history_entry_limit": self._history_entry_limit,
            },
            template_snapshot=template_snapshot.model_dump(mode="json"),
            document_snapshot=document_snapshot,
        )
        return await self._delivery_repository.claim_batch(owner, draft, outputs)

    @staticmethod
    def _standard_history(
        *,
        subscription: Any,
        feed: Any,
        item: Any,
        prepared: Any,
        output_order: int,
    ) -> PushHistory:
        source_context = {
            "input_xml": item.raw_xml,
            "send": {
                "content": prepared.effective_content,
                "media_urls": prepared.effective_media_urls,
                "media_items": prepared.effective_media_items,
                "layout": [
                    fragment.model_dump(mode="json")
                    if hasattr(fragment, "model_dump")
                    else fragment
                    for fragment in (prepared.effective_layout or [])
                ],
                "send_mode": prepared.effective_send_mode,
                "style": prepared.effective_style,
            },
        }
        return PushHistory(
            sub_id=subscription.id,
            user_id=subscription.user_id,
            feed_id=feed.id,
            source_type="feed",
            source_key=f"feed:{feed.id}:sub:{subscription.id}",
            content=prepared.effective_content,
            raw_xml=prepared.processed_entry.raw_xml or None,
            media_urls=prepared.persisted_media_urls,
            handler_trace=prepared.handler_trace,
            output_kind="standard",
            output_order=output_order,
            source_context=source_context,
            entry_title=prepared.effective_title,
            entry_link=prepared.effective_link,
            entry_guid=item.item_key,
            feed_title=feed.title,
            feed_link=feed.link,
            platform_name=subscription.platform_name,
            target_session=subscription.target_session,
            status="waiting",
        )

    @staticmethod
    def _entry_context(
        payload: dict[str, Any],
        feed: Any,
        raw_xml: str | None,
        stored_media_items: list[dict[str, Any]],
    ) -> EntryContentContext:
        content = payload.get("content") or payload.get("summary") or ""
        if isinstance(content, list):
            content = next(
                (
                    str(item.get("value") or "")
                    for item in content
                    if isinstance(item, dict) and item.get("value")
                ),
                "",
            )
        normalized_media: list[tuple[str, str]] = []
        for media in stored_media_items:
            if not isinstance(media, dict):
                continue
            url = str(media.get("url") or "").strip()
            if not url:
                continue
            media_type = str(media.get("type") or media.get("media_type") or "file")
            normalized_media.append((media_type, url))
        return EntryContentContext(
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            content=str(content),
            link=str(payload.get("link") or payload.get("guid") or ""),
            author=str(payload.get("author") or ""),
            feed_title=feed.title,
            feed_link=feed.link,
            raw_xml=str(raw_xml or ""),
            media_urls=tuple(url for _media_type, url in normalized_media),
            media_items=tuple(normalized_media),
        )

    @staticmethod
    def _entry_snapshot(item: Any, entry: EntryContentContext) -> dict[str, Any]:
        return {
            "item_key": item.item_key,
            "feed_id": item.feed_id,
            "title": entry.title,
            "link": entry.link,
            "author": entry.author,
            "published": item.published_at.isoformat() if item.published_at else None,
            "updated": item.entry_updated_at.isoformat()
            if item.entry_updated_at
            else None,
            "summary": entry.summary,
            "content_html": entry.content,
            "tags": [
                str(tag.get("term") if isinstance(tag, dict) else tag)
                for tag in (item.entry_payload.get("tags") or [])
            ],
            "media_items": [
                {"type": media_type, "url": url}
                for media_type, url in entry.media_items
            ],
        }
