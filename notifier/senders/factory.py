from __future__ import annotations

from .aiocqhttp import AiocqhttpMessageSender
from .base import MessageSender
from .qq_official import QQOfficialMessageSender
from .telegram import TelegramMessageSender
from .weixin_oc import WeixinOCMessageSender


def get_sender_for_platform_name(
    platform_name: str | None,
    config: object | None = None,
) -> type[MessageSender]:
    """根据平台类型名选择最优发送器。

    Args:
        platform_name: 平台类型名，如 "telegram", "aiocqhttp" 等
        config: 插件配置对象，包含 sender_strategies 配置

    Returns:
        对应的 MessageSender 子类，用于实现平台特定的发送策略
    """
    normalized = (platform_name or "").strip().lower()

    # Check if config has sender_strategies
    strategies = getattr(config, "sender_strategies", None) if config else None
    if strategies is None:
        strategies = {
            "telegram": True,
            "aiocqhttp": True,
            "qq_official": True,
            "weixin_oc": True,
        }

    # Telegram strategy
    if normalized in {"telegram", "tg"} or "telegram" in normalized:
        if strategies.get("telegram", True):
            return TelegramMessageSender
        return MessageSender

    # OneBot/Aiocqhttp strategy
    if normalized in {"aiocqhttp", "onebot", "onebot11", "onebotv11"}:
        if strategies.get("aiocqhttp", True):
            return AiocqhttpMessageSender
        return MessageSender
    if "aiocqhttp" in normalized or "onebot" in normalized:
        if strategies.get("aiocqhttp", True):
            return AiocqhttpMessageSender
        return MessageSender

    # QQ Official strategy
    if normalized in {"qq_official", "qqofficial", "qq"}:
        if strategies.get("qq_official", True):
            return QQOfficialMessageSender
        return MessageSender
    if "qq_official" in normalized or "qqofficial" in normalized:
        if strategies.get("qq_official", True):
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
        if strategies.get("weixin_oc", True):
            return WeixinOCMessageSender
        return MessageSender
    if (
        "weixin_oc" in normalized
        or "weixin_personal" in normalized
        or "wechat_personal" in normalized
    ):
        if strategies.get("weixin_oc", True):
            return WeixinOCMessageSender
        return MessageSender

    return MessageSender
