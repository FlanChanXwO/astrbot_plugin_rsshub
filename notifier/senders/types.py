from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PreparedMedia:
    media_type: str
    original_url: str
    local_path: Path | None = None
    download_failed: bool = False


@dataclass
class SendResult:
    """Send result with failure classification for retry/rebind decisions."""

    ok: bool
    needs_rebind: bool = False
    transient: bool = False
    detail: str = ""


@dataclass
class ChannelInfo:
    """RSS 频道元信息（从 Feed 表获取）"""

    title: str = ""
    link: str = ""


# 全局的 bot_self_id 获取函数，由插件在初始化时注入
_bot_self_id_provider: Callable[[str], str] | None = None


def set_bot_self_id_provider(provider: Callable[[str], str] | None) -> None:
    """设置全局的 bot_self_id 获取函数"""
    global _bot_self_id_provider
    _bot_self_id_provider = provider


def get_bot_self_id(platform_id: str) -> str:
    """获取指定平台的 bot_self_id"""
    if _bot_self_id_provider:
        return _bot_self_id_provider(platform_id)
    return "10000"


@dataclass
class NotifierContext:
    """通知发送上下文，包含频道元信息和运行时信息"""

    channel: ChannelInfo = field(default_factory=ChannelInfo)
    platform_name: str = ""

    def resolve_bot_self_id(self, platform_id: str) -> str:
        """解析 bot_self_id"""
        return get_bot_self_id(platform_id)
