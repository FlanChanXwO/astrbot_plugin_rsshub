"""Common helpers shared by RSSHub LLM tools."""

from __future__ import annotations

import json
from typing import Any

from .types import FunctionTool


def make_tool(
    *,
    name: str,
    description: str,
    parameters: dict,
    handler,
    plugin_context,
) -> FunctionTool:
    """Build an AstrBot FunctionTool and bind it to this plugin origin."""
    tool = FunctionTool(
        name=name,
        description=description,
        parameters=parameters,
        handler=handler,
    )
    tool.handler_module_path = getattr(plugin_context, "__module__", "") or None
    return tool


def extract_event(tool_context: Any) -> Any:
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


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
