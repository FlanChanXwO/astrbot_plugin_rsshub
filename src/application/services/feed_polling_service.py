"""Unified feed polling use case.

This service owns the application-level polling workflow:
load feed, fetch RSS, parse entries, update dedup state, and optionally dispatch
new entries. Scheduler adapters and manual refresh commands should converge on
this service instead of duplicating sync behavior.
"""

from __future__ import annotations

import hashlib
import html
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import format_datetime
from itertools import chain
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from ...domain.entities.content_types import AudioContent, FileContent, VideoContent
from ...domain.entities.feed import Feed, normalize_entry_hashes
from ...domain.repositories.feed_repository import FeedRepository
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ...infrastructure.config import FeedFetchSettings, RSSSettings
from ...infrastructure.pipeline import (
    EffectivePushOptions,
    EntryFormatInput,
    EntryTextFormatter,
)
from ...infrastructure.pipeline.entry_formatter import normalize_plain_text
from ...infrastructure.utils import get_logger
from ..ports import FeedFetcherFactory, FeedParser, MediaFingerprintService
from .content_handlers import EntryContentContext
from .html_parser import HTMLParser
from .notification_dispatcher import NotificationDispatcher

logger = get_logger()
_entry_text_formatter = EntryTextFormatter()

DEFAULT_TRACKING_QUERY_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "spm",
        "ref",
        "ref_src",
    }
)


@dataclass(frozen=True)
class FeedReadResult:
    """Result of fetching and parsing one feed URL."""

    success: bool
    status: str
    message: str
    entries: list[Any] = field(default_factory=list)
    web_feed: Any | None = None
    error: str = ""


@dataclass(frozen=True)
class FeedPollingResult:
    """Result of one feed polling run."""

    success: bool
    status: str
    message: str
    feed_id: int | None = None
    total_entries: int = 0
    new_entries: int = 0
    dispatched: int = 0
    bootstrap_skipped: bool = False
    feed: Feed | None = None
    error: str = ""


@dataclass(frozen=True)
class _DispatchEntriesResult:
    """Result of dispatching entries before committing dedup watermarks."""

    dispatched: int = 0
    acknowledged_entries: list[Any] = field(default_factory=list)


class FeedPollingService:
    """Unified application service for polling RSS feeds."""

    def __init__(
        self,
        feed_repo: FeedRepository,
        subscription_repo: SubscriptionRepository,
        fetch_settings: FeedFetchSettings | None = None,
        rss_settings: RSSSettings | None = None,
        fetcher_factory: FeedFetcherFactory | None = None,
        parser: FeedParser | None = None,
        notification_dispatcher: NotificationDispatcher | None = None,
        media_fingerprint_service: MediaFingerprintService | None = None,
        history_entry_limit: int = 0,
    ) -> None:
        self._feed_repo = feed_repo
        self._subscription_repo = subscription_repo
        self._fetch_settings = fetch_settings or FeedFetchSettings()
        self._rss_settings = rss_settings or RSSSettings()
        self._fetcher_factory = fetcher_factory
        self._parser = parser
        self._notification_dispatcher = notification_dispatcher
        self._media_fingerprint_service = media_fingerprint_service
        self._history_entry_limit = max(0, history_entry_limit)

    async def fetch_feed_entries(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        verbose: bool = False,
    ) -> FeedReadResult:
        """Fetch and parse one feed URL without mutating feed state."""
        if self._fetcher_factory is None or self._parser is None:
            raise RuntimeError(
                "FeedPollingService requires feed fetcher and parser ports"
            )

        fetcher = self._fetcher_factory(
            timeout=self._fetch_settings.timeout,
            proxy=self._fetch_settings.proxy,
        )

        try:
            web_feed = await fetcher.fetch(
                url,
                headers=headers,
                verbose=verbose,
            )
        except Exception as ex:
            logger.warning("fetch_feed_entries: 抓取异常: feed=%s, err=%s", url, ex)
            return FeedReadResult(
                success=False,
                status="fetch_error",
                message=f"抓取失败: {ex}",
                error=str(ex),
            )
        finally:
            await fetcher.close()

        if getattr(web_feed, "status", 0) == 304:
            return FeedReadResult(
                success=True,
                status="not_modified",
                message="Feed 未修改，无需更新",
                web_feed=web_feed,
            )

        if web_feed.error:
            error_name = getattr(web_feed.error, "error_name", str(web_feed.error))
            logger.warning(
                "fetch_feed_entries: 抓取失败: feed=%s, err=%s",
                url,
                error_name,
            )
            return FeedReadResult(
                success=False,
                status="fetch_error",
                message=f"抓取失败: {error_name}",
                web_feed=web_feed,
                error=error_name,
            )

        if not web_feed.content:
            return FeedReadResult(
                success=False,
                status="empty_content",
                message="抓取失败: RSS 内容为空",
                web_feed=web_feed,
                error="empty_content",
            )

        entries, parse_err = self._parser.parse(web_feed.content)
        if parse_err:
            logger.warning(
                "fetch_feed_entries: 解析失败: feed=%s, err=%s",
                url,
                parse_err,
            )
            return FeedReadResult(
                success=False,
                status="parse_error",
                message=f"解析失败: {parse_err}",
                web_feed=web_feed,
                error=parse_err,
            )

        return FeedReadResult(
            success=True,
            status="fetched",
            message=f"抓取完成，发现 {len(entries)} 个条目",
            entries=entries,
            web_feed=web_feed,
        )

    async def poll_feed(
        self,
        feed_id: int,
        *,
        notify_new_entries: bool = False,
        subscription_ids: list[int] | None = None,
        verbose: bool = False,
    ) -> FeedPollingResult:
        """Poll one feed and update its dedup history."""
        feed = await self._feed_repo.get_by_id(feed_id)
        if not feed:
            logger.warning("poll_feed: Feed %s 不存在", feed_id)
            return FeedPollingResult(
                success=False,
                status="not_found",
                message=f"Feed 不存在 (ID: {feed_id})",
                feed_id=feed_id,
                error="feed_not_found",
            )

        headers = self._build_conditional_headers(feed)
        read_result = await self.fetch_feed_entries(
            feed.link,
            headers=headers,
            verbose=verbose,
        )
        web_feed = read_result.web_feed

        if read_result.status == "not_modified":
            return FeedPollingResult(
                success=True,
                status="not_modified",
                message=f"Feed 未修改，无需更新 (ID: {feed_id})",
                feed_id=feed.id,
                feed=feed,
            )

        if not read_result.success:
            return FeedPollingResult(
                success=False,
                status=read_result.status,
                message=read_result.message,
                feed_id=feed.id,
                feed=feed,
                error=read_result.error,
            )

        entries = read_result.entries
        previous_etag = feed.etag
        previous_last_modified = feed.last_modified
        self._apply_feed_metadata(feed, web_feed)
        old_groups = normalize_entry_hashes(feed.entry_hashes) or []
        new_groups, new_entries = self._calculate_update(
            old_groups,
            entries,
            feed_link=feed.link,
        )

        dispatched = 0
        acknowledged_entries: list[Any] = []
        bootstrap_skipped = bool(
            notify_new_entries
            and new_entries
            and not old_groups
            and self._rss_settings.bootstrap_skip_history
        )
        if (
            notify_new_entries
            and new_entries
            and not bootstrap_skipped
            and self._notification_dispatcher
        ):
            dispatch_result = await self._dispatch_entries(
                feed,
                new_entries,
                subscription_ids=subscription_ids,
            )
            dispatched = dispatch_result.dispatched
            acknowledged_entries = dispatch_result.acknowledged_entries

        if notify_new_entries and new_entries and not bootstrap_skipped:
            acknowledged_ids = {id(entry) for entry in acknowledged_entries}
            unacknowledged_entries = [
                entry for entry in new_entries if id(entry) not in acknowledged_ids
            ]
            unacknowledged_ids = {id(entry) for entry in unacknowledged_entries}
            committed_groups = [
                group
                for entry, group in zip(entries, new_groups, strict=False)
                if id(entry) not in unacknowledged_ids
            ]
            if unacknowledged_entries:
                # 未确认处理的新条目不能推进条件请求水位，否则下一轮可能 304 而无法补推。
                feed.etag = previous_etag
                feed.last_modified = previous_last_modified
                logger.debug(
                    "poll_feed: keep previous validators for unacknowledged entries: "
                    "feed=%s, unacked=%d",
                    feed.link,
                    len(unacknowledged_entries),
                )
        else:
            committed_groups = new_groups

        feed.entry_hashes = self._merge_hash_history(
            old_groups,
            committed_groups,
            len(entries),
        )
        feed.updated_at = datetime.now(timezone.utc)
        saved_feed = await self._feed_repo.save(feed)

        message = f"刷新完成 (ID: {feed_id})，发现 {len(entries)} 个条目"
        if bootstrap_skipped:
            message += f"，首次初始化跳过历史 {len(new_entries)} 个"
        elif new_entries:
            message += f"，新增 {len(new_entries)} 个"
        else:
            message += "，无新增"

        logger.debug(
            "poll_feed: feed=%s, total=%d, new=%d, dispatched=%d",
            feed.link,
            len(entries),
            len(new_entries),
            dispatched,
        )
        return FeedPollingResult(
            success=True,
            status=(
                "bootstrapped"
                if bootstrap_skipped
                else "updated"
                if new_entries
                else "no_new_entries"
            ),
            message=message,
            feed_id=saved_feed.id,
            total_entries=len(entries),
            new_entries=len(new_entries),
            dispatched=dispatched,
            bootstrap_skipped=bootstrap_skipped,
            feed=saved_feed,
        )

    async def poll_feed_group(
        self,
        feed_id: int,
        subscription_ids: list[int],
        *,
        notify_new_entries: bool = True,
        verbose: bool = False,
    ) -> FeedPollingResult:
        """Poll one feed and dispatch only to the selected subscriptions."""
        return await self.poll_feed(
            feed_id,
            notify_new_entries=notify_new_entries,
            subscription_ids=list(dict.fromkeys(subscription_ids)),
            verbose=verbose,
        )

    async def poll_all_active_feeds(
        self,
        *,
        notify_new_entries: bool = False,
    ) -> list[FeedPollingResult]:
        """Poll all active feeds."""
        feeds = await self._feed_repo.get_all_active()
        results: list[FeedPollingResult] = []
        for feed in feeds:
            if feed.id is None:
                continue
            results.append(
                await self.poll_feed(
                    feed.id,
                    notify_new_entries=notify_new_entries,
                )
            )
        return results

    @staticmethod
    def _build_conditional_headers(feed: Feed) -> dict[str, str]:
        headers: dict[str, str] = {}
        if feed.etag:
            headers["If-None-Match"] = feed.etag
        if feed.last_modified:
            headers["If-Modified-Since"] = format_datetime(feed.last_modified)
        return headers

    @staticmethod
    def _apply_feed_metadata(feed: Feed, web_feed: Any) -> None:
        rss_d = getattr(web_feed, "rss_d", None)
        feed_meta = getattr(rss_d, "feed", {}) if rss_d else {}
        title = feed_meta.get("title", "") if hasattr(feed_meta, "get") else ""
        if title:
            feed.title = str(title)[:1024]

        etag = getattr(web_feed, "etag", None)
        if etag:
            feed.etag = etag

        last_modified = getattr(web_feed, "last_modified", None)
        if last_modified:
            feed.last_modified = last_modified

    def _calculate_update(
        self,
        old_groups: list[list[str]],
        entries: list[Any],
        feed_link: str | None = None,
    ) -> tuple[list[list[str]], list[Any]]:
        """Calculate new grouped fingerprints and entries not seen before."""
        known_hashes = {value for group in old_groups for value in group if value}
        new_groups: list[list[str]] = []
        new_entries: list[Any] = []

        for entry in entries:
            entry_hashes = self._hash_entry(entry, feed_link)
            stable_hash = next((h for h in entry_hashes if h.startswith("sid:")), "")
            known_by_identity = bool(stable_hash) and stable_hash in known_hashes
            known_by_any_hash = any(h in known_hashes for h in entry_hashes)

            if not (known_by_identity or known_by_any_hash):
                new_entries.append(entry)

            new_groups.append(entry_hashes)
            known_hashes.update(entry_hashes)

        return new_groups, new_entries

    def _hash_entry(self, entry: Any, feed_link: str | None = None) -> list[str]:
        """Build stable and compatibility fingerprints for one entry."""
        upstream_material = self._upstream_material(entry)
        upstream_crc = (
            hex(zlib.crc32(upstream_material.encode("utf-8", errors="ignore")))[2:]
            if upstream_material
            else ""
        )

        entry_id = self._normalize_identifier(
            str(
                self._entry_value(entry, "id")
                or self._entry_value(entry, "entry_id")
                or self._entry_value(entry, "guid")
                or ""
            )
        )
        link = self._resolve_entry_link(entry, feed_link)
        title = self._normalize_text(str(self._entry_value(entry, "title") or ""))
        summary = self._normalize_text(
            str(
                self._entry_value(entry, "summary")
                or self._entry_value(entry, "description")
                or self._entry_value(entry, "content")
                or ""
            ),
            max_length=2048,
        )

        stable_material = ""
        if entry_id:
            stable_material = f"v3|id={entry_id}"
        elif link:
            stable_material = f"v3|link={link}"
        elif title:
            stable_material = f"v3|title={title}"
        elif summary:
            stable_material = f"v3|summary={summary[:256]}"

        content_material = f"v3|title={title}|link={link}|summary={summary[:512]}"

        fingerprints: list[str] = []
        if stable_material:
            fingerprints.append(
                f"sid:{hashlib.sha256(stable_material.encode()).hexdigest()}"
            )

        content_hash = hashlib.sha256(content_material.encode()).hexdigest()
        fingerprints.append(content_hash)

        for compat_hash in (
            upstream_crc,
            self._legacy_crc32(entry),
            self._entry_identity(entry),
        ):
            if compat_hash and compat_hash not in fingerprints:
                fingerprints.append(compat_hash)

        return fingerprints

    def _merge_hash_history(
        self,
        old_groups: list[list[str]],
        new_groups: list[list[str]],
        entry_count: int,
    ) -> list[list[str]] | None:
        """Merge newest fingerprints with previous history under a bounded size."""
        history_limit = self._resolve_hash_history_limit(entry_count)
        merged: list[list[str]] = []
        seen_identity: set[str] = set()

        for group in chain(new_groups, old_groups):
            if not group:
                continue
            identity = next((h for h in group if h.startswith("sid:")), None)
            if identity and identity in seen_identity:
                continue
            if identity:
                seen_identity.add(identity)
            merged.append(group)
            if len(merged) >= history_limit:
                break

        return merged or None

    def _resolve_hash_history_limit(self, entry_count: int) -> int:
        min_limit = min(max(1, self._rss_settings.hash_history_min), 20000)
        multiplier = min(max(1, self._rss_settings.hash_history_multiplier), 20000)
        hard_limit = min(
            max(min_limit, self._rss_settings.hash_history_hard_limit), 20000
        )
        growth_limit = max(entry_count, 1) * multiplier
        return min(max(min_limit, growth_limit), hard_limit)

    @staticmethod
    def _entry_value(entry: Any, key: str, default: Any = "") -> Any:
        if isinstance(entry, dict):
            return entry.get(key, default)
        return getattr(entry, key, default)

    def _entry_identity(self, entry: Any) -> str:
        for key in ("guid", "entry_id", "id", "link"):
            value = self._entry_value(entry, key)
            if value:
                return str(value)
        return ""

    def _upstream_material(self, entry: Any) -> str:
        content = self._entry_value(entry, "content") or ""
        first_content_value = ""
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("value"):
                    first_content_value = str(item["value"]).strip()
                    break
        elif content:
            first_content_value = str(content).strip()

        return "\n".join(
            [
                str(self._entry_value(entry, "guid") or "").strip(),
                str(self._entry_value(entry, "link") or "").strip(),
                str(self._entry_value(entry, "title") or "").strip(),
                str(self._entry_value(entry, "summary") or "").strip(),
                first_content_value,
            ]
        )

    def _resolve_entry_link(self, entry: Any, feed_link: str | None = None) -> str:
        link = str(
            self._entry_value(entry, "link") or self._entry_value(entry, "guid") or ""
        ).strip()
        if not link:
            return ""
        if feed_link and not link.startswith("http"):
            link = urljoin(feed_link, link)

        return self._strip_tracking_params(link)

    def _strip_tracking_params(self, link: str) -> str:
        """Remove configured tracking parameters from an entry URL."""
        try:
            parsed = urlparse(link)
            if parsed.query:
                tracking_params = set(
                    self._rss_settings.tracking_query_params
                    or DEFAULT_TRACKING_QUERY_PARAMS
                )
                filtered_params = [
                    (key, value)
                    for key, value in parse_qsl(parsed.query)
                    if key not in tracking_params
                ]
                link = urlunparse(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        parsed.params,
                        urlencode(filtered_params),
                        parsed.fragment,
                    )
                )
        except Exception:
            pass

        return link

    def _legacy_crc32(self, entry: Any) -> str:
        hash_base = (
            str(self._entry_value(entry, "link") or "")
            + str(self._entry_value(entry, "title") or "")
            + str(
                self._entry_value(entry, "published")
                or self._entry_value(entry, "pubDate")
                or ""
            )
        )
        return str(zlib.crc32(hash_base.encode()))

    @staticmethod
    def _normalize_text(value: str, max_length: int = 1024) -> str:
        text = html.unescape(value or "")
        text = re.sub(r"\s+", " ", text).strip().lower()
        return text[:max_length]

    @staticmethod
    def _normalize_identifier(value: str, max_length: int = 1024) -> str:
        return (value or "").strip()[:max_length]

    async def _dispatch_entries(
        self,
        feed: Feed,
        entries: list[Any],
        *,
        subscription_ids: list[int] | None = None,
    ) -> _DispatchEntriesResult:
        if self._notification_dispatcher is None or feed.id is None:
            return _DispatchEntriesResult()

        dispatched = 0
        acknowledged_entries: list[Any] = []
        sorted_entries = sorted(entries, key=self._entry_sort_key, reverse=True)
        if self._history_entry_limit > 0:
            sorted_entries = sorted_entries[: self._history_entry_limit]

        for entry in sorted_entries:
            title = str(self._entry_value(entry, "title") or "")
            link = self._resolve_entry_link(entry, feed.link)
            guid = self._entry_identity(entry)
            author = str(self._entry_value(entry, "author") or "").strip()
            raw_content = str(
                self._entry_value(entry, "content")
                or self._entry_value(entry, "summary")
                or title
            )
            parsed = await HTMLParser(raw_content, feed_link=feed.link).parse()
            plain_content = await _entry_text_formatter.clean_text(raw_content)
            if any(isinstance(m, (AudioContent, VideoContent)) for m in parsed.media):
                plain_content = self._remove_media_placeholders(plain_content)
            media_items = self._media_items_from_parsed(parsed.media)
            media_urls = [url for _, url in media_items]
            enclosure_urls = [
                str(self._entry_value(enclosure, "url"))
                for enclosure in (self._entry_value(entry, "enclosures", []) or [])
                if self._entry_value(enclosure, "url")
            ]
            media_urls.extend(enclosure_urls)
            media_urls = list(dict.fromkeys(media_urls))
            tags = tuple(self._entry_value(entry, "tags", []) or ())
            content = await self._format_dispatch_content_async(
                title=title,
                body=plain_content,
                link=link,
                feed_title=feed.title,
                feed_link=feed.link,
                author=author,
                tags=tags,
            )
            if self._media_fingerprint_service is not None and media_urls:
                try:
                    media_hashes = (
                        await self._media_fingerprint_service.fingerprint_urls(
                            media_urls
                        )
                    )
                    if media_hashes:
                        logger.debug(
                            "poll_feed: media fingerprints calculated for feed=%s, count=%s",
                            feed.id,
                            len(media_hashes),
                        )
                except Exception as ex:
                    logger.debug(
                        "poll_feed: media fingerprint skipped: feed=%s, err=%s",
                        feed.id,
                        ex,
                    )
            stats = await self._notification_dispatcher.dispatch_to_feed_subscribers(
                feed_id=feed.id,
                content=content,
                entry_title=title,
                entry_link=link,
                feed_title=feed.title,
                feed_link=feed.link,
                media_urls=media_urls,
                media_items=media_items,
                entry_guid=guid,
                subscription_ids=subscription_ids,
                raw_entry=EntryContentContext(
                    title=title,
                    summary=plain_content,
                    content=plain_content,
                    link=link,
                    author=author,
                    feed_title=feed.title,
                    feed_link=feed.link,
                    raw_xml=str(getattr(entry, "raw_xml", "") or "").strip(),
                    media_urls=tuple(media_urls),
                    media_items=tuple(media_items),
                    layout=tuple(parsed.layout),
                ),
            )
            dispatched += (
                stats.get("success", 0)
                + stats.get("failed", 0)
                + stats.get("pending", 0)
            )
            if self._dispatch_stats_acknowledged(stats):
                acknowledged_entries.append(entry)
        return _DispatchEntriesResult(
            dispatched=dispatched,
            acknowledged_entries=acknowledged_entries,
        )

    @staticmethod
    def _dispatch_stats_acknowledged(stats: dict[str, Any]) -> bool:
        failed = int(stats.get("failed", 0) or 0)
        pending = int(stats.get("pending", 0) or 0)
        success = int(stats.get("success", 0) or 0)
        skipped = int(stats.get("skipped", 0) or 0)
        return failed == 0 and pending == 0 and (success + skipped) > 0

    @staticmethod
    def _format_dispatch_content(
        *,
        title: str,
        body: str,
        link: str,
        feed_title: str,
        feed_link: str,
        author: str,
    ) -> str:
        body = normalize_plain_text(body)
        title = normalize_plain_text(title)
        author = normalize_plain_text(author)
        feed_title = normalize_plain_text(feed_title)
        link = str(link or "").strip()
        feed_link = str(feed_link or "").strip()

        body = EntryTextFormatter._remove_repeated_title(body, title)
        lines = [part for part in (title, body) if part]
        content = "\n\n".join(lines)
        via_suffix = EntryTextFormatter._build_via_suffix(
            link=link,
            feed_title=feed_title,
            feed_link=feed_link,
            author=author,
            options=EffectivePushOptions(),
        )
        if via_suffix:
            return f"{content}\n\n{via_suffix}" if content else via_suffix
        return content

    @staticmethod
    async def _format_dispatch_content_async(
        *,
        title: str,
        body: str,
        link: str,
        feed_title: str,
        feed_link: str,
        author: str,
        tags: tuple[str, ...] = (),
    ) -> str:
        return await _entry_text_formatter.format_entry(
            EntryFormatInput(
                title=title,
                content=body,
                summary=body,
                link=link,
                author=author,
                feed_title=feed_title,
                feed_link=feed_link,
                tags=tags,
            ),
            EffectivePushOptions(),
        )

    @staticmethod
    def _remove_media_placeholders(text: str) -> str:
        text = re.sub(r"(?m)^\s*\[(视频|音频)\]\s*$\n?", "", text or "")
        text = re.sub(r"[ \t]*(\[视频\]|\[音频\])[ \t]*", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    @staticmethod
    def _media_items_from_parsed(media: list[Any]) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        for item in media:
            url = str(getattr(item, "url", "") or "").strip()
            if not url:
                continue
            if isinstance(item, VideoContent):
                media_type = "video"
            elif isinstance(item, AudioContent):
                media_type = "audio"
            elif isinstance(item, FileContent):
                media_type = "file"
            else:
                media_type = "image"
            items.append((media_type, url))
        return list(dict.fromkeys(items))

    @staticmethod
    def _normalize_processed_media_items(
        media_items: Any,
        media_urls: list[str],
    ) -> list[tuple[str, str]]:
        explicit: list[tuple[str, str]] = []
        if isinstance(media_items, (list, tuple)):
            for item in media_items:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                media_type = str(item[0] or "").strip()
                url = str(item[1] or "").strip()
                if media_type and url:
                    explicit.append((media_type, url))
        return list(dict.fromkeys(explicit))

    def _entry_sort_key(self, entry: Any) -> Any:
        return (
            self._entry_value(entry, "published")
            or self._entry_value(entry, "updated")
            or self._entry_value(entry, "published_parsed")
            or self._entry_value(entry, "updated_parsed")
            or ()
        )
