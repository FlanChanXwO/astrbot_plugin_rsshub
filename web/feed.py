"""
RSS-to-AstrBot Feed Fetcher
基于 RSS-to-Telegram-Bot 移植的 RSS feed 获取模块
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from ssl import SSLError
from typing import Final

import aiohttp
import feedparser

from .utils import WebError, WebFeed

FEED_ACCEPT: Final = (
    "application/rss+xml, application/rdf+xml, application/atom+xml, "
    "application/xml;q=0.9, text/xml;q=0.8, text/*;q=0.7, application/*;q=0.6"
)


async def feed_get(
    url: str,
    timeout: float | None = None,
    headers: dict | None = None,
    verbose: bool = True,
    proxy: str = "",
) -> WebFeed:
    """
    获取RSS feed

    Args:
        url: RSS feed URL
        timeout: 超时时间
        headers: 请求头
        verbose: 是否详细日志
        proxy: 代理地址

    Returns:
        WebFeed对象
    """
    ret = WebFeed(url=url, ori_url=url)

    log_level = 30 if verbose else 10  # WARNING or DEBUG
    _headers = {}
    if headers:
        _headers.update(headers)
    if "Accept" not in _headers:
        _headers["Accept"] = FEED_ACCEPT

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=_headers,
                timeout=timeout or 30,
                proxy=proxy or None,
            ) as resp:
                rss_content = await resp.read()
                ret.content = rss_content
                ret.url = str(resp.url)
                ret.headers = dict(resp.headers)
                ret.status = resp.status
                ret.reason = resp.reason

                if (
                    resp.status == 200
                    and int(resp.headers.get("Content-Length", "1")) == 0
                ):
                    ret.status = 304
                    return ret

                if resp.status == 304:
                    return ret

                if rss_content is None or resp.status != 200:
                    status_caption = f"{resp.status}" + (
                        f" {resp.reason}" if resp.reason else ""
                    )
                    ret.error = WebError(
                        error_name="status error",
                        status=status_caption,
                        url=url,
                        log_level=log_level,
                    )
                    return ret

                with BytesIO(rss_content) as rss_content_io:
                    rss_d = feedparser.parse(rss_content_io, sanitize_html=False)

                if not rss_d.feed.get("title"):
                    if not rss_d.entries and (
                        rss_d.bozo
                        or not (rss_d.feed.get("link") or rss_d.feed.get("updated"))
                    ):
                        ret.error = WebError(
                            error_name="feed invalid", url=ret.url, log_level=log_level
                        )
                        return ret
                    rss_d.feed["title"] = ret.url

                ret.rss_d = rss_d

    except aiohttp.InvalidURL:
        ret.error = WebError(error_name="URL invalid", url=url, log_level=log_level)
    except (
        asyncio.TimeoutError,
        aiohttp.ClientError,
        SSLError,
        OSError,
        ConnectionError,
        TimeoutError,
    ) as e:
        ret.error = WebError(
            error_name="network error", url=url, base_error=e, log_level=log_level
        )
    except Exception as e:
        ret.error = WebError(
            error_name="internal error", url=url, base_error=e, log_level=40
        )

    return ret
