"""Configuration LLM tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...interfaces import handlers as h
from .common import extract_event, make_tool
from .types import FunctionTool, LLMToolDeps

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.astr_agent_context import AstrAgentContext


def build_setting_tools(*, deps: LLMToolDeps, plugin_context) -> list[FunctionTool]:
    async def rss_set_subscription_option(
        context: ContextWrapper[AstrAgentContext],
        sub_id: str,
        key: str,
        value: str,
    ) -> str:
        event = extract_event(context)
        try:
            sub_id_int = int(sub_id)
        except ValueError:
            return "订阅 ID 必须是数字"
        result = await h.handle_sub_set(
            event,
            sub_id_int,
            key,
            value,
            deps,
        )
        return result.get("plain", "")

    async def rss_set_user_default_option(
        context: ContextWrapper[AstrAgentContext],
        key: str,
        value: str,
    ) -> str:
        event = extract_event(context)
        result = await h.handle_sub_set_user(event, key, value, deps)
        return result.get("plain", "")

    async def rss_set_session_default_option(
        context: ContextWrapper[AstrAgentContext],
        key: str,
        value: str,
    ) -> str:
        event = extract_event(context)
        result = await h.handle_sub_set_session(
            event,
            key,
            value,
            deps,
            plugin_context,
        )
        return result.get("plain", "")

    async def rss_get_session_defaults(
        context: ContextWrapper[AstrAgentContext],
    ) -> str:
        event = extract_event(context)
        result = await h.handle_sub_get_session(
            event,
            "",
            deps,
            plugin_context,
        )
        return result.get("plain", "")

    return [
        make_tool(
            name="rss_set_subscription_option",
            description=(
                "设置单个订阅的配置项。只改一个订阅时使用；如果用户没有给 sub_id，"
                "先用 rss_list_subscriptions 定位。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sub_id": {"type": "string", "description": "订阅 ID"},
                    "key": {"type": "string", "description": "配置项名称"},
                    "value": {"type": "string", "description": "配置项值"},
                },
                "required": ["sub_id", "key", "value"],
            },
            handler=rss_set_subscription_option,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_set_user_default_option",
            description="设置用户默认配置，影响该用户后续继承默认值的订阅；不要用于只修改当前会话的新订阅默认值。",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "配置项名称"},
                    "value": {"type": "string", "description": "配置项值"},
                },
                "required": ["key", "value"],
            },
            handler=rss_set_user_default_option,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_set_session_default_option",
            description="设置当前会话的新订阅默认配置；不要用于修改已经存在的订阅。",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "配置项名称"},
                    "value": {"type": "string", "description": "配置项值"},
                },
                "required": ["key", "value"],
            },
            handler=rss_set_session_default_option,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_get_session_defaults",
            description="查看当前会话的新订阅默认配置；修改会话级默认值前先用它确认现状。",
            parameters={"type": "object", "properties": {}},
            handler=rss_get_session_defaults,
            plugin_context=plugin_context,
        ),
    ]
