"""Content handler LLM tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain.entities.handlers import list_handler_registry
from ...interfaces import handlers as h
from .common import extract_event, json_dumps, make_tool
from .types import FunctionTool, LLMToolDeps

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.astr_agent_context import AstrAgentContext


def build_handler_tools(*, deps: LLMToolDeps, plugin_context) -> list[FunctionTool]:
    async def rss_list_handlers(
        context: ContextWrapper[AstrAgentContext],
    ) -> str:
        extract_event(context)
        return json_dumps({"ok": True, "items": list_handler_registry()})

    async def rss_get_handlers(
        context: ContextWrapper[AstrAgentContext],
        scope: str,
        sub_id: str = "",
    ) -> str:
        event = extract_event(context)
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope == "subscription":
            try:
                sub_id_int = int(str(sub_id).strip())
            except ValueError:
                return json_dumps({"ok": False, "error": "sub_id 必须是数字"})
            sub = await deps["subscription_repo"].get_by_id(sub_id_int)
            if sub is None or str(sub.user_id) != str(event.get_sender_id() or ""):
                return json_dumps({"ok": False, "error": "订阅不存在或无权访问"})
            return json_dumps(
                {
                    "ok": True,
                    "scope": "subscription",
                    "sub_id": sub.id,
                    "handlers_mode": sub.handlers_mode,
                    "handlers": sub.get_handlers(),
                }
            )
        if normalized_scope == "user":
            result = await deps["get_user_settings_cmd"].execute(
                user_id=str(event.get_sender_id() or "").strip()
            )
            settings = result.data or {}
            return json_dumps(
                {
                    "ok": bool(result.success),
                    "scope": "user",
                    "handlers": settings.get("handlers", []),
                    "error": "" if result.success else result.message,
                }
            )
        return json_dumps({"ok": False, "error": "scope 只支持 subscription 或 user"})

    async def rss_set_subscription_handlers(
        context: ContextWrapper[AstrAgentContext],
        sub_id: str,
        handlers_json: str,
        mode: str = "override",
    ) -> str:
        event = extract_event(context)
        try:
            sub_id_int = int(str(sub_id).strip())
        except ValueError:
            return "订阅 ID 必须是数字"
        sub = await deps["subscription_repo"].get_by_id(sub_id_int)
        if sub is None or str(sub.user_id) != str(event.get_sender_id() or ""):
            return "订阅不存在或无权访问"
        normalized_mode = str(mode or "override").strip().lower()
        if normalized_mode not in {"inherit", "override", "disabled"}:
            return "mode 只支持 inherit / override / disabled"
        mode_result = await h.handle_sub_set(
            event,
            sub_id_int,
            "handlers_mode",
            normalized_mode,
            deps,
        )
        if normalized_mode == "disabled":
            return mode_result.get("plain", "")
        result = await h.handle_sub_set(
            event,
            sub_id_int,
            "handlers",
            handlers_json,
            deps,
        )
        return result.get("plain", "")

    async def rss_set_user_handlers(
        context: ContextWrapper[AstrAgentContext],
        handlers_json: str,
    ) -> str:
        event = extract_event(context)
        result = await h.handle_sub_set_user(
            event,
            "handlers",
            handlers_json,
            deps,
        )
        return result.get("plain", "")

    return [
        make_tool(
            name="rss_list_handlers",
            description=(
                "列出可用内容 handlers 及 schema。长期 AI 过滤、总结、改写应配置 handlers；"
                "当前可执行内置 handler 是 ai_filter 与 ai_transform。"
            ),
            parameters={"type": "object", "properties": {}},
            handler=rss_list_handlers,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_get_handlers",
            description=(
                "读取用户默认或订阅级 handlers。改 AI 过滤/改写前先用它查看现状，"
                "scope 只支持 user 或 subscription。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "description": "user 或 subscription",
                    },
                    "sub_id": {
                        "type": "string",
                        "description": "scope=subscription 时必填订阅 ID",
                    },
                },
                "required": ["scope"],
            },
            handler=rss_get_handlers,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_set_subscription_handlers",
            description=(
                "设置单个订阅的 handlers。用于让某个订阅长期执行 AI 过滤或 AI 改写；"
                "handlers_json 必须是数组 JSON，mode=override/inherit/disabled。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sub_id": {"type": "string", "description": "订阅 ID"},
                    "handlers_json": {
                        "type": "string",
                        "description": "handlers JSON 数组，例如 ai_filter 使用 config.prompt/input_scope，ai_transform 使用 config.prompt/scope",
                    },
                    "mode": {
                        "type": "string",
                        "description": "override/inherit/disabled，默认 override",
                    },
                },
                "required": ["sub_id", "handlers_json"],
            },
            handler=rss_set_subscription_handlers,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_set_user_handlers",
            description=(
                "设置用户默认 handlers，适合把 AI 过滤、总结或改写作为该用户的长期默认策略；"
                "只保存 handler 配置，不保存 API key。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "handlers_json": {
                        "type": "string",
                        "description": "handlers JSON 数组，schema 可先调用 rss_list_handlers 查看",
                    }
                },
                "required": ["handlers_json"],
            },
            handler=rss_set_user_handlers,
            plugin_context=plugin_context,
        ),
    ]
