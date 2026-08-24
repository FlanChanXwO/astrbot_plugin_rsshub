"""卡片 Subscription 可靠批次服务测试。"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from astrbot_plugin_rsshub.src.application.services.content_handlers import (
    EntryContentContext,
    HandlerProcessResult,
)
from astrbot_plugin_rsshub.src.application.services.notification_dispatcher import (
    PreparedSubscriptionDispatch,
)
from astrbot_plugin_rsshub.src.application.services.subscription_batch_delivery_service import (
    SubscriptionBatchDeliveryService,
)
from astrbot_plugin_rsshub.src.domain.entities.delivery import (
    DeliveryInboxItem,
    DeliveryOwner,
)
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription
from astrbot_plugin_rsshub.src.domain.entities.user import User
from astrbot_plugin_rsshub.src.infrastructure.templates.repository import (
    CardTemplatePackage,
)


@pytest.mark.asyncio
async def test_claims_post_handler_snapshot_for_card_only_batch(tmp_path) -> None:
    owner = DeliveryOwner(owner_type="subscription", owner_id=7)
    inbox = DeliveryInboxItem(
        id=11,
        owner=owner,
        feed_id=3,
        item_key="entry-1",
        hash_group=["entry-1"],
        discovery_key="discovery-1",
        entry_payload={
            "title": "原始标题",
            "link": "https://example.com/posts/1",
            "summary": "原始摘要",
            "author": "作者",
        },
        raw_xml="<item><title>原始标题</title></item>",
        published_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )
    second_inbox = DeliveryInboxItem(
        id=12,
        owner=owner,
        feed_id=3,
        item_key="entry-2",
        hash_group=["entry-2"],
        discovery_key="discovery-1",
        entry_payload={
            "title": "第二标题",
            "link": "https://example.com/posts/2",
            "summary": "第二摘要",
            "author": "作者",
        },
        raw_xml="<item><title>第二标题</title></item>",
        published_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
    subscription = Subscription(
        id=7,
        user_id="user-1",
        feed_id=3,
        target_session="platform:GroupMessage:1",
        platform_name="test",
        send_card=True,
        template_id="astrbot_plugin_rsshub_card_demo",
    )
    package = CardTemplatePackage(
        metadata=MagicMock(
            id="astrbot_plugin_rsshub_card_demo",
            matches_owner=MagicMock(return_value=True),
        ),
        root=tmp_path,
        origin="installed",
    )
    processed = EntryContentContext(
        title="变换后标题",
        summary="变换后摘要",
        content="变换后正文",
        link="https://example.com/posts/1",
        author="作者",
        feed_title="Feed",
        feed_link="https://example.com/feed",
        media_items=(("image", "https://example.com/transformed.jpg"),),
    )
    handler_runtime = MagicMock()
    handler_runtime.process_entry_with_trace = AsyncMock(
        return_value=HandlerProcessResult(
            entry=processed,
            trace=({"name": "ai_transform", "status": "ok"},),
        )
    )
    delivery_repository = MagicMock()
    delivery_repository.get_pending_batch = AsyncMock(return_value=None)
    delivery_repository.list_inbox_items = AsyncMock(return_value=[inbox, second_inbox])
    delivery_repository.claim_batch = AsyncMock(
        side_effect=lambda _o, b, outputs: MagicMock(
            id=19,
            owner=owner,
            document_snapshot=b.document_snapshot,
            template_snapshot=b.template_snapshot,
            outputs=list(outputs),
        )
    )
    delivery_repository.confirm_batch = AsyncMock()
    orchestrator = MagicMock()
    orchestrator.run = AsyncMock(return_value=MagicMock(ready_to_confirm=False))
    template_service = MagicMock()
    template_service.snapshot.return_value = MagicMock(
        model_dump=lambda mode: {"template": "snapshot"}
    )

    service = SubscriptionBatchDeliveryService(
        delivery_repository=delivery_repository,
        subscription_repository=MagicMock(
            get_by_id=AsyncMock(return_value=subscription)
        ),
        feed_repository=MagicMock(
            get_by_id=AsyncMock(
                return_value=Feed(id=3, link="https://example.com/feed", title="Feed")
            )
        ),
        user_repository=MagicMock(get_by_id=AsyncMock(return_value=User(id="user-1"))),
        template_repository=MagicMock(get=MagicMock(return_value=package)),
        template_service=template_service,
        content_handler_runtime=handler_runtime,
        notification_dispatcher=MagicMock(),
        output_orchestrator=orchestrator,
        max_retries=5,
    )

    result = await service.deliver(7)

    assert result.batch_id == 19
    claim = delivery_repository.claim_batch.await_args
    batch_draft = claim.args[1]
    assert batch_draft.document_snapshot["entries"][0]["title"] == "变换后标题"
    assert batch_draft.document_snapshot["entries"][0]["summary"] == "变换后摘要"
    assert batch_draft.document_snapshot["entries"][0]["media_items"] == [
        {"type": "image", "url": "https://example.com/transformed.jpg"}
    ]
    assert batch_draft.document_snapshot["document"]["text"] == (
        "变换后正文\n\n变换后正文"
    )
    assert batch_draft.document_snapshot["handler_traces"] == [
        [{"name": "ai_transform", "status": "ok"}],
        [{"name": "ai_transform", "status": "ok"}],
    ]
    assert batch_draft.document_snapshot["input_entries"] == [
        {
            "item_key": "entry-1",
            "raw_xml": "<item><title>原始标题</title></item>",
        },
        {
            "item_key": "entry-2",
            "raw_xml": "<item><title>第二标题</title></item>",
        },
    ]
    outputs = claim.args[2]
    assert [(item.output_kind, item.status) for item in outputs] == [
        ("card", "waiting")
    ]
    assert outputs[0].max_retries == 5
    assert outputs[0].feed_title == "Feed"
    assert outputs[0].feed_link == "https://example.com/feed"
    orchestrator.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_active_card_subscriptions_uses_batch_retry_path() -> None:
    subscriptions = [
        Subscription(id=7, user_id="u", feed_id=3, send_card=True),
        Subscription(id=8, user_id="u", feed_id=3, send_card=True),
        Subscription(id=9, user_id="u", feed_id=3, send_card=False),
    ]
    service = SubscriptionBatchDeliveryService(
        delivery_repository=MagicMock(),
        subscription_repository=MagicMock(
            get_all_active=AsyncMock(return_value=subscriptions)
        ),
        feed_repository=MagicMock(),
        user_repository=MagicMock(),
        template_repository=MagicMock(),
        template_service=MagicMock(),
        content_handler_runtime=MagicMock(),
        notification_dispatcher=MagicMock(),
        output_orchestrator=MagicMock(),
    )
    service.deliver = AsyncMock(side_effect=[RuntimeError("owner 7 failed"), None])

    await service.retry_active_batches()

    assert service.deliver.await_args_list == [
        call(7, retry_failed=True),
        call(8, retry_failed=True),
    ]


@pytest.mark.asyncio
async def test_manual_retry_forces_exhausted_subscription_outputs() -> None:
    pending_batch = SimpleNamespace(id=19)
    delivery_repository = MagicMock()
    delivery_repository.get_pending_batch = AsyncMock(return_value=pending_batch)
    orchestrator = MagicMock()
    orchestrator.run = AsyncMock(return_value=SimpleNamespace(ready_to_confirm=False))
    service = SubscriptionBatchDeliveryService(
        delivery_repository=delivery_repository,
        subscription_repository=MagicMock(),
        feed_repository=MagicMock(),
        user_repository=MagicMock(),
        template_repository=MagicMock(),
        template_service=MagicMock(),
        content_handler_runtime=MagicMock(),
        notification_dispatcher=MagicMock(),
        output_orchestrator=orchestrator,
    )

    result = await service.retry(7)

    assert result.batch_id == 19
    orchestrator.run.assert_awaited_once_with(
        pending_batch,
        retry_failed=True,
        force_retry=True,
    )


@pytest.mark.asyncio
async def test_original_outputs_use_newest_limit_and_frozen_dispatch_payload() -> None:
    owner = DeliveryOwner(owner_type="subscription", owner_id=7)
    old = DeliveryInboxItem(
        id=11,
        owner=owner,
        feed_id=3,
        item_key="old",
        hash_group=["old"],
        discovery_key="discovery",
        entry_payload={"title": "Old", "link": "https://example.com/old"},
        published_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
    new = DeliveryInboxItem(
        id=12,
        owner=owner,
        feed_id=3,
        item_key="new",
        hash_group=["new"],
        discovery_key="discovery",
        entry_payload={"title": "New", "link": "https://example.com/new"},
        raw_xml="<item><title>New</title></item>",
        published_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )
    subscription = Subscription(
        id=7,
        user_id="user-1",
        feed_id=3,
        target_session="platform:GroupMessage:1",
        platform_name="test",
        send_card=True,
        template_id="astrbot_plugin_rsshub_card_demo",
        card_send_original_content=True,
    )
    feed = Feed(id=3, link="https://example.com/feed", title="Feed")
    handler_runtime = MagicMock()

    async def handle(**kwargs):
        return HandlerProcessResult(entry=kwargs["entry"])

    handler_runtime.process_entry_with_trace = AsyncMock(side_effect=handle)
    dispatcher = MagicMock()

    async def prepare(**kwargs):
        entry = kwargs["entry"]
        return PreparedSubscriptionDispatch(
            subscription=subscription,
            processed_entry=entry,
            handler_trace=None,
            effective_title=entry.title,
            effective_link=entry.link,
            effective_content=f"prepared:{entry.title}",
            effective_send_mode=1,
            effective_style=2,
            effective_media_urls=["https://example.com/image.jpg"],
            effective_media_items=[("image", "https://example.com/image.jpg")],
            effective_layout=None,
            persisted_media_urls=["https://example.com/image.jpg"],
        )

    dispatcher.prepare_subscription_entry = AsyncMock(side_effect=prepare)
    delivery_repository = MagicMock()
    delivery_repository.get_pending_batch = AsyncMock(return_value=None)
    delivery_repository.list_inbox_items = AsyncMock(return_value=[old, new])
    delivery_repository.claim_batch = AsyncMock(
        side_effect=lambda _owner, _draft, outputs: SimpleNamespace(
            id=19, outputs=list(outputs)
        )
    )
    orchestrator = MagicMock(
        run=AsyncMock(return_value=SimpleNamespace(ready_to_confirm=False))
    )
    snapshot = SimpleNamespace(model_dump=lambda mode: {"snapshot": True})
    package = SimpleNamespace(
        metadata=SimpleNamespace(
            id=subscription.template_id,
            matches_owner=lambda **_kwargs: True,
        )
    )
    service = SubscriptionBatchDeliveryService(
        delivery_repository=delivery_repository,
        subscription_repository=MagicMock(
            get_by_id=AsyncMock(return_value=subscription)
        ),
        feed_repository=MagicMock(get_by_id=AsyncMock(return_value=feed)),
        user_repository=MagicMock(get_by_id=AsyncMock(return_value=None)),
        template_repository=MagicMock(get=MagicMock(return_value=package)),
        template_service=MagicMock(snapshot=MagicMock(return_value=snapshot)),
        content_handler_runtime=handler_runtime,
        notification_dispatcher=dispatcher,
        output_orchestrator=orchestrator,
        history_entry_limit=1,
    )

    await service.deliver(7)

    outputs = delivery_repository.claim_batch.await_args.args[2]
    assert [(output.output_kind, output.entry_guid) for output in outputs] == [
        ("card", None),
        ("standard", "new"),
    ]
    assert outputs[1].source_context["send"] == {
        "content": "prepared:New",
        "media_urls": ["https://example.com/image.jpg"],
        "media_items": [("image", "https://example.com/image.jpg")],
        "layout": [],
        "send_mode": 1,
        "style": 2,
    }
    assert outputs[1].source_context["input_xml"] == ("<item><title>New</title></item>")
