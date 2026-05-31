"""消息推送包

提供消息发送和通知分发功能。所有发送器实现位于 senders/ 子包。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 仅供类型检查：让 __all__ 中的名称静态可见，运行时仍由下方 __getattr__
    # 按需懒加载（TYPE_CHECKING 为 False，这些 import 不会执行）。
    from .event_bus import (
        BaseEvent,
        DeduplicationEvent,
        EntryProcessEvent,
        EventBus,
        FeedFetchEvent,
        FeedParseEvent,
        MessageFormatEvent,
        MessageSendEvent,
        MessageSentEvent,
        get_event_bus,
        reset_event_bus,
    )
    from .notification_service import (
        NotificationServiceImpl,
        get_notification_service,
    )
    from .senders import (
        BaseMessageSender,
        ChannelInfo,
        DefaultMessageSender,
        InfrastructureMessageSenderAdapter,
        InfrastructureMessageSenderProvider,
        MessageContext,
        OneBotMessageSender,
        PreparedMedia,
        QQOfficialMessageSender,
        SendResult,
        TelegramMessageSender,
        WeixinOCMessageSender,
        get_bot_client,
        get_bot_self_id,
        get_sender_for_platform,
        register_sender,
        set_bot_client_provider,
        set_bot_self_id_provider,
    )

__all__ = [
    # Event System
    "BaseEvent",
    "EventBus",
    "get_event_bus",
    "reset_event_bus",
    "FeedFetchEvent",
    "FeedParseEvent",
    "EntryProcessEvent",
    "MessageFormatEvent",
    "MessageSendEvent",
    "MessageSentEvent",
    "DeduplicationEvent",
    # Senders
    "SendResult",
    "PreparedMedia",
    "ChannelInfo",
    "MessageContext",
    "BaseMessageSender",
    "DefaultMessageSender",
    "TelegramMessageSender",
    "OneBotMessageSender",
    "QQOfficialMessageSender",
    "WeixinOCMessageSender",
    "InfrastructureMessageSenderAdapter",
    "InfrastructureMessageSenderProvider",
    "get_sender_for_platform",
    "register_sender",
    "get_bot_self_id",
    "set_bot_self_id_provider",
    "get_bot_client",
    "set_bot_client_provider",
    # Notification
    "NotificationServiceImpl",
    "get_notification_service",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "BaseEvent": ("event_bus", "BaseEvent"),
    "EventBus": ("event_bus", "EventBus"),
    "get_event_bus": ("event_bus", "get_event_bus"),
    "reset_event_bus": ("event_bus", "reset_event_bus"),
    "FeedFetchEvent": ("event_bus", "FeedFetchEvent"),
    "FeedParseEvent": ("event_bus", "FeedParseEvent"),
    "EntryProcessEvent": ("event_bus", "EntryProcessEvent"),
    "MessageFormatEvent": ("event_bus", "MessageFormatEvent"),
    "MessageSendEvent": ("event_bus", "MessageSendEvent"),
    "MessageSentEvent": ("event_bus", "MessageSentEvent"),
    "DeduplicationEvent": ("event_bus", "DeduplicationEvent"),
    "SendResult": ("senders", "SendResult"),
    "PreparedMedia": ("senders", "PreparedMedia"),
    "ChannelInfo": ("senders", "ChannelInfo"),
    "MessageContext": ("senders", "MessageContext"),
    "BaseMessageSender": ("senders", "BaseMessageSender"),
    "DefaultMessageSender": ("senders", "DefaultMessageSender"),
    "TelegramMessageSender": ("senders", "TelegramMessageSender"),
    "OneBotMessageSender": ("senders", "OneBotMessageSender"),
    "QQOfficialMessageSender": ("senders", "QQOfficialMessageSender"),
    "WeixinOCMessageSender": ("senders", "WeixinOCMessageSender"),
    "InfrastructureMessageSenderAdapter": (
        "senders",
        "InfrastructureMessageSenderAdapter",
    ),
    "InfrastructureMessageSenderProvider": (
        "senders",
        "InfrastructureMessageSenderProvider",
    ),
    "get_sender_for_platform": ("senders", "get_sender_for_platform"),
    "register_sender": ("senders", "register_sender"),
    "get_bot_self_id": ("senders", "get_bot_self_id"),
    "set_bot_self_id_provider": ("senders", "set_bot_self_id_provider"),
    "get_bot_client": ("senders", "get_bot_client"),
    "set_bot_client_provider": ("senders", "set_bot_client_provider"),
    "NotificationServiceImpl": ("notification_service", "NotificationServiceImpl"),
    "get_notification_service": ("notification_service", "get_notification_service"),
}


def __getattr__(name: str):
    """按需加载 messaging 子模块，避免轻量导入触发应用层依赖。"""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    from importlib import import_module

    value = getattr(import_module(f"{__name__}.{module_name}"), attr_name)
    globals()[name] = value
    return value
