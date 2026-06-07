"""标准 JSON Feed 解析器。"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any
from xml.etree import ElementTree

import feedparser

from .models import Enclosure, EntryParsed

JSON_FEED_VERSIONS = {
    "https://jsonfeed.org/version/1",
    "https://jsonfeed.org/version/1.1",
}


class JSONFeedParser:
    """解析 JSON Feed 1.0 / 1.1 并适配为插件内部条目模型。"""

    def parse(self, json_content: str | bytes) -> tuple[list[EntryParsed], str | None]:
        """解析标准 JSON Feed 内容为条目列表。"""
        data, error, _ = self._load_json_feed(json_content)
        if error:
            return [], error

        entries = self._parse_entries(data)
        if not entries:
            return [], "JSON Feed has no items"
        return entries, None

    def parse_feedparser_dict(
        self,
        json_content: str | bytes,
        *,
        fallback_title: str = "",
    ) -> tuple[feedparser.FeedParserDict | None, str | None, Exception | None]:
        """解析 JSON Feed 元信息，供抓取器填充 WebFeed.rss_d。"""
        data, error, exc = self._load_json_feed(json_content)
        if error:
            return None, "feed invalid" if exc is None else "feed parse error", exc

        feed_meta = feedparser.FeedParserDict()
        feed_meta["title"] = self._text(data.get("title")) or fallback_title
        feed_meta["link"] = (
            self._text(data.get("home_page_url"))
            or self._text(data.get("feed_url"))
            or ""
        )
        feed_meta["href"] = self._text(data.get("feed_url"))
        feed_meta["description"] = self._text(data.get("description"))
        feed_meta["updated"] = self._text(data.get("date_modified"))

        parsed_entries = self._parse_entries(data)
        rss_d = feedparser.FeedParserDict()
        rss_d["feed"] = feed_meta
        rss_d["entries"] = [
            self._entry_to_feedparser_dict(entry) for entry in parsed_entries
        ]
        rss_d["bozo"] = False
        return rss_d, None, None

    @staticmethod
    def is_json_document(content: str | bytes) -> bool:
        """判断响应正文是否是 JSON 文档形态。"""
        if isinstance(content, bytes):
            text = content.decode("utf-8-sig", errors="ignore")
        else:
            text = str(content or "")
        stripped = text.lstrip()
        return stripped.startswith("{") or stripped.startswith("[")

    def _load_json_feed(
        self, json_content: str | bytes
    ) -> tuple[dict[str, Any], str | None, Exception | None]:
        if not json_content:
            return {}, "JSON Feed content is empty", None

        try:
            if isinstance(json_content, bytes):
                text = json_content.decode("utf-8-sig")
            else:
                text = str(json_content)
        except UnicodeDecodeError as exc:
            return {}, f"JSON Feed decode failed: {exc}", exc

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return {}, f"JSON Feed parse failed: {exc}", exc

        if not isinstance(data, dict):
            return {}, "JSON content is not a supported JSON Feed", None

        version = self._text(data.get("version"))
        if version not in JSON_FEED_VERSIONS:
            return {}, "JSON content is not a supported JSON Feed", None

        if not isinstance(data.get("items"), list):
            return {}, "JSON Feed items must be a list", None

        return data, None, None

    def _parse_entries(self, data: dict[str, Any]) -> list[EntryParsed]:
        feed_link = self._text(data.get("home_page_url")) or self._text(
            data.get("feed_url")
        )
        entries: list[EntryParsed] = []
        for item in data.get("items", []):
            if not isinstance(item, dict):
                continue
            entry = self._parse_item(item, feed_link=feed_link)
            entry.raw_xml = self._build_synthetic_item_xml(entry)
            entries.append(entry)
        return entries

    def _parse_item(self, item: dict[str, Any], *, feed_link: str = "") -> EntryParsed:
        entry_id = self._text(item.get("id"))
        link = self._text(item.get("url")) or self._text(item.get("external_url"))
        title = self._text(item.get("title"))
        summary = self._text(item.get("summary"))
        content = self._item_content(item)
        author = self._author_name(item)

        entry = EntryParsed()
        entry.id = entry_id or link or title
        entry.entry_id = entry_id
        entry.guid = entry_id
        entry.link = link or feed_link
        entry.title = title
        entry.author = author
        entry.content = content or summary
        entry.summary = summary
        entry.tags = self._tags(item)
        entry.enclosures = self._enclosures(item)
        entry.published = self._parse_datetime(item.get("date_published"))
        entry.updated = self._parse_datetime(item.get("date_modified"))
        return entry

    def _item_content(self, item: dict[str, Any]) -> str:
        content_html = item.get("content_html")
        if isinstance(content_html, str) and content_html:
            return content_html

        content_text = item.get("content_text")
        if isinstance(content_text, str) and content_text:
            return html.escape(content_text)

        return self._text(item.get("summary"))

    def _author_name(self, item: dict[str, Any]) -> str:
        authors = item.get("authors")
        if isinstance(authors, list):
            for author in authors:
                name = self._author_value(author)
                if name:
                    return name

        return self._author_value(item.get("author"))

    def _author_value(self, raw_author: Any) -> str:
        if isinstance(raw_author, dict):
            return self._text(raw_author.get("name"))
        if isinstance(raw_author, str):
            return raw_author.strip()
        return ""

    def _tags(self, item: dict[str, Any]) -> list[str]:
        raw_tags = item.get("tags")
        if not isinstance(raw_tags, list):
            return []
        return [tag for tag in (self._text(value) for value in raw_tags) if tag]

    def _enclosures(self, item: dict[str, Any]) -> list[Enclosure]:
        enclosures: list[Enclosure] = []
        attachments = item.get("attachments")
        if isinstance(attachments, list):
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                url = self._text(attachment.get("url"))
                if not url:
                    continue
                enclosures.append(
                    Enclosure(
                        url=url,
                        length=self._int(attachment.get("size_in_bytes")),
                        type=self._text(attachment.get("mime_type")),
                    )
                )

        for image_key in ("image", "banner_image"):
            url = self._text(item.get(image_key))
            if url and not any(enclosure.url == url for enclosure in enclosures):
                enclosures.append(Enclosure(url=url, type="image/*"))

        return enclosures

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None

    def _entry_to_feedparser_dict(
        self,
        entry: EntryParsed,
    ) -> feedparser.FeedParserDict:
        item = feedparser.FeedParserDict()
        item["id"] = entry.entry_id
        item["guid"] = entry.guid
        item["title"] = entry.title
        item["link"] = entry.link
        item["author"] = entry.author or ""
        item["summary"] = entry.summary or ""
        item["description"] = entry.summary or ""
        item["content"] = [
            feedparser.FeedParserDict(
                {
                    "value": entry.content or "",
                    "type": "text/html",
                }
            )
        ]
        item["tags"] = [feedparser.FeedParserDict({"term": tag}) for tag in entry.tags]
        item["enclosures"] = [
            feedparser.FeedParserDict(
                {
                    "href": enclosure.url,
                    "url": enclosure.url,
                    "length": str(enclosure.length),
                    "type": enclosure.type,
                }
            )
            for enclosure in entry.enclosures
        ]
        if entry.published:
            item["published"] = entry.published.isoformat()
            item["published_parsed"] = entry.published.utctimetuple()
        if entry.updated:
            item["updated"] = entry.updated.isoformat()
            item["updated_parsed"] = entry.updated.utctimetuple()
        return item

    def _build_synthetic_item_xml(self, entry: EntryParsed) -> str:
        root = ElementTree.Element("item")
        self._append_text(root, "title", entry.title)
        self._append_text(root, "link", entry.link)
        if entry.guid:
            guid = ElementTree.SubElement(root, "guid")
            guid.set("isPermaLink", "false")
            guid.text = entry.guid
        self._append_text(root, "description", entry.content or entry.summary or "")
        self._append_text(root, "author", entry.author or "")
        if entry.published:
            self._append_text(root, "pubDate", format_datetime(entry.published))
        if entry.updated:
            self._append_text(root, "updated", entry.updated.isoformat())
        for tag in entry.tags:
            self._append_text(root, "category", tag)
        for enclosure in entry.enclosures:
            attrs = {"url": enclosure.url}
            if enclosure.length:
                attrs["length"] = str(enclosure.length)
            if enclosure.type:
                attrs["type"] = enclosure.type
            ElementTree.SubElement(root, "enclosure", attrs)
        return ElementTree.tostring(root, encoding="unicode")

    @staticmethod
    def _append_text(root: ElementTree.Element, tag: str, value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        ElementTree.SubElement(root, tag).text = text

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
