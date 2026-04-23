"""RSSHub Plugin Exceptions

异常错误定义模块
"""

from .errors import (
    ConfigError,
    DatabaseError,
    FeedError,
    FeedNotFoundError,
    MediaDownloadError,
    MediaError,
    NetworkError,
    ParseError,
    RSSError,
    SubscriptionError,
    SubscriptionLimitError,
    SubscriptionNotFoundError,
)

__all__ = [
    "RSSError",
    "FeedError",
    "NetworkError",
    "ParseError",
    "DatabaseError",
    "SubscriptionError",
    "SubscriptionLimitError",
    "FeedNotFoundError",
    "SubscriptionNotFoundError",
    "MediaError",
    "MediaDownloadError",
    "ConfigError",
]
