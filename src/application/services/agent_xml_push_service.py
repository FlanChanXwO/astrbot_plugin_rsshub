"""Agent XML entry push service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from ...domain.entities.content_types import LayoutFragment
from ...infrastructure.pipeline import (
    EffectivePushOptions,
    EntryFormatInput,
    EntryTextFormatter,
)
from ...infrastructure.rendering import cleanup_ephemeral_generated_media_paths
from ...infrastructure.utils import get_logger
from ...shared.constants import (
    DISPLAY_AUTO,
    DISPLAY_DISABLED,
    DISPLAY_FORCED,
    DISPLAY_VIA_AUTO,
    DISPLAY_VIA_FORCED,
    DISPLAY_VIA_FULLY_DISABLED,
    DISPLAY_VIA_LINK_ONLY,
    SEND_MODE_AUTO,
    SEND_MODE_DIRECT,
    SEND_MODE_LINK_ONLY,
    STYLE_AUTO,
    STYLE_ORIGINAL,
    STYLE_RSSRT,
)
from .feed_polling_service import FeedPollingService
from .html_parser import HTMLParser
from .notification_dispatcher import (
    SendTarget,
    build_agent_entry_guid,
    normalize_media_items,
)

logger = get_logger()
_entry_text_formatter = EntryTextFormatter()

MAX_XML_BYTES = 256 * 1024
MAX_XML_NODES = 4096
FORBIDDEN_XML_TOKENS = ("<!DOCTYPE", "<!ENTITY")


class AgentXmlValidationError(ValueError):
    """Raised when agent XML input is invalid."""


@dataclass(frozen=True, slots=True)
class ParsedAgentXmlEntry:
    """Normalized agent XML payload ready for dispatch."""

    title: str
    content: str
    entry_link: str
    feed_title: str
    feed_link: str
    author: str
    entry_guid: str
    media_urls: list[str]
    media_items: list[tuple[str, str]]
    layout: list[LayoutFragment]


@dataclass(frozen=True, slots=True)
class AgentXmlPushOptions:
    """Per-call formatting overrides for agent XML pushes."""

    send_mode: int = SEND_MODE_AUTO
    style: int = STYLE_AUTO
    format_options: EffectivePushOptions = EffectivePushOptions()


def _validate_xml_input(xml: str) -> str:
    normalized = str(xml or "").strip()
    if not normalized:
        raise AgentXmlValidationError("xml 不能为空")
    if len(normalized.encode("utf-8")) > MAX_XML_BYTES:
        raise AgentXmlValidationError("xml 过大，超过 256 KiB 限制")

    upper_xml = normalized.upper()
    if any(token in upper_xml for token in FORBIDDEN_XML_TOKENS):
        raise AgentXmlValidationError("xml 不允许包含 DOCTYPE 或 ENTITY 声明")

    return normalized


def _serialize_xml_body(root: ElementTree.Element) -> str:
    parts: list[str] = []
    if root.text and root.text.strip():
        parts.append(root.text)
    for child in list(root):
        parts.append(ElementTree.tostring(child, encoding="unicode"))
        if child.tail and child.tail.strip():
            parts.append(child.tail)
    return "".join(parts).strip()


def _collect_xml_media(root: ElementTree.Element) -> list[str]:
    media_urls: list[str] = []
    for elem in root.iter():
        for attr_name in ("src", "href", "url"):
            value = str(elem.attrib.get(attr_name, "") or "").strip()
            if value.startswith(("http://", "https://")):
                media_urls.append(value)
    return list(dict.fromkeys(media_urls))


def _local_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1].lower()


def _collect_xml_tags(root: ElementTree.Element) -> tuple[str, ...]:
    tags: list[str] = []
    for elem in root.iter():
        if _local_name(elem.tag) not in {"category", "tag"}:
            continue
        value = str(elem.text or "").strip()
        if value:
            tags.append(value)
    return tuple(dict.fromkeys(tags))


def _coerce_int(value: Any, *, fallback: int) -> int:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _parse_mapped_int(
    value: Any,
    *,
    mapping: dict[str, int],
    allowed: set[int],
    fallback: int,
) -> int:
    if value is None:
        return fallback
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in mapping:
            return mapping[normalized]
    candidate = _coerce_int(value, fallback=fallback)
    return candidate if candidate in allowed else fallback


def _parse_bool(value: Any, *, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enable", "enabled", "开启"}:
            return True
        if normalized in {"0", "false", "no", "off", "disable", "disabled", "关闭"}:
            return False
    return fallback


def _build_link_only_content(*, title: str, link: str) -> str:
    title = str(title or "").strip()
    link = str(link or "").strip()
    if title and link:
        return f"{title}\n{link}"
    return title or link


def _resolve_push_options(
    *,
    send_mode: Any = None,
    style: Any = None,
    display_media: Any = None,
    display_title: Any = None,
    display_author: Any = None,
    display_via: Any = None,
    display_entry_tags: Any = None,
    length_limit: Any = None,
) -> AgentXmlPushOptions:
    send_mode_value = _parse_mapped_int(
        send_mode,
        mapping={
            "link_only": SEND_MODE_LINK_ONLY,
            "link-only": SEND_MODE_LINK_ONLY,
            "link": SEND_MODE_LINK_ONLY,
            "仅链接": SEND_MODE_LINK_ONLY,
            "auto": SEND_MODE_AUTO,
            "自动": SEND_MODE_AUTO,
            "direct": SEND_MODE_DIRECT,
            "直接发送": SEND_MODE_DIRECT,
        },
        allowed={SEND_MODE_LINK_ONLY, SEND_MODE_AUTO, SEND_MODE_DIRECT},
        fallback=SEND_MODE_AUTO,
    )
    style_value = _parse_mapped_int(
        style,
        mapping={
            "auto": STYLE_AUTO,
            "classic": STYLE_AUTO,
            "rsstt": STYLE_AUTO,
            "rssrt": STYLE_RSSRT,
            "original": STYLE_ORIGINAL,
        },
        allowed={STYLE_AUTO, STYLE_RSSRT, STYLE_ORIGINAL},
        fallback=STYLE_AUTO,
    )
    display_toggle_mapping = {
        "disabled": DISPLAY_DISABLED,
        "disable": DISPLAY_DISABLED,
        "off": DISPLAY_DISABLED,
        "false": DISPLAY_DISABLED,
        "禁用": DISPLAY_DISABLED,
        "auto": DISPLAY_AUTO,
        "自动": DISPLAY_AUTO,
        "forced": DISPLAY_FORCED,
        "force": DISPLAY_FORCED,
        "on": DISPLAY_FORCED,
        "true": DISPLAY_FORCED,
        "强制": DISPLAY_FORCED,
    }
    display_via_value = _parse_mapped_int(
        display_via,
        mapping={
            "fully_disabled": DISPLAY_VIA_FULLY_DISABLED,
            "full_disabled": DISPLAY_VIA_FULLY_DISABLED,
            "disabled": DISPLAY_VIA_FULLY_DISABLED,
            "disable": DISPLAY_VIA_FULLY_DISABLED,
            "off": DISPLAY_VIA_FULLY_DISABLED,
            "false": DISPLAY_VIA_FULLY_DISABLED,
            "完全禁用": DISPLAY_VIA_FULLY_DISABLED,
            "link_only": DISPLAY_VIA_LINK_ONLY,
            "link-only": DISPLAY_VIA_LINK_ONLY,
            "link": DISPLAY_VIA_LINK_ONLY,
            "仅链接": DISPLAY_VIA_LINK_ONLY,
            "auto": DISPLAY_VIA_AUTO,
            "自动": DISPLAY_VIA_AUTO,
            "forced": DISPLAY_VIA_FORCED,
            "force": DISPLAY_VIA_FORCED,
            "on": DISPLAY_VIA_FORCED,
            "true": DISPLAY_VIA_FORCED,
            "强制": DISPLAY_VIA_FORCED,
        },
        allowed={
            DISPLAY_VIA_FULLY_DISABLED,
            DISPLAY_VIA_LINK_ONLY,
            DISPLAY_VIA_AUTO,
            DISPLAY_VIA_FORCED,
        },
        fallback=DISPLAY_VIA_AUTO,
    )
    length_limit_value = max(0, _coerce_int(length_limit, fallback=0))
    return AgentXmlPushOptions(
        send_mode=send_mode_value,
        style=style_value,
        format_options=EffectivePushOptions(
            length_limit=length_limit_value,
            display_author=_parse_mapped_int(
                display_author,
                mapping=display_toggle_mapping,
                allowed={DISPLAY_DISABLED, DISPLAY_AUTO, DISPLAY_FORCED},
                fallback=DISPLAY_AUTO,
            ),
            display_via=display_via_value,
            display_title=_parse_mapped_int(
                display_title,
                mapping=display_toggle_mapping,
                allowed={DISPLAY_DISABLED, DISPLAY_AUTO, DISPLAY_FORCED},
                fallback=DISPLAY_AUTO,
            ),
            display_entry_tags=_parse_bool(display_entry_tags, fallback=False),
            style=style_value,
            display_media=_parse_bool(display_media, fallback=True),
        ),
    )


def _parse_xml_root(xml: str) -> tuple[ElementTree.Element, str]:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise AgentXmlValidationError(f"xml 格式错误: {exc}") from exc

    node_count = sum(1 for _ in root.iter())
    if node_count > MAX_XML_NODES:
        raise AgentXmlValidationError("xml 节点过多，超过安全限制")

    body_xml = _serialize_xml_body(root)
    if not body_xml:
        body_xml = ElementTree.tostring(root, encoding="unicode")
    return root, body_xml


class AgentXmlPushService:
    """Validate, normalize and dispatch one XML entry for the current agent user."""

    def __init__(self, notification_dispatcher):
        self._notification_dispatcher = notification_dispatcher

    async def push_entry(
        self,
        *,
        user_id: str,
        platform_name: str | None,
        target_session: str,
        source_key: str,
        title: str,
        xml: str,
        link: str = "",
        author: str = "",
        feed_title: str = "",
        entry_guid: str = "",
        idempotency_key: str = "",
        dry_run: bool = False,
        style: Any = None,
        send_mode: Any = None,
        display_media: Any = None,
        display_title: Any = None,
        display_author: Any = None,
        display_via: Any = None,
        display_entry_tags: Any = None,
        length_limit: Any = None,
    ) -> dict[str, object]:
        source_key = str(source_key or "").strip()
        if not source_key:
            raise AgentXmlValidationError("source_key 不能为空")

        title = str(title or "").strip()
        if not title:
            raise AgentXmlValidationError("title 不能为空")

        target_session = str(target_session or "").strip()
        if not target_session:
            raise AgentXmlValidationError("当前会话为空，无法推送")

        valid_xml = _validate_xml_input(xml)
        root, body_xml = _parse_xml_root(valid_xml)
        options = _resolve_push_options(
            style=style,
            send_mode=send_mode,
            display_media=display_media,
            display_title=display_title,
            display_author=display_author,
            display_via=display_via,
            display_entry_tags=display_entry_tags,
            length_limit=length_limit,
        )
        parsed = None
        try:
            parsed = await HTMLParser(body_xml, feed_link=link or "").parse()
            plain_body = FeedPollingService._remove_media_placeholders(
                parsed.html_tree.get_plain().strip()
            )
            content = await _entry_text_formatter.format_entry(
                EntryFormatInput(
                    title=title,
                    content=plain_body,
                    summary=plain_body,
                    link=str(link or "").strip(),
                    author=str(author or "").strip(),
                    feed_title=str(feed_title or "").strip(),
                    feed_link=str(link or "").strip(),
                    tags=_collect_xml_tags(root),
                ),
                options.format_options,
            )
            media_items = FeedPollingService._media_items_from_parsed(parsed.media)
            media_urls = [
                url
                for _media_type, url in normalize_media_items(media_items=media_items)
            ]
            extra_media = _collect_xml_media(root)
            media_urls.extend(extra_media)
            media_urls = list(dict.fromkeys(media_urls))
            normalized_media_items = normalize_media_items(
                media_urls=media_urls,
                media_items=media_items,
            )
            dispatch_media_urls = media_urls
            dispatch_media_items = normalized_media_items
            dispatch_layout = list(parsed.layout)
            if not options.format_options.display_media:
                dispatch_media_urls = []
                dispatch_media_items = []
                dispatch_layout = []
            if options.send_mode == SEND_MODE_LINK_ONLY:
                content = _build_link_only_content(
                    title=title, link=str(link or "").strip()
                )
                dispatch_media_urls = []
                dispatch_media_items = []
                dispatch_layout = []
            final_guid = (
                str(entry_guid or "").strip()
                or str(idempotency_key or "").strip()
                or build_agent_entry_guid(
                    source_key=source_key,
                    user_id=user_id,
                    target_session=target_session,
                    title=title,
                    link=str(link or "").strip(),
                    xml=valid_xml,
                    media_items=normalized_media_items,
                )
            )

            preview = ParsedAgentXmlEntry(
                title=title,
                content=content,
                entry_link=str(link or "").strip(),
                feed_title=str(feed_title or "").strip(),
                feed_link=str(link or "").strip(),
                author=str(author or "").strip(),
                entry_guid=final_guid,
                media_urls=media_urls,
                media_items=normalized_media_items,
                layout=dispatch_layout,
            )
            if dry_run:
                return {
                    "ok": True,
                    "dry_run": True,
                    "preview": {
                        "title": preview.title,
                        "content": preview.content,
                        "entry_link": preview.entry_link,
                        "feed_title": preview.feed_title,
                        "author": preview.author,
                        "entry_guid": preview.entry_guid,
                        "media_urls": dispatch_media_urls,
                    },
                }

            result = await self._notification_dispatcher.dispatch_agent_entry(
                source_key=source_key,
                target=SendTarget(
                    user_id=user_id,
                    platform_name=platform_name,
                    target_session=target_session,
                    sub_id=None,
                ),
                content=preview.content,
                raw_xml=valid_xml,
                entry_title=preview.title,
                entry_link=preview.entry_link,
                feed_title=preview.feed_title,
                feed_link=preview.feed_link,
                media_urls=dispatch_media_urls,
                media_items=dispatch_media_items,
                layout=dispatch_layout,
                entry_guid=preview.entry_guid,
                send_mode=options.send_mode,
                style=options.style,
            )
            result["dry_run"] = False
            result["preview"] = {
                "entry_guid": preview.entry_guid,
                "media_urls": preview.media_urls,
            }
            return result
        finally:
            if parsed is not None:
                cleanup_ephemeral_generated_media_paths(parsed.layout)

    async def push_entry_json(
        self,
        **kwargs,
    ) -> str:
        """JSON wrapper for LLM tool output."""
        result = await self.push_entry(**kwargs)
        return json.dumps(result, ensure_ascii=False, indent=2)
