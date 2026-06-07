"""Push history LLM tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .common import extract_event, json_dumps, make_tool
from .types import FunctionTool, LLMToolDeps

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.astr_agent_context import AstrAgentContext


def build_history_tools(*, deps: LLMToolDeps, plugin_context) -> list[FunctionTool]:
    async def rss_list_push_history(
        context: ContextWrapper[AstrAgentContext],
        page: str = "",
        page_size: str = "",
    ) -> str:
        event = extract_event(context)
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
        return json_dumps(
            {
                "ok": True,
                "page": page_num,
                "page_size": page_size_num,
                "total": total,
                "items": [_dump_history_item(item) for item in scoped_items],
            }
        )

    return [
        make_tool(
            name="rss_list_push_history",
            description=(
                "查看当前会话推送历史并返回 JSON。用于排查 success/skipped/failed、"
                "fail_reason、media_urls、raw_xml 与 handler_trace。"
            ),
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
        )
    ]


def _dump_history_item(item: Any) -> dict[str, Any]:
    return {
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
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }
