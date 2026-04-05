"""
RSS-to-AstrBot Error Collection
错误定义模块
"""

from __future__ import annotations


class RSSError(Exception):
    """RSS 插件基础错误"""

    def __init__(self, message: str = "RSS error"):
        self.message = message
        super().__init__(message)


class FeedError(RSSError):
    """Feed 相关错误"""

    def __init__(self, error_name: str, url: str = "", message: str = ""):
        self.error_name = error_name
        self.url = url
        super().__init__(message or f"Feed error: {error_name} ({url})")


class NetworkError(RSSError):
    """网络相关错误"""

    def __init__(self, url: str, base_error: Exception | None = None):
        self.url = url
        self.base_error = base_error
        message = f"Network error: {url}"
        if base_error:
            message += f" - {type(base_error).__name__}: {base_error}"
        super().__init__(message)


class ParseError(RSSError):
    """解析相关错误"""

    def __init__(self, message: str = "Parse error", content: str = ""):
        self.content = content
        super().__init__(message)


class DatabaseError(RSSError):
    """数据库相关错误"""

    def __init__(
        self, message: str = "Database error", base_error: Exception | None = None
    ):
        self.base_error = base_error
        if base_error:
            message = f"{message}: {base_error}"
        super().__init__(message)


class SubscriptionError(RSSError):
    """订阅相关错误"""

    def __init__(self, message: str = "Subscription error"):
        super().__init__(message)


class SubscriptionLimitError(SubscriptionError):
    """订阅数量限制错误"""

    def __init__(self, limit: int, current: int):
        self.limit = limit
        self.current = current
        super().__init__(f"订阅数量已达上限 ({current}/{limit})")


class FeedNotFoundError(RSSError):
    """Feed 未找到错误"""

    def __init__(self, feed_id: int = None, url: str = ""):
        self.feed_id = feed_id
        self.url = url
        message = "Feed not found"
        if feed_id:
            message += f" (id={feed_id})"
        elif url:
            message += f" ({url})"
        super().__init__(message)


class SubscriptionNotFoundError(RSSError):
    """订阅未找到错误"""

    def __init__(self, sub_id: int = None, user_id: int = None):
        self.sub_id = sub_id
        self.user_id = user_id
        message = "Subscription not found"
        if sub_id:
            message += f" (id={sub_id})"
        super().__init__(message)


class MediaError(RSSError):
    """媒体相关错误"""

    def __init__(self, url: str, message: str = "Media error"):
        self.url = url
        super().__init__(f"{message}: {url}")


class MediaDownloadError(MediaError):
    """媒体下载错误"""

    def __init__(self, url: str, base_error: Exception | None = None):
        self.base_error = base_error
        message = "Media download failed"
        if base_error:
            message += f" ({type(base_error).__name__})"
        super().__init__(url, message)


class ConfigError(RSSError):
    """配置相关错误"""

    def __init__(self, key: str = "", message: str = "Config error"):
        self.key = key
        if key:
            message = f"{message}: {key}"
        super().__init__(message)
