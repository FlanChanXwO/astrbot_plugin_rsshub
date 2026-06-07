"""Feed 文档格式识别与解析委派。"""

from __future__ import annotations

import feedparser

from .json_feed_parser import JSONFeedParser
from .models import EntryParsed
from .xml_parser import XMLFeedParser


class FeedDocumentParser:
    """在 XML RSS/Atom 与 JSON Feed 之间做格式路由。"""

    def __init__(
        self,
        *,
        xml_parser: XMLFeedParser | None = None,
        json_parser: JSONFeedParser | None = None,
    ) -> None:
        self._xml_parser = xml_parser or XMLFeedParser()
        self._json_parser = json_parser or JSONFeedParser()

    def parse(self, content: str | bytes) -> tuple[list[EntryParsed], str | None]:
        """解析 Feed 文档为统一条目模型。"""
        if JSONFeedParser.is_json_document(content):
            return self._json_parser.parse(content)
        return self._xml_parser.parse(content)

    def parse_feedparser_dict(
        self,
        content: str | bytes,
        *,
        fallback_title: str = "",
    ) -> tuple[feedparser.FeedParserDict | None, str | None, Exception | None]:
        """解析 Feed 文档元信息，供 WebFeed.rss_d 使用。"""
        if JSONFeedParser.is_json_document(content):
            return self._json_parser.parse_feedparser_dict(
                content,
                fallback_title=fallback_title,
            )
        return self._xml_parser.parse_feedparser_dict(
            content,
            fallback_title=fallback_title,
        )
