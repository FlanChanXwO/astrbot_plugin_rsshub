from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from astrbot_plugin_rsshub.src.application.services.bundle_collection_service import (
    BundleCollectionService,
)
from astrbot_plugin_rsshub.src.application.services.feed_polling_service import (
    FeedEntrySnapshot,
    FeedReadResult,
)
from astrbot_plugin_rsshub.src.domain.entities.bundle import Bundle
from astrbot_plugin_rsshub.src.domain.entities.bundle_feed import BundleFeed
from astrbot_plugin_rsshub.src.domain.entities.delivery import InboxStoreResult
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.infrastructure.config import RSSSettings


@dataclass
class _MemberRead:
    entries: list[dict[str, str]]
    status: str = "fetched"
    success: bool = True
    etag: str | None = None


class _BundleRepository:
    def __init__(self, bundle: Bundle, members: list[BundleFeed]) -> None:
        self.bundle = bundle
        self.members = members

    async def get_by_id(self, bundle_id: int) -> Bundle | None:
        return self.bundle if self.bundle.id == bundle_id else None

    async def list_members(self, bundle_id: int) -> list[BundleFeed]:
        assert bundle_id == self.bundle.id
        return list(self.members)


class _FeedRepository:
    def __init__(self, feeds: list[Feed]) -> None:
        self.feeds = {feed.id: feed for feed in feeds}

    async def get_by_id(self, feed_id: int) -> Feed | None:
        return self.feeds.get(feed_id)


class _PollingService:
    def __init__(self, reads: dict[str, _MemberRead]) -> None:
        self.reads = reads
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def fetch_feed_entries(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        verbose: bool = False,
    ) -> FeedReadResult:
        del verbose
        request_headers = dict(headers or {})
        self.calls.append((url, request_headers))
        read = self.reads[url]
        web_feed = SimpleNamespace(
            etag=read.etag,
            last_modified=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )
        return FeedReadResult(
            success=read.success,
            status=read.status,
            message=read.status,
            entries=read.entries,
            web_feed=web_feed,
            error="fetch failed" if not read.success else "",
        )

    def calculate_entry_update(
        self,
        old_groups: list[list[str]],
        entries: list[dict[str, str]],
        *,
        feed_link: str,
    ) -> tuple[list[list[str]], list[dict[str, str]]]:
        known = {item for group in old_groups for item in group}
        groups = [[f"sid:{entry['id']}"] for entry in entries]
        new_entries = [
            entry for entry, group in zip(entries, groups) if not set(group) & known
        ]
        return groups, new_entries

    def merge_entry_hash_history(
        self,
        old_groups: list[list[str]],
        new_groups: list[list[str]],
        entry_count: int,
    ) -> list[list[str]]:
        del entry_count
        return old_groups + [group for group in new_groups if group not in old_groups]

    def build_entry_snapshots(
        self,
        feed: Feed,
        entries: list[dict[str, str]],
    ) -> list[FeedEntrySnapshot]:
        del feed
        return [
            FeedEntrySnapshot(
                item_key=f"sid:{entry['id']}",
                hash_group=[f"sid:{entry['id']}"],
                entry_payload=dict(entry),
                raw_xml=f"<item><guid>{entry['id']}</guid></item>",
                media_items=[],
                published_at=None,
                entry_updated_at=None,
            )
            for entry in entries
        ]


class _DeliveryRepository:
    def __init__(self) -> None:
        self.discoveries: list[dict[str, object]] = []
        self.statuses: list[dict[str, object]] = []

    async def store_bundle_discovery(self, **kwargs) -> InboxStoreResult:
        self.discoveries.append(kwargs)
        return InboxStoreResult(
            inserted_count=len(kwargs["items"]),
            duplicate_count=0,
        )

    async def record_bundle_member_status(self, **kwargs) -> None:
        self.statuses.append(kwargs)


@pytest.mark.asyncio
async def test_collects_members_serially_and_persists_private_watermarks() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Daily",
        target_sessions=["test:Group:1"],
        interval=30,
    )
    members = [
        BundleFeed(
            id=101,
            bundle_id=7,
            feed_id=11,
            position=0,
            etag="member-one-etag",
        ),
        BundleFeed(id=102, bundle_id=7, feed_id=12, position=1),
    ]
    feeds = [
        Feed(id=11, link="https://example.com/one"),
        Feed(id=12, link="https://example.com/two"),
    ]
    polling = _PollingService(
        {
            feeds[0].link: _MemberRead(
                entries=[{"id": "one-entry"}],
                etag="one-next-etag",
            ),
            feeds[1].link: _MemberRead(entries=[{"id": "two-entry"}], etag="two-etag"),
        }
    )
    delivery = _DeliveryRepository()
    service = BundleCollectionService(
        bundle_repository=_BundleRepository(bundle, members),
        feed_repository=_FeedRepository(feeds),
        polling_service=polling,
        delivery_repository=delivery,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.collect_bundle(7)

    assert result.success is True
    assert [call[0] for call in polling.calls] == [
        "https://example.com/one",
        "https://example.com/two",
    ]
    assert polling.calls[0][1] == {"If-None-Match": "member-one-etag"}
    assert polling.calls[1][1] == {}
    assert [item["bundle_feed_id"] for item in delivery.discoveries] == [101, 102]
    assert [item["entry_hashes"] for item in delivery.discoveries] == [
        [["sid:one-entry"]],
        [["sid:two-entry"]],
    ]
    assert [len(item["items"]) for item in delivery.discoveries] == [1, 1]


@pytest.mark.asyncio
async def test_first_success_can_skip_history_but_initial_304_cannot_initialize() -> (
    None
):
    bundle = Bundle(
        id=8,
        user_id="user-1",
        name="Bootstrap",
        target_sessions=["test:Group:1"],
        interval=30,
    )
    feed = Feed(id=21, link="https://example.com/bootstrap")
    member = BundleFeed(id=201, bundle_id=8, feed_id=21, position=0)
    repository = _BundleRepository(bundle, [member])
    feed_repository = _FeedRepository([feed])
    polling = _PollingService(
        {
            feed.link: _MemberRead(
                entries=[{"id": "history-entry"}],
                etag="bootstrap-etag",
            )
        }
    )
    delivery = _DeliveryRepository()
    service = BundleCollectionService(
        bundle_repository=repository,
        feed_repository=feed_repository,
        polling_service=polling,
        delivery_repository=delivery,
        rss_settings=RSSSettings(bootstrap_skip_history=True),
    )

    result = await service.collect_bundle(8)

    assert result.success is True
    assert result.members[0].bootstrap_skipped is True
    assert result.members[0].new_entries == 1
    assert delivery.discoveries[0]["items"] == []
    assert delivery.discoveries[0]["entry_hashes"] == [["sid:history-entry"]]

    not_modified_polling = _PollingService(
        {
            feed.link: _MemberRead(
                entries=[],
                status="not_modified",
                success=True,
            )
        }
    )
    empty_member = BundleFeed(id=202, bundle_id=8, feed_id=21, position=0)
    empty_repository = _BundleRepository(bundle, [empty_member])
    not_modified_delivery = _DeliveryRepository()
    not_modified_service = BundleCollectionService(
        bundle_repository=empty_repository,
        feed_repository=feed_repository,
        polling_service=not_modified_polling,
        delivery_repository=not_modified_delivery,
        rss_settings=RSSSettings(bootstrap_skip_history=True),
    )

    not_modified_result = await not_modified_service.collect_bundle(8)

    assert not_modified_result.success is True
    assert not_modified_result.members[0].status == "not_modified"
    assert not_modified_delivery.discoveries == []
    assert not_modified_delivery.statuses[0]["status"] == "not_modified"
    assert empty_member.entry_hashes is None


@pytest.mark.asyncio
async def test_failed_member_does_not_block_later_members_or_advance_failed_watermark() -> (
    None
):
    bundle = Bundle(
        id=9,
        user_id="user-1",
        name="Partial",
        target_sessions=["test:Group:1"],
        interval=30,
    )
    members = [
        BundleFeed(
            id=301,
            bundle_id=9,
            feed_id=31,
            position=0,
            entry_hashes=[["sid:old"]],
            etag="failed-member-etag",
        ),
        BundleFeed(id=302, bundle_id=9, feed_id=32, position=1),
    ]
    feeds = [
        Feed(id=31, link="https://example.com/fails"),
        Feed(id=32, link="https://example.com/succeeds"),
    ]
    polling = _PollingService(
        {
            feeds[0].link: _MemberRead(
                entries=[],
                status="fetch_error",
                success=False,
            ),
            feeds[1].link: _MemberRead(
                entries=[{"id": "later-entry"}],
                etag="later-etag",
            ),
        }
    )
    delivery = _DeliveryRepository()
    service = BundleCollectionService(
        bundle_repository=_BundleRepository(bundle, members),
        feed_repository=_FeedRepository(feeds),
        polling_service=polling,
        delivery_repository=delivery,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.collect_bundle(9)

    assert result.success is False
    assert result.status == "partial_failure"
    assert [call[0] for call in polling.calls] == [feed.link for feed in feeds]
    assert [item["bundle_feed_id"] for item in delivery.discoveries] == [302]
    assert delivery.statuses[0]["bundle_feed_id"] == 301
    assert delivery.statuses[0]["status"] == "fetch_error"
    assert result.members[0].error == "fetch failed"
