"""Minimal Telegraph client for sender-side media diversion."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import aiohttp

from ...utils import get_logger

if TYPE_CHECKING:
    from .types import ChannelInfo

logger = get_logger()


class TelegraphClient:
    """Create Telegraph pages and return the public page URL."""

    API_BASE_URL = "https://api.telegra.ph"

    def __init__(self, *, access_token: str, timeout_seconds: int = 30) -> None:
        self._access_token = str(access_token or "").strip()
        self._timeout_seconds = max(1, int(timeout_seconds or 30))

    @property
    def enabled(self) -> bool:
        return bool(self._access_token)

    async def create_media_page(
        self,
        *,
        title: str,
        content: str,
        media_urls: list[str],
        channel: ChannelInfo | None = None,
    ) -> str:
        if not self.enabled:
            raise ValueError("missing telegraph access token")

        page_title = str(title or "").strip() or "RSSHub"
        html_content = self._build_html(
            title=page_title,
            content=content,
            media_urls=media_urls,
            channel=channel,
        )
        payload = {
            "access_token": self._access_token,
            "title": page_title[:256],
            "content": json.dumps(html_content, ensure_ascii=False),
            "return_content": "false",
        }

        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self.API_BASE_URL}/createPage",
                data=payload,
            ) as resp:
                data = await resp.json(content_type=None)

        if not isinstance(data, dict) or not data.get("ok"):
            raise RuntimeError(f"telegraph createPage failed: {data}")
        result = data.get("result") or {}
        url = str(result.get("url") or "").strip()
        if not url:
            raise RuntimeError("telegraph createPage returned empty url")
        return url

    @staticmethod
    def _build_html(
        *,
        title: str,
        content: str,
        media_urls: list[str],
        channel: ChannelInfo | None,
    ) -> list[dict[str, object]]:
        nodes: list[dict[str, object]] = []
        meta = TelegraphClient._build_meta_line(channel)
        if meta:
            nodes.append({"tag": "p", "children": meta})

        body_paragraphs = TelegraphClient._content_paragraphs(content, title, channel)
        for paragraph in body_paragraphs:
            nodes.append({"tag": "p", "children": [paragraph]})

        for media_url in media_urls:
            media_node = TelegraphClient._media_node(media_url)
            if media_node is not None:
                nodes.append(media_node)
        return nodes

    @staticmethod
    def _build_meta_line(channel: ChannelInfo | None) -> list[object]:
        channel_title = str(channel.title or "").strip() if channel else ""
        channel_link = str(channel.link or "").strip() if channel else ""
        if not channel_title and not channel_link:
            return []
        children: list[object] = []
        if channel_link and TelegraphClient._is_safe_http_url(channel_link):
            children.append(
                {
                    "tag": "a",
                    "attrs": {"href": channel_link},
                    "children": [channel_title or channel_link],
                }
            )
        elif channel_title or channel_link:
            children.append(channel_title or channel_link)
        return children

    @staticmethod
    def _is_safe_http_url(url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        return parsed.scheme in {"http", "https"}

    @staticmethod
    def _content_paragraphs(
        content: str,
        title: str,
        channel: ChannelInfo | None,
    ) -> list[str]:
        paragraphs: list[str] = []
        seen: set[str] = set()
        skipped_via = False
        channel_title = str(channel.title or "").strip() if channel else ""
        channel_link = str(channel.link or "").strip() if channel else ""
        for paragraph in [part.strip() for part in str(content or "").split("\n\n")]:
            if not paragraph:
                continue
            if paragraph == title and not paragraphs:
                continue
            if paragraph.startswith("via "):
                if skipped_via or channel_title or channel_link:
                    skipped_via = True
                    continue
                skipped_via = True
            if paragraph == channel_title or paragraph == channel_link:
                continue
            if paragraph in seen:
                continue
            paragraphs.append(paragraph)
            seen.add(paragraph)
        return paragraphs

    @staticmethod
    def _media_node(media_url: str) -> dict[str, object] | None:
        url = str(media_url or "").strip()
        if not url:
            return None
        if not TelegraphClient._is_safe_http_url(url):
            return None
        parsed = urlparse(url)
        suffix = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else ""
        if suffix in {"jpg", "jpeg", "png", "gif", "webp"}:
            return {"tag": "img", "attrs": {"src": url}}
        if suffix in {"mp4", "webm"}:
            return {"tag": "video", "attrs": {"src": url, "controls": "true"}}
        return {
            "tag": "p",
            "children": [
                {
                    "tag": "a",
                    "attrs": {"href": url},
                    "children": [url],
                }
            ],
        }
