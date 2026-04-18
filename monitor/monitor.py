"""
RSS-to-AstrBot Monitor
基于 RSS-to-Telegram-Bot 移植的 RSS 监控模块
"""

from __future__ import annotations

import asyncio
import hashlib
import zlib
from calendar import timegm
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from itertools import chain, repeat
from typing import TYPE_CHECKING, Final
from urllib.parse import urljoin, urlsplit, urlunsplit

from sqlalchemy.orm import selectinload
from sqlmodel import select

from astrbot.api import logger

from ..api import feed_get
from ..db import FailedNotification, Feed, MonitorSchedule, Sub, User, get_session
from ..notifier import Notifier
from ..utils.monitor_helpers import (
    looks_like_bare_domain_scheme,
    normalize_config_positive_int,
    normalize_identifier,
    normalize_path,
    normalize_query,
    normalize_text,
    resolve_hash_history_limit,
    tracking_query_params_cache_key,
)
from ..utils.retry_helper import process_failed_notification


def _ensure_utc_aware(dt: datetime | None) -> datetime | None:
    """Normalize datetime to UTC-aware for safe comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


if TYPE_CHECKING:
    from ..utils.config import PluginConfig


class RSSMonitor:
    """
    RSS监控器

    负责定时检查订阅的 RSS 源是否有更新。
    调度维度为订阅（Sub），可实现会话/订阅级 interval 生效。
    """

    TIMEOUT: Final = 300
    HASH_HISTORY_MIN: Final = 200
    HASH_HISTORY_MULTIPLIER: Final = 2
    HASH_HISTORY_HARD_LIMIT: Final = 5000
    HASH_HISTORY_ABSOLUTE_MAX: Final = 20000
    TRACKING_QUERY_PARAMS: Final = {
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

    def __init__(self, config: PluginConfig | None = None):
        self.config = config
        self._stat = MonitorStat()
        self._bg_task: asyncio.Task | None = None
        self._subtask_defer_map: Final[defaultdict[int, TaskState]] = defaultdict(
            lambda: TaskState.EMPTY
        )
        self._lock_up_period: int = 0
        self._running = False
        self._cached_tracking_query_params: set[str] | None = None
        self._cached_tracking_query_params_source: tuple[str, ...] | None = None

    def _config_value(self, key: str, default=None):
        """Read plugin config with attribute-first fallback to mapping style."""
        if self.config is None:
            return default

        if hasattr(self.config, key):
            value = getattr(self.config, key)
            if value is not None:
                return value

        getter = getattr(self.config, "get", None)
        if callable(getter):
            value = getter(key, default)
            return default if value is None else value

        return default

    async def _process_failed_queue(self) -> None:
        """Process pending failed notifications from the queue."""
        try:
            # Get max retries from config
            max_retries = self._config_value("failed_queue_max_retries", 3)

            # Cleanup exhausted failed notifications so the table doesn't grow unbounded
            deleted_count = await FailedNotification.delete_exceeded(max_retries)
            if deleted_count > 0:
                logger.debug(
                    "Cleaned up %d exhausted failed notifications (max_retries=%s)",
                    deleted_count,
                    max_retries,
                )

            # Get pending notifications
            pending = await FailedNotification.get_pending(
                limit=50, max_retries=max_retries
            )

            if not pending:
                return

            logger.info("Processing %d failed notifications from queue", len(pending))

            # Batch load all subscriptions to avoid N+1 pattern
            sub_ids = {notif.sub_id for notif in pending if notif.sub_id}
            subs_map = await Sub.get_by_ids(list(sub_ids))

            for notif in pending:
                try:
                    # Check subscription from batch-loaded map
                    sub = subs_map.get(notif.sub_id)
                    if not sub or sub.state != 1:
                        # Subscription deleted or disabled, remove notification
                        await FailedNotification.delete(notif.id)
                        logger.debug(
                            "Removed failed notification for inactive sub=%s",
                            notif.sub_id,
                        )
                        continue

                    # Use shared retry helper
                    success, _ = await process_failed_notification(
                        notif,
                        config=self.config,
                        timeout_seconds=self.config.timeout if self.config else 30,
                        proxy=self.config.proxy if self.config else "",
                        max_retries=max_retries,
                    )

                    if not success:
                        # Check if exhausted after retry increment
                        if notif.retry_count + 1 >= max_retries:
                            logger.warning(
                                "Failed notification exhausted retries: notif=%s, sub=%s",
                                notif.id,
                                notif.sub_id,
                            )

                except Exception as ex:
                    await FailedNotification.increment_retry(
                        notif.id, fail_reason=str(ex)
                    )
                    logger.error(
                        "Failed to process failed notification: notif=%s, error=%s",
                        notif.id,
                        ex,
                    )

        except Exception as ex:
            logger.error("Failed to process failed queue: %s", ex)

    async def start(self):
        self._running = True
        logger.info("RSS监控器已启动")

    async def stop(self):
        self._running = False
        if self._bg_task:
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        logger.info("RSS监控器已停止")

    async def run_periodic_task(self):
        """每分钟执行一次，按订阅调度并在 feed 级复用抓取结果。"""
        self._stat.print_summary()

        # Process failed notification queue
        await self._process_failed_queue()

        try:
            async with get_session() as session:
                stmt = (
                    select(Sub)
                    .join(Feed)
                    .where(Sub.state == 1, Feed.state == 1)
                    .distinct()
                )
                result = await session.execute(stmt)
                subs = result.scalars().all()

                if not subs:
                    return

                sub_ids = [s.id for s in subs if s.id is not None]
                sub_count = len(sub_ids)
                chunk_count = 60
                larger_chunk_count = sub_count % chunk_count
                smaller_chunk_size = sub_count // chunk_count
                smaller_chunk_count = chunk_count - larger_chunk_count
                larger_chunk_size = smaller_chunk_size + 1

                pos = 0
                for delay, count in enumerate(
                    chain(
                        repeat(larger_chunk_size, larger_chunk_count),
                        repeat(smaller_chunk_size, smaller_chunk_count),
                    )
                ):
                    if count == 0:
                        break
                    await asyncio.sleep(delay)
                    await self._monitor_subscriptions(sub_ids[pos : pos + count])
                    pos += count
        except Exception as ex:
            logger.error(f"执行定时监控任务失败: {ex}", exc_info=True)

    async def _monitor_subscriptions(self, sub_ids: list[int]):
        """监控一批订阅，并对同一 feed 进行抓取复用。"""
        try:
            async with get_session() as session:
                now = datetime.now(timezone.utc)

                # Batch-fetch all subs with their feeds and users in a single query
                stmt = (
                    select(Sub)
                    .where(Sub.id.in_(sub_ids), Sub.state == 1)
                    .options(selectinload(Sub.feed), selectinload(Sub.user))
                )
                result = await session.execute(stmt)
                all_subs = list(result.scalars().all())

                due_subs: list[Sub] = []
                for sub in all_subs:
                    if not sub.feed:
                        continue
                    if await self._is_sub_due(sub, now):
                        due_subs.append(sub)
                    else:
                        self._stat.skipped()

                if not due_subs:
                    return

                by_feed: dict[int, list[Sub]] = {}
                for sub in due_subs:
                    if sub.feed_id is None:
                        continue
                    by_feed.setdefault(sub.feed_id, []).append(sub)

                for feed_subs in by_feed.values():
                    feed = feed_subs[0].feed  # already loaded via selectinload
                    if not feed or feed.state != 1:
                        continue
                    await self._monitor_feed_with_subs(session, feed, feed_subs)
        except Exception as ex:
            logger.error(f"_monitor_subscriptions 失败: {ex}", exc_info=True)

    async def _is_sub_due(self, sub: Sub, now: datetime) -> bool:
        """判断订阅是否到达检查时间。"""
        if sub.id is None:
            return False
        schedule = await MonitorSchedule.get_or_create(sub.id)
        next_check = _ensure_utc_aware(schedule.next_check_time)
        return next_check is None or now >= next_check

    async def _monitor_feed_with_subs(self, session, feed: Feed, subs: list[Sub]):
        """抓取一次 feed 并按订阅粒度更新调度与通知。"""
        headers = {
            "If-Modified-Since": format_datetime(feed.last_modified or feed.updated_at)
        }
        if feed.etag:
            headers["If-None-Match"] = feed.etag

        wf = await feed_get(
            feed.link,
            headers=headers,
            verbose=False,
            timeout=self.config.timeout if self.config else None,
            proxy=self.config.proxy if self.config else "",
        )
        rss_d = wf.rss_d

        feed_updated_fields: set[str] = set()
        # 调度操作延迟到 session commit 之后执行
        schedule_action: tuple[str, str | None] | None = (
            None  # ("success" | "error", reason)
        )

        try:
            if wf.status == 304:
                schedule_action = ("success", None)
                self._stat.cached()

            elif rss_d is None:
                schedule_action = (
                    "error",
                    wf.error.error_name if wf.error else "未知错误",
                )
                if self._all_subs_blocked(subs):
                    feed.state = 0
                    feed_updated_fields.add("state")
                self._stat.failed()

            elif not rss_d.entries:
                schedule_action = ("success", None)
                self._stat.empty()

            else:
                if (etag := wf.etag) != feed.etag:
                    feed.etag = etag
                    feed_updated_fields.add("etag")

                title = rss_d.feed.get("title", "")
                if title and title != feed.title:
                    feed.title = title[:1024]
                    feed_updated_fields.add("title")

                old_hashes = list(feed.entry_hashes or [])
                fetched_entries = len(rss_d.entries)
                new_hashes, updated_entries = self._calculate_update(
                    old_hashes,
                    rss_d.entries,
                    feed_link=feed.link,
                )
                dedup_new_count = len(updated_entries)
                dedup_skipped_count = max(0, fetched_entries - dedup_new_count)
                merged_hashes = self._merge_hash_history(
                    old_hashes,
                    new_hashes,
                    fetched_entries,
                )

                if not old_hashes:
                    feed.last_modified = wf.last_modified
                    feed.entry_hashes = merged_hashes
                    feed_updated_fields.update({"last_modified", "entry_hashes"})
                    schedule_action = ("success", None)
                    self._stat.not_updated()
                    if self._config_value("bootstrap_skip_history", True):
                        logger.info(
                            "Feed首次初始化完成（不推送历史内容）: %s, fetched_entries=%s, bootstrap_skipped_count=%s",
                            feed.link,
                            fetched_entries,
                            fetched_entries,
                        )
                    else:
                        logger.info(
                            "Feed首次初始化推送历史内容: %s, fetched_entries=%s, bootstrap_sent_count=%s",
                            feed.link,
                            fetched_entries,
                            dedup_new_count,
                        )
                        ordered_entries = list(reversed(updated_entries))
                        fanout_subs = subs
                        if feed.id is not None:
                            fanout_subs = await Sub.get_active_by_feed_id(feed.id)

                        dedup_before_sub_count = len(fanout_subs)
                        if self.config and getattr(
                            self.config, "deduplicate_multi_bot", True
                        ):
                            fanout_subs = self._deduplicate_session_subscriptions(
                                fanout_subs
                            )
                        fanout_sub_count = len(fanout_subs)

                        notifier = Notifier(
                            feed=feed,
                            subs=fanout_subs,
                            entries=ordered_entries,
                            timeout_seconds=self.config.timeout if self.config else 30,
                            proxy=self.config.proxy if self.config else "",
                            download_media_before_send=(
                                self.config.download_image_before_send
                                if self.config
                                else True
                            ),
                            config=self.config,
                        )
                        await notifier.notify_all()
                        logger.info(
                            "Feed轮询统计: feed=%s, fetched_entries=%s, dedup_new_count=%s, dedup_skipped_count=%s, fanout_sub_count=%s, dedup_before_sub_count=%s, enqueue_failed_count=%s, failed_drop_count=%s, failed_process_count=%s, failed_process_success_count=%s, failed_process_retry_count=%s, failed_process_exhausted_count=%s",
                            feed.link,
                            fetched_entries,
                            dedup_new_count,
                            dedup_skipped_count,
                            fanout_sub_count,
                            dedup_before_sub_count,
                            notifier.stats["enqueue_failed_count"],
                            notifier.stats["failed_drop_count"],
                            notifier.stats["failed_process_count"],
                            notifier.stats["failed_process_success_count"],
                            notifier.stats["failed_process_retry_count"],
                            notifier.stats["failed_process_exhausted_count"],
                        )

                elif not updated_entries:
                    if merged_hashes != old_hashes:
                        feed.entry_hashes = merged_hashes
                        feed_updated_fields.add("entry_hashes")
                    schedule_action = ("success", None)
                    self._stat.not_updated()

                else:
                    logger.info(
                        f"Feed已更新: {feed.link} ({len(updated_entries)}条新内容)"
                    )
                    feed.last_modified = wf.last_modified
                    feed.entry_hashes = merged_hashes
                    feed_updated_fields.update({"last_modified", "entry_hashes"})

                    ordered_entries = list(reversed(updated_entries))
                    fanout_subs = subs
                    if feed.id is not None:
                        # Fan out once to all active subscribers of this feed,
                        # avoiding chunk-based preemption between sessions/platforms.
                        fanout_subs = await Sub.get_active_by_feed_id(feed.id)

                    dedup_before_sub_count = len(fanout_subs)
                    # Apply multi-bot deduplication if enabled
                    if self.config and getattr(
                        self.config, "deduplicate_multi_bot", True
                    ):
                        fanout_subs = self._deduplicate_session_subscriptions(
                            fanout_subs
                        )
                    fanout_sub_count = len(fanout_subs)

                    notifier = Notifier(
                        feed=feed,
                        subs=fanout_subs,
                        entries=ordered_entries,
                        timeout_seconds=self.config.timeout if self.config else 30,
                        proxy=self.config.proxy if self.config else "",
                        download_media_before_send=(
                            self.config.download_image_before_send
                            if self.config
                            else True
                        ),
                        config=self.config,
                    )
                    await notifier.notify_all()
                    logger.info(
                        "Feed轮询统计: feed=%s, fetched_entries=%s, dedup_new_count=%s, dedup_skipped_count=%s, fanout_sub_count=%s, dedup_before_sub_count=%s, enqueue_failed_count=%s, failed_drop_count=%s, failed_process_count=%s, failed_process_success_count=%s, failed_process_retry_count=%s, failed_process_exhausted_count=%s",
                        feed.link,
                        fetched_entries,
                        dedup_new_count,
                        dedup_skipped_count,
                        fanout_sub_count,
                        dedup_before_sub_count,
                        notifier.stats["enqueue_failed_count"],
                        notifier.stats["failed_drop_count"],
                        notifier.stats["failed_process_count"],
                        notifier.stats["failed_process_success_count"],
                        notifier.stats["failed_process_retry_count"],
                        notifier.stats["failed_process_exhausted_count"],
                    )
                    schedule_action = ("success", None)
                    self._stat.updated()
        finally:
            if feed_updated_fields:
                session.add(feed)
                await session.commit()
                logger.debug(f"Feed {feed.id} 已更新字段: {feed_updated_fields}")

        # 在 session commit 之后再执行调度操作，避免嵌套 session
        if schedule_action:
            action, reason = schedule_action
            if action == "success":
                await self._schedule_after_success(subs)
            elif action == "error" and reason:
                await self._schedule_after_error(subs, reason)

    @staticmethod
    def _all_subs_blocked(subs: list[Sub]) -> bool:
        return len(subs) > 0 and all((s.state == 0) for s in subs)

    @staticmethod
    def _deduplicate_session_subscriptions(subs: list[Sub]) -> list[Sub]:
        """Deduplicate subscriptions by session, keeping only the earliest one.

        When multiple BOTs in the same session subscribed to the same RSS feed,
        only the earliest subscription should be used for pushing.
        Subscriptions without target_session are preserved as-is.
        """
        if not subs:
            return subs

        # Group by target_session, keeping track of creation time
        session_subs: dict[str, Sub] = {}
        # Keep subscriptions without target_session separately
        no_session_subs: list[Sub] = []

        for sub in subs:
            session_id = sub.target_session or ""
            if not session_id:
                # Preserve subscriptions without target_session
                no_session_subs.append(sub)
                continue

            # If session not seen yet, or this sub is older, keep it
            if session_id not in session_subs:
                session_subs[session_id] = sub
            elif sub.created_at < session_subs[session_id].created_at:
                session_subs[session_id] = sub

        # Combine: deduplicated session subs + subs without target_session
        deduplicated = list(session_subs.values()) + no_session_subs
        if len(deduplicated) < len(subs):
            logger.debug(
                "Multi-bot deduplication: %d subscriptions -> %d unique sessions (%d without target)",
                len(subs),
                len(session_subs),
                len(no_session_subs),
            )
        return deduplicated

    async def _schedule_after_success(self, subs: list[Sub]) -> None:
        """成功后按订阅生效 interval 刷新 next_check_time 并重置 error。"""
        now = datetime.now(timezone.utc)
        for sub in subs:
            if sub.id is None:
                continue
            effective_interval = await self._resolve_sub_interval(sub)
            await MonitorSchedule.upsert(
                sub.id,
                next_check_time=now + timedelta(minutes=effective_interval),
                error_count=0,
            )

    async def _schedule_after_error(self, subs: list[Sub], reason: str) -> None:
        """失败后按订阅退避并发送错误通知（到达上限时停用订阅）。"""
        now = datetime.now(timezone.utc)
        for sub in subs:
            if sub.id is None:
                continue
            schedule = await MonitorSchedule.get_or_create(sub.id)
            new_error_count = schedule.error_count + 1

            if new_error_count >= 100:
                async with get_session() as session:
                    db_sub = await session.get(Sub, sub.id)
                    if db_sub:
                        db_sub.state = 0
                        session.add(db_sub)
                        await session.commit()
                await Notifier(
                    feed=sub.feed,
                    subs=[sub],
                    reason=reason,
                    timeout_seconds=self.config.timeout if self.config else 30,
                    proxy=self.config.proxy if self.config else "",
                    download_media_before_send=(
                        self.config.download_image_before_send if self.config else True
                    ),
                    config=self.config,
                ).notify_all()
                await MonitorSchedule.upsert(
                    sub.id,
                    next_check_time=None,
                    error_count=new_error_count,
                )
                continue

            effective_interval = await self._resolve_sub_interval(sub)
            if new_error_count >= 10:
                next_delay = min(effective_interval << (new_error_count // 10), 1440)
            else:
                next_delay = effective_interval

            await MonitorSchedule.upsert(
                sub.id,
                next_check_time=now + timedelta(minutes=next_delay),
                error_count=new_error_count,
            )

    async def _resolve_sub_interval(self, sub: Sub) -> int:
        """解析单个订阅生效 interval，优先级 Sub > User > Plugin default。"""
        if sub.interval and sub.interval > 0:
            return sub.interval

        user = sub.user
        if user is None:
            user = await User.get_or_create(sub.user_id)

        if user.interval and user.interval > 0:
            return user.interval

        plugin_default = self.config.default_interval if self.config else 10
        return max(1, int(plugin_default))

    def _calculate_update(
        self,
        old_hashes: list[str],
        entries: list,
        feed_link: str | None = None,
    ) -> tuple[list[str], list]:
        """计算哪些条目是新的。"""
        old_hashes_set = {h for h in old_hashes if h}
        known_hashes = set(old_hashes_set)
        known_identity_hashes = {h for h in old_hashes_set if self._is_identity_hash(h)}
        new_hashes = []
        new_hashes_seen: set[str] = set()
        updated_entries = []

        for entry in entries:
            entry_hashes = self._hash_entry(entry, feed_link=feed_link)
            stable_hash = next(
                (
                    entry_hash
                    for entry_hash in entry_hashes
                    if self._is_identity_hash(entry_hash)
                ),
                "",
            )

            known_by_identity = (
                bool(stable_hash) and stable_hash in known_identity_hashes
            )
            known_by_compat = False
            if not known_by_identity and not stable_hash:
                known_by_compat = any(
                    entry_hash in known_hashes for entry_hash in entry_hashes
                )
            known_entry = known_by_identity or known_by_compat

            if not known_entry:
                updated_entries.append(entry)

            for entry_hash in entry_hashes:
                if entry_hash not in new_hashes_seen:
                    new_hashes_seen.add(entry_hash)
                    new_hashes.append(entry_hash)
                known_hashes.add(entry_hash)
                if self._is_identity_hash(entry_hash):
                    known_identity_hashes.add(entry_hash)

        return new_hashes, updated_entries

    @staticmethod
    def _normalize_text(value: str, max_length: int = 1024) -> str:
        return normalize_text(value, max_length=max_length)

    @staticmethod
    def _normalize_identifier(value: str, max_length: int = 1024) -> str:
        return normalize_identifier(value, max_length=max_length)

    @staticmethod
    def _tracking_query_params_cache_key(raw) -> tuple[str, ...] | None:
        return tracking_query_params_cache_key(raw)

    def _tracking_query_params(self) -> set[str]:
        raw = self._config_value("tracking_query_params")
        source_key = self._tracking_query_params_cache_key(raw)

        # Rebuild cache only when normalized input changes.
        if (
            self._cached_tracking_query_params is not None
            and self._cached_tracking_query_params_source == source_key
        ):
            return self._cached_tracking_query_params

        if source_key is not None:
            normalized = set(source_key)
            self._cached_tracking_query_params = normalized
            self._cached_tracking_query_params_source = source_key
            return normalized

        default_key = tuple(sorted(self.TRACKING_QUERY_PARAMS))
        if (
            self._cached_tracking_query_params is not None
            and self._cached_tracking_query_params_source == default_key
        ):
            return self._cached_tracking_query_params

        self._cached_tracking_query_params = set(default_key)
        self._cached_tracking_query_params_source = default_key
        return self._cached_tracking_query_params

    @staticmethod
    def _normalize_path(path: str) -> str:
        return normalize_path(path)

    def _normalize_query(self, query: str) -> str:
        return normalize_query(query, self._tracking_query_params())

    @staticmethod
    def _looks_like_bare_domain_scheme(parsed, trimmed_link: str) -> bool:
        return looks_like_bare_domain_scheme(parsed, trimmed_link)

    @staticmethod
    def _normalize_config_positive_int(raw, key: str, default: int) -> int:
        return normalize_config_positive_int(raw, key, default, logger)

    def _normalize_link(self, link: str) -> str:
        if not link:
            return ""

        trimmed_link = link.strip()
        try:
            parsed = urlsplit(trimmed_link)
        except Exception:
            return self._normalize_text(trimmed_link, max_length=2048)

        path = self._normalize_path(parsed.path)
        query = self._normalize_query(parsed.query)

        # urlsplit may misclassify "example.com/post" as scheme="example.com".
        if self._looks_like_bare_domain_scheme(parsed, trimmed_link):
            return trimmed_link

        # Non-hierarchical URLs (mailto:, tel:, magnet:) should preserve scheme.
        if parsed.scheme and not parsed.netloc:
            scheme = parsed.scheme.lower()
            if scheme not in {"http", "https"}:
                opaque = urlunsplit((scheme, "", path, query, ""))
                return opaque or trimmed_link

        # Relative links must remain relative; avoid forcing invalid http(s) forms.
        if not parsed.netloc:
            relative = urlunsplit(("", "", path, query, ""))
            return relative or trimmed_link

        scheme = (parsed.scheme or "").lower()
        netloc = parsed.netloc.lower()
        return urlunsplit((scheme, netloc, path, query, ""))

    @staticmethod
    def _format_entry_timestamp(entry) -> str:
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed_time:
            try:
                return str(timegm(parsed_time))
            except Exception:
                pass

        for field_name in ("published", "updated"):
            raw_value = entry.get(field_name)
            if not raw_value:
                continue
            try:
                dt = parsedate_to_datetime(str(raw_value))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return str(int(dt.timestamp()))
            except Exception:
                continue

        return ""

    @staticmethod
    def _is_identity_hash(value: str) -> bool:
        return value.startswith("sid:")

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def _legacy_entry_crc32(entry) -> str:
        """Legacy v1 fingerprint for backward compatibility with stored hashes."""
        hash_base = (
            str(entry.get("link", ""))
            + str(entry.get("title", ""))
            + str(entry.get("published", ""))
        )
        return str(zlib.crc32(hash_base.encode()))

    @staticmethod
    def _upstream_compatible_material(entry) -> str:
        """Build upstream-compatible identity material.

        Order: guid -> link -> title -> summary -> first content.value.
        """
        guid = str(entry.get("guid") or "").strip()
        link = str(entry.get("link") or "").strip()
        title = str(entry.get("title") or "").strip()
        summary = str(entry.get("summary") or "").strip()

        content_items = entry.get("content") or []
        first_content_value = ""
        if isinstance(content_items, list):
            for content in content_items:
                if isinstance(content, dict):
                    value = content.get("value")
                    if value:
                        first_content_value = str(value).strip()
                        break

        return "\n".join([guid, link, title, summary, first_content_value])

    def _resolve_entry_link(self, entry, feed_link: str | None = None) -> str:
        link = str(entry.get("link") or entry.get("guid") or "").strip()
        if not link:
            return ""
        if feed_link and not link.startswith("http"):
            link = urljoin(feed_link, link)
        return self._normalize_link(link)

    def _hash_entry(self, entry, feed_link: str | None = None) -> list[str]:
        """Calculate a robust dedupe fingerprint set for one entry."""
        upstream_material = self._upstream_compatible_material(entry)
        upstream_crc = (
            hex(zlib.crc32(upstream_material.encode("utf-8", errors="ignore")))[2:]
            if upstream_material
            else ""
        )

        entry_id = self._normalize_identifier(
            str(entry.get("id") or entry.get("guid") or "")
        )
        link = self._resolve_entry_link(entry, feed_link)
        title = self._normalize_text(str(entry.get("title") or ""))
        summary = self._normalize_text(
            str(entry.get("summary") or entry.get("description") or ""),
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
            stable_hash = f"sid:{self._sha256(stable_material)}"
            fingerprints.append(stable_hash)

        content_hash = self._sha256(content_material)
        if content_hash not in fingerprints:
            fingerprints.append(content_hash)

        if upstream_crc and upstream_crc not in fingerprints:
            fingerprints.append(upstream_crc)

        # Keep legacy v1 crc32 fingerprint to avoid full re-push after upgrading.
        legacy_hash = self._legacy_entry_crc32(entry)
        if legacy_hash and legacy_hash not in fingerprints:
            fingerprints.append(legacy_hash)

        return fingerprints

    def _resolve_hash_history_limits(self, entry_count: int) -> int:
        configured_min = self._config_value("hash_history_min")
        configured_multiplier = self._config_value("hash_history_multiplier")
        configured_hard_limit = self._config_value("hash_history_hard_limit")

        min_limit = self._normalize_config_positive_int(
            configured_min,
            "hash_history_min",
            self.HASH_HISTORY_MIN,
        )
        multiplier = self._normalize_config_positive_int(
            configured_multiplier,
            "hash_history_multiplier",
            self.HASH_HISTORY_MULTIPLIER,
        )
        hard_limit = self._normalize_config_positive_int(
            configured_hard_limit,
            "hash_history_hard_limit",
            self.HASH_HISTORY_HARD_LIMIT,
        )

        return resolve_hash_history_limit(
            entry_count=entry_count,
            min_limit=min_limit,
            multiplier=multiplier,
            hard_limit=hard_limit,
            absolute_max=self.HASH_HISTORY_ABSOLUTE_MAX,
            logger=logger,
        )

    def _merge_hash_history(
        self,
        old_hashes: list[str],
        new_hashes: list[str],
        entry_count: int,
    ) -> list[str] | None:
        history_limit = self._resolve_hash_history_limits(entry_count)

        merged: list[str] = []
        seen: set[str] = set()

        for entry_hash in chain(new_hashes, old_hashes):
            if not entry_hash or entry_hash in seen:
                continue
            seen.add(entry_hash)
            merged.append(entry_hash)
            if len(merged) >= history_limit:
                break

        return merged or None


class TaskState:
    """任务状态"""

    EMPTY = 0
    LOCKED = 1 << 0
    IN_PROGRESS = 1 << 1
    DEFERRED = 1 << 2


class MonitorStat:
    """监控统计"""

    def __init__(self):
        self.cached_count = 0
        self.updated_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.not_updated_count = 0
        self.empty_count = 0

    def cached(self):
        self.cached_count += 1

    def updated(self):
        self.updated_count += 1

    def failed(self):
        self.failed_count += 1

    def skipped(self):
        self.skipped_count += 1

    def not_updated(self):
        self.not_updated_count += 1

    def empty(self):
        self.empty_count += 1

    def print_summary(self):
        if self.cached_count + self.updated_count + self.failed_count > 0:
            logger.debug(
                f"RSS监控统计: 更新={self.updated_count}, 缓存={self.cached_count}, "
                f"失败={self.failed_count}, 跳过={self.skipped_count}"
            )
