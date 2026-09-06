from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.dto.result_dto import CommandResult
from astrbot_plugin_rsshub.src.application.services.bundle_card_management_service import (
    BundleCardPreview,
)
from astrbot_plugin_rsshub.src.application.services.card_template_service import (
    CardTemplateInUseError,
)
from astrbot_plugin_rsshub.src.application.services.subscription_card_management_service import (
    CardTemplateOption,
)
from astrbot_plugin_rsshub.src.domain.repositories.delivery_repository import (
    DeliveryBatchNotFoundError,
)
from astrbot_plugin_rsshub.src.interfaces.web_api import WebApiHandler
from quart import Quart


def _handler(
    *,
    bundle_cmd,
    bundle_repository=None,
    bundle_card_management_service=None,
    bundle_batch_delivery_service=None,
    push_history_repo=None,
    delivery_repository=None,
    template_management_service=None,
):
    return WebApiHandler(
        subscribe_cmd=MagicMock(),
        unsubscribe_cmd=MagicMock(),
        update_sub_cmd=MagicMock(),
        batch_activate_cmd=MagicMock(),
        batch_deactivate_cmd=MagicMock(),
        batch_unsub_cmd=MagicMock(),
        export_cmd=MagicMock(),
        import_cmd=MagicMock(),
        get_user_settings_cmd=MagicMock(),
        set_user_settings_cmd=MagicMock(),
        test_sub_cmd=MagicMock(),
        get_items_query=MagicMock(),
        polling_service=MagicMock(),
        feed_repo=MagicMock(),
        sub_repo=MagicMock(),
        user_repo=MagicMock(),
        push_history_repo=push_history_repo or MagicMock(),
        bundle_cmd=bundle_cmd,
        bundle_repository=bundle_repository,
        bundle_card_management_service=bundle_card_management_service,
        bundle_batch_delivery_service=bundle_batch_delivery_service,
        delivery_repository=delivery_repository,
        template_management_service=template_management_service,
    )


def _request_handler(*, bundle_cmd, bundle_repository=None):
    return _handler(bundle_cmd=bundle_cmd, bundle_repository=bundle_repository)


@pytest.mark.asyncio
async def test_bundle_create_web_api_delegates_to_owned_application_command():
    bundle_cmd = MagicMock()
    bundle_cmd.create = AsyncMock(
        return_value=CommandResult(
            success=True,
            message="created",
            data=SimpleNamespace(id=11, name="Daily"),
        )
    )
    handler = _handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/create",
        method="POST",
        json={
            "name": "Daily",
            "user_id": "owner-1",
            "target_sessions": ["session-1"],
            "interval": 10,
            "feed_ids": [3, 7],
        },
    ):
        response = await handler.handle_bundle_create()

    payload = await response.get_json()
    assert payload == {
        "ok": True,
        "message": "created",
        "data": {"id": 11, "name": "Daily"},
    }
    bundle_cmd.create.assert_awaited_once_with(
        user_id="owner-1",
        name="Daily",
        feed_ids=[3, 7],
        target_sessions=["session-1"],
        interval=10,
    )


@pytest.mark.asyncio
async def test_bundle_update_web_api_flattens_safe_options_for_application_command():
    bundle_cmd = MagicMock()
    bundle_cmd.set = AsyncMock(
        return_value=CommandResult(success=True, message="updated", data={"id": 11})
    )
    handler = _request_handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/update",
        method="POST",
        json={
            "id": 11,
            "user_id": "owner-1",
            "name": "Morning",
            "target_sessions": ["session-2"],
            "interval": 20,
            "formatting": {"notify": 1, "style": 2},
            "send_card": True,
            "template_id": "astrbot_plugin_rsshub_card_bundle",
            "card_send_original_content": False,
        },
    ):
        response = await handler.handle_bundle_update()

    payload = await response.get_json()
    assert payload["ok"] is True
    bundle_cmd.set.assert_awaited_once_with(
        bundle_id=11,
        user_id="owner-1",
        options={
            "name": "Morning",
            "target_sessions": ["session-2"],
            "interval": 20,
            "notify": 1,
            "style": 2,
            "send_card": True,
            "template_id": "astrbot_plugin_rsshub_card_bundle",
            "card_send_original_content": False,
        },
    )


@pytest.mark.asyncio
async def test_bundle_members_web_api_uses_atomic_replace_members_use_case():
    bundle_cmd = MagicMock()
    bundle_cmd.replace_members = AsyncMock(
        return_value=CommandResult(success=True, message="members", data=[])
    )
    handler = _request_handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/members",
        method="POST",
        json={"id": 11, "user_id": "owner-1", "feed_ids": [7, 3]},
    ):
        response = await handler.handle_bundle_members()

    assert (await response.get_json())["ok"] is True
    bundle_cmd.replace_members.assert_awaited_once_with(
        bundle_id=11,
        user_id="owner-1",
        feed_ids=[7, 3],
    )


@pytest.mark.asyncio
async def test_bundle_handlers_web_api_delegates_document_handler_configuration():
    bundle_cmd = MagicMock()
    bundle_cmd.set_handlers = AsyncMock(
        return_value=CommandResult(success=True, message="handlers", data=[])
    )
    handler = _request_handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/handlers",
        method="POST",
        json={
            "id": 11,
            "user_id": "owner-1",
            "handlers": [{"name": "filter", "config": {"keyword": "rss"}}],
        },
    ):
        response = await handler.handle_bundle_handlers()

    assert (await response.get_json())["ok"] is True
    bundle_cmd.set_handlers.assert_awaited_once_with(
        bundle_id=11,
        user_id="owner-1",
        handlers=[{"name": "filter", "config": {"keyword": "rss"}}],
    )


@pytest.mark.asyncio
async def test_bundle_state_web_api_rejects_non_binary_state_before_command():
    bundle_cmd = MagicMock()
    bundle_cmd.state = AsyncMock()
    handler = _request_handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/state",
        method="POST",
        json={"id": 11, "user_id": "owner-1", "state": 2},
    ):
        response = await handler.handle_bundle_state()

    payload = await response.get_json()
    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_STATE"
    bundle_cmd.state.assert_not_awaited()


@pytest.mark.asyncio
async def test_bundle_delete_web_api_delegates_owner_scoped_delete():
    bundle_cmd = MagicMock()
    bundle_cmd.delete = AsyncMock(
        return_value=CommandResult(success=True, message="deleted")
    )
    handler = _request_handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/delete",
        method="POST",
        json={"id": 11, "user_id": "owner-1"},
    ):
        response = await handler.handle_bundle_delete()

    assert (await response.get_json())["ok"] is True
    bundle_cmd.delete.assert_awaited_once_with(bundle_id=11, user_id="owner-1")


@pytest.mark.asyncio
async def test_bundle_list_web_api_filters_command_results_by_keyword_and_paginates():
    bundle_cmd = MagicMock()
    bundle_cmd.list = AsyncMock(
        return_value=CommandResult(
            success=True,
            message="bundles",
            data=[
                SimpleNamespace(id=1, name="Daily", user_id="owner-1"),
                SimpleNamespace(id=2, name="Weekly", user_id="owner-1"),
            ],
        )
    )
    handler = _request_handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles?user_id=owner-1&keyword=daily&page=1&page_size=1"
    ):
        response = await handler.handle_bundles()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["items"] == [{"id": 1, "name": "Daily", "user_id": "owner-1"}]
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    bundle_cmd.list.assert_awaited_once_with(user_id="owner-1")


@pytest.mark.asyncio
async def test_bundle_list_web_api_can_use_dashboard_repository_scope_without_user_query():
    bundle_cmd = MagicMock()
    bundle_repo = MagicMock()
    bundle_repo.get_all = AsyncMock(
        return_value=[SimpleNamespace(id=3, name="All users", user_id="owner-2")]
    )
    handler = _request_handler(bundle_cmd=bundle_cmd, bundle_repository=bundle_repo)

    app = Quart(__name__)
    async with app.test_request_context("/astrbot_plugin_rsshub/bundles"):
        response = await handler.handle_bundles()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["items"] == [{"id": 3, "name": "All users", "user_id": "owner-2"}]
    bundle_repo.get_all.assert_awaited_once_with()
    bundle_cmd.list.assert_not_called()


@pytest.mark.asyncio
async def test_bundle_detail_web_api_keeps_owner_check_in_show_command():
    bundle_cmd = MagicMock()
    bundle_cmd.show = AsyncMock(
        return_value=CommandResult(
            success=True,
            message="detail",
            data={"bundle": SimpleNamespace(id=11), "members": []},
        )
    )
    handler = _request_handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/detail?id=11&user_id=owner-1"
    ):
        response = await handler.handle_bundle_detail()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["bundle"]["id"] == 11
    bundle_cmd.show.assert_awaited_once_with(bundle_id=11, user_id="owner-1")


@pytest.mark.asyncio
async def test_bundle_detail_web_api_includes_unclaimed_backlog_and_pending_batch_summary():
    bundle_cmd = MagicMock()
    bundle_cmd.show = AsyncMock(
        return_value=CommandResult(
            success=True,
            message="detail",
            data={"bundle": SimpleNamespace(id=11), "members": []},
        )
    )
    delivery_repo = MagicMock()
    delivery_repo.list_inbox_items = AsyncMock(
        return_value=[SimpleNamespace(id=1), SimpleNamespace(id=2)]
    )
    delivery_repo.get_pending_batch = AsyncMock(
        return_value=SimpleNamespace(
            id=5,
            status="pending",
            outputs=[
                SimpleNamespace(status="waiting"),
                SimpleNamespace(status="failed"),
            ],
        )
    )
    handler = _handler(
        bundle_cmd=bundle_cmd,
        delivery_repository=delivery_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/detail?id=11&user_id=owner-1"
    ):
        response = await handler.handle_bundle_detail()

    payload = await response.get_json()
    assert payload["data"]["backlog"] == {
        "unclaimed_count": 2,
        "items": [{"id": 1}, {"id": 2}],
    }
    assert payload["data"]["pending_batch"] == {
        "id": 5,
        "status": "pending",
        "output_count": 2,
        "output_statuses": ["waiting", "failed"],
    }
    delivery_repo.list_inbox_items.assert_awaited_once()
    delivery_repo.get_pending_batch.assert_awaited_once()


@pytest.mark.asyncio
async def test_bundle_test_web_api_is_admin_only_and_never_uses_llm_safe_command_set():
    bundle_cmd = MagicMock()
    bundle_cmd.test = AsyncMock(
        return_value=CommandResult(success=True, message="tested", data=[])
    )
    handler = _request_handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/test",
        method="POST",
        json={"id": 11, "user_id": "owner-1", "target_session": "session-1"},
    ):
        response = await handler.handle_bundle_test()

    assert (await response.get_json())["ok"] is True
    bundle_cmd.test.assert_awaited_once_with(
        bundle_id=11,
        user_id="owner-1",
        is_admin=True,
        target_session="session-1",
    )


def test_bundle_web_api_routes_are_registered_as_flat_dashboard_endpoints():
    handler = _request_handler(bundle_cmd=MagicMock())
    context = MagicMock()

    handler.register_all(context)

    registered = {
        (call.args[0], call.args[2][0])
        for call in context.register_web_api.call_args_list
    }
    prefix = "/astrbot_plugin_rsshub"
    assert {
        (f"{prefix}/bundles", "GET"),
        (f"{prefix}/bundles/detail", "GET"),
        (f"{prefix}/bundles/create", "POST"),
        (f"{prefix}/bundles/update", "POST"),
        (f"{prefix}/bundles/members", "POST"),
        (f"{prefix}/bundles/handlers", "POST"),
        (f"{prefix}/bundles/state", "POST"),
        (f"{prefix}/bundles/test", "POST"),
        (f"{prefix}/bundles/delete", "POST"),
    } <= registered


@pytest.mark.asyncio
async def test_template_options_web_api_supports_bundle_owner_via_generic_service():
    bundle_cmd = MagicMock()
    service = MagicMock()
    service.list_template_options = AsyncMock(
        return_value=[
            CardTemplateOption(
                id="astrbot_plugin_rsshub_card_bundle",
                name="Bundle",
                version="1.0.0",
                author="AstrBot",
                description="bundle template",
                repository="https://example.test/template",
            )
        ]
    )
    handler = _handler(
        bundle_cmd=bundle_cmd,
        bundle_card_management_service=service,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/templates/options?owner_type=bundle&owner_id=11&user_id=owner-1"
    ):
        response = await handler.handle_template_options()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["items"][0]["id"] == "astrbot_plugin_rsshub_card_bundle"
    service.list_template_options.assert_awaited_once_with(
        bundle_id=11,
        user_id="owner-1",
    )


@pytest.mark.asyncio
async def test_template_preview_web_api_supports_bundle_owner_without_persistence():
    bundle_cmd = MagicMock()
    service = MagicMock()
    service.preview = AsyncMock(
        return_value=BundleCardPreview(
            png=b"png",
            entry_count=3,
            template={"id": "astrbot_plugin_rsshub_card_bundle"},
            source_summary={"bundle_id": 11, "entry_count": 3},
        )
    )
    handler = _handler(
        bundle_cmd=bundle_cmd,
        bundle_card_management_service=service,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/templates/preview",
        method="POST",
        json={
            "owner_type": "bundle",
            "owner_id": 11,
            "user_id": "owner-1",
            "template_id": "astrbot_plugin_rsshub_card_bundle",
        },
    ):
        response = await handler.handle_template_preview()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["png_base64"] == "cG5n"
    assert payload["entry_count"] == 3
    service.preview.assert_awaited_once_with(
        bundle_id=11,
        user_id="owner-1",
        template_id="astrbot_plugin_rsshub_card_bundle",
    )


@pytest.mark.asyncio
async def test_bundle_delete_web_api_preserves_machine_readable_delivery_blockers():
    bundle_cmd = MagicMock()
    bundle_cmd.delete = AsyncMock(
        return_value=CommandResult(
            success=False,
            message="Bundle 有未解决投递，不能删除",
            error_code="DELIVERY_BLOCKED",
            details={"blocker_counts": {"pending_batch": 1}},
        )
    )
    handler = _handler(bundle_cmd=bundle_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/bundles/delete",
        method="POST",
        json={"id": 11, "user_id": "owner-1"},
    ):
        response = await handler.handle_bundle_delete()

    payload = await response.get_json()
    assert payload == {
        "ok": False,
        "error": "Bundle 有未解决投递，不能删除",
        "error_code": "DELIVERY_BLOCKED",
        "details": {"blocker_counts": {"pending_batch": 1}},
    }


@pytest.mark.asyncio
async def test_push_history_retry_web_api_routes_bundle_batch_to_bundle_service():
    history_repo = MagicMock()
    history_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=12, batch_id=5, bundle_id=11, sub_id=None)
    )
    bundle_batch_service = MagicMock()
    bundle_batch_service.retry = AsyncMock(
        return_value=SimpleNamespace(batch_id=5, ready_to_confirm=False)
    )
    handler = _handler(
        bundle_cmd=MagicMock(),
        push_history_repo=history_repo,
        bundle_batch_delivery_service=bundle_batch_service,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/push-history/retry",
        method="POST",
        json={"history_id": 12},
    ):
        response = await handler.handle_retry_push_history()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["batch_id"] == 5
    bundle_batch_service.retry.assert_awaited_once_with(11)


@pytest.mark.asyncio
async def test_template_delete_web_api_returns_reference_conflict_details():
    template_service = MagicMock()
    template_service.delete_template = AsyncMock(
        side_effect=CardTemplateInUseError(
            "astrbot_plugin_rsshub_card_bundle",
            [{"owner_type": "bundle", "owner_id": 11, "user_id": "owner-1"}],
        )
    )
    handler = _handler(
        bundle_cmd=MagicMock(),
        template_management_service=template_service,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/templates/delete",
        method="POST",
        json={"template_id": "astrbot_plugin_rsshub_card_bundle"},
    ):
        response = await handler.handle_template_delete()

    payload = await response.get_json()
    assert payload["ok"] is False
    assert payload["error_code"] == "CARD_TEMPLATE_IN_USE"
    assert payload["details"] == [
        {"owner_type": "bundle", "owner_id": 11, "user_id": "owner-1"}
    ]


@pytest.mark.asyncio
async def test_push_history_retry_web_api_returns_machine_error_for_unknown_history():
    history_repo = MagicMock()
    history_repo.get_by_id = AsyncMock(return_value=None)
    bundle_batch_service = MagicMock()
    handler = _handler(
        bundle_cmd=MagicMock(),
        push_history_repo=history_repo,
        bundle_batch_delivery_service=bundle_batch_service,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/push-history/retry",
        method="POST",
        json={"history_id": 404},
    ):
        response = await handler.handle_retry_push_history()

    payload = await response.get_json()
    assert payload == {
        "ok": False,
        "error": "推送历史不存在",
        "error_code": "HISTORY_NOT_FOUND",
    }
    bundle_batch_service.retry.assert_not_called()


@pytest.mark.asyncio
async def test_delivery_batch_discard_web_api_returns_unknown_batch_error():
    delivery_repo = MagicMock()
    delivery_repo.discard_batch = AsyncMock(
        side_effect=DeliveryBatchNotFoundError("投递批次不存在: 404")
    )
    handler = _handler(
        bundle_cmd=MagicMock(),
        delivery_repository=delivery_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/delivery-batches/discard",
        method="POST",
        json={"batch_id": 404},
    ):
        response = await handler.handle_discard_delivery_batch()

    assert await response.get_json() == {
        "ok": False,
        "error": "投递批次不存在: 404",
        "error_code": "DELIVERY_BATCH_NOT_FOUND",
        "details": {"batch_id": 404},
    }
