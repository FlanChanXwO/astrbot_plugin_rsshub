"""
RSS-to-AstrBot Web Utils
基于 RSS-to-Telegram-Bot 移植，简化网络请求处理
"""

from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import AnyStr, Optional

import feedparser


@dataclass
class WebResponse:
    """网络响应"""

    url: str
    ori_url: str = ""
    content: AnyStr | None = None
    headers: dict = field(default_factory=dict)
    status: int = 0
    reason: str | None = None
    now: datetime | None = None

    @property
    def etag(self) -> str | None:
        return self.headers.get("ETag")

    @property
    def last_modified(self) -> datetime | None:
        lm = self.headers.get("Last-Modified")
        if lm:
            try:
                return parsedate_to_datetime(lm)
            except Exception:
                return None
        return None


@dataclass
class WebFeed(WebResponse):
    """RSS Feed 响应"""

    rss_d: feedparser.FeedParserDict | None = None
    error: Optional["WebError"] = None

    @property
    def feed_title(self) -> str | None:
        if self.rss_d and self.rss_d.feed:
            return self.rss_d.feed.get("title")
        return None

    @property
    def entries(self) -> list:
        if self.rss_d:
            return self.rss_d.entries
        return []

    def calc_next_check_as_per_server_side_cache(self) -> datetime | None:
        """根据服务器端缓存计算下次检查时间"""
        # 简化实现，原项目有更复杂的缓存逻辑
        return None


@dataclass
class WebError:
    """网络错误"""

    error_name: str
    url: str
    status: str | None = None
    base_error: Exception | None = None
    log_level: int = 30  # WARNING

    def __str__(self):
        return f"{self.error_name}: {self.url}"


# sentinel对象用于表示未设置的默认值
class _Sentinel:
    def __repr__(self):
        return "<sentinel>"


sentinel = _Sentinel()
