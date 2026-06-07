"""Feed 条目解析兼容门面。"""

from __future__ import annotations

from .document_parser import FeedDocumentParser
from .models import Enclosure, EntryParsed
from .xml_parser import XMLFeedParser


class RSSParser(FeedDocumentParser):
    """兼容历史 import 的统一 Feed 解析器。"""

    parse_entry = staticmethod(XMLFeedParser.parse_entry)


__all__ = ["RSSParser", "EntryParsed", "Enclosure"]
