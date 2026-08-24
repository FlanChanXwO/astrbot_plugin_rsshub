from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from astrbot_plugin_rsshub.src.application.services.bundle_card_management_service import (
    BundleCardManagementService,
)
from astrbot_plugin_rsshub.src.application.services.bundle_document_service import (
    BundleDocumentService,
)
from astrbot_plugin_rsshub.src.application.services.feed_polling_service import (
    FeedEntrySnapshot,
    FeedReadResult,
)
from astrbot_plugin_rsshub.src.application.services.subscription_card_management_service import (
    SubscriptionCardManagementService,
)
from astrbot_plugin_rsshub.src.domain.entities.bundle import Bundle
from astrbot_plugin_rsshub.src.domain.entities.bundle_feed import BundleFeed
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription
from astrbot_plugin_rsshub.src.infrastructure.fetcher import RSSParser
from astrbot_plugin_rsshub.src.infrastructure.rendering import AstrBotHtmlImageRenderer
from astrbot_plugin_rsshub.src.infrastructure.templates import (
    CardTemplatePackageRepository,
    CardTemplateService,
    get_builtin_card_template_dirs,
)


class FixturePolling:
    def __init__(self, entries: list[object]) -> None:
        self.entries = entries

    async def fetch_feed_entries(self, link: str) -> SimpleNamespace:
        assert link == "https://rsshub.app/juya/ai"
        return SimpleNamespace(
            success=True,
            message="fixture",
            error="",
            entries=self.entries,
        )


class BundleFixturePolling:
    def __init__(self, entries: list[object]) -> None:
        self.entries = entries

    async def fetch_feed_entries(self, _link: str) -> FeedReadResult:
        return FeedReadResult(
            success=True,
            status="updated",
            message="fixture",
            entries=self.entries,
        )

    def build_entry_snapshots(
        self,
        _feed: Feed,
        entries: list[object],
    ) -> list[FeedEntrySnapshot]:
        snapshots: list[FeedEntrySnapshot] = []
        for entry in entries:
            item_key = str(entry.id)
            snapshots.append(
                FeedEntrySnapshot(
                    item_key=item_key,
                    hash_group=[item_key],
                    entry_payload=entry.model_dump(mode="json"),
                    raw_xml=entry.raw_xml,
                    media_items=[
                        item.model_dump(mode="json") for item in entry.enclosures
                    ],
                    published_at=entry.published,
                    entry_updated_at=entry.updated,
                )
            )
        return snapshots


class HandlerAfterSnapshot:
    def __init__(self) -> None:
        self.calls = 0
        self.input_titles: list[str] = []

    async def process_entry_with_trace(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        entry = kwargs["entry"]
        self.input_titles.append(entry.title)
        return SimpleNamespace(
            allow=True,
            entry=SimpleNamespace(
                title=f"{entry.title}（handler后）",
                link=entry.link,
                author=entry.author,
                summary="handler 后摘要",
                content="<p>handler 后正文</p>",
                media_items=entry.media_items,
            ),
            trace=("fixture-handler",),
        )


class RecordingT2I:
    def __init__(self) -> None:
        self.html = ""

    async def render_custom_template(
        self,
        html: str,
        data: dict[str, object],
        **kwargs: object,
    ) -> bytes:
        del data, kwargs
        self.html = html
        return b"\x89PNG\r\nfixture"


class SubscriptionRepository:
    def __init__(self, subscription: Subscription) -> None:
        self.subscription = subscription
        self.update_calls: list[object] = []

    async def get_by_id(self, subscription_id: int) -> Subscription | None:
        return self.subscription if subscription_id == self.subscription.id else None

    async def update_options(self, *args: object, **kwargs: object) -> None:
        self.update_calls.append((args, kwargs))


class FeedRepository:
    def __init__(self, feed: Feed) -> None:
        self.feed = feed
        self.save_calls: list[object] = []

    async def get_by_id(self, feed_id: int) -> Feed | None:
        return self.feed if feed_id == self.feed.id else None

    async def save(self, *args: object, **kwargs: object) -> None:
        self.save_calls.append((args, kwargs))


class UserRepository:
    async def get_by_id(self, _user_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_builtin_juya_preview_uses_fixture_and_handler_snapshot_without_writes(
    fixtures_dir: Path,
) -> None:
    xml = (fixtures_dir / "feeds" / "juya_ai_daily_minimal.xml").read_text(
        encoding="utf-8"
    )
    entries, error = RSSParser().parse(xml)
    assert error is None

    subscription = Subscription(
        id=7,
        user_id="owner-1",
        feed_id=3,
        target_session="test:group:1",
    )
    feed = Feed(
        id=3,
        title="Juya AI",
        link="https://rsshub.app/juya/ai",
    )
    subscription_repository = SubscriptionRepository(subscription)
    feed_repository = FeedRepository(feed)
    handler = HandlerAfterSnapshot()
    t2i = RecordingT2I()
    template_repository = CardTemplatePackageRepository(
        storage_dir=fixtures_dir / "installed-card-templates",
        builtin_package_dirs=get_builtin_card_template_dirs(),
    )
    service = SubscriptionCardManagementService(
        subscription_repository=subscription_repository,
        feed_repository=feed_repository,
        template_repository=template_repository,
        polling_service=FixturePolling(entries),
        user_repository=UserRepository(),
        content_handler_runtime=handler,
        template_service=CardTemplateService(),
        image_renderer=AstrBotHtmlImageRenderer(t2i=t2i),
    )

    preview = await service.preview(
        subscription_id=7,
        user_id="owner-1",
        template_id="astrbot_plugin_rsshub_card_juya",
    )

    assert preview.png.startswith(b"\x89PNG")
    assert preview.entry_count == 1
    assert handler.calls == 1
    assert handler.input_titles == ["2026-05-19"]
    assert "（handler后）" in t2i.html
    assert "handler 后正文" in t2i.html
    assert "Juya AI" in t2i.html
    assert subscription_repository.update_calls == []
    assert feed_repository.save_calls == []


@pytest.mark.asyncio
async def test_builtin_bundle_preview_uses_two_sources_without_delivery_writes(
    fixtures_dir: Path,
) -> None:
    xml = (fixtures_dir / "feeds" / "simple_rss.xml").read_text(encoding="utf-8")
    entries, error = RSSParser().parse(xml)
    assert error is None

    bundle = Bundle(
        id=21,
        user_id="owner-1",
        name="AI sources",
        target_sessions=["test:group:1"],
        interval=10,
    )
    members = [
        BundleFeed(id=31, bundle_id=21, feed_id=3, position=0),
        BundleFeed(id=32, bundle_id=21, feed_id=4, position=1),
    ]
    feeds = {
        3: Feed(id=3, title="Source A", link="https://example.com/a"),
        4: Feed(id=4, title="Source B", link="https://example.com/b"),
    }
    bundle_repository = SimpleNamespace(
        get_by_id=_async_value(bundle),
        list_members=_async_value(members),
    )
    feed_repository = SimpleNamespace(
        get_by_id=_async_feed(feeds),
    )
    t2i = RecordingT2I()
    template_repository = CardTemplatePackageRepository(
        storage_dir=fixtures_dir / "installed-bundle-card-templates",
        builtin_package_dirs=get_builtin_card_template_dirs(),
    )
    service = BundleCardManagementService(
        bundle_repository=bundle_repository,
        feed_repository=feed_repository,
        template_repository=template_repository,
        polling_service=BundleFixturePolling(entries),
        document_service=BundleDocumentService(),
        template_service=CardTemplateService(),
        image_renderer=AstrBotHtmlImageRenderer(t2i=t2i),
    )

    preview = await service.preview(
        bundle_id=21,
        user_id="owner-1",
        template_id="astrbot_plugin_rsshub_card_bundle",
    )

    assert preview.png.startswith(b"\x89PNG")
    assert preview.entry_count == 6
    assert "Source A" in t2i.html
    assert "Source B" in t2i.html
    assert "Test Article 1" in t2i.html
    assert preview.source_summary["feeds"][0]["position"] == 0
    assert preview.source_summary["feeds"][1]["position"] == 1


def _async_value(value: object):
    async def getter(*_args: object, **_kwargs: object) -> object:
        return value

    return getter


def _async_feed(feeds: dict[int, Feed]):
    async def getter(feed_id: int) -> Feed | None:
        return feeds.get(feed_id)

    return getter
