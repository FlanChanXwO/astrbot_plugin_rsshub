"""消息发送器基础类型

提供跨平台消息发送的基础类型和协议定义。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ....domain.entities.content_types import LayoutFragment


@dataclass
class PreparedMedia:
    """预处理后的媒体文件信息"""

    media_type: str
    original_url: str
    local_path: Path | None = None
    download_failed: bool = False


@dataclass
class SendResult:
    """发送结果

    Attributes:
        ok: 是否发送成功
        needs_rebind: 是否需要重新绑定会话
        transient: 是否为临时错误（可重试）
        detail: 详细错误信息
        http_status: HTTP 状态码
    """

    ok: bool = False
    needs_rebind: bool = False
    transient: bool = False
    detail: str = ""
    http_status: int | None = None


@dataclass
class ChannelInfo:
    """RSS 频道元信息"""

    title: str = ""
    link: str = ""


@dataclass
class MessageContext:
    """消息发送上下文（运行时元信息）"""

    channel: ChannelInfo = field(default_factory=ChannelInfo)
    entry_title: str = ""
    entry_link: str = ""
    platform_name: str = ""
    send_mode: int | None = None
    style: int = 0
    sender_strategy: Any = None


@dataclass
class SendRequest:
    """消息发送请求

    封装 session_id / message / media 三要素，简化 send_to_user 调用。
    """

    session_id: str
    message: str = ""
    media: list[tuple[str, str]] | None = None
    prepared_media: list[PreparedMedia] | None = None
    layout: list[LayoutFragment] | None = None


class BaseMessageSender(Protocol):
    """消息发送器协议

    所有平台发送器必须实现此协议。
    """

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送消息给用户

        Args:
            request: 发送请求，包含 session_id / message / media / prepared_media
            context: 发送上下文（可选）

        Returns:
            发送结果
        """
        ...

    async def send_to_group(
        self,
        platform: str,
        group_id: str,
        message: str = "",
        media: list[tuple[str, str]] | None = None,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送消息到群组

        Args:
            platform: 平台名称
            group_id: 群组 ID
            message: 文本消息
            media: 媒体文件列表
            context: 发送上下文

        Returns:
            发送结果
        """
        ...


# 全局的 bot_self_id 获取函数
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
