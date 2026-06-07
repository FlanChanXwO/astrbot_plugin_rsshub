"""Registry for RSSHub LLM tools."""

from __future__ import annotations

from .handler_tools import build_handler_tools
from .history import build_history_tools
from .settings import build_setting_tools
from .subscriptions import build_subscription_tools
from .types import FunctionTool, LLMToolDeps
from .xml_push import build_xml_push_tools

LLM_TOOL_NAMES = [
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
]


def build_llm_tools(*, deps: LLMToolDeps, plugin_context) -> list[FunctionTool]:
    """构建 RSSHub 插件 LLM 工具列表。"""
    return [
        *build_subscription_tools(deps=deps, plugin_context=plugin_context),
        *build_setting_tools(deps=deps, plugin_context=plugin_context),
        *build_history_tools(deps=deps, plugin_context=plugin_context),
        *build_xml_push_tools(deps=deps, plugin_context=plugin_context),
        *build_handler_tools(deps=deps, plugin_context=plugin_context),
    ]
