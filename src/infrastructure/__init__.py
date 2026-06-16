"""基础设施层

提供技术能力实现：数据库、网络、文件系统、配置管理等。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MAP = {
    "BasicConfig": ("config", "BasicConfig"),
    "GlobalConfig": ("config", "GlobalConfig"),
    "RsshubPluginConfig": ("config", "RsshubPluginConfig"),
    "SenderStrategiesConfig": ("config", "SenderStrategiesConfig"),
    "HttpFetcher": ("fetcher", "HttpFetcher"),
    "WebFeed": ("fetcher", "WebFeed"),
    "RSSFeedFetcher": ("fetcher", "RSSFeedFetcher"),
    "RSSParser": ("fetcher", "RSSParser"),
    "EntryParsed": ("fetcher", "EntryParsed"),
    "Enclosure": ("fetcher", "Enclosure"),
    "FeedDiscoverer": ("fetcher", "FeedDiscoverer"),
    "FeedDiscoveryResult": ("fetcher", "FeedDiscoveryResult"),
    "MediaDownloader": ("media", "MediaDownloader"),
    "BaseEvent": ("messaging", "BaseEvent"),
    "BaseMessageSender": ("messaging", "BaseMessageSender"),
    "ChannelInfo": ("messaging", "ChannelInfo"),
    "DefaultMessageSender": ("messaging", "DefaultMessageSender"),
    "EventBus": ("messaging", "EventBus"),
    "InfrastructureMessageSenderAdapter": (
        "messaging",
        "InfrastructureMessageSenderAdapter",
    ),
    "InfrastructureMessageSenderProvider": (
        "messaging",
        "InfrastructureMessageSenderProvider",
    ),
    "MessageContext": ("messaging", "MessageContext"),
    "NotificationServiceImpl": ("messaging", "NotificationServiceImpl"),
    "OneBotMessageSender": ("messaging", "OneBotMessageSender"),
    "PreparedMedia": ("messaging", "PreparedMedia"),
    "QQOfficialMessageSender": ("messaging", "QQOfficialMessageSender"),
    "SendResult": ("messaging", "SendResult"),
    "TelegramMessageSender": ("messaging", "TelegramMessageSender"),
    "get_bot_self_id": ("messaging", "get_bot_self_id"),
    "get_event_bus": ("messaging", "get_event_bus"),
    "get_notification_service": ("messaging", "get_notification_service"),
    "get_sender_for_platform": ("messaging", "get_sender_for_platform"),
    "register_sender": ("messaging", "register_sender"),
    "set_bot_self_id_provider": ("messaging", "set_bot_self_id_provider"),
    "DatabaseManager": ("persistence", "DatabaseManager"),
    "FeedORM": ("persistence", "FeedORM"),
    "FeedRepositoryImpl": ("persistence", "FeedRepositoryImpl"),
    "PushHistoryORM": ("persistence", "PushHistoryORM"),
    "PushHistoryRepositoryImpl": ("persistence", "PushHistoryRepositoryImpl"),
    "RSSHubBaseModel": ("persistence", "RSSHubBaseModel"),
    "SubORM": ("persistence", "SubORM"),
    "SubscriptionRepositoryImpl": ("persistence", "SubscriptionRepositoryImpl"),
    "UserORM": ("persistence", "UserORM"),
    "UserRepositoryImpl": ("persistence", "UserRepositoryImpl"),
    "get_database": ("persistence", "get_database"),
    "get_feed_repository": ("persistence", "get_feed_repository"),
    "get_push_history_repository": ("persistence", "get_push_history_repository"),
    "get_subscription_repository": ("persistence", "get_subscription_repository"),
    "get_user_repository": ("persistence", "get_user_repository"),
    "RSSScheduler": ("schedule", "RSSScheduler"),
    "SchedulerStats": ("schedule", "SchedulerStats"),
    "AsyncTool": ("utils", "AsyncTool"),
    "BaseCache": ("utils", "BaseCache"),
    "CompiledExpression": ("utils", "CompiledExpression"),
    "ExpressionEvaluator": ("utils", "ExpressionEvaluator"),
    "ExpressionParser": ("utils", "ExpressionParser"),
    "FFmpegTool": ("utils", "FFmpegTool"),
    "LockManager": ("utils", "LockManager"),
    "cacheevict": ("utils", "cacheevict"),
    "cacheput": ("utils", "cacheput"),
    "caching": ("utils", "caching"),
    "get_logger": ("utils", "get_logger"),
    "get_memory_cache": ("utils", "get_memory_cache"),
    "locked": ("utils", "locked"),
    "set_cache_backend": ("utils", "set_cache_backend"),
}

__all__ = sorted(_EXPORT_MAP)


def __getattr__(name: str) -> Any:
    module_info = _EXPORT_MAP.get(name)
    if module_info is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = module_info
    module = import_module(f".{module_name}", __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
