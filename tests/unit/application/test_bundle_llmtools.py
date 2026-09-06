from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.dto.result_dto import CommandResult
from astrbot_plugin_rsshub.src.application.llmtools import build_llm_tools


def _context():
    event = MagicMock()
    event.get_sender_id.return_value = "owner-1"
    event.unified_msg_origin = "telegram:group:1"
    return SimpleNamespace(context=SimpleNamespace(event=event))


@pytest.mark.asyncio
async def test_bundle_create_tool_uses_current_event_owner_and_application_command():
    bundle_cmd = MagicMock()
    bundle_cmd.create = AsyncMock(
        return_value=CommandResult(
            success=True,
            message="已创建 Bundle",
            data=SimpleNamespace(id=7, name="Daily"),
        )
    )
    deps = {"bundle_cmd": bundle_cmd}
    plugin_context = MagicMock()

    tools = build_llm_tools(deps=deps, plugin_context=plugin_context)
    tool = next(item for item in tools if item.name == "rss_bundle_create")

    assert set(tool.parameters["properties"]) == {
        "name",
        "feed_ids",
        "target_sessions",
        "interval",
    }
    assert tool.parameters["required"] == [
        "name",
        "feed_ids",
        "target_sessions",
    ]

    result = await tool.handler(
        _context(),
        "Daily",
        [1, 2],
        ["telegram:group:1"],
        15,
    )

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["message"] == "已创建 Bundle"
    assert payload["bundle_id"] == 7
    assert payload["data"]["name"] == "Daily"
    bundle_cmd.create.assert_awaited_once_with(
        user_id="owner-1",
        name="Daily",
        feed_ids=[1, 2],
        target_sessions=["telegram:group:1"],
        interval=15,
    )


@pytest.mark.asyncio
async def test_bundle_list_tool_scopes_to_current_event_owner():
    bundle_cmd = MagicMock()
    bundle_cmd.list = AsyncMock(
        return_value=CommandResult(
            success=True,
            message="共有 1 个聚合订阅",
            data=[SimpleNamespace(id=7, name="Daily")],
        )
    )
    tools = build_llm_tools(
        deps={"bundle_cmd": bundle_cmd},
        plugin_context=MagicMock(),
    )
    tool = next(item for item in tools if item.name == "rss_bundle_list")

    result = await tool.handler(_context())

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["items"] == [{"id": 7, "name": "Daily"}]
    bundle_cmd.list.assert_awaited_once_with(user_id="owner-1")


@pytest.mark.asyncio
async def test_bundle_get_tool_delegates_owned_detail_lookup():
    bundle_cmd = MagicMock()
    bundle_cmd.show = AsyncMock(
        return_value=CommandResult(
            success=True,
            message="detail",
            data={"bundle": {"id": 7}, "members": []},
        )
    )
    tools = build_llm_tools(
        deps={"bundle_cmd": bundle_cmd},
        plugin_context=MagicMock(),
    )
    tool = next(item for item in tools if item.name == "rss_bundle_get")

    result = await tool.handler(_context(), 7)

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["data"]["bundle"]["id"] == 7
    bundle_cmd.show.assert_awaited_once_with(bundle_id=7, user_id="owner-1")


@pytest.mark.asyncio
async def test_bundle_update_members_uses_atomic_application_use_case():
    bundle_cmd = MagicMock()
    bundle_cmd.replace_members = AsyncMock(
        return_value=CommandResult(
            success=True,
            message="已更新 Bundle 成员",
            data=[{"feed_id": 2, "position": 0}],
        )
    )
    tools = build_llm_tools(
        deps={"bundle_cmd": bundle_cmd},
        plugin_context=MagicMock(),
    )
    tool = next(item for item in tools if item.name == "rss_bundle_update_members")

    result = await tool.handler(_context(), 7, [2, 3])

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["data"] == [{"feed_id": 2, "position": 0}]
    bundle_cmd.replace_members.assert_awaited_once_with(
        bundle_id=7,
        user_id="owner-1",
        feed_ids=[2, 3],
    )


@pytest.mark.asyncio
async def test_bundle_set_option_delegates_key_value_with_owner_scope():
    bundle_cmd = MagicMock()
    bundle_cmd.set_option = AsyncMock(
        return_value=CommandResult(success=True, message="已更新", data=None)
    )
    tools = build_llm_tools(
        deps={"bundle_cmd": bundle_cmd},
        plugin_context=MagicMock(),
    )
    tool = next(item for item in tools if item.name == "rss_bundle_set_option")

    result = await tool.handler(_context(), 7, "send_card", True)

    assert json.loads(result)["ok"] is True
    bundle_cmd.set_option.assert_awaited_once_with(
        bundle_id=7,
        user_id="owner-1",
        option="send_card",
        value=True,
    )


@pytest.mark.asyncio
async def test_bundle_set_handlers_delegates_structured_handlers():
    bundle_cmd = MagicMock()
    bundle_cmd.set_handlers = AsyncMock(
        return_value=CommandResult(success=True, message="handlers updated")
    )
    tools = build_llm_tools(
        deps={"bundle_cmd": bundle_cmd},
        plugin_context=MagicMock(),
    )
    tool = next(item for item in tools if item.name == "rss_bundle_set_handlers")
    handlers = [{"id": "builtin.ai_filter.default", "status": 1}]

    result = await tool.handler(_context(), 7, handlers)

    assert json.loads(result)["ok"] is True
    bundle_cmd.set_handlers.assert_awaited_once_with(
        bundle_id=7,
        user_id="owner-1",
        handlers=handlers,
    )


@pytest.mark.asyncio
async def test_bundle_set_state_accepts_only_explicit_binary_state():
    bundle_cmd = MagicMock()
    bundle_cmd.state = AsyncMock(
        return_value=CommandResult(success=True, message="已启用")
    )
    tools = build_llm_tools(
        deps={"bundle_cmd": bundle_cmd},
        plugin_context=MagicMock(),
    )
    tool = next(item for item in tools if item.name == "rss_bundle_set_state")

    result = await tool.handler(_context(), 7, 1)

    assert json.loads(result)["ok"] is True
    bundle_cmd.state.assert_awaited_once_with(
        bundle_id=7,
        user_id="owner-1",
        enable=True,
    )


@pytest.mark.asyncio
async def test_bundle_set_state_rejects_boolean_as_integer_state():
    bundle_cmd = MagicMock()
    bundle_cmd.state = AsyncMock()
    tools = build_llm_tools(
        deps={"bundle_cmd": bundle_cmd},
        plugin_context=MagicMock(),
    )
    tool = next(item for item in tools if item.name == "rss_bundle_set_state")

    result = await tool.handler(_context(), 7, True)

    payload = json.loads(result)
    assert payload["ok"] is False
    bundle_cmd.state.assert_not_awaited()


@pytest.mark.asyncio
async def test_bundle_delete_uses_owner_scoped_application_command():
    bundle_cmd = MagicMock()
    bundle_cmd.delete = AsyncMock(
        return_value=CommandResult(success=True, message="已删除 Bundle")
    )
    tools = build_llm_tools(
        deps={"bundle_cmd": bundle_cmd},
        plugin_context=MagicMock(),
    )
    tool = next(item for item in tools if item.name == "rss_bundle_delete")

    result = await tool.handler(_context(), 7)

    assert json.loads(result)["ok"] is True
    bundle_cmd.delete.assert_awaited_once_with(bundle_id=7, user_id="owner-1")


def test_bundle_tool_registry_excludes_high_risk_runtime_operations():
    tools = build_llm_tools(
        deps={"bundle_cmd": MagicMock()},
        plugin_context=MagicMock(),
    )
    names = {item.name for item in tools}

    assert {
        "rss_bundle_create",
        "rss_bundle_list",
        "rss_bundle_get",
        "rss_bundle_update_members",
        "rss_bundle_set_option",
        "rss_bundle_set_handlers",
        "rss_bundle_set_state",
        "rss_bundle_delete",
    } <= names
    assert not names.intersection(
        {"rss_bundle_test", "rss_bundle_retry", "rss_bundle_discard"}
    )
