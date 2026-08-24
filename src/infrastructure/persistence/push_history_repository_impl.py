"""推送历史仓库实现

基于 SQLModel/SQLAlchemy 实现 PushHistoryRepository 接口。
负责推送历史实体的持久化操作。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Integer,
    String,
    cast,
    delete,
    func,
    literal,
    or_,
    text,
    union_all,
)
from sqlmodel import asc, desc, select

from ...domain.entities.push_history import (
    PushHistory,
    PushHistoryDeletionResult,
    PushHistoryDeletionSkip,
    PushHistoryPage,
    normalize_fail_reason,
    normalize_fail_reason_for_status,
)
from ...domain.repositories.push_history_repository import PushHistoryRepository
from ..utils import get_logger
from .database import get_database
from .models import DeliveryBatchORM, PushHistoryORM

logger = get_logger()

_RESOLVED_BATCH_STATUSES = {"confirmed", "discarded"}
_RESOLVED_OUTPUT_STATUSES = {"success", "skipped", "discarded"}


def _apply_history_keyword_filters(stmt, keywords: list[str] | None):
    if not keywords:
        return stmt

    clauses = []
    for keyword in keywords:
        term = str(keyword or "").strip()
        if not term:
            continue
        like = f"%{term}%"
        term_clauses = [
            PushHistoryORM.user_id.ilike(like),
            PushHistoryORM.source_type.ilike(like),
            PushHistoryORM.source_key.ilike(like),
            PushHistoryORM.content.ilike(like),
            PushHistoryORM.entry_title.ilike(like),
            PushHistoryORM.entry_link.ilike(like),
            PushHistoryORM.entry_guid.ilike(like),
            PushHistoryORM.feed_title.ilike(like),
            PushHistoryORM.feed_link.ilike(like),
            PushHistoryORM.platform_name.ilike(like),
            PushHistoryORM.target_session.ilike(like),
            PushHistoryORM.fail_reason.ilike(like),
        ]
        if term.isdigit():
            value = int(term)
            term_clauses.extend(
                [
                    PushHistoryORM.id == value,
                    PushHistoryORM.sub_id == value,
                    PushHistoryORM.feed_id == value,
                    cast(PushHistoryORM.id, String).ilike(like),
                    cast(PushHistoryORM.sub_id, String).ilike(like),
                    cast(PushHistoryORM.feed_id, String).ilike(like),
                ]
            )
        clauses.append(or_(*term_clauses))

    if not clauses:
        return stmt
    return stmt.where(or_(*clauses))


def _apply_history_scope_filters(
    stmt,
    *,
    user_id: str | None = None,
    target_session: str | None = None,
    status: str | None = None,
    keywords: list[str] | None = None,
):
    if user_id:
        stmt = stmt.where(PushHistoryORM.user_id == user_id)
    if target_session is not None:
        stmt = stmt.where(PushHistoryORM.target_session == target_session)
    if status:
        stmt = stmt.where(PushHistoryORM.status == status)
    return _apply_history_keyword_filters(stmt, keywords)


def _history_last_activity_expr():
    return func.max(
        PushHistoryORM.created_at,
        PushHistoryORM.updated_at,
        func.coalesce(PushHistoryORM.completed_at, PushHistoryORM.updated_at),
    )


def _history_bucket_expr(bucket: str):
    pattern = (
        "%Y-%m-%dT%H:00:00+00:00" if bucket == "hour" else "%Y-%m-%dT00:00:00+00:00"
    )
    return func.strftime(pattern, _history_last_activity_expr())


class PushHistoryRepositoryImpl:
    """推送历史仓库实现类"""

    async def get_by_id(self, history_id: int) -> PushHistory | None:
        """根据ID获取推送历史"""
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(PushHistoryORM, history_id)
            return self._to_entity(orm) if orm else None

    async def get_by_sub(
        self, sub_id: int, limit: int | None = None, status: str | None = None
    ) -> list[PushHistory]:
        """获取订阅的推送历史"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(PushHistoryORM).where(PushHistoryORM.sub_id == sub_id)
            if status:
                stmt = stmt.where(PushHistoryORM.status == status)
            stmt = stmt.order_by(desc(_history_last_activity_expr()))
            if limit:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def exists_success_by_scope_and_guid(
        self,
        *,
        source_type: str,
        user_id: str,
        target_session: str,
        entry_guid: str,
        source_key: str | None = None,
    ) -> bool:
        """检查指定作用域内是否存在成功的相同 GUID 推送记录。"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(PushHistoryORM.id).where(
                PushHistoryORM.source_type == source_type,
                PushHistoryORM.user_id == user_id,
                PushHistoryORM.target_session == target_session,
                PushHistoryORM.entry_guid == entry_guid,
                PushHistoryORM.status == "success",
            )
            if source_key is None:
                stmt = stmt.where(PushHistoryORM.source_key.is_(None))
            else:
                stmt = stmt.where(PushHistoryORM.source_key == source_key)
            result = await session.execute(stmt.limit(1))
            return result.scalar_one_or_none() is not None

    async def get_pending_for_retry(self, limit: int = 100) -> list[PushHistory]:
        """获取需要重试的推送记录（已标记为 failed 且未超限）"""
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(PushHistoryORM)
                .where(
                    PushHistoryORM.status == "failed",
                    PushHistoryORM.retry_count < PushHistoryORM.max_retries,
                    PushHistoryORM.batch_id.is_(None),
                )
                .order_by(asc(PushHistoryORM.created_at))
                .limit(limit)
            )
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def count_retryable_failures(self) -> int:
        """统计当前可自动重试的失败记录数。"""
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(func.count())
                .select_from(PushHistoryORM)
                .where(
                    PushHistoryORM.status.in_(("failed", "retrying")),
                    PushHistoryORM.retry_count < PushHistoryORM.max_retries,
                    PushHistoryORM.batch_id.is_(None),
                )
            )
            result = await session.execute(stmt)
            return int(result.scalar_one() or 0)

    async def count_retryable(self) -> int:
        """Backward-compatible alias."""
        return await self.count_retryable_failures()

    async def get_and_mark_retrying(self, limit: int = 100) -> list[PushHistory]:
        """原子获取并标记待重试记录，防止多 worker 重复拉取。

        在同一事务内：先 UPDATE status='retrying'，再 SELECT 返回。
        同时将此前卡在 retrying 状态的记录重新激活（fallback），
        防止 worker 崩溃导致记录永久卡死。
        SQLite 的 SERIALIZABLE 隔离级别保证原子性。
        """
        db = get_database()
        async with db.get_session() as session:
            now = datetime.now(timezone.utc)
            # fallback：重新激活 retrying 状态的旧记录（超过 5 分钟的）
            from datetime import timedelta

            retrying_cutoff = now - timedelta(minutes=5)
            fallback_stmt = select(PushHistoryORM).where(
                PushHistoryORM.status == "retrying",
                PushHistoryORM.updated_at < retrying_cutoff,
                PushHistoryORM.batch_id.is_(None),
            )
            fallback_result = await session.execute(fallback_stmt)
            stale = list(fallback_result.scalars().all())
            for orm in stale:
                orm.status = "failed"
                orm.updated_at = now

            if stale:
                await session.flush()

            # 原子获取新记录并标记为 retrying
            update_stmt = (
                select(PushHistoryORM)
                .where(
                    PushHistoryORM.status == "failed",
                    PushHistoryORM.retry_count < PushHistoryORM.max_retries,
                    PushHistoryORM.batch_id.is_(None),
                )
                .order_by(asc(PushHistoryORM.created_at))
                .limit(limit)
            )
            result = await session.execute(update_stmt)
            orms = list(result.scalars().all())
            if not orms:
                return []
            for orm in orms:
                orm.status = "retrying"
                orm.updated_at = now
            await session.flush()
            # 再查询返回（同一事务中）
            ids = [orm.id for orm in orms]
            select_stmt = select(PushHistoryORM).where(PushHistoryORM.id.in_(ids))
            result2 = await session.execute(select_stmt)
            updated_orms = result2.scalars().all()
            return [self._to_entity(orm) for orm in updated_orms]

    async def save(self, history: PushHistory) -> PushHistory:
        """保存推送历史"""
        db = get_database()
        async with db.get_session() as session:
            orm = self._to_orm(history)
            # 使用 merge 而不是 add，以正确处理新增和更新
            merged_orm = await session.merge(orm)
            await session.commit()
            await session.refresh(merged_orm)
            return self._to_entity(merged_orm)

    async def delete_old_records(self, days: int = 30) -> int:
        """删除指定天数前的历史记录"""
        db = get_database()
        async with db.get_session() as session:
            return await self._delete_candidates(
                session,
                select(PushHistoryORM, DeliveryBatchORM.status)
                .outerjoin(
                    DeliveryBatchORM,
                    PushHistoryORM.batch_id == DeliveryBatchORM.id,
                )
                .where(
                    _history_last_activity_expr()
                    < datetime.now(timezone.utc) - timedelta(days=days)
                ),
            )

    async def delete_all(self) -> int:
        """删除全部推送历史记录。"""
        db = get_database()
        async with db.get_session() as session:
            return await self._delete_candidates(
                session,
                select(PushHistoryORM, DeliveryBatchORM.status).outerjoin(
                    DeliveryBatchORM,
                    PushHistoryORM.batch_id == DeliveryBatchORM.id,
                ),
            )

    async def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        keywords: list[str] | None = None,
    ) -> list[PushHistory]:
        """获取所有推送历史"""
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(PushHistoryORM, DeliveryBatchORM.status)
                .outerjoin(
                    DeliveryBatchORM,
                    PushHistoryORM.batch_id == DeliveryBatchORM.id,
                )
                .order_by(desc(_history_last_activity_expr()))
            )
            if status:
                stmt = stmt.where(PushHistoryORM.status == status)
            stmt = _apply_history_keyword_filters(stmt, keywords)
            stmt = stmt.offset(offset).limit(limit)
            result = await session.execute(stmt)
            return [
                self._to_entity(orm, batch_status=batch_status)
                for orm, batch_status in result.all()
            ]

    async def get_by_user(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        target_session: str | None = None,
        status: str | None = None,
        keywords: list[str] | None = None,
    ) -> list[PushHistory]:
        """获取用户的推送历史"""
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(PushHistoryORM, DeliveryBatchORM.status)
                .outerjoin(
                    DeliveryBatchORM,
                    PushHistoryORM.batch_id == DeliveryBatchORM.id,
                )
                .where(PushHistoryORM.user_id == user_id)
            )
            if target_session is not None:
                stmt = stmt.where(PushHistoryORM.target_session == target_session)
            if status:
                stmt = stmt.where(PushHistoryORM.status == status)
            stmt = _apply_history_keyword_filters(stmt, keywords)
            stmt = (
                stmt.order_by(desc(_history_last_activity_expr()))
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [
                self._to_entity(orm, batch_status=batch_status)
                for orm, batch_status in result.all()
            ]

    async def get_grouped_page(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        user_id: str | None = None,
        target_session: str | None = None,
        status: str | None = None,
        keywords: list[str] | None = None,
    ) -> PushHistoryPage:
        """按批次/单条输出分页，避免批次在页面边界产生重复分组。"""
        db = get_database()
        async with db.get_session() as session:
            filtered_stmt = _apply_history_scope_filters(
                select(
                    PushHistoryORM.id.label("history_id"),
                    PushHistoryORM.batch_id.label("batch_id"),
                    _history_last_activity_expr().label("last_activity"),
                ),
                user_id=user_id,
                target_session=target_session,
                status=status,
                keywords=keywords,
            )
            filtered_rows = filtered_stmt.subquery("filtered_history")

            total_result = await session.execute(
                select(func.count()).select_from(filtered_rows)
            )
            total = int(total_result.scalar_one() or 0)

            batch_groups = (
                select(
                    filtered_rows.c.batch_id,
                    literal(None).cast(Integer).label("history_id"),
                    func.max(filtered_rows.c.last_activity).label("last_activity"),
                    literal(1).label("is_batch"),
                )
                .where(filtered_rows.c.batch_id.is_not(None))
                .group_by(filtered_rows.c.batch_id)
            )
            single_groups = select(
                literal(None).cast(Integer).label("batch_id"),
                filtered_rows.c.history_id,
                filtered_rows.c.last_activity,
                literal(0).label("is_batch"),
            ).where(filtered_rows.c.batch_id.is_(None))
            grouped_rows = union_all(batch_groups, single_groups).subquery(
                "history_groups"
            )

            group_total_result = await session.execute(
                select(func.count()).select_from(grouped_rows)
            )
            group_total = int(group_total_result.scalar_one() or 0)

            group_offset = (page - 1) * page_size
            group_page_result = await session.execute(
                select(
                    grouped_rows.c.batch_id,
                    grouped_rows.c.history_id,
                    grouped_rows.c.is_batch,
                )
                .order_by(
                    grouped_rows.c.last_activity.desc(),
                    grouped_rows.c.is_batch.desc(),
                    func.coalesce(
                        grouped_rows.c.batch_id, grouped_rows.c.history_id
                    ).desc(),
                )
                .offset(group_offset)
                .limit(page_size)
            )
            group_rows = group_page_result.all()
            if not group_rows:
                return PushHistoryPage(items=[], total=total, group_total=group_total)

            batch_ids = [
                int(row.batch_id) for row in group_rows if row.batch_id is not None
            ]
            history_ids = [
                int(row.history_id) for row in group_rows if row.history_id is not None
            ]
            group_conditions = []
            if batch_ids:
                group_conditions.append(PushHistoryORM.batch_id.in_(batch_ids))
            if history_ids:
                group_conditions.append(PushHistoryORM.id.in_(history_ids))

            item_stmt = _apply_history_scope_filters(
                select(PushHistoryORM, DeliveryBatchORM.status)
                .outerjoin(
                    DeliveryBatchORM,
                    PushHistoryORM.batch_id == DeliveryBatchORM.id,
                )
                .where(or_(*group_conditions)),
                user_id=user_id,
                target_session=target_session,
                status=status,
                keywords=keywords,
            )
            item_result = await session.execute(item_stmt)
            entities = [
                self._to_entity(orm, batch_status=batch_status)
                for orm, batch_status in item_result.all()
            ]

            group_order = {}
            for index, row in enumerate(group_rows):
                if row.batch_id is not None:
                    group_order[("batch", int(row.batch_id))] = index
                else:
                    group_order[("history", int(row.history_id))] = index

            def sort_key(history: PushHistory):
                key = (
                    ("batch", int(history.batch_id))
                    if history.batch_id is not None
                    else ("history", int(history.id or 0))
                )
                return (
                    group_order.get(key, len(group_order)),
                    history.output_order if history.batch_id is not None else 0,
                    int(history.id or 0),
                )

            entities.sort(key=sort_key)
            return PushHistoryPage(
                items=entities,
                total=total,
                group_total=group_total,
            )

    async def count_by_user(
        self,
        user_id: str,
        target_session: str | None = None,
        status: str | None = None,
        keywords: list[str] | None = None,
    ) -> int:
        """统计用户推送历史数量，可按目标会话和状态过滤。"""
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(func.count())
                .select_from(PushHistoryORM)
                .where(PushHistoryORM.user_id == user_id)
            )
            if target_session is not None:
                stmt = stmt.where(PushHistoryORM.target_session == target_session)
            if status:
                stmt = stmt.where(PushHistoryORM.status == status)
            stmt = _apply_history_keyword_filters(stmt, keywords)
            result = await session.execute(stmt)
            return int(result.scalar_one() or 0)

    async def count_all(
        self,
        status: str | None = None,
        keywords: list[str] | None = None,
    ) -> int:
        """统计全部推送历史数量，可按状态和关键词过滤。"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(func.count()).select_from(PushHistoryORM)
            if status:
                stmt = stmt.where(PushHistoryORM.status == status)
            stmt = _apply_history_keyword_filters(stmt, keywords)
            result = await session.execute(stmt)
            return int(result.scalar_one() or 0)

    async def delete(self, history_id: int) -> bool:
        """删除推送历史"""
        result = await self.delete_many([history_id])
        return bool(int(result))

    async def delete_many(self, history_ids: list[int]) -> int:
        """批量删除推送历史。"""
        ids = sorted(
            {int(history_id) for history_id in history_ids if int(history_id) > 0}
        )
        if not ids:
            return PushHistoryDeletionResult(0)

        db = get_database()
        async with db.get_session() as session:
            return await self._delete_candidates(
                session,
                select(PushHistoryORM, DeliveryBatchORM.status)
                .outerjoin(
                    DeliveryBatchORM,
                    PushHistoryORM.batch_id == DeliveryBatchORM.id,
                )
                .where(PushHistoryORM.id.in_(ids)),
            )

    async def _delete_candidates(
        self,
        session,
        statement,
    ) -> PushHistoryDeletionResult:
        """在同一写事务内筛选并删除可安全移除的历史行。"""
        try:
            await session.execute(text("BEGIN IMMEDIATE"))
            rows = (await session.execute(statement)).all()
            deletable_ids: list[int] = []
            skipped: list[PushHistoryDeletionSkip] = []
            for history, batch_status in rows:
                if self._is_unresolved_batch_output(history, batch_status):
                    skipped.append(
                        PushHistoryDeletionSkip(
                            history_id=int(history.id),
                            batch_id=int(history.batch_id),
                            status=history.status,
                        )
                    )
                elif history.id is not None:
                    deletable_ids.append(int(history.id))

            removed_count = 0
            if deletable_ids:
                result = await session.execute(
                    delete(PushHistoryORM).where(PushHistoryORM.id.in_(deletable_ids))
                )
                removed_count = int(result.rowcount or 0)
            await session.commit()
            return PushHistoryDeletionResult(removed_count, tuple(skipped))
        except BaseException:
            await session.rollback()
            raise

    @staticmethod
    def _is_unresolved_batch_output(
        history: PushHistoryORM,
        batch_status: str | None,
    ) -> bool:
        if history.batch_id is None:
            return False
        # 批次记录缺失、状态未确认或输出状态异常时都保留审计数据。
        return not (
            batch_status in _RESOLVED_BATCH_STATUSES
            and history.status in _RESOLVED_OUTPUT_STATUSES
        )

    async def delete_by_user(self, user_id: str) -> int:
        """删除指定用户的全部推送历史。"""
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return 0

        db = get_database()
        async with db.get_session() as session:
            stmt = delete(PushHistoryORM).where(
                PushHistoryORM.user_id == normalized_user_id
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_by_sub_ids(self, sub_ids: list[int]) -> int:
        """删除指定订阅的全部推送历史。"""
        ids = sorted({int(sub_id) for sub_id in sub_ids if int(sub_id) > 0})
        if not ids:
            return 0

        db = get_database()
        async with db.get_session() as session:
            stmt = delete(PushHistoryORM).where(PushHistoryORM.sub_id.in_(ids))
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_by_feed_ids(self, feed_ids: list[int]) -> int:
        """删除指定 Feed 的全部推送历史。"""
        ids = sorted({int(feed_id) for feed_id in feed_ids if int(feed_id) > 0})
        if not ids:
            return 0

        db = get_database()
        async with db.get_session() as session:
            stmt = delete(PushHistoryORM).where(PushHistoryORM.feed_id.in_(ids))
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def get_stats(self) -> dict[str, int]:
        """获取推送统计信息"""
        db = get_database()
        async with db.get_session() as session:
            total_stmt = select(func.count()).select_from(PushHistoryORM)
            total = (await session.execute(total_stmt)).scalar_one() or 0

            status_counts = {}
            for status in ["pending", "success", "failed", "stopped", "skipped"]:
                stmt = (
                    select(func.count())
                    .select_from(PushHistoryORM)
                    .where(PushHistoryORM.status == status)
                )
                count = (await session.execute(stmt)).scalar_one() or 0
                status_counts[status] = int(count)

            return {
                "total": int(total),
                **status_counts,
            }

    async def get_status_buckets(
        self,
        *,
        since: datetime,
        bucket: str,
    ) -> list[dict[str, int | str]]:
        """按最后活动时间聚合推送状态，服务 Dashboard 成功率图。"""
        normalized_bucket = "hour" if bucket == "hour" else "day"
        bucket_expr = _history_bucket_expr(normalized_bucket)
        last_activity = _history_last_activity_expr()
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(bucket_expr, PushHistoryORM.status, func.count())
                .select_from(PushHistoryORM)
                .where(last_activity >= since)
                .group_by(bucket_expr, PushHistoryORM.status)
                .order_by(bucket_expr, PushHistoryORM.status)
            )
            result = await session.execute(stmt)
            rows: list[dict[str, int | str]] = []
            for bucket_value, status, count in result.all():
                if not bucket_value:
                    continue
                rows.append(
                    {
                        "bucket": str(bucket_value),
                        "status": str(status or "unknown"),
                        "count": int(count or 0),
                    }
                )
            return rows

    @staticmethod
    def _to_entity(
        orm: PushHistoryORM,
        *,
        batch_status: str | None = None,
    ) -> PushHistory:
        """将 ORM 模型转换为领域实体"""
        return PushHistory(
            id=orm.id,
            sub_id=orm.sub_id,
            batch_id=orm.batch_id,
            batch_status=batch_status,
            bundle_id=orm.bundle_id,
            user_id=orm.user_id,
            feed_id=orm.feed_id,
            source_type=orm.source_type or "feed",
            source_key=orm.source_key,
            content=orm.content,
            raw_xml=orm.raw_xml,
            media_urls=orm.media_urls,
            handler_trace=orm.handler_trace,
            output_kind=orm.output_kind,
            output_order=orm.output_order,
            source_context=orm.source_context,
            entry_title=orm.entry_title,
            entry_link=orm.entry_link,
            entry_guid=orm.entry_guid,
            feed_title=orm.feed_title,
            feed_link=orm.feed_link,
            platform_name=orm.platform_name,
            target_session=orm.target_session,
            status=orm.status,
            retry_count=orm.retry_count,
            max_retries=orm.max_retries,
            fail_reason=normalize_fail_reason_for_status(orm.status, orm.fail_reason),
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            completed_at=orm.completed_at,
        )

    @staticmethod
    def _to_orm(history: PushHistory) -> PushHistoryORM:
        """将领域实体转换为 ORM 模型"""
        return PushHistoryORM(
            id=history.id,
            sub_id=history.sub_id,
            batch_id=history.batch_id,
            bundle_id=history.bundle_id,
            user_id=history.user_id,
            feed_id=history.feed_id,
            source_type=history.source_type or "feed",
            source_key=history.source_key,
            content=history.content,
            raw_xml=history.raw_xml,
            media_urls=history.media_urls,
            handler_trace=history.handler_trace,
            output_kind=history.output_kind,
            output_order=history.output_order,
            source_context=history.source_context,
            entry_title=history.entry_title,
            entry_link=history.entry_link,
            entry_guid=history.entry_guid,
            feed_title=history.feed_title,
            feed_link=history.feed_link,
            platform_name=history.platform_name,
            target_session=history.target_session,
            status=history.status,
            retry_count=history.retry_count,
            max_retries=history.max_retries,
            fail_reason=normalize_fail_reason(history.fail_reason),
            created_at=history.created_at,
            updated_at=history.updated_at,
            completed_at=history.completed_at,
        )


_history_repo_instance: PushHistoryRepositoryImpl | None = None


def get_push_history_repository() -> PushHistoryRepository:
    """获取推送历史仓库实例"""
    global _history_repo_instance
    if _history_repo_instance is None:
        _history_repo_instance = PushHistoryRepositoryImpl()
    return _history_repo_instance
