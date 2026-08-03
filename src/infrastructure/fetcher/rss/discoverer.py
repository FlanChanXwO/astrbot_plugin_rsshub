"""Feed 自动发现模块

从网页 HTML 中自动发现 RSS/Atom Feed 链接。
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from ...utils import get_logger

logger = get_logger()


class FeedDiscoveryResult:
    """Feed 发现结果"""

    def __init__(self, url: str, title: str = "", feed_type: str = "") -> None:
        self.url = url
        self.title = title
        self.feed_type = feed_type

    def __repr__(self) -> str:
        return f"FeedDiscoveryResult(url={self.url}, title={self.title})"


class FeedDiscoverer:
    """Feed 自动发现器"""

    def __init__(self, timeout: int = 30, proxy: str = "") -> None:
        self.timeout = max(1, int(timeout or 30))
        self.proxy = (proxy or "").strip()

    async def discover_from_url(self, page_url: str) -> list[FeedDiscoveryResult]:
        """从网页 URL 中发现 Feed 链接

        Args:
            page_url: 网页 URL

        Returns:
            发现的 Feed 列表
        """
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(
                    page_url,
                    timeout=self.timeout,
                    proxy=self.proxy or None,
                    headers={
                        "Accept": "text/html,application/xhtml+xml",
                        "User-Agent": "Mozilla/5.0 (compatible; RSSHubBot/1.0)",
                    },
                ) as resp,
            ):
                if resp.status != 200:
                    return []
                html = await resp.text()
                base_url = str(resp.url)
        except Exception as ex:
            logger.warning("Feed discovery failed for %s: %s", page_url, ex)
            return []

        return self._discover_from_html(html, base_url)

    @staticmethod
    def _discover_from_html(html: str, base_url: str) -> list[FeedDiscoveryResult]:
        """从 HTML 内容中解析 Feed 链接

        Args:
            html: HTML 内容
            base_url: 基础 URL（用于解析相对链接）

        Returns:
            发现的 Feed 列表
        """
        soup = BeautifulSoup(html, "lxml")
        results: list[FeedDiscoveryResult] = []
        seen: set[str] = set()

        for link in soup.find_all("link", rel="alternate"):
            feed_type = link.get("type", "").lower()
            if feed_type not in (
                "application/rss+xml",
                "application/atom+xml",
                "application/feed+json",
                "application/json",
            ):
                continue

            href = link.get("href", "")
            if not href:
                continue

            url = FeedDiscoverer._resolve_url(href, base_url)
            if url in seen:
                continue
            seen.add(url)

            title = link.get("title", "")
            results.append(
                FeedDiscoveryResult(
                    url=url,
                    title=title,
                    feed_type=feed_type,
                )
            )

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href:
                continue
            lowered = href.lower()
            if any(
                pattern in lowered
                for pattern in ("/rss", "/feed", "/atom", ".rss", ".xml")
            ):
                url = FeedDiscoverer._resolve_url(href, base_url)
                if url in seen:
                    continue
                seen.add(url)

                title = a.get_text(strip=True) or ""
                results.append(
                    FeedDiscoveryResult(
                        url=url,
                        title=title,
                        feed_type="application/rss+xml",
                    )
                )

        return results

    @staticmethod
    def _resolve_url(url: str, base_url: str) -> str:
        """解析相对 URL"""
        if not url:
            return ""
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("//"):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}:{url}"
        return urljoin(base_url, url)
