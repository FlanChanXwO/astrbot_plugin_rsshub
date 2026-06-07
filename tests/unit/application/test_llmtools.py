from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.llmtools import (
    LLM_TOOL_NAMES,
    build_llm_tools,
)
from astrbot_plugin_rsshub.src.application.services.agent_xml_push_service import (
    AgentXmlPushService,
)
from astrbot_plugin_rsshub.src.infrastructure.config import (
    BasicConfig,
    GlobalConfig,
    RsshubPluginConfig,
    set_config,
)


def _build_deps():
    return {
        "subscribe_cmd": MagicMock(),
        "unsubscribe_cmd": MagicMock(),
        "update_sub_cmd": MagicMock(),
        "get_subs_query": MagicMock(),
        "set_user_settings_cmd": MagicMock(),
        "get_user_settings_cmd": MagicMock(),
        "subscription_repo": MagicMock(),
        "push_history_repo": MagicMock(),
        "export_cmd": MagicMock(),
        "notification_dispatcher": AsyncMock(),
        "agent_xml_push_service": AgentXmlPushService(
            notification_dispatcher=AsyncMock()
        ),
    }


def _make_event():
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.unified_msg_origin = "p:g:1"
    event.get_platform_name.return_value = "aiocqhttp"
    event.is_admin.return_value = False
    return event


def _make_ctx():
    event = _make_event()
    plugin_ctx = MagicMock()
    wrapper = SimpleNamespace(context=SimpleNamespace(event=event))
    return wrapper, plugin_ctx


def test_build_llm_tools_names():
    deps = _build_deps()
    _, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    assert [tool.name for tool in tools] == LLM_TOOL_NAMES
    assert set(LLM_TOOL_NAMES) == {
        "rss_subscribe",
        "rss_unsubscribe",
        "rss_unsubscribe_all",
        "rss_list_subscriptions",
        "rss_set_subscription_option",
        "rss_set_user_default_option",
        "rss_set_session_default_option",
        "rss_get_session_defaults",
        "rss_list_push_history",
        "rss_push_xml_entry",
        "rss_list_handlers",
        "rss_get_handlers",
        "rss_set_subscription_handlers",
        "rss_set_user_handlers",
    }


@pytest.mark.asyncio
async def test_llm_tool_list_handlers_returns_registry_schema():
    deps = _build_deps()
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_list_handlers")

    result = await tool.handler(ctx)

    data = json.loads(result)
    names = {item["name"] for item in data["items"]}
    assert names == {"ai_filter", "ai_transform"}
    ai_filter = next(item for item in data["items"] if item["name"] == "ai_filter")
    assert any(field["key"] == "input_scope" for field in ai_filter["schema"])
    ai_transform = next(
        item for item in data["items"] if item["name"] == "ai_transform"
    )
    scope_field = next(
        field for field in ai_transform["schema"] if field["key"] == "scope"
    )
    assert scope_field["default"] == "plaintext"
    assert scope_field["options"] == ["plaintext", "xml"]


@pytest.mark.asyncio
async def test_llm_tool_rss_subscribe_schema_only_exposes_targets():
    deps = _build_deps()
    _, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_subscribe")

    assert tool.parameters["properties"] == {
        "targets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "订阅目标数组；每项可为完整 RSS URL 或 RSSHub 路由路径，例如 /twitter/user/123。",
        }
    }
    assert tool.parameters["required"] == ["targets"]


@pytest.mark.asyncio
async def test_llm_tool_rss_subscribe_schema_does_not_expose_legacy_params():
    deps = _build_deps()
    _, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_subscribe")

    assert set(tool.parameters["properties"]) == {"targets"}
    assert "url" not in tool.parameters["properties"]
    assert "interval" not in tool.parameters["properties"]
    assert "targets" in tool.parameters["properties"]


def test_llm_tool_descriptions_guide_agent_decisions():
    deps = _build_deps()
    _, plugin_ctx = _make_ctx()
    tools = {
        tool.name: tool
        for tool in build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    }

    assert "rss_list_subscriptions" in tools["rss_subscribe"].description
    assert "sub_id" in tools["rss_list_subscriptions"].description
    assert "当前会话" in tools["rss_set_session_default_option"].description
    assert "用户默认" in tools["rss_set_user_default_option"].description
    assert "handlers" in tools["rss_list_handlers"].description
    assert "AI 过滤" in tools["rss_set_subscription_handlers"].description
    assert "handler_trace" in tools["rss_list_push_history"].description
    assert "dry_run" in tools["rss_push_xml_entry"].description
    assert "不创建长期订阅" in tools["rss_push_xml_entry"].description


def test_llm_tools_do_not_restore_route_search_tools():
    assert "rss_search_routes" not in LLM_TOOL_NAMES
    assert "rss_build_route" not in LLM_TOOL_NAMES
    assert "rss_route_search" not in LLM_TOOL_NAMES


@pytest.mark.asyncio
async def test_llm_tool_rss_subscribe_supports_url_targets():
    deps = _build_deps()
    deps["subscribe_cmd"].execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="订阅成功")
    )
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_subscribe")

    result = await tool.handler(
        ctx,
        ["https://example.com/rss.xml", "https://example.com/atom.xml"],
    )

    assert result == "成功订阅 2 个 RSS 源"
    assert deps["subscribe_cmd"].execute.await_count == 2
    assert [
        call.kwargs["url"] for call in deps["subscribe_cmd"].execute.await_args_list
    ] == [
        "https://example.com/rss.xml",
        "https://example.com/atom.xml",
    ]


@pytest.mark.asyncio
async def test_llm_tool_rss_subscribe_supports_uri_targets_with_default_base_url():
    set_config(
        RsshubPluginConfig(
            basic_config=BasicConfig(rsshub_base_url="https://rss.example.com"),
            global_config=GlobalConfig(),
        )
    )
    deps = _build_deps()
    deps["subscribe_cmd"].execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="订阅成功")
    )
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_subscribe")

    result = await tool.handler(
        ctx,
        ["/twitter/user/dynamic/123", "pixiv/search/碧蓝档案"],
    )
    assert result == "成功订阅 2 个 RSS 源"
    assert deps["subscribe_cmd"].execute.await_count == 2
    assert [
        call.kwargs["url"] for call in deps["subscribe_cmd"].execute.await_args_list
    ] == [
        "https://rss.example.com/twitter/user/dynamic/123",
        "https://rss.example.com/pixiv/search/碧蓝档案",
    ]


@pytest.mark.asyncio
async def test_llm_tool_rss_subscribe_mixed_targets_deduplicate_in_order():
    set_config(
        RsshubPluginConfig(
            basic_config=BasicConfig(rsshub_base_url="https://rss.example.com"),
            global_config=GlobalConfig(),
        )
    )
    deps = _build_deps()
    deps["subscribe_cmd"].execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="订阅成功")
    )
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_subscribe")

    await tool.handler(
        ctx,
        [
            " https://example.com/rss.xml ",
            "/twitter/user/dynamic/123",
            "https://example.com/rss.xml",
            "",
            "twitter/user/dynamic/123",
        ],
    )

    assert deps["subscribe_cmd"].execute.await_count == 2
    assert [
        call.kwargs["url"] for call in deps["subscribe_cmd"].execute.await_args_list
    ] == [
        "https://example.com/rss.xml",
        "https://rss.example.com/twitter/user/dynamic/123",
    ]


@pytest.mark.asyncio
async def test_llm_tool_rss_subscribe_empty_targets_returns_error_without_subscribe():
    deps = _build_deps()
    deps["subscribe_cmd"].execute = AsyncMock()
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_subscribe")

    result = await tool.handler(ctx, ["", "   "])

    assert "订阅目标不能为空" in result
    deps["subscribe_cmd"].execute.assert_not_called()


@pytest.mark.asyncio
async def test_llm_tool_rss_subscribe_accepts_direct_event():
    deps = _build_deps()
    deps["subscribe_cmd"].execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="订阅成功")
    )
    event = _make_event()
    _, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_subscribe")

    result = await tool.handler(event, ["https://example.com/rss.xml"])

    assert "订阅成功" in result
    deps["subscribe_cmd"].execute.assert_awaited_once_with(
        url="https://example.com/rss.xml",
        user_id="u1",
        target_session="p:g:1",
        platform_name="aiocqhttp",
    )


@pytest.mark.asyncio
async def test_llm_tool_rss_get_session_defaults_uses_plugin_kv_store():
    deps = _build_deps()
    ctx, plugin_ctx = _make_ctx()
    plugin_ctx.get_kv_data = AsyncMock(
        return_value={"send_mode": 1, "display_media": 0}
    )
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_get_session_defaults")

    result = await tool.handler(ctx)

    assert "会话默认配置" in result
    assert "send_mode = 1" in result
    assert "display_media = 0" in result
    plugin_ctx.get_kv_data.assert_awaited_once_with("rsshub_session_defaults_p:g:1", {})


@pytest.mark.asyncio
async def test_llm_tool_list_push_history_only_returns_current_session():
    deps = _build_deps()
    deps["push_history_repo"].get_by_user = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=1,
                source_type="agent",
                source_key="daily:ai-news",
                content="content-1",
                raw_xml="<entry><p>One</p></entry>",
                media_urls=["https://example.com/1.png"],
                handler_trace=[
                    {
                        "id": "builtin.ai_filter.default",
                        "name": "ai_filter",
                        "status": "ok",
                        "allow": True,
                        "reason": "matched",
                    }
                ],
                entry_title="title-1",
                entry_link="https://example.com/1",
                entry_guid="guid-1",
                feed_title="Feed",
                feed_link="https://example.com/feed",
                platform_name="aiocqhttp",
                target_session="p:g:1",
                status="success",
                retry_count=0,
                max_retries=3,
                fail_reason=None,
                created_at=None,
                updated_at=None,
                completed_at=None,
            ),
        ]
    )
    deps["push_history_repo"].count_by_user = AsyncMock(return_value=1)
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_list_push_history")

    result = await tool.handler(ctx, "1", "20")
    data = json.loads(result)
    assert data["ok"] is True
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == 1
    assert "sub_id" not in data["items"][0]
    assert data["items"][0]["handler_trace"][0]["name"] == "ai_filter"
    deps["push_history_repo"].get_by_user.assert_awaited_once_with(
        user_id="u1",
        limit=20,
        offset=0,
        target_session="p:g:1",
    )


@pytest.mark.asyncio
async def test_llm_tool_set_subscription_handlers_uses_update_command():
    deps = _build_deps()
    deps["subscription_repo"].get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=3, user_id="u1", handlers_mode="inherit")
    )
    deps["update_sub_cmd"].execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="ok")
    )
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_set_subscription_handlers")
    handlers_json = json.dumps(
        [
            {
                "id": "builtin.ai_filter.default",
                "type": "builtin",
                "name": "ai_filter",
                "status": 1,
                "config": {"prompt": "skip ads", "input_scope": "both"},
            }
        ],
        ensure_ascii=False,
    )

    result = await tool.handler(ctx, "3", handlers_json, "override")

    assert result == "ok"
    assert deps["update_sub_cmd"].execute.await_count == 2
    assert deps["update_sub_cmd"].execute.await_args_list[0].kwargs == {
        "sub_id": 3,
        "user_id": "u1",
        "handlers_mode": "override",
    }
    assert deps["update_sub_cmd"].execute.await_args_list[1].kwargs == {
        "sub_id": 3,
        "user_id": "u1",
        "handlers": handlers_json,
    }


@pytest.mark.asyncio
async def test_llm_tool_list_push_history_accepts_direct_event():
    deps = _build_deps()
    deps["push_history_repo"].get_by_user = AsyncMock(return_value=[])
    deps["push_history_repo"].count_by_user = AsyncMock(return_value=0)
    event = _make_event()
    _, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_list_push_history")

    result = await tool.handler(event, "1", "20")

    data = json.loads(result)
    assert data["ok"] is True
    assert data["items"] == []
    deps["push_history_repo"].get_by_user.assert_awaited_once_with(
        user_id="u1",
        limit=20,
        offset=0,
        target_session="p:g:1",
    )


@pytest.mark.asyncio
async def test_llm_tool_rss_push_xml_entry_dry_run_validates_and_previews():
    deps = _build_deps()
    deps["notification_dispatcher"].dispatch_agent_entry = AsyncMock()
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_push_xml_entry")

    result = await tool.handler(
        ctx,
        "daily:ai-news",
        "Daily",
        "<entry><p>Hello</p><img src='https://example.com/a.jpg'/></entry>",
        "https://example.com/post",
        "Alice",
        "Feed",
        "",
        "",
        True,
    )

    data = json.loads(result)
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert data["preview"]["entry_guid"].startswith("agent:")
    deps["notification_dispatcher"].assert_not_called()


@pytest.mark.asyncio
async def test_llm_tool_rss_push_xml_entry_schema_exposes_safe_formatting_params():
    deps = _build_deps()
    _, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_push_xml_entry")

    properties = tool.parameters["properties"]
    for key in (
        "style",
        "send_mode",
        "display_media",
        "display_title",
        "display_author",
        "display_via",
        "display_entry_tags",
        "length_limit",
    ):
        assert key in properties
    assert properties["style"]["enum"] == ["auto", "rssrt", "original"]
    assert properties["send_mode"]["enum"] == ["auto", "link_only", "direct"]
    assert properties["display_media"]["type"] == "boolean"
    assert properties["length_limit"]["type"] == "integer"


@pytest.mark.asyncio
async def test_llm_tool_rss_push_xml_entry_passes_safe_formatting_params():
    service = MagicMock()
    service.push_entry_json = AsyncMock(return_value='{"ok": true}')
    deps = _build_deps()
    deps["agent_xml_push_service"] = service
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_push_xml_entry")

    result = await tool.handler(
        ctx,
        "daily:ai-news",
        "Daily",
        "<entry><p>Hello</p></entry>",
        "https://example.com/post",
        "Alice",
        "Feed",
        "guid-1",
        "idem-1",
        False,
        style="original",
        send_mode="link_only",
        display_media=False,
        display_title="disabled",
        display_author="forced",
        display_via="link_only",
        display_entry_tags=True,
        length_limit=120,
    )

    assert json.loads(result)["ok"] is True
    service.push_entry_json.assert_awaited_once_with(
        user_id="u1",
        platform_name="aiocqhttp",
        target_session="p:g:1",
        source_key="daily:ai-news",
        title="Daily",
        xml="<entry><p>Hello</p></entry>",
        link="https://example.com/post",
        author="Alice",
        feed_title="Feed",
        entry_guid="guid-1",
        idempotency_key="idem-1",
        dry_run=False,
        style="original",
        send_mode="link_only",
        display_media=False,
        display_title="disabled",
        display_author="forced",
        display_via="link_only",
        display_entry_tags=True,
        length_limit=120,
    )


@pytest.mark.asyncio
async def test_llm_tool_rss_push_xml_entry_accepts_direct_event():
    deps = _build_deps()
    event = _make_event()
    _, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_push_xml_entry")

    result = await tool.handler(
        event,
        "daily:ai-news",
        "Daily",
        "<entry><p>Hello</p></entry>",
        dry_run=True,
    )

    data = json.loads(result)
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert data["preview"]["entry_guid"].startswith("agent:")


@pytest.mark.asyncio
async def test_llm_tool_rss_push_xml_entry_rejects_invalid_xml():
    deps = _build_deps()
    deps["notification_dispatcher"].dispatch_agent_entry = AsyncMock()
    ctx, plugin_ctx = _make_ctx()
    tools = build_llm_tools(deps=deps, plugin_context=plugin_ctx)
    tool = next(t for t in tools if t.name == "rss_push_xml_entry")

    result = await tool.handler(ctx, "daily:ai-news", "Daily", "<entry><p>bad</entry>")

    assert "xml 格式错误" in result


def test_agent_skill_mentions_only_existing_plugin_tools_and_no_xml_parse_handler():
    plugin_root = Path(__file__).resolve().parents[3]
    skill_text = (plugin_root / "skills/rsshub-agent-tools/SKILL.md").read_text(
        encoding="utf-8"
    )
    for tool_name in LLM_TOOL_NAMES:
        assert tool_name in skill_text
    assert "xml_parse" not in skill_text
    assert "rss_subscribe(uri=" not in skill_text
    assert "rss_subscribe(targets=" in skill_text
