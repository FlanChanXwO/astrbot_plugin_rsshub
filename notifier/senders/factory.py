from __future__ import annotations

from .aiocqhttp import AiocqhttpMessageSender
from .base import MessageSender
from .telegram import TelegramMessageSender


def get_sender_for_platform_name(platform_name: str | None) -> type[MessageSender]:
    """根据平台类型名选择最优发送器。

    Args:
        platform_name: 平台类型名，如 "telegram", "aiocqhttp" 等

    Returns:
        对应的 MessageSender 子类，用于实现平台特定的发送策略
    """
    normalized = (platform_name or "").strip().lower()

    if normalized in {"telegram", "tg"} or "telegram" in normalized:
        return TelegramMessageSender

    if normalized in {"aiocqhttp", "onebot", "onebot11", "onebotv11"}:
        return AiocqhttpMessageSender
    if "aiocqhttp" in normalized or "onebot" in normalized:
        return AiocqhttpMessageSender

    return MessageSender
