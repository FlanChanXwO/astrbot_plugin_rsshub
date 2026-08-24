from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.services.subscription_card_management_service import (
    SubscriptionCardManagementService,
)
from astrbot_plugin_rsshub.src.domain.entities.card_template import CardTemplateMetadata
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription
from astrbot_plugin_rsshub.src.domain.repositories.delivery_repository import (
    DeliveryDeletionBlockedError,
)
from astrbot_plugin_rsshub.src.infrastructure.fetcher.rss.models import EntryParsed


def _metadata(
    template_id: str,
    *,
    targets: list[str] | None = None,
    feed_patterns: list[str] | None = None,
) -> CardTemplateMetadata:
    return CardTemplateMetadata(
        id=template_id,
        name=template_id.removeprefix("astrbot_plugin_rsshub_card_"),
        version="1.0.0",
        author="tester",
        description="test template",
        repository="https://example.com/template",
        targets=targets or ["feed"],
        feed_patterns=feed_patterns or [],
    )


@pytest.mark.asyncio
async def test_lists_only_templates_matching_subscription_feed() -> None:
    subscription_repo = AsyncMock()
    subscription_repo.get_by_id.return_value = Subscription(
        id=7,
        user_id="u1",
        feed_id=3,
    )
    feed_repo = AsyncMock()
    feed_repo.get_by_id.return_value = Feed(
        id=3,
        link="https://rsshub.app/juya/ai",
    )
    matching = _metadata(
        "astrbot_plugin_rsshub_card_juya",
        feed_patterns=[r"/juya/ai$"],
    )
    wrong_feed = _metadata(
        "astrbot_plugin_rsshub_card_other",
        feed_patterns=[r"/other$"],
    )
    wrong_target = _metadata(
        "astrbot_plugin_rsshub_card_bundle",
        targets=["bundle"],
    )
    template_repo = MagicMock()
    template_repo.list_packages.return_value = [
        SimpleNamespace(metadata=wrong_feed),
        SimpleNamespace(metadata=matching),
        SimpleNamespace(metadata=wrong_target),
    ]

    service = SubscriptionCardManagementService(
        subscription_repository=subscription_repo,
        feed_repository=feed_repo,
        template_repository=template_repo,
    )

    options = await service.list_template_options(subscription_id=7, user_id="u1")

    assert [option.id for option in options] == [matching.id]
    assert options[0].name == "juya"


@pytest.mark.asyncio
async def test_enabling_card_requires_a_matching_template() -> None:
    subscription_repo = AsyncMock()
    subscription_repo.get_by_id.return_value = Subscription(
        id=7,
        user_id="u1",
        feed_id=3,
    )
    feed_repo = AsyncMock()
    feed_repo.get_by_id.return_value = Feed(
        id=3,
        link="https://rsshub.app/juya/ai",
    )
    template_repo = MagicMock()
    template_repo.get.return_value = None
    service = SubscriptionCardManagementService(
        subscription_repository=subscription_repo,
        feed_repository=feed_repo,
        template_repository=template_repo,
    )

    with pytest.raises(ValueError, match="模板"):
        await service.update_configuration(
            subscription_id=7,
            user_id="u1",
            send_card=True,
            template_id=None,
        )

    subscription_repo.update_options.assert_not_awaited()


@pytest.mark.asyncio
async def test_updates_valid_card_configuration_from_candidate() -> None:
    subscription = Subscription(id=7, user_id="u1", feed_id=3)
    subscription_repo = AsyncMock()
    subscription_repo.get_by_id.return_value = subscription
    subscription_repo.update_options.return_value = subscription.model_copy(
        update={
            "send_card": True,
            "template_id": "astrbot_plugin_rsshub_card_juya",
            "card_send_original_content": True,
        }
    )
    feed_repo = AsyncMock()
    feed_repo.get_by_id.return_value = Feed(
        id=3,
        link="https://rsshub.app/juya/ai",
    )
    template_repo = MagicMock()
    template_repo.get.return_value = SimpleNamespace(
        metadata=_metadata(
            "astrbot_plugin_rsshub_card_juya",
            feed_patterns=[r"/juya/ai$"],
        )
    )
    service = SubscriptionCardManagementService(
        subscription_repository=subscription_repo,
        feed_repository=feed_repo,
        template_repository=template_repo,
    )

    updated = await service.update_configuration(
        subscription_id=7,
        user_id="u1",
        send_card=True,
        template_id="astrbot_plugin_rsshub_card_juya",
        card_send_original_content=True,
    )

    assert updated.send_card is True
    subscription_repo.update_options.assert_awaited_once_with(
        7,
        "u1",
        send_card=True,
        template_id="astrbot_plugin_rsshub_card_juya",
        card_send_original_content=True,
    )


@pytest.mark.asyncio
async def test_unresolved_delivery_blocks_disabling_card() -> None:
    subscription_repo = AsyncMock()
    subscription_repo.get_by_id.return_value = Subscription(
        id=7,
        user_id="u1",
        feed_id=3,
        send_card=True,
        template_id="astrbot_plugin_rsshub_card_juya",
    )
    feed_repo = AsyncMock()
    feed_repo.get_by_id.return_value = Feed(id=3, link="https://rsshub.app/juya/ai")
    delivery_repo = AsyncMock()
    delivery_repo.ensure_owner_deletable.side_effect = DeliveryDeletionBlockedError(
        {"pending_batch": 1}
    )
    service = SubscriptionCardManagementService(
        subscription_repository=subscription_repo,
        feed_repository=feed_repo,
        template_repository=MagicMock(),
        delivery_repository=delivery_repo,
    )

    with pytest.raises(DeliveryDeletionBlockedError):
        await service.update_configuration(
            subscription_id=7,
            user_id="u1",
            send_card=False,
        )

    subscription_repo.update_options.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_renders_current_handlers_without_business_writes() -> None:
    subscription_repo = AsyncMock()
    subscription_repo.get_by_id.return_value = Subscription(
        id=7,
        user_id="u1",
        feed_id=3,
        handlers_mode="override",
    )
    feed_repo = AsyncMock()
    feed_repo.get_by_id.return_value = Feed(
        id=3,
        title="Juya AI",
        link="https://rsshub.app/juya/ai",
    )
    metadata = _metadata(
        "astrbot_plugin_rsshub_card_juya",
        feed_patterns=[r"/juya/ai$"],
    )
    package = SimpleNamespace(metadata=metadata)
    template_repo = MagicMock()
    template_repo.get.return_value = package
    polling_service = AsyncMock()
    polling_service.fetch_feed_entries.return_value = SimpleNamespace(
        success=True,
        message="ok",
        error="",
        entries=[
            EntryParsed(
                id="entry-1",
                title="Before handler",
                link="https://example.com/1",
                content="original",
            )
        ],
    )
    handler_runtime = AsyncMock()
    handler_runtime.process_entry_with_trace.return_value = SimpleNamespace(
        allow=True,
        entry=SimpleNamespace(
            title="After handler",
            link="https://example.com/1",
            author="",
            summary="",
            content="transformed",
            media_items=(),
        ),
        trace=(),
    )
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = None
    template_service = MagicMock()
    template_service.snapshot.return_value = "snapshot"
    template_service.render.return_value = "<html>preview</html>"
    image_renderer = AsyncMock()
    image_renderer.render.return_value = b"png-preview"
    service = SubscriptionCardManagementService(
        subscription_repository=subscription_repo,
        feed_repository=feed_repo,
        template_repository=template_repo,
        polling_service=polling_service,
        user_repository=user_repo,
        content_handler_runtime=handler_runtime,
        template_service=template_service,
        image_renderer=image_renderer,
    )

    preview = await service.preview(
        subscription_id=7,
        user_id="u1",
        template_id=metadata.id,
    )

    assert preview.png == b"png-preview"
    assert preview.entry_count == 1
    assert preview.template == {
        "id": metadata.id,
        "name": metadata.name,
        "version": metadata.version,
        "author": metadata.author,
    }
    assert preview.source_summary == {
        "feed_id": 3,
        "feed_title": "Juya AI",
        "feed_link": "https://rsshub.app/juya/ai",
        "entry_count": 1,
    }
    render_context = template_service.render.call_args.args[1]
    assert render_context["entries"][0]["title"] == "After handler"
    assert render_context["document"]["text"] == "transformed"
    subscription_repo.update_options.assert_not_awaited()
    feed_repo.save.assert_not_awaited()
