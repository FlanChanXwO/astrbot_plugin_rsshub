"""Shared LLM tool types and AstrBot fallback shims."""

from __future__ import annotations

from dataclasses import dataclass as py_dataclass
from typing import Any, TypedDict

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
