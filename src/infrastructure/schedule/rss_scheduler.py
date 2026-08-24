"""RSS scheduler adapter.

This module owns only timing concerns: finding due subscriptions, grouping them
by feed, triggering the application polling use case, and updating the next
check time. Fetching, parsing, deduplication, and notification dispatch live in
FeedPollingService.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol

from sqlmodel import or_, select

from ..persistence.database import get_database
from ..persistence.models import FeedORM, SubORM
from ..utils import get_logger
from ..utils.lock import locked

if TYPE_CHECKING:
    from ...application.services.bundle_batch_delivery_service import (
        BundleBatchDeliveryService,
    )
    from ...application.services.bundle_collection_service import (
        BundleCollectionService,
    )
    from ...application.services.feed_polling_service import FeedPollingService
    from ...application.services.notification_dispatcher import NotificationDispatcher
    from ...domain.entities.bundle import Bundle
    from ...domain.entities.feed import Feed
    from ...domain.entities.subscription import Subscription
    from ...domain.repositories.bundle_repository import BundleRepository

logger = get_logger()


def _is_database_unavailable_error(exc: Exception) -> bool:
    return isinstance(exc, RuntimeError) and "数据库未初始化" in str(exc)


def _database_is_initialized(reason: str) -> bool:
    db = get_database()
    if db.is_initialized:
        return True
    logger.warning("数据库未初始化，跳过%s", reason)
    return False


@asynccontextmanager
async def _safe_db_session(reason: str):
    db = get_database()
    if not db.is_initialized:
        logger.warning("数据库未初始化，跳过%s", reason)
        yield None
        return
    try:
        async with db.get_session() as session:
            yield session
    except RuntimeError as ex:
        if _is_database_unavailable_error(ex):
            logger.warning("数据库会话不可用，跳过%s: %s", reason, ex)
            yield None
            return
        raise


class NotificationService(Protocol):
    """Legacy notification protocol kept for compatibility with old imports."""

    async def notify_feed_update(
        self,
        feed: Feed,
        subscriptions: list[Subscription],
        entries: list[dict[str, Any]],
    ) -> bool:
        """Notify subscribers about feed updates."""
        ...

    async def notify_feed_error(
        self,
        feed: Feed,
        subscriptions: list[Subscription],
        error: str,
    ) -> None:
        """Notify subscribers about feed polling errors."""
        ...


@dataclass(frozen=True)
class DueSubscription:
    """Subscription selected by the scheduler for the current tick."""

    id: int
    feed_id: int
    interval: int


class SchedulerStats:
    """调度器统计"""

    def __init__(self) -> None:
        self.cached_count = 0
        self.updated_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.not_updated_count = 0
        self.empty_count = 0

    def cached(self) -> None:
        self.cached_count += 1

    def updated(self) -> None:
        self.updated_count += 1

    def failed(self) -> None:
        self.failed_count += 1

    def skipped(self) -> None:
        self.skipped_count += 1

    def not_updated(self) -> None:
        self.not_updated_count += 1

    def empty(self) -> None:
        self.empty_count += 1

    def print_summary(self) -> None:
        if self.cached_count + self.updated_count + self.failed_count > 0:
            logger.debug(
                "RSS调度统计: 更新=%s, 缓存=%s, 失败=%s, 跳过=%s",
                self.updated_count,
                self.cached_count,
                self.failed_count,
                self.skipped_count,
            )

    def reset(self) -> None:
        self.cached_count = 0
        self.updated_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.not_updated_count = 0
        self.empty_count = 0


class RSSScheduler:
    """RSS 调度器，负责定时触发到期订阅的 Feed 轮询"""

    TIMEOUT = 300

    def __init__(
        self,
        *,
        feed_polling_service: FeedPollingService | None = None,
        notification_dispatcher: NotificationDispatcher | None = None,
        notification_service: NotificationService | None = None,
        subscription_batch_delivery_service: Any | None = None,
        bundle_repository: BundleRepository | None = None,
        bundle_collection_service: BundleCollectionService | None = None,
        bundle_batch_delivery_service: BundleBatchDeliveryService | None = None,
        default_interval: int = 10,
        history_retention_days: int = 30,
        **_: Any,
    ) -> None:
        self._feed_polling_service = feed_polling_service
        self._notification_dispatcher = notification_dispatcher
        self._legacy_notification_service = notification_service
        self._subscription_batch_delivery_service = subscription_batch_delivery_service
        self._bundle_repository = bundle_repository
        self._bundle_collection_service = bundle_collection_service
        self._bundle_batch_delivery_service = bundle_batch_delivery_service
        self._stats = SchedulerStats()
        self._running = False
        self._bg_task: asyncio.Task | None = None
        self._default_interval = max(1, default_interval)
        self._history_retention_days = max(1, history_retention_days)

    async def start(self) -> None:
        """启动调度器"""
        self._running = True
        logger.info("RSS调度器已启动")

    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._bg_task:
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        logger.info("RSS调度器已停止")

    async def run_periodic_task(self) -> None:
        """执行一次定时任务（每分钟调用）"""
        self._stats.print_summary()
        self._stats.reset()

        if not _database_is_initialized("本轮 RSS 调度"):
            return

        now = datetime.now(timezone.utc)
        if now.minute == 0:
            await self._cleanup_old_records()

        await self._process_due_bundles(now)
        await self._retry_subscription_batches()
        await self._retry_bundle_batches()
        await self._dispatch_pending_retries()

        try:
            due_by_feed = await self._load_due_subscriptions(now)
            for feed_id, due_subs in due_by_feed.items():
                await self._process_feed_group(feed_id, due_subs)
        except Exception:
            logger.exception("执行定时任务失败")

    async def _dispatch_pending_retries(self) -> None:
        if self._notification_dispatcher is None:
            return

        try:
            retry_stats = await self._notification_dispatcher.dispatch_pending_retries(
                limit=50
            )
            if retry_stats.get("success", 0) > 0 or retry_stats.get("failed", 0) > 0:
                logger.info(
                    "重试推送完成: 成功=%s, 失败=%s, 跳过=%s",
                    retry_stats.get("success", 0),
                    retry_stats.get("failed", 0),
                    retry_stats.get("skipped", 0),
                )
        except Exception as e:
            if _is_database_unavailable_error(e):
                logger.warning("数据库未初始化，跳过重试推送")
                return
            logger.exception("处理重试推送失败")

    async def _retry_subscription_batches(self) -> None:
        if self._subscription_batch_delivery_service is None:
            return
        try:
            await self._subscription_batch_delivery_service.retry_active_batches()
        except Exception as exc:
            if _is_database_unavailable_error(exc):
                logger.warning("数据库未初始化，跳过卡片 Subscription 批次重试")
                return
            logger.exception("处理卡片 Subscription 批次重试失败")

    async def _retry_bundle_batches(self) -> None:
        if self._bundle_batch_delivery_service is None:
            return
        try:
            await self._bundle_batch_delivery_service.retry_active_batches()
        except Exception as exc:
            if _is_database_unavailable_error(exc):
                logger.warning("数据库未初始化，跳过 Bundle 批次重试")
                return
            logger.exception("处理 Bundle 批次重试失败")

    async def _process_due_bundles(self, now: datetime) -> None:
        if self._bundle_repository is None or self._bundle_collection_service is None:
            return
        try:
            due_bundles = await self._bundle_repository.list_due(now)
        except Exception as exc:
            if _is_database_unavailable_error(exc):
                logger.warning("数据库未初始化，跳过 Bundle 到期采集")
                return
            logger.exception("加载 Bundle 到期列表失败")
            return

        for bundle in due_bundles:
            if bundle.id is None or bundle.state != 1:
                continue
            try:
                await self._bundle_collection_service.collect_bundle(bundle.id)
            except Exception as exc:
                if _is_database_unavailable_error(exc):
                    logger.warning("数据库未初始化，跳过 Bundle 采集: %s", bundle.id)
                else:
                    logger.exception("Bundle 定时采集失败: bundle_id=%s", bundle.id)
            try:
                await self._update_bundle_next_check_time(bundle, now)
            except Exception as exc:
                if _is_database_unavailable_error(exc):
                    logger.warning("数据库未初始化，跳过 Bundle 下次检查时间更新")
                else:
                    logger.exception(
                        "Bundle 下次检查时间更新失败: bundle_id=%s",
                        bundle.id,
                    )

    async def _update_bundle_next_check_time(
        self,
        bundle: Bundle,
        now: datetime,
    ) -> None:
        if self._bundle_repository is None or bundle.id is None:
            return
        interval = timedelta(minutes=self._resolve_interval(bundle.interval))
        previous = bundle.next_check_time
        if previous is None:
            next_check = now + interval
        else:
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            else:
                previous = previous.astimezone(timezone.utc)
            if previous > now:
                next_check = previous
            else:
                elapsed_intervals = (now - previous) // interval + 1
                next_check = previous + interval * elapsed_intervals
        bundle.next_check_time = next_check
        await self._bundle_repository.update_next_check_time(bundle.id, next_check)

    async def _cleanup_old_records(self) -> None:
        """清理指定天数前的推送历史记录"""
        if self._notification_dispatcher is None:
            return

        try:
            deleted_count = await self._notification_dispatcher.cleanup_old_records(
                days=self._history_retention_days
            )
            if deleted_count > 0:
                logger.info(
                    "清理了 %s 条超过 %s 天的推送历史记录",
                    deleted_count,
                    self._history_retention_days,
                )
        except Exception as e:
            if _is_database_unavailable_error(e):
                logger.warning("数据库未初始化，跳过清理推送历史记录")
                return
            logger.exception("清理推送历史记录失败")

    async def _load_due_subscriptions(
        self,
        now: datetime,
    ) -> dict[int, list[DueSubscription]]:
        due_by_feed: dict[int, list[DueSubscription]] = {}

        async with _safe_db_session("本轮 RSS 调度") as session:
            if session is None:
                return {}
            stmt = (
                select(SubORM.id, SubORM.feed_id, SubORM.interval)
                .join(FeedORM)
                .where(
                    SubORM.state == 1,
                    FeedORM.state == 1,
                    or_(
                        SubORM.next_check_time.is_(None),  # type: ignore[attr-defined]
                        SubORM.next_check_time <= now,
                    ),
                )
            )
            result = await session.execute(stmt)
            due_rows = list(result.all())

        for sub_id, feed_id, interval in due_rows:
            if sub_id is None or feed_id is None:
                continue
            due = DueSubscription(
                id=sub_id,
                feed_id=feed_id,
                interval=self._resolve_interval(interval),
            )
            due_by_feed.setdefault(feed_id, []).append(due)

        return due_by_feed

    def _resolve_interval(self, interval: int | None) -> int:
        """解析订阅生效的监控间隔"""
        if interval and interval > 0:
            return interval
        return self._default_interval

    @locked("#feed_id")
    async def _process_feed_group(
        self,
        feed_id: int,
        due_subs: list[DueSubscription],
    ) -> None:
        """Trigger the polling use case for one feed and update schedule fields."""
        if not due_subs:
            return

        try:
            if self._feed_polling_service is None:
                raise RuntimeError("RSSScheduler requires FeedPollingService")

            result = await self._feed_polling_service.poll_feed_group(
                feed_id,
                [sub.id for sub in due_subs],
                notify_new_entries=True,
            )
            self._record_polling_result(result)
        except Exception:
            self._stats.failed()
            logger.exception(
                "Feed 定时轮询失败: feed_id=%s, subs=%s",
                feed_id,
                [sub.id for sub in due_subs],
            )
        finally:
            await self._update_next_check_times(due_subs)

    async def _update_next_check_times(
        self,
        due_subs: list[DueSubscription],
    ) -> None:
        """更新订阅的下次检查时间"""
        if not due_subs:
            return

        now = datetime.now(timezone.utc)
        async with _safe_db_session("下次检查时间更新") as session:
            if session is None:
                return
            for due in due_subs:
                db_sub = await session.get(SubORM, due.id)
                if db_sub:
                    db_sub.next_check_time = now + timedelta(minutes=due.interval)
                    session.add(db_sub)
            await session.commit()

    def _record_polling_result(self, result: Any) -> None:
        if not result.success:
            self._stats.failed()
            return

        if result.status == "not_modified":
            self._stats.cached()
        elif result.total_entries == 0:
            self._stats.empty()
        elif result.bootstrap_skipped:
            self._stats.skipped()
        elif result.new_entries > 0:
            self._stats.updated()
        else:
            self._stats.not_updated()
