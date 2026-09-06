"""Bundle 成员串行采集与私有水位用例。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any

from ...domain.entities.bundle import Bundle
from ...domain.entities.bundle_feed import BundleFeed
from ...domain.entities.delivery import (
    DeliveryInboxItemDraft,
    DeliveryOwner,
)
from ...domain.entities.feed import Feed, normalize_entry_hashes
from ...domain.repositories.bundle_repository import BundleRepository
from ...domain.repositories.delivery_repository import DeliveryRepository
from ...domain.repositories.feed_repository import FeedRepository
from ...infrastructure.config import RSSSettings
from ...infrastructure.utils import get_logger
from .feed_polling_service import FeedEntrySnapshot, FeedReadResult

logger = get_logger()


@dataclass(frozen=True)
class BundleMemberCollectionResult:
    """一次成员采集的可观测结果。"""

    bundle_feed_id: int | None
    feed_id: int | None
    position: int
    success: bool
    status: str
    total_entries: int = 0
    new_entries: int = 0
    inserted_count: int = 0
    bootstrap_skipped: bool = False
    error: str = ""


@dataclass(frozen=True)
class BundleCollectionResult:
    """一次 Bundle 采集的汇总结果。"""

    bundle_id: int
    success: bool
    status: str
    members: list[BundleMemberCollectionResult] = field(default_factory=list)
    total_entries: int = 0
    new_entries: int = 0
    inserted_count: int = 0
    error: str = ""


class BundleCollectionService:
    """按成员 position 串行抓取 Bundle，并隔离每个成员的私有水位。"""

    def __init__(
        self,
        *,
        bundle_repository: BundleRepository,
        feed_repository: FeedRepository,
        polling_service: Any,
        delivery_repository: DeliveryRepository,
        rss_settings: RSSSettings | None = None,
    ) -> None:
        self._bundle_repository = bundle_repository
        self._feed_repository = feed_repository
        self._polling_service = polling_service
        self._delivery_repository = delivery_repository
        self._rss_settings = rss_settings or RSSSettings()

    async def collect_bundle(
        self,
        bundle_id: int,
        *,
        verbose: bool = False,
    ) -> BundleCollectionResult:
        """顺序采集一个 Bundle 的全部成员；单成员失败不会中断后续成员。"""
        bundle = await self._bundle_repository.get_by_id(bundle_id)
        if bundle is None:
            return BundleCollectionResult(
                bundle_id=bundle_id,
                success=False,
                status="not_found",
                error="bundle_not_found",
            )
        if bundle.id is None:
            raise ValueError("Bundle 采集要求已持久化的 Bundle")

        members = await self._bundle_repository.list_members(bundle.id)
        results: list[BundleMemberCollectionResult] = []
        for member in sorted(members, key=lambda item: item.position):
            try:
                results.append(
                    await self._collect_member(bundle, member, verbose=verbose)
                )
            except Exception as exc:
                logger.exception(
                    "Bundle 成员采集失败并继续后续成员: bundle=%s, bundle_feed=%s",
                    bundle.id,
                    member.id,
                )
                results.append(
                    BundleMemberCollectionResult(
                        bundle_feed_id=member.id,
                        feed_id=member.feed_id,
                        position=member.position,
                        success=False,
                        status="collection_error",
                        error=str(exc),
                    )
                )

        failed = [result for result in results if not result.success]
        return BundleCollectionResult(
            bundle_id=bundle.id,
            success=not failed,
            status="partial_failure" if failed else "collected",
            members=results,
            total_entries=sum(result.total_entries for result in results),
            new_entries=sum(result.new_entries for result in results),
            inserted_count=sum(result.inserted_count for result in results),
            error="; ".join(result.error for result in failed if result.error),
        )

    async def _collect_member(
        self,
        bundle: Bundle,
        member: BundleFeed,
        *,
        verbose: bool,
    ) -> BundleMemberCollectionResult:
        if bundle.id is None or member.id is None:
            raise ValueError("Bundle 成员采集要求持久化 ID")

        feed = await self._feed_repository.get_by_id(member.feed_id)
        if feed is None:
            status = "feed_not_found"
            await self._delivery_repository.record_bundle_member_status(
                bundle_feed_id=member.id,
                status=status,
                checked_at=datetime.now(timezone.utc),
            )
            return BundleMemberCollectionResult(
                bundle_feed_id=member.id,
                feed_id=member.feed_id,
                position=member.position,
                success=False,
                status=status,
                error=f"Feed 不存在: {member.feed_id}",
            )

        read_result: FeedReadResult = await self._polling_service.fetch_feed_entries(
            feed.link,
            headers=self._build_conditional_headers(member),
            verbose=verbose,
        )
        checked_at = datetime.now(timezone.utc)
        old_groups = normalize_entry_hashes(member.entry_hashes) or []

        if read_result.status == "not_modified":
            await self._delivery_repository.record_bundle_member_status(
                bundle_feed_id=member.id,
                status="not_modified",
                checked_at=checked_at,
            )
            return BundleMemberCollectionResult(
                bundle_feed_id=member.id,
                feed_id=member.feed_id,
                position=member.position,
                success=True,
                status="not_modified",
            )

        if not read_result.success:
            await self._delivery_repository.record_bundle_member_status(
                bundle_feed_id=member.id,
                status=read_result.status,
                checked_at=checked_at,
            )
            return BundleMemberCollectionResult(
                bundle_feed_id=member.id,
                feed_id=member.feed_id,
                position=member.position,
                success=False,
                status=read_result.status,
                error=read_result.error or read_result.message,
            )

        new_groups, new_entries = self._polling_service.calculate_entry_update(
            old_groups,
            read_result.entries,
            feed_link=feed.link,
        )
        merged_groups = (
            self._polling_service.merge_entry_hash_history(
                old_groups,
                new_groups,
                len(read_result.entries),
            )
            or []
        )
        first_success = member.entry_hashes is None
        bootstrap_skipped = first_success and self._rss_settings.bootstrap_skip_history
        snapshots = (
            []
            if bootstrap_skipped
            else self._build_inbox_items(
                bundle,
                member,
                feed,
                self._polling_service.build_entry_snapshots(feed, new_entries),
            )
        )
        web_feed = read_result.web_feed
        etag = getattr(web_feed, "etag", None) or member.etag
        last_modified = getattr(web_feed, "last_modified", None) or member.last_modified
        status = (
            "bootstrapped"
            if bootstrap_skipped
            else "updated"
            if new_entries
            else "no_new_entries"
        )
        stored = await self._delivery_repository.store_bundle_discovery(
            owner=DeliveryOwner(owner_type="bundle", owner_id=bundle.id),
            bundle_feed_id=member.id,
            member_position=member.position,
            items=snapshots,
            entry_hashes=merged_groups,
            etag=etag,
            last_modified=last_modified,
            status=status,
            checked_at=checked_at,
        )
        return BundleMemberCollectionResult(
            bundle_feed_id=member.id,
            feed_id=member.feed_id,
            position=member.position,
            success=True,
            status=status,
            total_entries=len(read_result.entries),
            new_entries=len(new_entries),
            inserted_count=stored.inserted_count,
            bootstrap_skipped=bootstrap_skipped,
        )

    @staticmethod
    def _build_conditional_headers(member: BundleFeed) -> dict[str, str]:
        headers: dict[str, str] = {}
        if member.etag:
            headers["If-None-Match"] = member.etag
        if member.last_modified:
            headers["If-Modified-Since"] = format_datetime(member.last_modified)
        return headers

    @staticmethod
    def _build_inbox_items(
        bundle: Bundle,
        member: BundleFeed,
        feed: Feed,
        snapshots: list[FeedEntrySnapshot],
    ) -> list[DeliveryInboxItemDraft]:
        if bundle.id is None or member.id is None or feed.id is None:
            raise ValueError("Bundle inbox 条目要求已持久化的 owner、成员和 Feed")
        material = "\n".join(sorted(snapshot.item_key for snapshot in snapshots))
        digest = hashlib.sha256(
            f"{bundle.id}\n{member.id}\n{feed.id}\n{material}".encode()
        ).hexdigest()
        discovery_key = f"bundle:{bundle.id}:member:{member.id}:discovery:{digest}"
        discovered_at = datetime.now(timezone.utc)
        return [
            DeliveryInboxItemDraft(
                feed_id=feed.id,
                bundle_feed_id=member.id,
                member_position=member.position,
                item_key=snapshot.item_key,
                hash_group=snapshot.hash_group,
                discovery_key=discovery_key,
                entry_payload=snapshot.entry_payload,
                raw_xml=snapshot.raw_xml,
                media_items=snapshot.media_items,
                published_at=snapshot.published_at,
                entry_updated_at=snapshot.entry_updated_at,
                discovered_at=discovered_at,
            )
            for snapshot in snapshots
        ]
