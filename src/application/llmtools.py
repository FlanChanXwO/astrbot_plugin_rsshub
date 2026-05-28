"""RSSHub LLM 工具注册。"""

from __future__ import annotations

import json
from dataclasses import dataclass as py_dataclass
from typing import TYPE_CHECKING, Any, TypedDict
from urllib.parse import urlparse

try:
    from astrbot.core.agent.tool import FunctionTool
except Exception:  # pragma: no cover - test/mocking fallback

    @py_dataclass
    class FunctionTool:  # type: ignore[no-redef]
        name: str
        description: str
        parameters: dict
        handler: Any = None
        handler_module_path: str | None = None


if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.astr_agent_context import AstrAgentContext

from ..domain.entities.handlers import list_handler_registry
from ..infrastructure.config import get_config
from ..infrastructure.utils import get_logger
from ..interfaces import handlers as h
from .services.agent_xml_push_service import AgentXmlValidationError

logger = get_logger()


class LLMToolDeps(TypedDict):
    subscribe_cmd: Any
    unsubscribe_cmd: Any
    update_sub_cmd: Any
    get_subs_query: Any
    set_user_settings_cmd: Any
    get_user_settings_cmd: Any
    subscription_repo: Any
    push_history_repo: Any
    export_cmd: Any
    agent_xml_push_service: Any


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


def _normalize_subscribe_targets(targets: list[str] | None = None) -> str:
    normalized_targets: list[str] = []
    seen: set[str] = set()
    for target in targets or []:
        raw_target = str(target or "").strip()
        if not raw_target:
            continue
        resolved = _resolve_rsshub_uri(raw_target)
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


def _resolve_rsshub_uri(value: str) -> str:
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


def _tool(
    *,
    name: str,
    description: str,
    parameters: dict,
    handler,
    plugin_context,
) -> FunctionTool:
    tool = FunctionTool(
        name=name,
        description=description,
        parameters=parameters,
        handler=handler,
    )
    tool.handler_module_path = getattr(plugin_context, "__module__", "") or None
    return tool


def _extract_event(tool_context: Any) -> Any:
    """兼容 AstrBot 工具上下文包装器与直接事件对象。"""
    if callable(getattr(tool_context, "get_sender_id", None)) and hasattr(
        tool_context, "unified_msg_origin"
    ):
        return tool_context

    wrapper_context = getattr(tool_context, "context", None)
    if wrapper_context is not None:
        wrapped_event = getattr(wrapper_context, "event", None)
        if wrapped_event is not None:
            return wrapped_event

    direct_event = getattr(tool_context, "event", None)
    if direct_event is not None:
        return direct_event

    raise TypeError("无法从工具上下文中解析消息事件")


def build_llm_tools(*, deps: LLMToolDeps, plugin_context) -> list[FunctionTool]:
    """构建 RSSHub 插件 LLM 工具列表。"""

    async def rss_subscribe(
        context: ContextWrapper[AstrAgentContext],
        targets: list[str] | None = None,
    ) -> str:
        event = _extract_event(context)
        normalized_targets = _normalize_subscribe_targets(targets)
        if not normalized_targets:
            return "订阅目标不能为空，请提供至少一个 RSS URL 或 RSSHub 路由路径"
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
        event = _extract_event(context)
        result = await h.handle_unsub(event, sub_id, deps)
        return result.get("plain", "")

    async def rss_unsubscribe_all(
        context: ContextWrapper[AstrAgentContext],
        scope: str = "",
    ) -> str:
        event = _extract_event(context)
        result = await h.handle_unsub_all(event, scope, deps)
        return result.get("plain", "")

    async def rss_list_subscriptions(
        context: ContextWrapper[AstrAgentContext],
        page: str = "",
        page_size: str = "",
    ) -> str:
        event = _extract_event(context)
        args = " ".join(part for part in (page, page_size) if str(part).strip())
        result = await h.handle_sub_list(event, args, deps)
        return result.get("plain", "")

    async def rss_set_subscription_option(
        context: ContextWrapper[AstrAgentContext],
        sub_id: str,
        key: str,
        value: str,
    ) -> str:
        event = _extract_event(context)
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
        event = _extract_event(context)
        result = await h.handle_sub_set_user(event, key, value, deps)
        return result.get("plain", "")

    async def rss_set_session_default_option(
        context: ContextWrapper[AstrAgentContext],
        key: str,
        value: str,
    ) -> str:
        event = _extract_event(context)
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
        event = _extract_event(context)
        result = await h.handle_sub_get_session(
            event,
            "",
            deps,
            plugin_context,
        )
        return result.get("plain", "")

    async def rss_list_handlers(
        context: ContextWrapper[AstrAgentContext],
    ) -> str:
        _extract_event(context)
        return json.dumps(
            {"ok": True, "items": list_handler_registry()},
            ensure_ascii=False,
            indent=2,
        )

    async def rss_get_handlers(
        context: ContextWrapper[AstrAgentContext],
        scope: str,
        sub_id: str = "",
    ) -> str:
        event = _extract_event(context)
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope == "subscription":
            try:
                sub_id_int = int(str(sub_id).strip())
            except ValueError:
                return json.dumps(
                    {"ok": False, "error": "sub_id 必须是数字"},
                    ensure_ascii=False,
                    indent=2,
                )
            sub = await deps["subscription_repo"].get_by_id(sub_id_int)
            if sub is None or str(sub.user_id) != str(event.get_sender_id() or ""):
                return json.dumps(
                    {"ok": False, "error": "订阅不存在或无权访问"},
                    ensure_ascii=False,
                    indent=2,
                )
            return json.dumps(
                {
                    "ok": True,
                    "scope": "subscription",
                    "sub_id": sub.id,
                    "handlers_mode": sub.handlers_mode,
                    "handlers": sub.get_handlers(),
                },
                ensure_ascii=False,
                indent=2,
            )
        if normalized_scope == "user":
            result = await deps["get_user_settings_cmd"].execute(
                user_id=str(event.get_sender_id() or "").strip()
            )
            settings = result.data or {}
            return json.dumps(
                {
                    "ok": bool(result.success),
                    "scope": "user",
                    "handlers": settings.get("handlers", []),
                    "error": "" if result.success else result.message,
                },
                ensure_ascii=False,
                indent=2,
            )
        return json.dumps(
            {"ok": False, "error": "scope 只支持 subscription 或 user"},
            ensure_ascii=False,
            indent=2,
        )

    async def rss_set_subscription_handlers(
        context: ContextWrapper[AstrAgentContext],
        sub_id: str,
        handlers_json: str,
        mode: str = "override",
    ) -> str:
        event = _extract_event(context)
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
        event = _extract_event(context)
        result = await h.handle_sub_set_user(
            event,
            "handlers",
            handlers_json,
            deps,
        )
        return result.get("plain", "")

    async def rss_list_push_history(
        context: ContextWrapper[AstrAgentContext],
        page: str = "",
        page_size: str = "",
    ) -> str:
        event = _extract_event(context)
        user_id = str(event.get_sender_id() or "").strip()
        target_session = str(getattr(event, "unified_msg_origin", "") or "").strip()
        try:
            page_num = max(1, int(str(page).strip() or "1"))
        except ValueError:
            page_num = 1
        try:
            page_size_num = max(1, min(100, int(str(page_size).strip() or "20")))
        except ValueError:
            page_size_num = 20

        scoped_items = await deps["push_history_repo"].get_by_user(
            user_id=user_id,
            limit=page_size_num,
            offset=(page_num - 1) * page_size_num,
            target_session=target_session,
        )
        total = await deps["push_history_repo"].count_by_user(
            user_id=user_id,
            target_session=target_session,
        )
        return json.dumps(
            {
                "ok": True,
                "page": page_num,
                "page_size": page_size_num,
                "total": total,
                "items": [
                    {
                        "id": item.id,
                        "source_type": item.source_type,
                        "source_key": item.source_key,
                        "content": item.content,
                        "raw_xml": getattr(item, "raw_xml", None),
                        "media_urls": item.media_urls,
                        "handler_trace": getattr(item, "handler_trace", None),
                        "entry_title": item.entry_title,
                        "entry_link": item.entry_link,
                        "entry_guid": item.entry_guid,
                        "feed_title": item.feed_title,
                        "feed_link": item.feed_link,
                        "platform_name": item.platform_name,
                        "target_session": item.target_session,
                        "status": item.status,
                        "retry_count": item.retry_count,
                        "max_retries": item.max_retries,
                        "fail_reason": item.fail_reason,
                        "created_at": item.created_at.isoformat()
                        if item.created_at
                        else None,
                        "updated_at": item.updated_at.isoformat()
                        if item.updated_at
                        else None,
                        "completed_at": item.completed_at.isoformat()
                        if item.completed_at
                        else None,
                    }
                    for item in scoped_items
                ],
            },
            ensure_ascii=False,
            indent=2,
        )

    async def rss_push_xml_entry(
        context: ContextWrapper[AstrAgentContext],
        source_key: str,
        title: str,
        xml: str,
        link: str = "",
        author: str = "",
        feed_title: str = "",
        entry_guid: str = "",
        idempotency_key: str = "",
        dry_run: bool = False,
        style: Any = None,
        send_mode: Any = None,
        display_media: Any = None,
        display_title: Any = None,
        display_author: Any = None,
        display_via: Any = None,
        display_entry_tags: Any = None,
        length_limit: Any = None,
    ) -> str:
        event = _extract_event(context)
        service = deps["agent_xml_push_service"]
        try:
            return await service.push_entry_json(
                user_id=str(event.get_sender_id() or "").strip(),
                platform_name=str(event.get_platform_name() or "").strip().lower()
                or None,
                target_session=str(
                    getattr(event, "unified_msg_origin", "") or ""
                ).strip(),
                source_key=source_key,
                title=title,
                xml=xml,
                link=link,
                author=author,
                feed_title=feed_title,
                entry_guid=entry_guid,
                idempotency_key=idempotency_key,
                dry_run=bool(dry_run),
                style=style,
                send_mode=send_mode,
                display_media=display_media,
                display_title=display_title,
                display_author=display_author,
                display_via=display_via,
                display_entry_tags=display_entry_tags,
                length_limit=length_limit,
            )
        except AgentXmlValidationError as exc:
            return json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )

    return [
        _tool(
            name="rss_subscribe",
            description="订阅 RSS 源。targets 每项可为完整 http/https URL 或 RSSHub 路由路径，路由路径会自动用插件默认 RSSHub 基址拼接。",
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
        _tool(
            name="rss_unsubscribe",
            description="取消订阅，支持 ID/URL，支持空格分隔多个目标。",
            parameters={
                "type": "object",
                "properties": {
                    "sub_id": {
                        "type": "string",
                        "description": "订阅 ID 或 URL，支持多个。",
                    }
                },
                "required": ["sub_id"],
            },
            handler=rss_unsubscribe,
            plugin_context=plugin_context,
        ),
        _tool(
            name="rss_unsubscribe_all",
            description="取消全部订阅。scope=global 需要管理员权限。",
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
        _tool(
            name="rss_list_subscriptions",
            description="查看当前会话订阅列表。",
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
        _tool(
            name="rss_set_subscription_option",
            description="设置订阅级配置项。",
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
        _tool(
            name="rss_set_user_default_option",
            description="设置用户默认配置项。",
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
        _tool(
            name="rss_set_session_default_option",
            description="设置当前会话默认配置项。",
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
        _tool(
            name="rss_get_session_defaults",
            description="查看当前会话默认配置。",
            parameters={"type": "object", "properties": {}},
            handler=rss_get_session_defaults,
            plugin_context=plugin_context,
        ),
        _tool(
            name="rss_list_push_history",
            description="查看当前会话推送历史，返回 JSON 列表；handler_trace 会摘要展示 AI 过滤、AI 改写执行结果。基础 HTML/XML 清洗属于内建推送链。",
            parameters={
                "type": "object",
                "properties": {
                    "page": {"type": "string", "description": "页码，默认1"},
                    "page_size": {
                        "type": "string",
                        "description": "每页数量，默认20，最大100",
                    },
                },
            },
            handler=rss_list_push_history,
            plugin_context=plugin_context,
        ),
        _tool(
            name="rss_list_handlers",
            description="列出可用内容 handlers 及 schema。基础 HTML/XML 清洗属于内建推送链；当前只配置 AI 过滤(ai_filter) 与 AI 改写(ai_transform)。",
            parameters={"type": "object", "properties": {}},
            handler=rss_list_handlers,
            plugin_context=plugin_context,
        ),
        _tool(
            name="rss_get_handlers",
            description="读取当前用户或某个订阅的 handlers 配置；先用它查看现状，再决定是否设置 AI 过滤或 AI 改写。",
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
        _tool(
            name="rss_set_subscription_handlers",
            description="设置订阅级 handlers。handlers_json 必须是数组 JSON；基础 HTML/XML 清洗属于内建推送链，可配置 ai_filter 按 AstrBot 当前 Provider 过滤、ai_transform(scope=plaintext|xml) 通过 Agent 改写文本或整段 XML。外部 handler 可保存但运行时会跳过。",
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
        _tool(
            name="rss_set_user_handlers",
            description="设置用户默认 handlers。适合给用户所有继承订阅添加 AI 过滤或 AI 改写；ai_transform 支持 scope=plaintext|xml，只保存 prompt 等配置，不保存 API key。",
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
        _tool(
            name="rss_push_xml_entry",
            description="将 XML/HTML 标签内容解析为消息组件并推送到当前会话。",
            parameters={
                "type": "object",
                "properties": {
                    "source_key": {
                        "type": "string",
                        "description": "稳定推送流 ID，例如 daily:ai-news",
                    },
                    "title": {"type": "string", "description": "消息标题"},
                    "xml": {
                        "type": "string",
                        "description": "要解析推送的 XML/HTML 标签内容",
                    },
                    "link": {"type": "string", "description": "可选条目链接"},
                    "author": {"type": "string", "description": "可选作者"},
                    "feed_title": {"type": "string", "description": "可选来源标题"},
                    "entry_guid": {"type": "string", "description": "可选条目 GUID"},
                    "idempotency_key": {
                        "type": "string",
                        "description": "可选显式幂等键",
                    },
                    "dry_run": {"type": "boolean", "description": "仅解析预览，不发送"},
                    "style": {
                        "type": "string",
                        "enum": ["auto", "rssrt", "original"],
                        "description": "可选推送样式；original 会尽量按 XML/HTML 原始布局推送。",
                    },
                    "send_mode": {
                        "type": "string",
                        "enum": ["auto", "link_only", "direct"],
                        "description": "可选发送模式：auto 自动、link_only 仅链接、direct 直接发送。",
                    },
                    "display_media": {
                        "type": "boolean",
                        "description": "是否发送 XML/HTML 中解析出的媒体。",
                    },
                    "display_title": {
                        "type": "string",
                        "enum": ["auto", "disabled", "forced"],
                        "description": "标题显示策略。",
                    },
                    "display_author": {
                        "type": "string",
                        "enum": ["auto", "disabled", "forced"],
                        "description": "作者显示策略。",
                    },
                    "display_via": {
                        "type": "string",
                        "enum": ["auto", "fully_disabled", "link_only", "forced"],
                        "description": "via 来源尾注显示策略。",
                    },
                    "display_entry_tags": {
                        "type": "boolean",
                        "description": "是否显示 XML 中的 category/tag 标签。",
                    },
                    "length_limit": {
                        "type": "integer",
                        "description": "正文截断长度；0 表示不截断。",
                    },
                },
                "required": ["source_key", "title", "xml"],
            },
            handler=rss_push_xml_entry,
            plugin_context=plugin_context,
        ),
    ]
