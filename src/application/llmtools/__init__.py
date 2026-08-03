"""RSSHub LLM 工具注册包。"""

from __future__ import annotations

from .registry import LLM_TOOL_NAMES, build_llm_tools
from .types import FunctionTool, LLMToolDeps

__all__ = [
    "LLM_TOOL_NAMES",
    "FunctionTool",
    "LLMToolDeps",
    "build_llm_tools",
]
