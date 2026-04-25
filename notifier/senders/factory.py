from __future__ import annotations

from ...config import cfg
from .aiocqhttp import AiocqhttpMessageSender
from .base import MessageSender
from .qq_official import QQOfficialMessageSender
from .telegram import TelegramMessageSender
from .weixin_oc import WeixinOCMessageSender


def get_sender_for_platform_name(
    platform_name: str | None,
) -> type[MessageSender]:
    """根据平台类型名选择最优发送器。

    Args:
        platform_name: 平台类型名，如 "telegram", "aiocqhttp" 等

    Returns:
        对应的 MessageSender 子类，用于实现平台特定的发送策略
    """
    normalized = (platform_name or "").strip().lower()

    # Check if cfg has sender_strategies
    strategies = cfg.sender_strategies if cfg else None
    if strategies is None:
        # Use default values when cfg is not available
        telegram_enabled = True
        aiocqhttp_enabled = True
        qq_official_enabled = True
        weixin_oc_enabled = True
    else:
        telegram_enabled = strategies.telegram
        aiocqhttp_enabled = strategies.aiocqhttp
        qq_official_enabled = (
            strategies.qq_official if hasattr(strategies, "qq_official") else True
        )
        weixin_oc_enabled = strategies.weixin_oc

    # Telegram strategy
    if normalized in {"telegram", "tg"} or "telegram" in normalized:
        if telegram_enabled:
            return TelegramMessageSender
        return MessageSender

    # OneBot/Aiocqhttp strategy
    if normalized in {"aiocqhttp", "onebot", "onebot11", "onebotv11"}:
        if aiocqhttp_enabled:
            return AiocqhttpMessageSender
        return MessageSender
    if "aiocqhttp" in normalized or "onebot" in normalized:
        if aiocqhttp_enabled:
            return AiocqhttpMessageSender
        return MessageSender

    # QQ Official strategy
    if normalized in {"qq_official", "qqofficial", "qq"}:
        if qq_official_enabled:
            return QQOfficialMessageSender
        return MessageSender
    if "qq_official" in normalized or "qqofficial" in normalized:
        if qq_official_enabled:
            return QQOfficialMessageSender
        return MessageSender

    # Weixin personal strategy
    if normalized in {
        "weixin_oc",
        "weixin_personal",
        "wechat",
        "wechat_personal",
        "weixin",
    }:
        if weixin_oc_enabled:
            return WeixinOCMessageSender
        return MessageSender
    if (
        "weixin_oc" in normalized
        or "weixin_personal" in normalized
        or "wechat_personal" in normalized
    ):
        if weixin_oc_enabled:
            return WeixinOCMessageSender
        return MessageSender

    return MessageSender
