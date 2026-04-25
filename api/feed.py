"""RSS feed fetcher for outbound subscription requests."""

from __future__ import annotations

import asyncio
from io import BytesIO
from ssl import SSLError
from typing import Final

import aiohttp
import feedparser

from ..web.models import WebError, WebFeed

FEED_ACCEPT: Final = (
    "application/rss+xml, application/rdf+xml, application/atom+xml, "
    "application/xml;q=0.9, text/xml;q=0.8, text/*;q=0.7, application/*;q=0.6"
)

_shared_session: aiohttp.ClientSession | None = None
_session_lock: asyncio.Lock | None = None


async def _get_shared_session() -> aiohttp.ClientSession:
    global _shared_session, _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    async with _session_lock:
        if _shared_session is None or _shared_session.closed:
            _shared_session = aiohttp.ClientSession()
    return _shared_session


async def close_shared_session() -> None:
    """Close module-level shared session if it exists."""
    global _shared_session, _session_lock
    if _session_lock is not None:
        async with _session_lock:
            if _shared_session is not None and not _shared_session.closed:
                await _shared_session.close()
            _shared_session = None
    else:
        if _shared_session is not None and not _shared_session.closed:
            await _shared_session.close()
        _shared_session = None


async def feed_get(
    url: str,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
    verbose: bool = True,
    proxy: str = "",
    session: aiohttp.ClientSession | None = None,
) -> WebFeed:
    """Fetch RSS/Atom content and parse into ``WebFeed``."""
    ret = WebFeed(url=url, ori_url=url)

    log_level = 30 if verbose else 10  # WARNING or DEBUG
    _headers = {}
    if headers:
        _headers.update(headers)
    if "Accept" not in _headers:
        _headers["Accept"] = FEED_ACCEPT

    # 如果有 proxy，创建临时 session（不使用共享 session）
    use_shared_session = not proxy and session is None

    try:
        if use_shared_session:
            client = await _get_shared_session()
            temp_session = None
        elif session is not None:
            client = session
            temp_session = None
        else:
            # 创建带 proxy 的临时 session
            temp_session = aiohttp.ClientSession(proxy=proxy if proxy else None)
            client = temp_session

        async with client.get(
            url,
            headers=_headers,
            timeout=timeout or 30,
            proxy=proxy or None if not use_shared_session else None,
        ) as resp:
            rss_content = await resp.read()
            ret.content = rss_content
            ret.url = str(resp.url)
            # Preserve case-insensitive headers by converting to dict
            # CIMultiDictProxy preserves original case when converted to dict
            ret.headers = dict(resp.headers.items())
            ret.status = resp.status
            ret.reason = resp.reason

            # Debug: log ETag header if present
            etag_header = ret.headers.get("ETag") or ret.headers.get("etag")
            if etag_header:
                from ..utils.log_utils import logger

                logger.debug(f"feed_get: Received ETag '{etag_header}' for {url}")

            if resp.status == 200 and int(resp.headers.get("Content-Length", "1")) == 0:
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
    finally:
        # 关闭临时创建的 session
        if temp_session is not None and not temp_session.closed:
            await temp_session.close()

    return ret
