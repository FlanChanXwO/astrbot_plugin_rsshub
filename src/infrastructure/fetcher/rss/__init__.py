"""Feed 数据源子包

提供 RSS/Atom/JSON Feed 订阅源的抓取、解析和自动发现能力。
"""

from __future__ import annotations

from typing import Final

import aiohttp

from ....application.dto import WebFeed
from ....domain.exceptions import WebError
from ...utils import get_logger
from ..http import HttpFetcher
from .discoverer import FeedDiscoverer, FeedDiscoveryResult
from .document_parser import FeedDocumentParser
from .parser import Enclosure, EntryParsed, RSSParser

logger = get_logger()

FEED_ACCEPT: Final = (
    "application/rss+xml, application/rdf+xml, application/atom+xml, "
    "application/feed+json, application/xml;q=0.9, text/xml;q=0.8, "
    "application/json;q=0.7, text/*;q=0.7, application/*;q=0.6"
)


class RSSFeedFetcher(HttpFetcher):
    """Feed 专用抓取器

    在 HttpFetcher 基础上添加 RSS/Atom/JSON Feed 内容校验。
    """

    async def fetch(
        self,
        url: str,
        *,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
        verbose: bool = True,
        proxy: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> WebFeed:
        """抓取 RSS/Atom/JSON Feed 内容并解析为 WebFeed。

        Args:
            url: Feed URL
            timeout: 请求超时（秒），默认使用实例配置
            headers: 额外请求头
            verbose: 是否输出详细日志
            proxy: 临时代理地址（优先于实例代理）
            session: 外部 session（若提供则直接使用）

        Returns:
            WebFeed 抓取结果对象，包含 rss_d
        """
        _headers: dict[str, str] = {}
        if headers:
            _headers.update(headers)
        if "Accept" not in _headers:
            _headers["Accept"] = FEED_ACCEPT

        ret = await super().fetch(
            url,
            timeout=timeout,
            headers=_headers,
            verbose=verbose,
            proxy=proxy,
            session=session,
        )

        if ret.error or ret.status == 304 or ret.content is None:
            return ret

        log_level = 30 if verbose else 10

        parser = FeedDocumentParser()
        rss_d, parse_error, base_error = parser.parse_feedparser_dict(
            ret.content,
            fallback_title=ret.url,
        )
        if parse_error:
            ret.error = WebError(
                error_name=parse_error,
                url=ret.url,
                base_error=base_error,
                log_level=40 if parse_error == "feed parse error" else log_level,
            )
            return ret

        if rss_d is not None:
            ret.rss_d = rss_d

            etag_header = ret.etag
            if etag_header:
                logger.debug("feed_get: Received ETag '%s' for %s", etag_header, url)

        return ret


__all__ = [
    "RSSFeedFetcher",
    "RSSParser",
    "EntryParsed",
    "Enclosure",
    "FeedDiscoverer",
    "FeedDiscoveryResult",
]
