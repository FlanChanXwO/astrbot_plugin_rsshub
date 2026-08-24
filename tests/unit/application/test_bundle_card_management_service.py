from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.services.bundle_card_management_service import (
    BundleCardManagementService,
)
from astrbot_plugin_rsshub.src.application.services.bundle_document_service import (
    BundleAggregateDocument,
    BundleDocumentEntry,
    BundleDocumentHandlerResult,
)
from astrbot_plugin_rsshub.src.application.services.feed_polling_service import (
    FeedEntrySnapshot,
    FeedReadResult,
)
from astrbot_plugin_rsshub.src.domain.entities.bundle import Bundle
from astrbot_plugin_rsshub.src.domain.entities.bundle_feed import BundleFeed
from astrbot_plugin_rsshub.src.domain.entities.card_template import CardTemplateMetadata
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed


def _metadata() -> CardTemplateMetadata:
    return CardTemplateMetadata(
        id="astrbot_plugin_rsshub_card_bundle",
        name="Bundle",
        version="1.0.0",
        author="AstrBot",
        description="bundle template",
        repository="https://example.test/template",
        targets=["bundle"],
    )


@pytest.mark.asyncio
async def test_bundle_card_management_lists_only_templates_matching_all_member_feeds():
    bundle = Bundle(
        id=11,
        user_id="owner-1",
        name="Daily",
        target_sessions=["session-1"],
        interval=10,
    )
    members = [
        BundleFeed(id=21, bundle_id=11, feed_id=3, position=0),
        BundleFeed(id=22, bundle_id=11, feed_id=7, position=1),
    ]
    feeds = {
        3: Feed(id=3, link="https://example.test/a", title="A"),
        7: Feed(id=7, link="https://example.test/b", title="B"),
    }
    bundle_repo = MagicMock()
    bundle_repo.get_by_id = AsyncMock(return_value=bundle)
    bundle_repo.list_members = AsyncMock(return_value=members)
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(side_effect=lambda feed_id: feeds.get(feed_id))
    template_repo = MagicMock()
    template_repo.list_packages.return_value = [SimpleNamespace(metadata=_metadata())]
    service = BundleCardManagementService(
        bundle_repository=bundle_repo,
        feed_repository=feed_repo,
        template_repository=template_repo,
    )

    options = await service.list_template_options(bundle_id=11, user_id="owner-1")

    assert [option.id for option in options] == ["astrbot_plugin_rsshub_card_bundle"]


@pytest.mark.asyncio
async def test_bundle_card_management_rejects_non_owner_before_loading_members():
    bundle_repo = MagicMock()
    bundle_repo.get_by_id = AsyncMock(
        return_value=Bundle(
            id=11,
            user_id="owner-1",
            name="Daily",
            target_sessions=["session-1"],
            interval=10,
        )
    )
    bundle_repo.list_members = AsyncMock()
    service = BundleCardManagementService(
        bundle_repository=bundle_repo,
        feed_repository=MagicMock(),
        template_repository=MagicMock(),
    )

    with pytest.raises(PermissionError, match="无权访问"):
        await service.list_template_options(bundle_id=11, user_id="other")

    bundle_repo.list_members.assert_not_awaited()


@pytest.mark.asyncio
async def test_bundle_card_preview_fetches_and_renders_without_delivery_persistence():
    bundle = Bundle(
        id=11,
        user_id="owner-1",
        name="Daily",
        target_sessions=["session-1"],
        interval=10,
    )
    member = BundleFeed(id=21, bundle_id=11, feed_id=3, position=0)
    feed = Feed(id=3, link="https://example.test/a", title="A")
    bundle_repo = MagicMock()
    bundle_repo.get_by_id = AsyncMock(return_value=bundle)
    bundle_repo.list_members = AsyncMock(return_value=[member])
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    metadata = _metadata()
    package = SimpleNamespace(metadata=metadata)
    template_repo = MagicMock()
    template_repo.get.return_value = package

    polling = MagicMock()
    polling.fetch_feed_entries = AsyncMock(
        return_value=FeedReadResult(
            success=True,
            status="updated",
            message="ok",
            entries=[SimpleNamespace(id="entry-1")],
        )
    )
    polling.build_entry_snapshots.return_value = [
        FeedEntrySnapshot(
            item_key="entry-1",
            hash_group=["entry-1"],
            entry_payload={"title": "Entry", "link": "https://example.test/e"},
            raw_xml=None,
            media_items=[],
            published_at=None,
            entry_updated_at=None,
        )
    ]
    document_service = MagicMock()
    document_service.build_and_process = AsyncMock(
        return_value=BundleDocumentHandlerResult(
            document=BundleAggregateDocument(
                entries=(
                    BundleDocumentEntry(
                        item_key="entry-1",
                        feed_id=3,
                        member_position=0,
                        title="Entry",
                        link="https://example.test/e",
                        author="",
                        summary="Summary",
                        content_html="<p>Summary</p>",
                        tags=(),
                        media_items=(),
                        published=None,
                        updated=None,
                    ),
                ),
                text="Summary",
                rss_xml="<rss version='2.0' />",
                consumption_item_keys=("entry-1",),
            )
        )
    )
    template_service = MagicMock()
    template_service.snapshot.return_value = SimpleNamespace()
    template_service.render.return_value = "<html>preview</html>"
    image_renderer = MagicMock()
    image_renderer.render = AsyncMock(return_value=b"png")
    service = BundleCardManagementService(
        bundle_repository=bundle_repo,
        feed_repository=feed_repo,
        template_repository=template_repo,
        polling_service=polling,
        document_service=document_service,
        template_service=template_service,
        image_renderer=image_renderer,
    )

    preview = await service.preview(
        bundle_id=11,
        user_id="owner-1",
        template_id="astrbot_plugin_rsshub_card_bundle",
    )

    assert preview.png == b"png"
    assert preview.entry_count == 1
    assert preview.source_summary["bundle_id"] == 11
    polling.fetch_feed_entries.assert_awaited_once_with("https://example.test/a")
    document_service.build_and_process.assert_awaited_once()
