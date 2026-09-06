"""Bundle 可靠批次创建与输出编排测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.services.bundle_batch_delivery_service import (
    BundleBatchDeliveryService,
    BundleSendPayload,
)
from astrbot_plugin_rsshub.src.application.services.bundle_document_service import (
    BundleAggregateDocument,
    BundleDocumentEntry,
    BundleDocumentHandlerResult,
)
from astrbot_plugin_rsshub.src.application.services.bundle_output_executor import (
    BundleOutputExecutor,
)
from astrbot_plugin_rsshub.src.domain.entities.bundle import Bundle
from astrbot_plugin_rsshub.src.domain.entities.bundle_feed import BundleFeed
from astrbot_plugin_rsshub.src.domain.entities.card_template import CardTemplateMetadata
from astrbot_plugin_rsshub.src.domain.entities.delivery import (
    DeliveryInboxItem,
    DeliveryOwner,
)
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.domain.entities.push_history import PushHistory
from astrbot_plugin_rsshub.src.infrastructure.templates.rendering import (
    CardTemplateSnapshot,
)


def _inbox(item_id: int, member_id: int, feed_id: int, key: str) -> DeliveryInboxItem:
    return DeliveryInboxItem(
        id=item_id,
        owner=DeliveryOwner(owner_type="bundle", owner_id=7),
        feed_id=feed_id,
        bundle_feed_id=member_id,
        member_position=member_id - 100,
        item_key=key,
        hash_group=[key],
        discovery_key=f"discovery-{key}",
        entry_payload={"title": key, "link": f"https://example.com/{key}"},
        discovered_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_deliver_claims_one_bundle_batch_with_card_and_aggregate_outputs() -> (
    None
):
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Daily",
        target_sessions=["test:Group:1", "test:Group:2"],
        interval=30,
        state=1,
        send_card=True,
        template_id="bundle-template",
        card_send_original_content=True,
    )
    members = [
        BundleFeed(id=101, bundle_id=7, feed_id=11, position=0),
        BundleFeed(id=102, bundle_id=7, feed_id=12, position=1),
    ]
    feeds = [
        Feed(id=11, title="One", link="https://example.com/one"),
        Feed(id=12, title="Two", link="https://example.com/two"),
    ]
    inbox = [_inbox(201, 101, 11, "one"), _inbox(202, 102, 12, "two")]
    document = BundleAggregateDocument(
        entries=(
            BundleDocumentEntry(
                item_key="one",
                feed_id=11,
                member_position=0,
                title="One",
                link="https://example.com/one",
                author="",
                summary="One",
                content_html="One",
                tags=(),
                media_items=(),
                published=None,
                updated=None,
            ),
        ),
        text="One",
        rss_xml="<rss version='2.0' />",
        consumption_item_keys=("one", "two"),
    )
    input_document = BundleAggregateDocument(
        entries=document.entries,
        text="Before handler",
        rss_xml="<rss><item>before</item></rss>",
        consumption_item_keys=document.consumption_item_keys,
    )
    handler_result = BundleDocumentHandlerResult(
        document=document,
        trace=({"name": "ai_transform", "status": "ok"},),
        input_document=input_document,
    )

    delivery_repository = MagicMock()
    delivery_repository.get_pending_batch = AsyncMock(return_value=None)
    delivery_repository.list_inbox_items = AsyncMock(return_value=inbox)
    delivery_repository.claim_batch = AsyncMock(return_value=SimpleNamespace(id=19))
    document_service = MagicMock()
    document_service.build_and_process = AsyncMock(return_value=handler_result)
    package = SimpleNamespace(
        metadata=SimpleNamespace(
            id="bundle-template",
            matches_owner=lambda **_kwargs: True,
        )
    )
    template_service = MagicMock()
    template_service.snapshot.return_value = SimpleNamespace(
        model_dump=lambda mode: {"template": "snapshot"}
    )
    orchestrator = MagicMock()
    orchestrator.run = AsyncMock(return_value=SimpleNamespace(ready_to_confirm=False))

    service = BundleBatchDeliveryService(
        delivery_repository=delivery_repository,
        bundle_repository=MagicMock(
            get_by_id=AsyncMock(return_value=bundle),
            list_members=AsyncMock(return_value=members),
        ),
        feed_repository=MagicMock(
            get_by_id=AsyncMock(side_effect=feeds),
        ),
        template_repository=MagicMock(get=MagicMock(return_value=package)),
        template_service=template_service,
        document_service=document_service,
        output_orchestrator=orchestrator,
        history_entry_limit=0,
        max_retries=4,
    )

    result = await service.deliver(7)

    assert result.batch_id == 19
    claim = delivery_repository.claim_batch.await_args
    assert claim.kwargs["item_ids"] == [201, 202]
    draft = claim.args[1]
    assert draft.target_sessions == bundle.target_sessions
    assert draft.config_snapshot["send_card"] is True
    assert draft.document_snapshot["document"]["text"] == "One"
    assert draft.document_snapshot["input_document"]["document"] == {
        "text": "Before handler",
        "rss_xml": "<rss><item>before</item></rss>",
    }
    outputs = claim.args[2]
    assert [
        (item.target_session, item.output_kind, item.output_order, item.status)
        for item in outputs
    ] == [
        ("test:Group:1", "card", 0, "waiting"),
        ("test:Group:1", "standard", 1, "waiting"),
        ("test:Group:2", "card", 0, "waiting"),
        ("test:Group:2", "standard", 1, "waiting"),
    ]
    assert all(item.bundle_id == 7 and item.sub_id is None for item in outputs)
    assert all(item.max_retries == 4 for item in outputs)
    assert all(
        item.handler_trace == [{"name": "ai_transform", "status": "ok"}]
        for item in outputs
    )
    orchestrator.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_bundle_standard_payload_uses_effective_inherited_options() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Daily",
        target_sessions=["test:Group:1"],
        interval=30,
        state=1,
    )
    members = [BundleFeed(id=101, bundle_id=7, feed_id=11, position=0)]
    feed = Feed(id=11, title="One", link="https://example.com/one")
    inbox = [_inbox(201, 101, 11, "one")]
    document = BundleAggregateDocument(
        entries=(),
        text="raw aggregate",
        rss_xml="<rss version='2.0' />",
        consumption_item_keys=("one",),
    )
    delivery_repository = MagicMock()
    delivery_repository.get_pending_batch = AsyncMock(return_value=None)
    delivery_repository.list_inbox_items = AsyncMock(return_value=inbox)
    delivery_repository.claim_batch = AsyncMock(return_value=SimpleNamespace(id=19))
    document_service = MagicMock()
    document_service.build_and_process = AsyncMock(
        return_value=BundleDocumentHandlerResult(document=document)
    )
    dispatcher = MagicMock()
    dispatcher.prepare_subscription_entry = AsyncMock(
        return_value=SimpleNamespace(
            effective_content="resolved aggregate",
            effective_media_urls=["https://example.com/resolved.jpg"],
            effective_media_items=[("image", "https://example.com/resolved.jpg")],
            effective_layout=[],
            effective_send_mode=1,
            effective_style=2,
            notify=True,
        )
    )
    orchestrator = MagicMock()
    orchestrator.run = AsyncMock(return_value=SimpleNamespace(ready_to_confirm=False))
    user = SimpleNamespace(id="user-1")
    user_repository = MagicMock(get_by_id=AsyncMock(return_value=user))
    service = BundleBatchDeliveryService(
        delivery_repository=delivery_repository,
        bundle_repository=MagicMock(
            get_by_id=AsyncMock(return_value=bundle),
            list_members=AsyncMock(return_value=members),
        ),
        feed_repository=MagicMock(get_by_id=AsyncMock(return_value=feed)),
        template_repository=MagicMock(),
        template_service=MagicMock(),
        document_service=document_service,
        output_orchestrator=orchestrator,
        notification_dispatcher=dispatcher,
        user_repository=user_repository,
    )

    await service.deliver(7)

    standard = delivery_repository.claim_batch.await_args.args[2][0]
    assert standard.content == "resolved aggregate"
    assert standard.media_urls == ["https://example.com/resolved.jpg"]
    assert standard.source_context["send"]["send_mode"] == 1
    assert standard.source_context["send"]["style"] == 2
    dispatcher.prepare_subscription_entry.assert_awaited_once()
    assert dispatcher.prepare_subscription_entry.await_args.kwargs["user"] is user


@pytest.mark.asyncio
async def test_deliver_reuses_pending_batch_and_does_not_claim_new_inbox() -> None:
    pending = SimpleNamespace(id=19, status="pending")
    delivery_repository = MagicMock()
    delivery_repository.get_pending_batch = AsyncMock(return_value=pending)
    delivery_repository.reconcile_batch = AsyncMock(return_value=pending)
    delivery_repository.list_inbox_items = AsyncMock()
    delivery_repository.claim_batch = AsyncMock()
    orchestrator = MagicMock()
    orchestrator.run = AsyncMock(return_value=SimpleNamespace(ready_to_confirm=False))
    service = BundleBatchDeliveryService(
        delivery_repository=delivery_repository,
        bundle_repository=MagicMock(),
        feed_repository=MagicMock(),
        template_repository=MagicMock(),
        template_service=MagicMock(),
        document_service=MagicMock(),
        output_orchestrator=orchestrator,
    )

    result = await service.deliver(7, retry_failed=True)

    assert result.batch_id == 19
    orchestrator.run.assert_awaited_once_with(pending, retry_failed=True)
    delivery_repository.list_inbox_items.assert_not_awaited()
    delivery_repository.claim_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_reconciles_resolved_pending_batch_before_running_outputs() -> (
    None
):
    pending = SimpleNamespace(id=19, status="pending")
    confirmed = SimpleNamespace(id=19, status="confirmed")
    delivery_repository = MagicMock()
    delivery_repository.get_pending_batch = AsyncMock(return_value=pending)
    delivery_repository.reconcile_batch = AsyncMock(return_value=confirmed)
    delivery_repository.confirm_batch = AsyncMock()
    orchestrator = MagicMock()
    orchestrator.run = AsyncMock()
    service = BundleBatchDeliveryService(
        delivery_repository=delivery_repository,
        bundle_repository=MagicMock(),
        feed_repository=MagicMock(),
        template_repository=MagicMock(),
        template_service=MagicMock(),
        document_service=MagicMock(),
        output_orchestrator=orchestrator,
    )

    result = await service.deliver(7, retry_failed=True)

    assert result.batch_id == 19
    assert result.ready_to_confirm is True
    delivery_repository.reconcile_batch.assert_awaited_once_with(19)
    orchestrator.run.assert_not_awaited()
    delivery_repository.confirm_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_leaves_per_member_history_limit_backlog_unclaimed() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Limited",
        target_sessions=["test:Group:1"],
        interval=30,
        state=1,
    )
    members = [BundleFeed(id=101, bundle_id=7, feed_id=11, position=0)]
    inbox = [_inbox(201, 101, 11, "first"), _inbox(202, 101, 11, "second")]
    document = BundleAggregateDocument(
        entries=(),
        text="first",
        rss_xml="<rss version='2.0' />",
        consumption_item_keys=("first",),
    )
    delivery_repository = MagicMock()
    delivery_repository.get_pending_batch = AsyncMock(return_value=None)
    delivery_repository.list_inbox_items = AsyncMock(return_value=inbox)
    delivery_repository.claim_batch = AsyncMock(return_value=SimpleNamespace(id=19))
    document_service = MagicMock()
    document_service.build_and_process = AsyncMock(
        return_value=BundleDocumentHandlerResult(
            document=document,
        )
    )
    orchestrator = MagicMock()
    orchestrator.run = AsyncMock(return_value=SimpleNamespace(ready_to_confirm=False))
    service = BundleBatchDeliveryService(
        delivery_repository=delivery_repository,
        bundle_repository=MagicMock(
            get_by_id=AsyncMock(return_value=bundle),
            list_members=AsyncMock(return_value=members),
        ),
        feed_repository=MagicMock(
            get_by_id=AsyncMock(
                return_value=Feed(id=11, title="One", link="https://example.com/one")
            )
        ),
        template_repository=MagicMock(),
        template_service=MagicMock(),
        document_service=document_service,
        output_orchestrator=orchestrator,
        history_entry_limit=1,
    )

    await service.deliver(7)

    assert delivery_repository.claim_batch.await_args.kwargs["item_ids"] == [201]


def test_bundle_skipped_output_is_completed() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Blocked",
        target_sessions=["test:Group:1"],
        interval=30,
        state=1,
    )
    member = BundleFeed(id=101, bundle_id=7, feed_id=11, position=0)
    feed = Feed(id=11, title="One", link="https://example.com/one")
    service = BundleBatchDeliveryService(
        delivery_repository=MagicMock(),
        bundle_repository=MagicMock(),
        feed_repository=MagicMock(),
        template_repository=MagicMock(),
        template_service=MagicMock(),
        document_service=MagicMock(),
        output_orchestrator=MagicMock(),
    )

    output = service._history(
        bundle=bundle,
        members=[member],
        target_session="test:Group:1",
        output_kind="standard",
        output_order=0,
        status="skipped",
        document_snapshot={
            "entries": [],
            "document": {"text": "", "rss_xml": ""},
        },
        template_snapshot=None,
        feeds={11: feed},
        handler_trace=(),
        send_payload=BundleSendPayload(
            content="",
            media_urls=None,
            media_items=None,
            layout=[],
            send_mode=0,
            style=0,
            notify=True,
        ),
        reason="文档被 handler 拒绝",
    )

    assert output.status == "skipped"
    assert output.completed_at is not None
    assert output.max_retries == 0


@pytest.mark.asyncio
async def test_bundle_output_executor_replays_frozen_standard_payload() -> None:
    history = PushHistory(
        id=31,
        batch_id=19,
        bundle_id=7,
        user_id="user-1",
        source_type="bundle",
        output_kind="standard",
        output_order=0,
        target_session="test:Group:1",
        platform_name="test",
        feed_title="Daily",
        feed_link="https://example.com/one",
        source_context={
            "send": {
                "content": "frozen digest",
                "media_urls": ["https://example.com/image.jpg"],
                "media_items": [("image", "https://example.com/image.jpg")],
                "layout": [],
                "send_mode": 1,
                "style": 2,
            }
        },
    )
    dispatcher = MagicMock()
    dispatcher.send_to_session = AsyncMock(return_value={"ok": True})
    executor = BundleOutputExecutor(
        notification_dispatcher=dispatcher,
        card_renderer=MagicMock(),
    )

    result = await executor.execute(history)

    assert result.ok is True
    dispatcher.send_to_session.assert_awaited_once()
    kwargs = dispatcher.send_to_session.await_args.kwargs
    assert kwargs["content"] == "frozen digest"
    assert kwargs["media_items"] == [("image", "https://example.com/image.jpg")]
    assert kwargs["sub_id"] is None
    assert kwargs["feed_id"] is None


@pytest.mark.asyncio
async def test_bundle_output_executor_renders_card_from_frozen_bundle_context() -> None:
    history = PushHistory(
        id=32,
        batch_id=19,
        bundle_id=7,
        user_id="user-1",
        source_type="bundle",
        output_kind="card",
        output_order=0,
        target_session="test:Group:1",
        platform_name="test",
        feed_title="Daily",
        source_context={
            "template_snapshot": CardTemplateSnapshot(
                metadata=CardTemplateMetadata(
                    id="astrbot_plugin_rsshub_card_bundle",
                    name="Bundle",
                    version="1.0.0",
                    author="Test",
                    description="Test",
                    repository="https://example.com/template",
                    targets=["bundle"],
                ),
                templates={"template.html": "{{ bundle.name }}"},
            ).model_dump(mode="json"),
            "document_snapshot": {
                "entries": [],
                "document": {"text": "", "rss_xml": "<rss version='2.0' />"},
                "rendered_at": "2026-08-24T00:00:00+00:00",
            },
            "bundle": {"id": 7, "name": "Daily"},
            "feeds": [
                {
                    "id": 11,
                    "title": "One",
                    "link": "https://example.com/one",
                    "position": 0,
                }
            ],
        },
    )
    dispatcher = MagicMock()
    dispatcher.send_to_session = AsyncMock(return_value={"ok": True})
    renderer = MagicMock()
    renderer.render = AsyncMock(
        return_value=SimpleNamespace(png_path=Path("/tmp/bundle-card.png"))
    )
    executor = BundleOutputExecutor(
        notification_dispatcher=dispatcher,
        card_renderer=renderer,
    )

    result = await executor.execute(history)

    assert result.ok is True
    render_context = renderer.render.await_args.args[2]
    assert render_context["source"] == {"type": "bundle", "owner_id": 7}
    assert render_context["bundle"] == {"id": 7, "name": "Daily"}
    assert render_context["feeds"][0]["position"] == 0
    kwargs = dispatcher.send_to_session.await_args.kwargs
    assert kwargs["content"] == ""
    assert kwargs["media_items"] == [("image", "file:///tmp/bundle-card.png")]
