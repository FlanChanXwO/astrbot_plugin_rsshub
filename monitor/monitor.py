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
from itertools import chain
from typing import Final
from urllib.parse import urljoin, urlsplit, urlunsplit

from sqlalchemy.orm import selectinload
from sqlmodel import select

from ..api import feed_get
from ..db import Feed, PushHistory, Sub, User, get_session
from ..notifier import Notifier
from ..utils.locks import locked
from ..utils.log_utils import logger
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

_cfg = None


def _get_cfg():
    global _cfg
    if _cfg is None:
        from ..config import cfg

        _cfg = cfg
    return _cfg


def _ensure_utc_aware(dt: datetime | None) -> datetime | None:
    """Normalize datetime to UTC-aware for safe comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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

    def __init__(self):
        self._stat = MonitorStat()
        self._bg_task: asyncio.Task | None = None
        self._subtask_defer_map: Final[defaultdict[int, TaskState]] = defaultdict(
            lambda: TaskState.EMPTY
        )
        self._lock_up_period: int = 0
        self._running = False
        self._cached_tracking_query_params: set[str] | None = None
        self._cached_tracking_query_params_source: tuple[str, ...] | None = None

    @staticmethod
    def _config_value(key: str, default=None):
        """Read plugin config with attribute-first fallback to mapping style."""
        cfg = _get_cfg()
        if not cfg:
            return default

        if hasattr(cfg, key):
            value = getattr(cfg, key)
            if value is not None:
                return value

        getter = getattr(cfg, "get", None)
        if callable(getter):
            value = getter(key, default)
            return default if value is None else value

        return default

    async def _cleanup_old_records(self) -> None:
        """清理30天前的推送历史记录。"""
        try:
            deleted_count = await PushHistory.delete_old_records(days=30)
            if deleted_count > 0:
                logger.info(
                    "已清理 %d 条30天前的推送历史记录",
                    deleted_count,
                )
        except Exception as ex:
            logger.error("清理旧推送历史记录失败: %s", ex)

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
        """每分钟执行一次，按订阅调度并在相同(feed_id, interval)间复用抓取结果。"""
        self._stat.print_summary()

        now = datetime.now(timezone.utc)
        if now.minute == 0:
            await self._cleanup_old_records()

        try:
            now = datetime.now(timezone.utc)
            async with get_session() as session:
                # 查询所有到达检查时间的活跃订阅
                stmt = (
                    select(Sub)
                    .join(Feed)
                    .where(
                        Sub.state == 1,
                        Feed.state == 1,
                        (Sub.next_check_time.is_(None)) | (Sub.next_check_time <= now),
                    )
                    .options(selectinload(Sub.feed), selectinload(Sub.user))
                )
                result = await session.execute(stmt)
                due_subs = list(result.scalars().all())

                if not due_subs:
                    return

                # 按 (feed_id, interval) 分组
                # interval 从三层配置实时解析
                groups: dict[tuple[int, int], list[Sub]] = {}
                for sub in due_subs:
                    if not sub.feed or sub.feed_id is None:
                        continue
                    effective_interval = await self._resolve_sub_interval(sub)
                    key = (sub.feed_id, effective_interval)
                    groups.setdefault(key, []).append(sub)

                # 对每组执行抓取和推送
                for (feed_id, interval), subs in groups.items():
                    feed = subs[0].feed
                    await self._monitor_feed_with_subs(session, feed, subs, interval)

        except Exception as ex:
            logger.error(f"执行定时监控任务失败: {ex}", exc_info=True)

    async def _monitor_feed_with_subs(
        self, session, feed: Feed, subs: list[Sub], interval: int
    ):
        """抓取一次 feed 并按订阅粒度更新调度与通知（加锁版本）。"""
        if feed.id is None:
            logger.warning(
                "跳过未持久化的 Feed 监控: link=%s, title=%s, sub_count=%s",
                feed.link,
                feed.title,
                len(subs),
            )
            return

        return await self._do_monitor_feed(session, feed, subs, interval)

    @locked("#feed.id")
    async def _do_monitor_feed(
        self, session, feed: Feed, subs: list[Sub], interval: int
    ):
        """实际抓取 feed 的逻辑（已加锁）。"""
        # 调度操作延迟到 session commit 之后执行，避免嵌套 session
        notifier_to_run: Notifier | None = None

        headers = {
            "If-Modified-Since": format_datetime(feed.last_modified or feed.updated_at)
        }
        if feed.etag:
            headers["If-None-Match"] = feed.etag

        wf = await feed_get(
            feed.link,
            headers=headers,
            verbose=False,
            timeout=_get_cfg().timeout if _get_cfg() else None,
            proxy=_get_cfg().proxy if _get_cfg() else "",
        )
        rss_d = wf.rss_d

        feed_updated_fields: set[str] = set()

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
                etag = wf.etag
                if etag:
                    if etag != feed.etag:
                        feed.etag = etag
                        feed_updated_fields.add("etag")
                        logger.debug(f"Updated ETag for feed {feed.id}: {etag}")
                else:
                    logger.debug(f"No ETag received for feed {feed.id} ({feed.link})")

                title = rss_d.feed.get("title", "")
                if title and title != feed.title:
                    feed.title = title[:1024]
                    feed_updated_fields.add("title")

                old_groups = self._migrate_flat_hashes(feed.entry_hashes or [])
                fetched_entries = len(rss_d.entries)
                new_groups, updated_entries = self._calculate_update(
                    old_groups,
                    rss_d.entries,
                    feed_link=feed.link,
                )
                dedup_new_count = len(updated_entries)
                dedup_skipped_count = max(0, fetched_entries - dedup_new_count)
                merged = self._merge_hash_history(
                    old_groups,
                    new_groups,
                    fetched_entries,
                )

                if not old_groups:
                    # 首次初始化（数据库中没有哈希历史）
                    feed.last_modified = wf.last_modified
                    feed.entry_hashes = merged
                    feed_updated_fields.update({"last_modified", "entry_hashes"})
                    schedule_action = ("success", None)

                    if not updated_entries:
                        self._stat.not_updated()
                        logger.info(
                            "Feed 首次初始化完成（无内容）: %s, fetched_entries=%s",
                            feed.link,
                            fetched_entries,
                        )
                    elif self._config_value("bootstrap_skip_history", True):
                        # bootstrap_skip_history=true: 仅保存哈希，不推送历史条目
                        logger.info(
                            "Feed 首次初始化跳过历史: %s, entries=%s",
                            feed.link,
                            len(updated_entries),
                        )
                        self._stat.not_updated()
                    else:
                        # bootstrap_skip_history=false: 按最新到最老推送历史条目，受 history_entry_limit 限制
                        history_limit = (
                            _get_cfg().history_entry_limit if _get_cfg() else 0
                        )
                        sorted_entries = sorted(
                            updated_entries,
                            key=lambda e: (
                                e.get("published_parsed")
                                or e.get("updated_parsed")
                                or ()
                            ),
                            reverse=True,
                        )
                        if history_limit > 0 and len(sorted_entries) > history_limit:
                            limited_entries = sorted_entries[:history_limit]
                            skipped = len(sorted_entries) - history_limit
                            logger.info(
                                "Feed 首次初始化推送历史: %s, 推送=%s, 跳过=%s (history_entry_limit=%s)",
                                feed.link,
                                len(limited_entries),
                                skipped,
                                history_limit,
                            )
                        else:
                            limited_entries = sorted_entries
                            logger.info(
                                "Feed 首次初始化推送全部历史: %s, entries=%s",
                                feed.link,
                                len(limited_entries),
                            )

                        notifier_to_run = await self._build_feed_notifier(
                            feed=feed,
                            subs=subs,
                            entries=limited_entries,
                        )
                        push_success = False
                        try:
                            await notifier_to_run.notify_all()
                            push_success = True
                        except Exception as push_err:
                            logger.error(
                                "首次初始化推送失败: feed=%s, error=%s",
                                feed.link,
                                push_err,
                                exc_info=True,
                            )
                            feed_updated_fields.clear()
                            raise
                        finally:
                            await notifier_to_run.close()

                        if push_success:
                            feed.last_modified = wf.last_modified
                            feed.entry_hashes = merged
                            feed_updated_fields.update(
                                {"last_modified", "entry_hashes"}
                            )
                            self._log_feed_polling_stats(
                                feed=feed,
                                fetched_entries=fetched_entries,
                                dedup_new_count=len(limited_entries),
                                dedup_skipped_count=len(updated_entries)
                                - len(limited_entries),
                                notifier=notifier_to_run,
                            )
                            self._stat.updated()

                elif not updated_entries:
                    if merged != old_groups:
                        feed.entry_hashes = merged
                        feed_updated_fields.add("entry_hashes")
                    schedule_action = ("success", None)
                    self._stat.not_updated()

                else:
                    logger.info(
                        f"Feed已更新: {feed.link} ({len(updated_entries)}条新内容)"
                    )
                    # 先推送通知，成功后再更新数据库
                    # 这样可以确保推送失败时不会记录哈希，避免永久漏推
                    notifier_to_run = await self._build_feed_notifier(
                        feed=feed,
                        subs=subs,
                        entries=updated_entries,
                    )

                    # 执行推送
                    push_success = False
                    try:
                        await notifier_to_run.notify_all()
                        push_success = True
                    except Exception as push_err:
                        logger.error(
                            "推送失败，不更新数据库以避免漏推: feed=%s, error=%s",
                            feed.link,
                            push_err,
                            exc_info=True,
                        )
                        raise  # 重新抛出以触发错误处理
                    finally:
                        await notifier_to_run.close()

                    # 推送成功后才更新数据库
                    if push_success:
                        feed.last_modified = wf.last_modified
                        feed.entry_hashes = merged
                        feed_updated_fields.update({"last_modified", "entry_hashes"})
                        self._log_feed_polling_stats(
                            feed=feed,
                            fetched_entries=fetched_entries,
                            dedup_new_count=dedup_new_count,
                            dedup_skipped_count=dedup_skipped_count,
                            notifier=notifier_to_run,
                        )
                        schedule_action = ("success", None)
                        self._stat.updated()
        finally:
            # 注意：notifier_to_run 的关闭已在各分支中处理，不在此处统一关闭
            # 这样可以确保推送失败时不更新数据库，避免永久漏推
            if feed_updated_fields:
                session.add(feed)
                await session.commit()
                logger.debug(f"Feed {feed.id} 已更新字段: {feed_updated_fields}")

        if schedule_action:
            action, reason = schedule_action
            if action == "success":
                await self._schedule_after_success(subs, interval)
            elif action == "error" and reason:
                await self._schedule_after_error(subs, interval, reason)

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
                "Multi-bot deduplication: %d subscriptions -> %d unique sessions "
                "(%d without target)",
                len(subs),
                len(session_subs),
                len(no_session_subs),
            )
        return deduplicated

    async def _build_feed_notifier(
        self, feed: Feed, subs: list[Sub], entries: list
    ) -> Notifier:
        ordered_entries = list(reversed(entries))

        # Apply history entry limit if configured
        history_limit = _get_cfg().history_entry_limit if _get_cfg() else 0
        if history_limit > 0:
            # Sort by published_parsed (newest first) and limit
            # Use index as tie-breaker to maintain stable order when time parsing fails
            failed_time_parse_count = [
                0
            ]  # Use list to allow mutation in nested function

            def _entry_sort_key(entry_index_pair):
                original_index, entry = entry_index_pair
                # published_parsed is a time.struct_time tuple or None
                parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if parsed:
                    try:
                        # Convert to timestamp for comparison
                        from calendar import timegm

                        return (
                            timegm(parsed),
                            -original_index,
                        )  # Negative for stable reverse
                    except (TypeError, ValueError):
                        pass

                # Time parsing failed, use original order as tie-breaker
                failed_time_parse_count[0] += 1
                return (0, -original_index)  # Put at end but maintain relative order

            # Pair entries with their original indices for stable sorting
            indexed_entries = list(enumerate(ordered_entries))
            indexed_entries.sort(key=_entry_sort_key, reverse=True)

            if failed_time_parse_count[0] > 0:
                logger.warning(
                    "Feed %s: %d entries failed time parsing, using original order as fallback",
                    feed.link,
                    failed_time_parse_count[0],
                )

            # Extract just the entries (already in reverse order due to sort)
            ordered_entries = [entry for _, entry in indexed_entries]

            limited_entries = ordered_entries[:history_limit]
            if len(limited_entries) < len(ordered_entries):
                skipped_count = len(ordered_entries) - len(limited_entries)
                logger.warning(
                    "History entry limit applied: feed=%s, total=%s, limited=%s, skipped=%s "
                    "(consider increasing history_entry_limit to avoid missing entries)",
                    feed.link,
                    len(ordered_entries),
                    len(limited_entries),
                    skipped_count,
                )
            ordered_entries = limited_entries

        fanout_subs = subs
        fanout_feed_id = feed.id
        if fanout_feed_id is not None:
            fanout_subs = await Sub.get_active_by_feed_id(fanout_feed_id)

        dedup_before_sub_count = len(fanout_subs)
        if _get_cfg() and _get_cfg().deduplicate_multi_bot:
            fanout_subs = self._deduplicate_session_subscriptions(fanout_subs)
        fanout_sub_count = len(fanout_subs)

        notifier = Notifier(
            feed=feed,
            subs=fanout_subs,
            entries=ordered_entries,
            timeout_seconds=_get_cfg().timeout if _get_cfg() else 30,
            proxy=_get_cfg().proxy if _get_cfg() else "",
            download_media_before_send=(
                _get_cfg().download_media_before_send if _get_cfg() else True
            ),
        )
        notifier.stats.setdefault("fanout_sub_count", fanout_sub_count)
        notifier.stats.setdefault("dedup_before_sub_count", dedup_before_sub_count)
        return notifier

    def _log_feed_polling_stats(
        self,
        *,
        feed: Feed,
        fetched_entries: int,
        dedup_new_count: int,
        dedup_skipped_count: int,
        notifier: Notifier,
    ) -> None:
        logger.info(
            "Feed 轮询统计：feed=%s, fetched_entries=%s, dedup_new_count=%s, "
            "dedup_skipped_count=%s, fanout_sub_count=%s, dedup_before_sub_count=%s, "
            "push_pending=%s, push_success=%s, push_failed=%s",
            feed.link,
            fetched_entries,
            dedup_new_count,
            dedup_skipped_count,
            notifier.stats.get("fanout_sub_count", len(notifier.subs)),
            notifier.stats.get("dedup_before_sub_count", len(notifier.subs)),
            notifier.stats.get("pending_count", 0),
            notifier.stats.get("success_count", 0),
            notifier.stats.get("failed_count", 0),
        )

    async def _schedule_after_success(self, subs: list[Sub], interval: int) -> None:
        """成功后刷新订阅的 next_check_time。"""
        now = datetime.now(timezone.utc)

        async with get_session() as session:
            for sub in subs:
                if sub.id is None:
                    continue
                db_sub = await session.get(Sub, sub.id)
                if db_sub:
                    db_sub.next_check_time = now + timedelta(minutes=interval)
                    session.add(db_sub)
            await session.commit()

    async def _schedule_after_error(
        self, subs: list[Sub], interval: int, reason: str
    ) -> None:
        """失败后刷新订阅的 next_check_time。"""
        async with get_session() as session:
            for sub in subs:
                if sub.id is None:
                    continue
                db_sub = await session.get(Sub, sub.id)
                if not db_sub:
                    continue
                db_sub.next_check_time = datetime.now(timezone.utc) + timedelta(
                    minutes=interval
                )
                session.add(db_sub)
            await session.commit()

    async def _resolve_sub_interval(self, sub: Sub) -> int:
        """解析单个订阅生效 interval，优先级 Sub > User > Plugin default。"""
        if sub.interval and sub.interval > 0:
            return sub.interval

        user = sub.user
        if user is None:
            user = await User.get_or_create(sub.user_id)

        if user.interval and user.interval > 0:
            return user.interval

        plugin_default = _get_cfg().default_interval if _get_cfg() else 10
        return max(1, int(plugin_default))

    def _calculate_update(
        self,
        old_entry_groups: list[list[str]],
        entries: list,
        feed_link: str | None = None,
    ) -> tuple[list[list[str]], list]:
        """计算哪些条目是新的。

        Args:
            old_entry_groups: 已有的按 entry 分组的指纹，
                每个子列表是一条 entry 的完整指纹集。
            entries: feedparser 解析出的条目列表。
            feed_link: feed 链接，用于解析相对 URL。

        Returns:
            (new_entry_groups, updated_entries) —
            新的按 entry 分组的指纹列表，以及需要推送的新条目。
        """
        old_flat = {h for group in old_entry_groups for h in group if h}
        known_hashes = set(old_flat)
        new_entry_groups: list[list[str]] = []
        updated_entries = []

        for entry in entries:
            entry_hashes = self._hash_entry(entry, feed_link=feed_link)
            stable_hash = next(
                (h for h in entry_hashes if self._is_identity_hash(h)),
                "",
            )

            known_by_identity = bool(stable_hash) and stable_hash in known_hashes
            known_by_compat = False
            if not known_by_identity and not stable_hash:
                known_by_compat = any(h in known_hashes for h in entry_hashes)

            if not (known_by_identity or known_by_compat):
                updated_entries.append(entry)

            new_entry_groups.append(entry_hashes)
            # Only add identity hash to known_hashes to avoid false positives
            # from content hash collisions within the same batch
            if stable_hash:
                known_hashes.add(stable_hash)

        return new_entry_groups, updated_entries

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
        except ValueError:
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
            except (TypeError, ValueError):
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
            except (TypeError, ValueError):
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

    @staticmethod
    def _migrate_flat_hashes(raw: list) -> list[list[str]]:
        """将旧的扁平 list[str] 格式迁移为按 entry 分组的 list[list[str]]。

        如果已经是新格式（嵌套列表）或为空，直接返回。
        旧格式按 identity hash (sid:) 边界分组。
        """
        if not raw:
            return []
        if isinstance(raw[0], list):
            return raw
        # 旧的扁平格式：按 sid: 前缀边界分组
        groups: list[list[str]] = []
        current: list[str] = []
        for h in raw:
            if RSSMonitor._is_identity_hash(h) and current:
                groups.append(current)
                current = []
            current.append(h)
        if current:
            groups.append(current)
        return groups

    def _merge_hash_history(
        self,
        old_groups: list[list[str]],
        new_groups: list[list[str]],
        entry_count: int,
    ) -> list[list[str]] | None:
        """合并新旧 entry 指纹分组，按 entry 粒度截断。

        Args:
            old_groups: 旧的按 entry 分组的指纹列表。
            new_groups: 新的按 entry 分组的指纹列表。
            entry_count: 当前已有的 entry 数量，用于计算历史窗口大小。

        Returns:
            合并后的分组列表，或 None（无数据时）。
        """
        history_limit = self._resolve_hash_history_limits(entry_count)

        merged: list[list[str]] = []
        seen_identity: set[str] = set()

        for group in chain(new_groups, old_groups):
            if not group:
                continue
            identity = next((h for h in group if self._is_identity_hash(h)), None)
            if identity and identity in seen_identity:
                continue
            if identity:
                seen_identity.add(identity)
            merged.append(group)
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
