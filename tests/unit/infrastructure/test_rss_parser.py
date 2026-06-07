"""测试 RSS 解析器"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from astrbot_plugin_rsshub.src.application.dto import WebFeed
from astrbot_plugin_rsshub.src.infrastructure.fetcher import EntryParsed, RSSParser
from astrbot_plugin_rsshub.src.infrastructure.fetcher.http import HttpFetcher
from astrbot_plugin_rsshub.src.infrastructure.fetcher.rss import RSSFeedFetcher
from astrbot_plugin_rsshub.src.infrastructure.utils import get_lock_manager
from feedparser import FeedParserDict


def _json_feed_bytes(**overrides: Any) -> bytes:
    data = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "JSON Timeline",
        "home_page_url": "https://example.com/",
        "feed_url": "https://example.com/feed.json",
        "description": "JSON feed fixture",
        "date_modified": "2026-06-01T10:00:00Z",
        "items": [
            {
                "id": "post-1",
                "url": "https://example.com/posts/1",
                "external_url": "https://mirror.example.com/posts/1",
                "title": "JSON Entry",
                "content_html": "<p>Hello <strong>JSON</strong></p>",
                "summary": "Short JSON summary",
                "authors": [{"name": "Alice"}],
                "tags": ["json", "feed"],
                "date_published": "2026-06-01T09:00:00Z",
                "date_modified": "2026-06-01T09:30:00Z",
                "attachments": [
                    {
                        "url": "https://example.com/video.mp4",
                        "mime_type": "video/mp4",
                        "size_in_bytes": 12345,
                    }
                ],
                "image": "https://example.com/image.jpg",
                "banner_image": "https://example.com/banner.jpg",
            }
        ],
    }
    data.update(overrides)
    return json.dumps(data).encode("utf-8")


class TestRSSParser:
    """测试 RSSParser 类"""

    def setup_method(self):
        """每个测试前清理锁管理器"""
        # 清理锁管理器状态
        manager = get_lock_manager()
        manager._feed_locks.clear()
        manager._user_locks.clear()
        manager._hostname_locks.clear()

    def test_parse_simple_rss(self, sample_rss_feed):
        """测试解析简单 RSS"""
        parser = RSSParser()
        entries, error = parser.parse(sample_rss_feed)

        assert error is None
        assert len(entries) == 3

        # 验证第一个条目
        entry = entries[0]
        assert entry.title == "Test Article 1"
        assert entry.link == "https://example.com/article1"
        assert entry.id == "https://example.com/article1"
        assert entry.published is not None
        assert "<title>Test Article 1</title>" in entry.raw_xml
        assert entry.raw_xml.startswith("<item>")
        assert "<title>Test Article 1</title>" in entry.raw_xml
        assert "<link>https://example.com/article1</link>" in entry.raw_xml

    def test_parse_atom_feed(self, sample_atom_feed):
        """测试解析 Atom feed"""
        parser = RSSParser()
        entries, error = parser.parse(sample_atom_feed)

        assert error is None
        assert len(entries) == 2

        entry = entries[0]
        assert entry.title == "Atom Entry 1"
        assert entry.link == "https://example.com/entry1"
        assert "entry" in entry.raw_xml.split(">", 1)[0]
        assert "Atom Entry 1" in entry.raw_xml

    def test_parse_with_media(self, sample_media_feed):
        """测试解析带媒体的 RSS"""
        parser = RSSParser()
        entries, error = parser.parse(sample_media_feed)

        assert error is None
        assert len(entries) == 3

        # 第一个条目应该有媒体
        entry1 = entries[0]
        assert len(entry1.enclosures) >= 1
        assert entry1.enclosures[0].url == "https://example.com/image1.jpg"

    def test_parse_content_encoded_from_juya_ai_daily_fixture(self, fixtures_dir: Path):
        """测试解析 content:encoded 中的完整正文。"""
        xml = (fixtures_dir / "feeds" / "juya_ai_daily_minimal.xml").read_text(
            encoding="utf-8"
        )

        parser = RSSParser()
        entries, error = parser.parse(xml)

        assert error is None
        assert len(entries) == 1
        entry = entries[0]
        assert entry.summary.startswith("AI 早报 2026-05-19")
        assert "<h1>AI 早报 2026-05-19</h1>" in entry.content
        assert "Qwen3.7 Max Preview" in entry.content
        assert len(entry.content) > len(entry.summary)

    def test_parse_entry_reads_feedparser_content_encoded_compat_field(self):
        """测试 feedparser 兼容字段 content_encoded 也能作为正文。"""
        entry = FeedParserDict(
            {
                "title": "compat",
                "link": "https://example.com/compat",
                "summary": "short summary",
                "content_encoded": "<p>full compat content</p>",
            }
        )

        parsed = RSSParser.parse_entry(entry)

        assert parsed.content == "<p>full compat content</p>"
        assert parsed.summary == "short summary"

    def test_parse_invalid_xml(self):
        """测试解析无效 XML"""
        parser = RSSParser()
        entries, error = parser.parse("not valid xml")

        assert error is not None
        assert len(entries) == 0

    def test_parse_empty_string(self):
        """测试解析空字符串"""
        parser = RSSParser()
        entries, error = parser.parse("")

        assert error is not None
        assert len(entries) == 0

    def test_parse_json_feed_1_1_with_media_and_synthetic_xml(self):
        """测试解析 JSON Feed 1.1 并合成 item XML。"""
        parser = RSSParser()
        entries, error = parser.parse(_json_feed_bytes())

        assert error is None
        assert len(entries) == 1

        entry = entries[0]
        assert entry.id == "post-1"
        assert entry.entry_id == "post-1"
        assert entry.guid == "post-1"
        assert entry.link == "https://example.com/posts/1"
        assert entry.title == "JSON Entry"
        assert entry.content == "<p>Hello <strong>JSON</strong></p>"
        assert entry.summary == "Short JSON summary"
        assert entry.author == "Alice"
        assert entry.tags == ["json", "feed"]
        assert entry.published is not None
        assert entry.updated is not None
        assert [item.url for item in entry.enclosures] == [
            "https://example.com/video.mp4",
            "https://example.com/image.jpg",
            "https://example.com/banner.jpg",
        ]
        assert entry.enclosures[0].length == 12345
        assert entry.enclosures[0].type == "video/mp4"
        assert entry.raw_xml.startswith("<item>")
        assert '<guid isPermaLink="false">post-1</guid>' in entry.raw_xml
        assert "&lt;p&gt;Hello" in entry.raw_xml
        assert '<enclosure url="https://example.com/video.mp4"' in entry.raw_xml

    def test_parse_json_feed_1_0_content_text_and_author_object(self):
        """测试 JSON Feed 1.0 的 author 与 content_text fallback。"""
        parser = RSSParser()
        content = _json_feed_bytes(
            version="https://jsonfeed.org/version/1",
            items=[
                {
                    "id": "post-2",
                    "external_url": "https://example.com/external/2",
                    "title": "Text Entry",
                    "content_text": "Plain <JSON> text",
                    "author": {"name": "Bob"},
                    "date_published": "2026-06-02T01:02:03+00:00",
                }
            ],
        )

        entries, error = parser.parse(content)

        assert error is None
        assert len(entries) == 1
        entry = entries[0]
        assert entry.link == "https://example.com/external/2"
        assert entry.content == "Plain &lt;JSON&gt; text"
        assert entry.author == "Bob"
        assert entry.published is not None

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"ok": True}, "not a supported JSON Feed"),
            (
                {"version": "https://jsonfeed.org/version/1.1", "items": {}},
                "items must be a list",
            ),
            (
                {"version": "https://jsonfeed.org/version/9", "items": []},
                "not a supported JSON Feed",
            ),
        ],
    )
    def test_parse_rejects_ordinary_or_unsupported_json(
        self,
        payload: dict[str, Any],
        expected: str,
    ):
        """测试普通 JSON 不会被误当作 Feed。"""
        parser = RSSParser()
        entries, error = parser.parse(json.dumps(payload).encode("utf-8"))

        assert entries == []
        assert error is not None
        assert expected in error


@pytest.mark.asyncio
async def test_rss_feed_fetcher_accepts_json_feed(monkeypatch: pytest.MonkeyPatch):
    """测试抓取器能把 JSON Feed 适配为 WebFeed.rss_d。"""
    captured_headers: dict[str, str] = {}

    async def fake_fetch(
        self: HttpFetcher,
        url: str,
        **kwargs: Any,
    ) -> WebFeed:
        captured_headers.update(kwargs.get("headers") or {})
        return WebFeed(
            url=url,
            ori_url=url,
            content=_json_feed_bytes(),
            status=200,
            headers={"Content-Type": "application/feed+json"},
        )

    monkeypatch.setattr(HttpFetcher, "fetch", fake_fetch)

    result = await RSSFeedFetcher().fetch("https://example.com/feed.json")

    assert result.error is None
    assert result.rss_d is not None
    assert result.rss_d.feed["title"] == "JSON Timeline"
    assert result.rss_d.entries[0]["id"] == "post-1"
    assert "application/feed+json" in captured_headers["Accept"]
    assert "application/json" in captured_headers["Accept"]


@pytest.mark.asyncio
async def test_rss_feed_fetcher_rejects_ordinary_json(monkeypatch: pytest.MonkeyPatch):
    """测试普通 JSON 响应不会被误判为有效 Feed。"""

    async def fake_fetch(
        self: HttpFetcher,
        url: str,
        **kwargs: Any,
    ) -> WebFeed:
        return WebFeed(
            url=url,
            ori_url=url,
            content=b'{"ok": true}',
            status=200,
            headers={"Content-Type": "application/json"},
        )

    monkeypatch.setattr(HttpFetcher, "fetch", fake_fetch)

    result = await RSSFeedFetcher().fetch("https://example.com/api.json")

    assert result.rss_d is None
    assert result.error is not None
    assert result.error.error_name == "feed invalid"


class TestEntryParsed:
    """测试 EntryParsed 类"""

    def test_entry_to_dict(self):
        """测试条目转换为字典"""
        entry = EntryParsed(
            id="entry-001",
            title="Test Entry",
            link="https://example.com/entry",
            summary="Test summary",
            content="Full content",
            author="Test Author",
            enclosures=[],
            published=None,
            tags=["tag1", "tag2"],
        )

        data = entry.to_dict()
        assert data["id"] == "entry-001"
        assert data["title"] == "Test Entry"
        assert data["link"] == "https://example.com/entry"
        assert data["tags"] == ["tag1", "tag2"]

    def test_entry_text_content(self):
        """测试条目文本内容"""
        entry = EntryParsed(
            id="entry-001",
            title="Test Entry",
            link="https://example.com/entry",
            summary="Summary text",
            content="Full content text",
            author=None,
            enclosures=[],
            published=None,
            tags=[],
        )

        # 优先使用 content
        text = entry.text_content()
        assert "Full content text" in text

    def test_entry_text_content_fallback_to_summary(self):
        """测试文本内容回退到 summary"""
        entry = EntryParsed(
            id="entry-001",
            title="Test Entry",
            link="https://example.com/entry",
            summary="Summary text",
            content=None,
            author=None,
            enclosures=[],
            published=None,
            tags=[],
        )

        text = entry.text_content()
        assert "Summary text" in text
