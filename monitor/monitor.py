"""
RSS-to-AstrBot Monitor
基于 RSS-to-Telegram-Bot 移植的 RSS 监控模块
"""

from __future__ import annotations

import asyncio
import zlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from itertools import chain, islice, repeat
from typing import TYPE_CHECKING, Final

from sqlmodel import select

from astrbot.api import logger

from ..db import Feed, MonitorSchedule, Sub, User, get_session
from ..notifier import Notifier
from ..web import feed_get


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

    def __init__(self, config: PluginConfig | None = None):
        self.config = config
        self._stat = MonitorStat()
        self._bg_task: asyncio.Task | None = None
        self._subtask_defer_map: Final[defaultdict[int, TaskState]] = defaultdict(
            lambda: TaskState.EMPTY
        )
        self._lock_up_period: int = 0
        self._running = False

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
                due_subs: list[Sub] = []
                now = datetime.now(timezone.utc)

                for sub_id in sub_ids:
                    sub = await Sub.get_by_id(sub_id)
                    if not sub or not sub.feed or sub.state != 1:
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

                for feed_id, feed_subs in by_feed.items():
                    feed = await Feed.get_by_id(feed_id)
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
        schedule_action: tuple[str, str | None] | None = None  # ("success" | "error", reason)

        try:
            if wf.status == 304:
                schedule_action = ("success", None)
                self._stat.cached()

            elif rss_d is None:
                schedule_action = ("error", wf.error.error_name if wf.error else "未知错误")
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

                old_hashes = feed.entry_hashes or []
                new_hashes, updated_entries = self._calculate_update(
                    old_hashes, rss_d.entries
                )

                if not old_hashes:
                    feed.last_modified = wf.last_modified
                    feed.entry_hashes = (
                        list(islice(new_hashes, max(len(rss_d.entries) * 2, 100))) or None
                    )
                    feed_updated_fields.update({"last_modified", "entry_hashes"})
                    schedule_action = ("success", None)
                    self._stat.not_updated()
                    logger.info(f"Feed首次初始化完成（不推送历史内容）: {feed.link}")

                elif not updated_entries:
                    schedule_action = ("success", None)
                    self._stat.not_updated()

                else:
                    logger.info(f"Feed已更新: {feed.link} ({len(updated_entries)}条新内容)")
                    feed.last_modified = wf.last_modified
                    feed.entry_hashes = (
                        list(islice(new_hashes, max(len(rss_d.entries) * 2, 100))) or None
                    )
                    feed_updated_fields.update({"last_modified", "entry_hashes"})

                    updated_entries.reverse()
                    await Notifier(
                        feed=feed,
                        subs=subs,
                        entries=updated_entries,
                        timeout_seconds=self.config.timeout if self.config else 30,
                        proxy=self.config.proxy if self.config else "",
                        download_media_before_send=(
                            self.config.download_image_before_send if self.config else True
                        ),
                    ).notify_all()
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

    def _calculate_update(self, old_hashes: list[str], entries: list) -> tuple:
        """计算哪些条目是新的。"""
        new_hashes = []
        updated_entries = []

        for entry in entries:
            entry_hash = self._hash_entry(entry)
            new_hashes.append(entry_hash)
            if entry_hash not in old_hashes:
                updated_entries.append(entry)

        return new_hashes, updated_entries

    def _hash_entry(self, entry) -> str:
        """计算条目哈希。"""
        hash_base = (
            entry.get("link", "")
            + entry.get("title", "")
            + str(entry.get("published", ""))
        )
        return str(zlib.crc32(hash_base.encode()))


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


Monitor = RSSMonitor()
