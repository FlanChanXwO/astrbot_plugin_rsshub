"""Subscription 卡片配置、候选与预览应用服务。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...domain.entities.card_template import CardTemplateMetadata
from ...domain.entities.delivery import DeliveryOwner
from ...domain.entities.feed import Feed
from ...domain.entities.subscription import Subscription
from ...domain.exceptions import DomainException
from .card_template_policy import validate_card_template_selection
from .content_handlers import EntryContentContext

_UNSET = object()


class SubscriptionCardAccessError(PermissionError):
    """Subscription 不存在或不属于当前用户。"""


class SubscriptionCardConfigurationError(ValueError):
    """Subscription 卡片配置无效。"""


@dataclass(frozen=True, slots=True)
class CardTemplateOption:
    """Pages 可安全选择的模板候选。"""

    id: str
    name: str
    version: str
    author: str
    description: str
    repository: str

    @classmethod
    def from_metadata(cls, metadata: CardTemplateMetadata) -> CardTemplateOption:
        return cls(
            id=metadata.id,
            name=metadata.name,
            version=metadata.version,
            author=metadata.author,
            description=metadata.description,
            repository=metadata.repository,
        )


@dataclass(frozen=True, slots=True)
class SubscriptionCardPreview:
    """不持久化的 Subscription 卡片预览结果。"""

    png: bytes
    entry_count: int
    template: dict[str, str]
    source_summary: dict[str, Any]


class SubscriptionCardManagementService:
    """集中实现 Subscription 卡片管理规则。"""

    def __init__(
        self,
        *,
        subscription_repository: Any,
        feed_repository: Any,
        template_repository: Any,
        delivery_repository: Any | None = None,
        polling_service: Any | None = None,
        user_repository: Any | None = None,
        content_handler_runtime: Any | None = None,
        template_service: Any | None = None,
        image_renderer: Any | None = None,
    ) -> None:
        self._subscription_repository = subscription_repository
        self._feed_repository = feed_repository
        self._template_repository = template_repository
        self._delivery_repository = delivery_repository
        self._polling_service = polling_service
        self._user_repository = user_repository
        self._content_handler_runtime = content_handler_runtime
        self._template_service = template_service
        self._image_renderer = image_renderer

    async def list_template_options(
        self,
        *,
        subscription_id: int,
        user_id: str,
    ) -> list[CardTemplateOption]:
        """返回适配当前 Subscription Feed 的严格候选列表。"""
        subscription, feed = await self._load_owned_subscription(
            subscription_id,
            user_id,
        )
        packages = await asyncio.to_thread(self._template_repository.list_packages)
        del subscription
        return [
            CardTemplateOption.from_metadata(package.metadata)
            for package in packages
            if package.metadata.matches_owner(
                owner_type="subscription",
                feed_urls=[feed.link],
            )
        ]

    async def update_configuration(
        self,
        *,
        subscription_id: int,
        user_id: str,
        send_card: bool | None = None,
        template_id: str | None | object = _UNSET,
        card_send_original_content: bool | None = None,
    ) -> Subscription:
        """校验候选模板后原子提交 Subscription 卡片配置。"""
        await self.validate_configuration(
            subscription_id=subscription_id,
            user_id=user_id,
            send_card=send_card,
            template_id=template_id,
            card_send_original_content=card_send_original_content,
        )
        updates: dict[str, bool | str | None] = {}
        if send_card is not None:
            updates["send_card"] = send_card
        if template_id is not _UNSET:
            updates["template_id"] = template_id
        if card_send_original_content is not None:
            updates["card_send_original_content"] = card_send_original_content
        updated = await self._subscription_repository.update_options(
            subscription_id,
            user_id,
            **updates,
        )
        if updated is None:
            raise SubscriptionCardAccessError("订阅不存在或无权访问")
        return updated

    async def validate_configuration(
        self,
        *,
        subscription_id: int,
        user_id: str,
        send_card: bool | None = None,
        template_id: str | None | object = _UNSET,
        card_send_original_content: bool | None = None,
    ) -> None:
        """验证配置变更，不执行持久化。"""
        subscription, feed = await self._load_owned_subscription(
            subscription_id,
            user_id,
        )
        effective_send_card = subscription.send_card if send_card is None else send_card
        effective_template_id = (
            subscription.template_id if template_id is _UNSET else template_id
        )

        if subscription.send_card and not effective_send_card:
            if self._delivery_repository is None:
                raise SubscriptionCardConfigurationError(
                    "可靠投递仓储未初始化，不能关闭卡片"
                )
            await self._delivery_repository.ensure_owner_deletable(
                DeliveryOwner(
                    owner_type="subscription",
                    owner_id=subscription_id,
                )
            )

        candidate = subscription.model_copy(
            update={
                "send_card": effective_send_card,
                "template_id": effective_template_id,
                "card_send_original_content": (
                    subscription.card_send_original_content
                    if card_send_original_content is None
                    else card_send_original_content
                ),
            }
        )
        await self.validate_owner_configuration(candidate, feed)

    async def validate_owner_configuration(
        self,
        subscription: Subscription,
        feed: Feed,
    ) -> None:
        """验证尚未持久化的 Subscription 卡片配置。"""
        package = None
        if subscription.template_id:
            package = await asyncio.to_thread(
                self._template_repository.get,
                subscription.template_id,
            )
        try:
            validate_card_template_selection(
                owner=subscription,
                template=package.metadata if package else None,
                feed_urls=[feed.link],
            )
        except (DomainException, ValueError) as exc:
            raise SubscriptionCardConfigurationError(
                f"卡片模板配置无效: {exc}"
            ) from exc

    async def preview(
        self,
        *,
        subscription_id: int,
        user_id: str,
        template_id: str,
    ) -> SubscriptionCardPreview:
        """抓取当前 Feed、运行当前 handlers 并在内存中生成 PNG。"""
        dependencies = (
            self._polling_service,
            self._user_repository,
            self._content_handler_runtime,
            self._template_service,
            self._image_renderer,
        )
        if any(dependency is None for dependency in dependencies):
            raise SubscriptionCardConfigurationError("卡片预览服务未初始化")
        subscription, feed = await self._load_owned_subscription(
            subscription_id,
            user_id,
        )
        package = await asyncio.to_thread(self._template_repository.get, template_id)
        if package is None or not package.metadata.matches_owner(
            owner_type="subscription",
            feed_urls=[feed.link],
        ):
            raise SubscriptionCardConfigurationError("卡片模板不属于当前候选")

        read_result = await self._polling_service.fetch_feed_entries(feed.link)
        if not read_result.success:
            raise SubscriptionCardConfigurationError(
                read_result.error or read_result.message
            )
        user = await self._user_repository.get_by_id(subscription.user_id)
        entries: list[dict[str, Any]] = []
        text_parts: list[str] = []
        for index, raw_entry in enumerate(read_result.entries, start=1):
            media_items = tuple(
                (
                    str(getattr(enclosure, "type", "") or "file"),
                    str(getattr(enclosure, "url", "") or ""),
                )
                for enclosure in (getattr(raw_entry, "enclosures", None) or [])
                if str(getattr(enclosure, "url", "") or "").strip()
            )
            entry_context = EntryContentContext(
                title=str(getattr(raw_entry, "title", "") or ""),
                summary=str(getattr(raw_entry, "summary", "") or ""),
                content=str(getattr(raw_entry, "content", "") or ""),
                link=str(getattr(raw_entry, "link", "") or ""),
                author=str(getattr(raw_entry, "author", "") or ""),
                feed_title=feed.title,
                feed_link=feed.link,
                raw_xml=str(getattr(raw_entry, "raw_xml", "") or ""),
                media_urls=tuple(url for _media_type, url in media_items),
                media_items=media_items,
            )
            handled = await self._content_handler_runtime.process_entry_with_trace(
                subscription=subscription,
                user=user,
                entry=entry_context,
                session_id=subscription.target_session,
                target_session=subscription.target_session,
                platform_name=subscription.platform_name,
                user_id=subscription.user_id,
            )
            if not handled.allow:
                continue
            handled_entry = handled.entry
            item_key = str(
                getattr(raw_entry, "id", "")
                or getattr(raw_entry, "guid", "")
                or getattr(raw_entry, "link", "")
                or f"preview-entry-{index}"
            )
            entries.append(
                {
                    "item_key": item_key,
                    "feed_id": feed.id,
                    "title": handled_entry.title,
                    "link": handled_entry.link,
                    "author": handled_entry.author,
                    "published": self._iso_time(getattr(raw_entry, "published", None)),
                    "updated": self._iso_time(getattr(raw_entry, "updated", None)),
                    "summary": handled_entry.summary,
                    "content_html": handled_entry.content,
                    "tags": [
                        str(tag) for tag in (getattr(raw_entry, "tags", None) or [])
                    ],
                    "media_items": [
                        {"type": media_type, "url": url}
                        for media_type, url in handled_entry.media_items
                    ],
                }
            )
            text_parts.append(handled_entry.content or handled_entry.summary)

        context = {
            "source": {"type": "feed", "owner_id": subscription_id},
            "feed": {"id": feed.id, "title": feed.title, "link": feed.link},
            "bundle": None,
            "feeds": [],
            "entries": entries,
            "document": {"text": "\n\n".join(text_parts), "rss_xml": ""},
            "meta": {
                # 预览不创建 DeliveryBatch；使用 owner ID 保持模板上下文形状稳定。
                "batch_id": subscription_id,
                "rendered_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        snapshot = await asyncio.to_thread(self._template_service.snapshot, package)
        html = await asyncio.to_thread(self._template_service.render, snapshot, context)
        png = await self._image_renderer.render(html)
        return SubscriptionCardPreview(
            png=png,
            entry_count=len(entries),
            template=package.metadata.model_dump(
                include={"id", "name", "version", "author"},
                mode="json",
            ),
            source_summary={
                "feed_id": feed.id,
                "feed_title": feed.title,
                "feed_link": feed.link,
                "entry_count": len(entries),
            },
        )

    @staticmethod
    def _iso_time(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    async def _load_owned_subscription(
        self,
        subscription_id: int,
        user_id: str,
    ) -> tuple[Subscription, Feed]:
        subscription = await self._subscription_repository.get_by_id(subscription_id)
        if subscription is None or subscription.user_id != user_id:
            raise SubscriptionCardAccessError("订阅不存在或无权访问")
        feed = await self._feed_repository.get_by_id(subscription.feed_id)
        if feed is None:
            raise SubscriptionCardConfigurationError("订阅对应的 Feed 不存在")
        return subscription, feed
