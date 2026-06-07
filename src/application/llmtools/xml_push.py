"""XML/HTML direct-push LLM tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..services.agent_xml_push_service import AgentXmlValidationError
from .common import extract_event, json_dumps, make_tool
from .types import FunctionTool, LLMToolDeps

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.astr_agent_context import AstrAgentContext


def build_xml_push_tools(*, deps: LLMToolDeps, plugin_context) -> list[FunctionTool]:
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
        event = extract_event(context)
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
            return json_dumps({"ok": False, "error": str(exc)})

    return [
        make_tool(
            name="rss_push_xml_entry",
            description=(
                "一次性解析 XML/HTML 标签内容并推送到当前会话。可用 dry_run 预览；"
                "不创建长期订阅，也不读取或注入 handlers。"
            ),
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
        )
    ]
