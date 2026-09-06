"""Bundle 聚合 RSS 文档构造与文档级 handler 运行时。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

from ...domain.entities.bundle import Bundle
from ...domain.entities.bundle_feed import BundleFeed
from ...domain.entities.delivery import DeliveryInboxItem
from ...domain.entities.feed import Feed
from ...domain.entities.handlers import (
    HandlerSpec,
    is_handler_enabled,
    normalize_handlers,
)
from ...infrastructure.utils import get_logger
from .content_handlers import ToolSet, XmlValidationTool, _SyntheticHandlerEvent

logger = get_logger()


def _as_utc(value: datetime | None) -> datetime | None:
    """把内部时间快照规范化为带 UTC 时区的 datetime。"""
    if value is None:
        return None
    if value.tzinfo is None:
        # 数据库历史值可能没有时区；项目现有兼容约定将其解释为 UTC。
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class BundleDocumentValidationError(ValueError):
    """聚合 RSS 文档不是安全且合法的 RSS 2.0 文档。"""


@dataclass(frozen=True, slots=True)
class BundleDocumentEntry:
    """聚合文档中的一条 JSON-safe 条目快照。"""

    item_key: str
    feed_id: int
    member_position: int
    title: str
    link: str
    author: str
    summary: str
    content_html: str
    tags: tuple[str, ...]
    media_items: tuple[dict[str, Any], ...]
    published: datetime | None
    updated: datetime | None

    def to_json(self) -> dict[str, Any]:
        """返回卡片模板可消费的 JSON-safe 条目。"""
        published = _as_utc(self.published)
        updated = _as_utc(self.updated)
        return {
            "item_key": self.item_key,
            "feed_id": self.feed_id,
            "title": self.title,
            "link": self.link,
            "author": self.author,
            "published": published.isoformat() if published else None,
            "updated": updated.isoformat() if updated else None,
            "summary": self.summary,
            "content_html": self.content_html,
            "tags": list(self.tags),
            "media_items": [dict(item) for item in self.media_items],
        }


@dataclass(frozen=True, slots=True)
class BundleAggregateDocument:
    """Bundle RSS 文档及其当前结构化条目快照。"""

    entries: tuple[BundleDocumentEntry, ...]
    text: str
    rss_xml: str
    consumption_item_keys: tuple[str, ...]
    # 仅供 XML handler 将新增条目映射回稳定的 Bundle 来源，不暴露给模板。
    feed_sources: tuple[tuple[int, str, int], ...] = ()

    def to_json(self) -> dict[str, Any]:
        """返回文档级 handler 与模板共同使用的 JSON-safe 快照。"""
        return {
            "entries": [entry.to_json() for entry in self.entries],
            "document": {"text": self.text, "rss_xml": self.rss_xml},
        }


class BundleDocumentBuilder:
    """按 Bundle 成员顺序构造稳定的 RSS 2.0 文档。"""

    def build(
        self,
        *,
        bundle: Bundle,
        members: Sequence[BundleFeed],
        feeds: Mapping[int, Feed],
        inbox_items: Sequence[DeliveryInboxItem],
        history_entry_limit: int = 0,
    ) -> BundleAggregateDocument:
        """构造聚合文档；限制只应用于每个成员，不设置 Bundle 总量限制。"""
        if bundle.id is None:
            raise ValueError("Bundle 聚合要求 Bundle 已持久化")
        ordered_members = sorted(members, key=lambda member: member.position)
        member_by_id = {member.id: member for member in ordered_members}
        if any(member.id is None for member in ordered_members):
            raise ValueError("Bundle 聚合要求成员已持久化")
        if any(member.bundle_id != bundle.id for member in ordered_members):
            raise ValueError("Bundle 成员与当前 Bundle 不匹配")

        grouped: dict[int, list[DeliveryInboxItem]] = {
            member.id: [] for member in ordered_members if member.id is not None
        }
        for item in inbox_items:
            member_id = item.bundle_feed_id
            if member_id not in member_by_id:
                raise ValueError(f"inbox 条目不属于当前 Bundle 成员: {member_id}")
            if item.owner.owner_type != "bundle":
                raise ValueError("Bundle 聚合只能消费 Bundle inbox 条目")
            if item.owner.owner_id != bundle.id:
                raise ValueError("inbox 条目 owner 与 Bundle 不匹配")
            member = member_by_id[member_id]
            if item.feed_id != member.feed_id:
                raise ValueError("inbox 条目来源 Feed 与 Bundle 成员不匹配")
            grouped[member_id].append(item)

        limit = max(0, int(history_entry_limit))
        entries: list[BundleDocumentEntry] = []
        for member in ordered_members:
            feed = feeds.get(member.feed_id)
            if feed is None:
                raise ValueError(f"Bundle 成员 Feed 不存在: {member.feed_id}")
            member_items = self._order_member_items(grouped[member.id])
            if limit > 0:
                member_items = member_items[:limit]
            entries.extend(
                self._entry_from_item(item, member, feed) for item in member_items
            )

        channel_link = ""
        if ordered_members:
            first_feed = feeds.get(ordered_members[0].feed_id)
            channel_link = first_feed.link if first_feed else ""
        rss_xml = self._build_rss_xml(bundle, entries, feeds, channel_link)
        text = "\n\n".join(
            entry.content_html or entry.summary or entry.title for entry in entries
        )
        return BundleAggregateDocument(
            entries=tuple(entries),
            text=text,
            rss_xml=rss_xml,
            consumption_item_keys=tuple(entry.item_key for entry in entries),
            feed_sources=tuple(
                (
                    feed.id if feed.id is not None else member.feed_id,
                    feed.link,
                    member.position,
                )
                for member in ordered_members
                for feed in [feeds[member.feed_id]]
            ),
        )

    @staticmethod
    def _order_member_items(
        items: Sequence[DeliveryInboxItem],
    ) -> list[DeliveryInboxItem]:
        timed: list[DeliveryInboxItem] = []
        untimed: list[DeliveryInboxItem] = []
        for item in items:
            if item.published_at or item.entry_updated_at:
                timed.append(item)
            else:
                untimed.append(item)
        timed.sort(key=BundleDocumentBuilder._normalized_sort_time, reverse=True)
        return [*timed, *untimed]

    @staticmethod
    def _normalized_sort_time(item: DeliveryInboxItem) -> datetime:
        """把数据库与解析器可能混用的 naive/aware 时间统一到 UTC。"""
        value = item.published_at or item.entry_updated_at
        if value is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return _as_utc(value) or datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _entry_from_item(
        item: DeliveryInboxItem,
        member: BundleFeed,
        feed: Feed,
    ) -> BundleDocumentEntry:
        payload = item.entry_payload
        content = BundleDocumentBuilder._content_value(payload.get("content"))
        summary = BundleDocumentBuilder._content_value(payload.get("summary"))
        return BundleDocumentEntry(
            item_key=item.item_key,
            feed_id=feed.id if feed.id is not None else item.feed_id,
            member_position=member.position,
            title=str(payload.get("title") or ""),
            link=str(payload.get("link") or payload.get("guid") or ""),
            author=str(payload.get("author") or ""),
            summary=summary,
            content_html=content or summary,
            tags=tuple(BundleDocumentBuilder._tags_value(payload.get("tags"))),
            media_items=tuple(BundleDocumentBuilder._media_value(item.media_items)),
            published=item.published_at,
            updated=item.entry_updated_at,
        )

    @staticmethod
    def _content_value(value: Any) -> str:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("value"):
                    return str(item["value"])
            return ""
        return str(value or "")

    @staticmethod
    def _tags_value(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            tag = item.get("term") if isinstance(item, dict) else item
            normalized = str(tag or "").strip()
            if normalized:
                result.append(normalized)
        return list(dict.fromkeys(result))

    @staticmethod
    def _media_value(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("href") or "").strip()
            if not url:
                continue
            media: dict[str, Any] = {"url": url}
            media_type = str(item.get("type") or item.get("media_type") or "").strip()
            if media_type:
                media["type"] = media_type
            if item.get("length") is not None:
                media["length"] = int(item["length"])
            result.append(media)
        return result

    @staticmethod
    def _build_rss_xml(
        bundle: Bundle,
        entries: Sequence[BundleDocumentEntry],
        feeds: Mapping[int, Feed],
        channel_link: str,
    ) -> str:
        root = ElementTree.Element("rss", {"version": "2.0"})
        channel = ElementTree.SubElement(root, "channel")
        BundleDocumentBuilder._append_text(channel, "title", bundle.name)
        BundleDocumentBuilder._append_text(channel, "link", channel_link)
        BundleDocumentBuilder._append_text(channel, "description", bundle.name)

        for entry in entries:
            item = ElementTree.SubElement(channel, "item")
            BundleDocumentBuilder._append_text(item, "title", entry.title)
            BundleDocumentBuilder._append_text(item, "link", entry.link)
            guid = ElementTree.SubElement(item, "guid", {"isPermaLink": "false"})
            guid.text = entry.item_key
            BundleDocumentBuilder._append_text(
                item, "description", entry.content_html or entry.summary
            )
            BundleDocumentBuilder._append_text(item, "author", entry.author)
            effective_time = entry.published or entry.updated
            if effective_time:
                BundleDocumentBuilder._append_text(
                    item,
                    "pubDate",
                    format_datetime(_as_utc(effective_time) or effective_time),
                )
            feed = feeds.get(entry.feed_id)
            if feed:
                source = ElementTree.SubElement(item, "source", {"url": feed.link})
                source.text = feed.title
            for tag in entry.tags:
                BundleDocumentBuilder._append_text(item, "category", tag)
            for media in entry.media_items:
                attributes = {"url": str(media["url"])}
                if media.get("length") is not None:
                    attributes["length"] = str(media["length"])
                if media.get("type"):
                    attributes["type"] = str(media["type"])
                ElementTree.SubElement(item, "enclosure", attributes)

        return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)

    @staticmethod
    def _append_text(parent: ElementTree.Element, tag: str, value: Any) -> None:
        text = str(value or "")
        if text:
            ElementTree.SubElement(parent, tag).text = text


BundleRssDocumentBuilder = BundleDocumentBuilder


class BundleRssDocumentValidator:
    """验证 Bundle handler 产生的 RSS 2.0 文档。"""

    def validate(self, rss_xml: str) -> ElementTree.Element:
        normalized = str(rss_xml or "").strip()
        if not normalized:
            raise BundleDocumentValidationError("RSS 文档不能为空")
        upper = normalized.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise BundleDocumentValidationError(
                "RSS 文档不允许包含 DOCTYPE 或 ENTITY 声明"
            )
        try:
            root = ElementTree.fromstring(normalized)
        except ElementTree.ParseError as exc:
            raise BundleDocumentValidationError(f"RSS 文档格式错误: {exc}") from exc

        if self._local_name(root.tag) != "rss":
            raise BundleDocumentValidationError("RSS 文档根节点必须是 rss")
        if root.attrib.get("version") != "2.0":
            raise BundleDocumentValidationError("RSS 文档 version 必须是 2.0")
        channels = [
            child for child in list(root) if self._local_name(child.tag) == "channel"
        ]
        if len(channels) != 1:
            raise BundleDocumentValidationError("RSS 文档必须包含一个 channel")
        return root

    @staticmethod
    def _local_name(tag: str) -> str:
        return str(tag or "").rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


@dataclass(frozen=True, slots=True)
class BundleDocumentHandlerResult:
    """一次 Bundle 文档 handler 运行的快照与 trace。"""

    document: BundleAggregateDocument
    allowed: bool = True
    reason: str = ""
    trace: tuple[dict[str, Any], ...] = ()
    input_document: BundleAggregateDocument | None = None

    def to_snapshot(self) -> dict[str, Any]:
        """返回供批次持久化使用的 handler 前后文档快照。"""
        snapshot = self.document.to_json()
        if self.input_document is not None:
            snapshot["input_document"] = self.input_document.to_json()
        snapshot["handler_trace"] = [dict(item) for item in self.trace]
        snapshot["consumption_item_keys"] = list(self.document.consumption_item_keys)
        snapshot["allowed"] = self.allowed
        if self.reason:
            snapshot["reason"] = self.reason
        return snapshot


class BundleDocumentHandlerRuntime:
    """运行独立于 entry handler 契约的 Bundle 文档级 handlers。"""

    def __init__(self, context: Any | None = None) -> None:
        self._context = context

    async def process(
        self,
        *,
        bundle: Bundle,
        document: BundleAggregateDocument,
        session_id: str | None = None,
    ) -> BundleDocumentHandlerResult:
        input_document = document
        current = document
        trace: list[dict[str, Any]] = []
        for spec in normalize_handlers(bundle.handlers):
            if not is_handler_enabled(spec):
                trace.append(
                    {
                        "id": spec.id,
                        "name": spec.name,
                        "status": "disabled",
                    }
                )
                continue
            if spec.type != "builtin":
                trace.append(
                    {
                        "id": spec.id,
                        "name": spec.name,
                        "status": "skipped",
                        "reason": "external handler",
                    }
                )
                continue
            try:
                if spec.name == "ai_filter":
                    allowed, reason, fallback = await self._run_filter(
                        current,
                        spec,
                        session_id=session_id,
                    )
                    trace.append(
                        {
                            "id": spec.id,
                            "name": spec.name,
                            "status": "ok",
                            "allow": allowed,
                            "reason": reason,
                            "fallback": fallback,
                        }
                    )
                    if not allowed:
                        return BundleDocumentHandlerResult(
                            document=current,
                            input_document=input_document,
                            allowed=False,
                            reason=reason,
                            trace=tuple(trace),
                        )
                elif spec.name == "ai_transform":
                    current, transform_trace = await self._run_transform(
                        current,
                        spec,
                        session_id=session_id,
                    )
                    trace.append(
                        {
                            "id": spec.id,
                            "name": spec.name,
                            "status": "ok",
                            **transform_trace,
                        }
                    )
                else:
                    trace.append(
                        {
                            "id": spec.id,
                            "name": spec.name,
                            "status": "skipped",
                            "reason": "unknown builtin handler",
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - handler 失败必须可观测回退
                logger.warning(
                    "Bundle 文档 handler 执行失败，已回退上一步结果: %s (%s)",
                    spec.id,
                    exc,
                )
                trace.append(
                    {
                        "id": spec.id,
                        "name": spec.name,
                        "status": "error",
                        "reason": str(exc),
                        "fallback": True,
                    }
                )
        return BundleDocumentHandlerResult(
            document=current,
            input_document=input_document,
            trace=tuple(trace),
        )

    async def _run_filter(
        self,
        document: BundleAggregateDocument,
        spec: HandlerSpec,
        *,
        session_id: str | None,
    ) -> tuple[bool, str, bool]:
        provider = self._resolve_provider(session_id)
        if provider is None:
            return True, "provider unavailable", True
        prompt = str(spec.config.get("prompt") or "").strip()
        if not prompt:
            return True, "ai_filter 未配置 prompt", True
        response = await provider.text_chat(
            prompt=self._filter_prompt(prompt, document),
            session_id=session_id or "rsshub-bundle-handlers",
            contexts=[],
            persist=False,
            system_prompt="",
        )
        payload = self._response_text(response)
        try:
            parsed = json.loads(payload)
        except (TypeError, ValueError) as exc:
            logger.warning("Bundle ai_filter 返回非法 JSON: %s", exc)
            return True, "invalid json", True
        if not isinstance(parsed, dict) or not isinstance(parsed.get("allow"), bool):
            return True, "invalid schema", True
        return bool(parsed["allow"]), str(parsed.get("reason") or ""), False

    async def _run_transform(
        self,
        document: BundleAggregateDocument,
        spec: HandlerSpec,
        *,
        session_id: str | None,
    ) -> tuple[BundleAggregateDocument, dict[str, Any]]:
        scope = str(spec.config.get("scope") or "plaintext").strip().lower()
        if scope not in {"plaintext", "xml"}:
            scope = "plaintext"
        provider = self._resolve_provider(session_id)
        base_trace = {"scope": scope, "fallback": True}
        if provider is None:
            return document, {**base_trace, "fallback_reason": "provider unavailable"}
        prompt = str(spec.config.get("prompt") or "").strip()
        if not prompt:
            return document, {**base_trace, "fallback_reason": "missing prompt"}

        response = await self._call_transform_provider(
            provider=provider,
            prompt=self._transform_prompt(prompt, scope, document),
            scope=scope,
            session_id=session_id,
        )
        steps_used = max(len(getattr(response, "tools_call_name", []) or []) + 1, 1)
        payload = self._response_text(response)
        try:
            parsed = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"ai_transform 输出不是合法 JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise TypeError("ai_transform 输出必须是 JSON 对象")
        allowed_fields = {"text"} if scope == "plaintext" else {"rss_xml"}
        invalid_keys = [key for key in parsed if key not in allowed_fields]
        if invalid_keys:
            raise ValueError(
                f"ai_transform 输出包含非法字段: {', '.join(invalid_keys)}"
            )
        if scope == "plaintext":
            text = str(parsed.get("text") or "")
            if not text:
                raise ValueError("ai_transform 输出缺少 text")
            return replace(document, text=text), {
                "scope": scope,
                "steps_used": steps_used,
                "fallback": False,
            }

        rss_xml = str(parsed.get("rss_xml") or "").strip()
        if not rss_xml:
            raise ValueError("ai_transform(xml) 输出缺少 rss_xml")
        root = BundleRssDocumentValidator().validate(rss_xml)
        entries = self._entries_from_rss_xml(root, document)
        return replace(
            document,
            entries=entries,
            text=self._text_from_rss_xml(rss_xml),
            rss_xml=rss_xml,
        ), {
            "scope": scope,
            "steps_used": steps_used,
            "fallback": False,
        }

    async def _call_transform_provider(
        self,
        *,
        provider: Any,
        prompt: str,
        scope: str,
        session_id: str | None,
    ) -> Any:
        tool_loop_agent = getattr(self._context, "tool_loop_agent", None)
        if not callable(tool_loop_agent):
            return await provider.text_chat(
                prompt=prompt,
                session_id=session_id or "rsshub-bundle-handlers",
                contexts=[],
                persist=False,
                system_prompt="",
            )

        provider_id = self._provider_id(provider)
        if not provider_id:
            raise ValueError("Bundle 文档 handler 无法解析当前 provider_id")
        target_session = session_id or "rsshub:FriendMessage:rsshub-bundle-handlers"
        event = _SyntheticHandlerEvent(
            unified_msg_origin=target_session,
            platform_name=target_session.split(":", 1)[0],
            sender_id="rsshub-bundle-handler",
        )
        return await tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=prompt,
            tools=ToolSet([XmlValidationTool()]) if scope == "xml" else ToolSet(),
            contexts=[],
            system_prompt="",
            max_steps=6 if scope == "xml" else 1,
            stream=False,
        )

    @staticmethod
    def _filter_prompt(prompt: str, document: BundleAggregateDocument) -> str:
        return (
            "你是 RSS Bundle 文档过滤器。根据要求判断整份 RSS 文档是否允许推送。"
            '\n只返回 JSON: {"allow":true,"reason":"..."}。'
            f"\n用户要求:\n{prompt}"
            f"\n\n文档数据:\n{json.dumps(document.to_json(), ensure_ascii=False)}"
        )

    @staticmethod
    def _transform_prompt(
        prompt: str,
        scope: str,
        document: BundleAggregateDocument,
    ) -> str:
        output_key = "text" if scope == "plaintext" else "rss_xml"
        return (
            "你是 RSS Bundle 文档改写 agent。只返回 JSON 对象，不要解释、Markdown 或代码块。"
            f"\n必须返回字段 {output_key!r}。"
            f"\n用户要求:\n{prompt}"
            f"\n\n文档数据:\n{json.dumps(document.to_json(), ensure_ascii=False)}"
        )

    def _resolve_provider(self, session_id: str | None) -> Any | None:
        if self._context is None:
            return None
        getter = getattr(self._context, "get_using_provider", None)
        if getter is None:
            return None
        provider = getter(session_id) if session_id else getter()
        return provider if callable(getattr(provider, "text_chat", None)) else None

    @staticmethod
    def _provider_id(provider: Any) -> str:
        meta = getattr(provider, "meta", None)
        if not callable(meta):
            return ""
        provider_meta = meta()
        return str(getattr(provider_meta, "id", "") or "").strip()

    @classmethod
    def _entries_from_rss_xml(
        cls,
        root: ElementTree.Element,
        document: BundleAggregateDocument,
    ) -> tuple[BundleDocumentEntry, ...]:
        """将合法 XML 的 item 重新投影为模板可见的 post-handler entries。"""
        channel = next(
            child
            for child in list(root)
            if BundleRssDocumentValidator._local_name(child.tag) == "channel"
        )
        by_key = {entry.item_key: entry for entry in document.entries}
        by_link = {entry.link: entry for entry in document.entries if entry.link}
        source_map = {
            link: (feed_id, position)
            for feed_id, link, position in document.feed_sources
            if link
        }
        fallback_source: tuple[int, int] | None = None
        if document.feed_sources:
            first_source = document.feed_sources[0]
            fallback_source = (first_source[0], first_source[2])
        elif document.entries:
            fallback_source = (
                document.entries[0].feed_id,
                document.entries[0].member_position,
            )

        entries: list[BundleDocumentEntry] = []
        output_index = 0
        for item in list(channel):
            if BundleRssDocumentValidator._local_name(item.tag) not in {
                "item",
                "entry",
            }:
                continue
            output_index += 1
            link = cls._xml_link(item)
            item_key = cls._xml_text(item, {"guid", "id"}) or link
            if not item_key:
                item_key = f"generated:{output_index}"
            matched = by_key.get(item_key) or by_link.get(link)
            source = source_map.get(cls._xml_source_url(item))
            if source is None and matched is not None:
                source = (matched.feed_id, matched.member_position)
            if source is None:
                source = fallback_source
            if source is None:
                # 仅会出现在手工构造且没有来源元数据的测试/预览文档中；不伪造 Feed ID。
                continue

            summary = cls._xml_text(item, {"summary", "description"})
            content = cls._xml_text(
                item,
                {"content", "encoded", "description", "summary"},
            )
            entries.append(
                BundleDocumentEntry(
                    item_key=item_key,
                    feed_id=source[0],
                    member_position=source[1],
                    title=cls._xml_text(item, {"title"}),
                    link=link,
                    author=cls._xml_text(item, {"author", "creator"}),
                    summary=summary,
                    content_html=content or summary,
                    tags=tuple(cls._xml_all_text(item, {"category", "tag"})),
                    media_items=tuple(cls._xml_media(item)),
                    published=cls._xml_datetime(
                        cls._xml_text(item, {"pubdate", "published"})
                    ),
                    updated=cls._xml_datetime(cls._xml_text(item, {"updated"})),
                )
            )
        return tuple(entries)

    @classmethod
    def _xml_text(cls, element: ElementTree.Element, names: set[str]) -> str:
        for child in list(element):
            if BundleRssDocumentValidator._local_name(child.tag) in names:
                value = "".join(child.itertext()).strip()
                if value:
                    return value
        return ""

    @classmethod
    def _xml_all_text(cls, element: ElementTree.Element, names: set[str]) -> list[str]:
        values: list[str] = []
        for child in list(element):
            if BundleRssDocumentValidator._local_name(child.tag) in names:
                value = "".join(child.itertext()).strip()
                if value:
                    values.append(value)
        return list(dict.fromkeys(values))

    @classmethod
    def _xml_link(cls, element: ElementTree.Element) -> str:
        for child in list(element):
            if BundleRssDocumentValidator._local_name(child.tag) != "link":
                continue
            href = str(child.attrib.get("href") or "").strip()
            return href or "".join(child.itertext()).strip()
        return ""

    @classmethod
    def _xml_source_url(cls, element: ElementTree.Element) -> str:
        for child in list(element):
            if BundleRssDocumentValidator._local_name(child.tag) == "source":
                return str(child.attrib.get("url") or "").strip()
        return ""

    @classmethod
    def _xml_media(cls, element: ElementTree.Element) -> list[dict[str, Any]]:
        media_items: list[dict[str, Any]] = []
        for child in list(element):
            if BundleRssDocumentValidator._local_name(child.tag) != "enclosure":
                continue
            url = str(child.attrib.get("url") or child.attrib.get("href") or "").strip()
            if not url:
                continue
            media: dict[str, Any] = {"url": url}
            media_type = str(child.attrib.get("type") or "").strip()
            if media_type:
                media["type"] = media_type
            length = child.attrib.get("length")
            if length is not None:
                try:
                    media["length"] = int(length)
                except (TypeError, ValueError):
                    pass
            media_items.append(media)
        return media_items

    @staticmethod
    def _xml_datetime(value: str) -> datetime | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        try:
            parsed = parsedate_to_datetime(normalized)
        except (TypeError, ValueError, OverflowError):
            try:
                parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            except ValueError:
                return None
        return _as_utc(parsed)

    @staticmethod
    def _text_from_rss_xml(rss_xml: str) -> str:
        root = BundleRssDocumentValidator().validate(rss_xml)
        channel = next(
            child
            for child in list(root)
            if BundleRssDocumentValidator._local_name(child.tag) == "channel"
        )
        parts: list[str] = []
        for item in list(channel):
            if BundleRssDocumentValidator._local_name(item.tag) not in {
                "item",
                "entry",
            }:
                continue
            value = ""
            for child in list(item):
                if BundleRssDocumentValidator._local_name(child.tag) in {
                    "description",
                    "content",
                    "encoded",
                    "summary",
                }:
                    value = "".join(child.itertext()).strip()
                    if value:
                        break
            if not value:
                title = next(
                    (
                        "".join(child.itertext()).strip()
                        for child in list(item)
                        if BundleRssDocumentValidator._local_name(child.tag) == "title"
                    ),
                    "",
                )
                value = title
            if value:
                parts.append(value)
        return "\n\n".join(parts)

    @staticmethod
    def _response_text(response: Any) -> str:
        return str(getattr(response, "completion_text", "") or "").strip()


class BundleDocumentService:
    """连接聚合 builder 与文档 handler runtime 的应用服务。"""

    def __init__(
        self,
        *,
        builder: BundleDocumentBuilder | None = None,
        handler_runtime: BundleDocumentHandlerRuntime | None = None,
    ) -> None:
        self._builder = builder or BundleDocumentBuilder()
        self._handler_runtime = handler_runtime or BundleDocumentHandlerRuntime()

    async def build_and_process(
        self,
        *,
        bundle: Bundle,
        members: Sequence[BundleFeed],
        feeds: Mapping[int, Feed],
        inbox_items: Sequence[DeliveryInboxItem],
        history_entry_limit: int = 0,
        session_id: str | None = None,
    ) -> BundleDocumentHandlerResult:
        """构造聚合文档并运行 Bundle 当前生效的文档 handlers。"""
        document = self._builder.build(
            bundle=bundle,
            members=members,
            feeds=feeds,
            inbox_items=inbox_items,
            history_entry_limit=history_entry_limit,
        )
        return await self._handler_runtime.process(
            bundle=bundle,
            document=document,
            session_id=session_id,
        )
