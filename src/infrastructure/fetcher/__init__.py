"""数据采集层

提供通用 HTTP 抓取和 RSS 数据源处理能力。
"""

from ...application.dto import WebFeed as WebFeed
from .http import HttpFetcher
from .rss import (
    Enclosure as Enclosure,
)
from .rss import (
    EntryParsed as EntryParsed,
)
from .rss import (
    FeedDiscoverer as FeedDiscoverer,
)
from .rss import (
    FeedDiscoveryResult as FeedDiscoveryResult,
)
from .rss import (
    RSSFeedFetcher as RSSFeedFetcher,
)
from .rss import (
    RSSParser as RSSParser,
)

__all__ = [
    "Enclosure",
    "EntryParsed",
    "FeedDiscoverer",
    "FeedDiscoveryResult",
    "HttpFetcher",
    "RSSFeedFetcher",
    "RSSParser",
    "WebFeed",
]
