# RSS-to-AstrBot Notifier Module

from .notifier import Notifier
from .senders import (
    ChannelInfo,
    MessageSender,
    NotifierContext,
    SendResult,
    TelegramMessageSender,
    get_sender_for_platform_name,
    set_bot_self_id_provider,
)

__all__ = [
    "Notifier",
    "MessageSender",
    "TelegramMessageSender",
    "SendResult",
    "ChannelInfo",
    "NotifierContext",
    "get_sender_for_platform_name",
    "set_bot_self_id_provider",
]
