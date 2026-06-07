"""Subscription-oriented LLM tools."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ...infrastructure.config import get_config
from ...infrastructure.utils import get_logger
from ...interfaces import handlers as h
from .common import extract_event, make_tool
from .types import FunctionTool, LLMToolDeps

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.astr_agent_context import AstrAgentContext

logger = get_logger()


def build_subscription_tools(
    *, deps: LLMToolDeps, plugin_context
) -> list[FunctionTool]:
    async def rss_subscribe(
        context: ContextWrapper[AstrAgentContext],
        targets: list[str] | None = None,
    ) -> str:
        event = extract_event(context)
        normalized_targets = normalize_subscribe_targets(targets)
        if not normalized_targets:
            return "订阅目标不能为空，请提供至少一个已确认的 RSS URL 或 RSSHub 路由路径"
        result = await h.handle_sub(
            event,
            normalized_targets,
            deps,
        )
        return result.get("plain", "")

    async def rss_unsubscribe(
        context: ContextWrapper[AstrAgentContext],
        sub_id: str,
    ) -> str:
        event = extract_event(context)
        result = await h.handle_unsub(event, sub_id, deps)
        return result.get("plain", "")

    async def rss_unsubscribe_all(
        context: ContextWrapper[AstrAgentContext],
        scope: str = "",
    ) -> str:
        event = extract_event(context)
        result = await h.handle_unsub_all(event, scope, deps)
        return result.get("plain", "")

    async def rss_list_subscriptions(
        context: ContextWrapper[AstrAgentContext],
        page: str = "",
        page_size: str = "",
    ) -> str:
        event = extract_event(context)
        args = " ".join(part for part in (page, page_size) if str(part).strip())
        result = await h.handle_sub_list(event, args, deps)
        return result.get("plain", "")

    return [
        make_tool(
            name="rss_subscribe",
            description=(
                "订阅已确认的 RSS/Atom Feed 或 RSSHub 路由到当前会话。"
                "targets 是唯一公开参数；修改或退订前先用 rss_list_subscriptions 定位订阅。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "订阅目标数组；每项可为完整 RSS URL 或 RSSHub 路由路径，例如 /twitter/user/123。",
                    },
                },
                "required": ["targets"],
            },
            handler=rss_subscribe,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_unsubscribe",
            description="取消当前会话订阅；用户不知道 ID 时，先调用 rss_list_subscriptions 定位目标。",
            parameters={
                "type": "object",
                "properties": {
                    "sub_id": {
                        "type": "string",
                        "description": "订阅 ID 或 URL，支持空格分隔多个目标。",
                    }
                },
                "required": ["sub_id"],
            },
            handler=rss_unsubscribe,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_unsubscribe_all",
            description="取消当前会话全部订阅；scope=global 只在用户明确要求全局清理且具备权限时使用。",
            parameters={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "description": "可选: 留空(当前会话) 或 global(所有会话)",
                    }
                },
            },
            handler=rss_unsubscribe_all,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_list_subscriptions",
            description="查看当前会话订阅列表；修改订阅选项、设置订阅级 handlers 或退订前优先调用它获取 sub_id。",
            parameters={
                "type": "object",
                "properties": {
                    "page": {"type": "string", "description": "页码，默认1"},
                    "page_size": {
                        "type": "string",
                        "description": "每页数量，默认5，最大100",
                    },
                },
            },
            handler=rss_list_subscriptions,
            plugin_context=plugin_context,
        ),
    ]


def normalize_subscribe_targets(targets: list[str] | None = None) -> str:
    normalized_targets: list[str] = []
    seen: set[str] = set()
    for target in targets or []:
        raw_target = str(target or "").strip()
        if not raw_target:
            continue
        resolved = resolve_rsshub_uri(raw_target)
        if raw_target != resolved:
            logger.debug(
                "LLM 订阅工具解析 RSSHub 路由: target=%s -> url=%s",
                raw_target,
                resolved,
            )
        if resolved and resolved not in seen:
            normalized_targets.append(resolved)
            seen.add(resolved)
    return " ".join(normalized_targets)


def resolve_rsshub_uri(value: str) -> str:
    trimmed = str(value or "").strip()
    if not trimmed:
        return ""
    parsed = urlparse(trimmed)
    if parsed.scheme in {"http", "https"}:
        return trimmed

    config = get_config()
    base_url = "https://rsshub.app"
    if config is not None:
        candidate = str(
            getattr(config.basic_config, "rsshub_base_url", "") or ""
        ).strip()
        if candidate:
            base_url = candidate

    normalized_base = base_url.rstrip("/")
    normalized_path = trimmed if trimmed.startswith("/") else f"/{trimmed}"
    return f"{normalized_base}{normalized_path}"
