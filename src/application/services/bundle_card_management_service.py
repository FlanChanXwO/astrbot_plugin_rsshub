"""Bundle owner 的卡片候选与零副作用预览。"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...domain.entities.bundle import Bundle
from ...domain.entities.bundle_feed import BundleFeed
from ...domain.entities.delivery import DeliveryInboxItem, DeliveryOwner
from ...domain.entities.feed import Feed
from ...infrastructure.templates.rendering import CardTemplateService
from .bundle_document_service import BundleDocumentService
from .feed_polling_service import FeedPollingService
from .subscription_card_management_service import CardTemplateOption


@dataclass(frozen=True, slots=True)
class BundleCardPreview:
    """不写入水位、inbox、批次或历史的 Bundle 卡片预览。"""

    png: bytes
    entry_count: int
    template: dict[str, str]
    source_summary: dict[str, Any]


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class BundleCardManagementService:
    """集中实现 Bundle 模板匹配和内存预览规则。"""

    def __init__(
        self,
        *,
        bundle_repository: Any,
        feed_repository: Any,
        template_repository: Any,
        polling_service: FeedPollingService | None = None,
        document_service: BundleDocumentService | None = None,
        template_service: CardTemplateService | None = None,
        image_renderer: Any | None = None,
    ) -> None:
        self._bundle_repository = bundle_repository
        self._feed_repository = feed_repository
        self._template_repository = template_repository
        self._polling_service = polling_service
        self._document_service = document_service
        self._template_service = template_service
        self._image_renderer = image_renderer

    async def list_template_options(
        self,
        *,
        bundle_id: int,
        user_id: str,
    ) -> list[CardTemplateOption]:
        """仅返回同时匹配 Bundle 全部成员 Feed 的模板。"""
        _bundle, _members, feeds = await self._load_owned_bundle(bundle_id, user_id)
        packages = await asyncio.to_thread(self._template_repository.list_packages)
        feed_urls = [feed.link for feed in feeds]
        return [
            CardTemplateOption.from_metadata(package.metadata)
            for package in packages
            if package.metadata.matches_owner(
                owner_type="bundle",
                feed_urls=feed_urls,
            )
        ]

    async def preview(
        self,
        *,
        bundle_id: int,
        user_id: str,
        template_id: str,
    ) -> BundleCardPreview:
        """抓取成员并在内存中运行文档 handlers、模板和 PNG 渲染。"""
        dependencies = (
            self._polling_service,
            self._document_service,
            self._template_service,
            self._image_renderer,
        )
        if any(dependency is None for dependency in dependencies):
            raise ValueError("Bundle 卡片预览服务未初始化")

        bundle, members, feeds = await self._load_owned_bundle(bundle_id, user_id)
        package = await asyncio.to_thread(self._template_repository.get, template_id)
        if package is None or not package.metadata.matches_owner(
            owner_type="bundle",
            feed_urls=[feed.link for feed in feeds],
        ):
            raise ValueError("卡片模板不属于当前候选")

        inbox_items = await self._fetch_preview_items(bundle, members, feeds)
        document_result = await self._document_service.build_and_process(
            bundle=bundle,
            members=members,
            feeds={feed.id: feed for feed in feeds if feed.id is not None},
            inbox_items=inbox_items,
            history_entry_limit=0,
            session_id=bundle.target_sessions[0] if bundle.target_sessions else None,
        )
        document = document_result.document
        context = {
            "source": {"type": "bundle", "owner_id": bundle.id},
            "feed": None,
            "bundle": {"id": bundle.id, "name": bundle.name},
            "feeds": [
                {
                    "id": feed.id,
                    "title": feed.title,
                    "link": feed.link,
                    "position": member.position,
                }
                for member in members
                for feed in [feeds_by_id(feeds, member.feed_id)]
            ],
            "entries": [entry.to_json() for entry in document.entries],
            "document": {
                "text": document.text,
                "rss_xml": document.rss_xml,
            },
            "meta": {
                # 预览没有真实 DeliveryBatch，使用 owner ID 保持上下文合法。
                "batch_id": bundle.id,
                "rendered_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        snapshot = await asyncio.to_thread(self._template_service.snapshot, package)
        html = await asyncio.to_thread(self._template_service.render, snapshot, context)
        png = await _maybe_await(self._image_renderer.render(html))
        return BundleCardPreview(
            png=png,
            entry_count=len(document.entries),
            template=package.metadata.model_dump(
                include={"id", "name", "version", "author"},
                mode="json",
            ),
            source_summary={
                "bundle_id": bundle.id,
                "bundle_name": bundle.name,
                "feeds": [
                    {
                        "id": feed.id,
                        "title": feed.title,
                        "link": feed.link,
                        "position": member.position,
                    }
                    for member in members
                    for feed in [feeds_by_id(feeds, member.feed_id)]
                ],
                "entry_count": len(document.entries),
                "handler_allowed": document_result.allowed,
                "handler_reason": document_result.reason,
            },
        )

    async def _load_owned_bundle(
        self,
        bundle_id: int,
        user_id: str,
    ) -> tuple[Bundle, list[BundleFeed], list[Feed]]:
        bundle = await _maybe_await(self._bundle_repository.get_by_id(bundle_id))
        if bundle is None or bundle.user_id != user_id:
            raise PermissionError("Bundle 不存在或无权访问")
        if bundle.id is None:
            raise ValueError("Bundle 缺少持久化 ID")
        members = sorted(
            await _maybe_await(self._bundle_repository.list_members(bundle.id)) or [],
            key=lambda member: member.position,
        )
        feeds: list[Feed] = []
        for member in members:
            feed = await _maybe_await(self._feed_repository.get_by_id(member.feed_id))
            if feed is None:
                raise ValueError(f"Bundle 成员 Feed 不存在: {member.feed_id}")
            feeds.append(feed)
        return bundle, members, feeds

    async def _fetch_preview_items(
        self,
        bundle: Bundle,
        members: list[BundleFeed],
        feeds: list[Feed],
    ) -> list[DeliveryInboxItem]:
        items: list[DeliveryInboxItem] = []
        feed_by_id = {feed.id: feed for feed in feeds}
        next_id = 1
        for member in members:
            if member.id is None:
                raise ValueError("Bundle 成员缺少持久化 ID")
            feed = feed_by_id.get(member.feed_id)
            if feed is None or feed.id is None:
                raise ValueError(f"Bundle 成员 Feed 不存在: {member.feed_id}")
            read_result = await self._polling_service.fetch_feed_entries(feed.link)
            if not read_result.success:
                raise ValueError(read_result.error or read_result.message)
            snapshots = self._polling_service.build_entry_snapshots(
                feed,
                read_result.entries,
            )
            for index, snapshot in enumerate(snapshots):
                items.append(
                    DeliveryInboxItem(
                        id=next_id,
                        owner=DeliveryOwner(owner_type="bundle", owner_id=bundle.id),
                        feed_id=feed.id,
                        bundle_feed_id=member.id,
                        member_position=member.position,
                        item_key=snapshot.item_key,
                        hash_group=snapshot.hash_group,
                        discovery_key=(
                            f"preview:bundle:{bundle.id}:member:{member.id}:{index}"
                        ),
                        entry_payload=snapshot.entry_payload,
                        raw_xml=snapshot.raw_xml,
                        media_items=snapshot.media_items,
                        published_at=snapshot.published_at,
                        entry_updated_at=snapshot.entry_updated_at,
                        discovered_at=datetime.now(timezone.utc),
                    )
                )
                next_id += 1
        return items


def feeds_by_id(feeds: list[Feed], feed_id: int) -> Feed:
    for feed in feeds:
        if feed.id == feed_id:
            return feed
    raise ValueError(f"Bundle 成员 Feed 不存在: {feed_id}")
