from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.domain.entities.bundle import Bundle
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.domain.repositories.delivery_repository import (
    DeliveryDeletionBlockedError,
)


@pytest.mark.asyncio
async def test_create_validates_all_feed_ids_before_persisting() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    bundle_repository = MagicMock()
    bundle_repository.get_by_user = AsyncMock(return_value=[])
    bundle_repository.save = AsyncMock()
    feed_repository = MagicMock()
    feed_repository.get_by_ids = AsyncMock(
        return_value=[Feed(id=1, link="https://example.com/one")]
    )

    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=feed_repository,
    )

    result = await command.create(
        user_id="user-1",
        name="Daily",
        feed_ids=[1, 2],
        target_sessions=["telegram:group:1"],
        interval=10,
    )

    assert result.success is False
    assert "Feed" in result.message
    bundle_repository.save.assert_not_awaited()
    bundle_repository.replace_members.assert_not_called()


@pytest.mark.asyncio
async def test_create_rejects_partial_target_list_before_persisting() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    bundle_repository = MagicMock()
    bundle_repository.get_by_user = AsyncMock(return_value=[])
    bundle_repository.save = AsyncMock()
    feed_repository = MagicMock()
    feed_repository.get_by_ids = AsyncMock(
        return_value=[
            Feed(id=1, link="https://example.com/one"),
            Feed(id=2, link="https://example.com/two"),
        ]
    )

    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=feed_repository,
    )

    result = await command.create(
        user_id="user-1",
        name="Daily",
        feed_ids=[1, 2],
        target_sessions=["telegram:group:1", ""],
        interval=10,
    )

    assert result.success is False
    assert "目标会话" in result.message
    bundle_repository.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_cleans_up_owner_if_member_persistence_fails() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    saved = Bundle(
        id=7,
        user_id="user-1",
        name="Daily",
        target_sessions=["telegram:group:1"],
        interval=10,
    )
    bundle_repository = MagicMock()
    bundle_repository.get_by_user = AsyncMock(return_value=[])
    bundle_repository.save = AsyncMock(return_value=saved)
    bundle_repository.replace_members = AsyncMock(
        side_effect=ValueError("member transaction failed")
    )
    bundle_repository.delete = AsyncMock(return_value=True)
    feed_repository = MagicMock()
    feed_repository.get_by_ids = AsyncMock(
        return_value=[
            Feed(id=1, link="https://example.com/one"),
            Feed(id=2, link="https://example.com/two"),
        ]
    )

    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=feed_repository,
    )

    result = await command.create(
        user_id="user-1",
        name="Daily",
        feed_ids=[1, 2],
        target_sessions=["telegram:group:1"],
        interval=10,
    )

    assert result.success is False
    bundle_repository.delete.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_set_card_configuration_requires_matching_template() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Daily",
        target_sessions=["telegram:group:1"],
        interval=10,
        send_card=False,
    )
    bundle_repository = MagicMock()
    bundle_repository.get_by_id = AsyncMock(return_value=bundle)
    bundle_repository.list_members = AsyncMock(
        return_value=[
            SimpleNamespace(feed_id=1, id=101, position=0),
            SimpleNamespace(feed_id=2, id=102, position=1),
        ]
    )
    bundle_repository.save = AsyncMock(return_value=bundle)
    feed_repository = MagicMock()
    feed_repository.get_by_ids = AsyncMock(
        return_value=[
            Feed(id=1, link="https://example.com/one"),
            Feed(id=2, link="https://example.com/two"),
        ]
    )
    template_repository = MagicMock()
    template_repository.get.return_value = None

    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=feed_repository,
        template_repository=template_repository,
    )

    result = await command.set_option(
        bundle_id=7,
        user_id="user-1",
        option="send_card",
        value="true",
    )

    assert result.success is False
    assert "模板" in result.message
    bundle_repository.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_card_configuration_turns_invalid_template_id_into_result() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Daily",
        target_sessions=["telegram:group:1"],
        interval=10,
    )
    bundle_repository = MagicMock()
    bundle_repository.get_by_id = AsyncMock(return_value=bundle)
    bundle_repository.get_by_user = AsyncMock(return_value=[bundle])
    bundle_repository.list_members = AsyncMock(
        return_value=[SimpleNamespace(feed_id=1, id=101, position=0)]
    )
    bundle_repository.save = AsyncMock(return_value=bundle)
    feed_repository = MagicMock()
    feed_repository.get_by_ids = AsyncMock(
        return_value=[Feed(id=1, link="https://example.com/one")]
    )
    template_repository = MagicMock()
    template_repository.get.side_effect = ValueError("invalid template id")

    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=feed_repository,
        template_repository=template_repository,
    )

    result = await command.set(
        bundle_id=7,
        user_id="user-1",
        options={"send_card": True, "template_id": "invalid"},
    )

    assert result.success is False
    assert "模板" in result.message
    bundle_repository.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_bundle_test_uses_read_only_fetches() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    bundle = Bundle(
        id=7,
        user_id="owner",
        name="Daily",
        target_sessions=["telegram:group:1"],
        interval=10,
    )
    bundle_repository = MagicMock()
    bundle_repository.get_by_id = AsyncMock(return_value=bundle)
    bundle_repository.list_members = AsyncMock(
        return_value=[SimpleNamespace(feed_id=1, id=101, position=0)]
    )
    feed_repository = MagicMock()
    feed_repository.get_by_id = AsyncMock(
        return_value=Feed(id=1, link="https://example.com/one")
    )
    polling_service = MagicMock()
    polling_service.fetch_feed_entries = AsyncMock(
        return_value=SimpleNamespace(success=True, entries=[object()], message="ok")
    )
    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=feed_repository,
        polling_service=polling_service,
    )

    result = await command.test(bundle_id=7, user_id="admin", is_admin=True)

    assert result.success is True
    assert "1" in result.message
    polling_service.fetch_feed_entries.assert_awaited_once_with(
        "https://example.com/one"
    )


@pytest.mark.asyncio
async def test_bundle_commands_enforce_owner_before_delete() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    bundle_repository = MagicMock()
    bundle_repository.get_by_id = AsyncMock(
        return_value=Bundle(
            id=7,
            user_id="owner",
            name="Daily",
            target_sessions=["telegram:group:1"],
            interval=10,
        )
    )
    bundle_repository.delete = AsyncMock()

    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=MagicMock(),
    )

    result = await command.delete(bundle_id=7, user_id="intruder")

    assert result.success is False
    assert "无权" in result.message
    bundle_repository.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_uses_one_atomic_replacement_and_reports_backlog_blocker() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    bundle_repository = MagicMock()
    bundle_repository.get_by_id = AsyncMock(
        return_value=Bundle(
            id=7,
            user_id="owner",
            name="Daily",
            target_sessions=["telegram:group:1"],
            interval=10,
        )
    )
    bundle_repository.list_members = AsyncMock(
        return_value=[
            SimpleNamespace(id=101, feed_id=1, position=0),
            SimpleNamespace(id=102, feed_id=2, position=1),
            SimpleNamespace(id=103, feed_id=3, position=2),
        ]
    )
    bundle_repository.replace_members = AsyncMock(
        side_effect=DeliveryDeletionBlockedError({"unclaimed_inbox": 2})
    )

    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=MagicMock(),
    )

    result = await command.remove(bundle_id=7, user_id="owner", member_ids=[101, 102])

    assert result.success is False
    assert "未解决" in result.message or "可靠投递" in result.message
    bundle_repository.replace_members.assert_awaited_once_with(7, [3])


@pytest.mark.asyncio
async def test_set_template_is_ignored_when_cards_are_disabled() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    bundle = Bundle(
        id=7,
        user_id="owner",
        name="Daily",
        target_sessions=["telegram:group:1"],
        interval=10,
        send_card=False,
    )
    bundle_repository = MagicMock()
    bundle_repository.get_by_id = AsyncMock(return_value=bundle)
    bundle_repository.list_members = AsyncMock(return_value=[])
    bundle_repository.save = AsyncMock(return_value=bundle)
    template_repository = MagicMock()

    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=MagicMock(),
        template_repository=template_repository,
    )

    result = await command.set_option(
        bundle_id=7,
        user_id="owner",
        option="template_id",
        value="not-a-template",
    )

    assert result.success is True
    template_repository.get.assert_not_called()
    bundle_repository.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_name_rejects_another_owned_bundle_before_save() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    current = Bundle(
        id=7,
        user_id="owner",
        name="Daily",
        target_sessions=["telegram:group:1"],
        interval=10,
    )
    other = Bundle(
        id=8,
        user_id="owner",
        name="Weekly",
        target_sessions=["telegram:group:1"],
        interval=10,
    )
    bundle_repository = MagicMock()
    bundle_repository.get_by_id = AsyncMock(return_value=current)
    bundle_repository.get_by_user = AsyncMock(return_value=[current, other])
    bundle_repository.save = AsyncMock()

    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=MagicMock(),
    )

    result = await command.set_option(
        bundle_id=7,
        user_id="owner",
        option="name",
        value="Weekly",
    )

    assert result.success is False
    assert "名称已存在" in result.message
    bundle_repository.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_members_validates_all_feeds_before_atomic_write() -> None:
    from astrbot_plugin_rsshub.src.application.commands.bundle_cmd import (
        BundleCommand,
    )

    bundle_repository = MagicMock()
    bundle_repository.get_by_id = AsyncMock(
        return_value=Bundle(
            id=7,
            user_id="owner",
            name="Daily",
            target_sessions=["telegram:group:1"],
            interval=10,
        )
    )
    bundle_repository.replace_members = AsyncMock()
    feed_repository = MagicMock()
    feed_repository.get_by_ids = AsyncMock(
        return_value=[Feed(id=1, link="https://example.com/one")]
    )
    command = BundleCommand(
        bundle_repository=bundle_repository,
        feed_repository=feed_repository,
    )

    result = await command.replace_members(
        bundle_id=7,
        user_id="owner",
        feed_ids=[1, 2],
    )

    assert result.success is False
    assert "Feed" in result.message
    bundle_repository.replace_members.assert_not_awaited()
