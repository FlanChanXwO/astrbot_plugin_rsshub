"""推送历史仓库实现

基于 SQLModel/SQLAlchemy 实现 PushHistoryRepository 接口。
负责推送历史实体的持久化操作。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import String, cast, delete, func, or_
from sqlmodel import asc, desc, select

from ...domain.entities.push_history import (
    PushHistory,
    normalize_fail_reason,
    normalize_fail_reason_for_status,
)
from ...domain.repositories.push_history_repository import PushHistoryRepository
from ..utils import get_logger
from .database import get_database
from .models import PushHistoryORM

logger = get_logger()


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


def _history_last_activity_expr():
    return func.max(
        PushHistoryORM.created_at,
        PushHistoryORM.updated_at,
        func.coalesce(PushHistoryORM.completed_at, PushHistoryORM.updated_at),
    )


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
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            last_activity = _history_last_activity_expr()
            stmt = (
                delete(PushHistoryORM)
                .where(last_activity < cutoff_date)
                .execution_options(synchronize_session=False)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    async def delete_all(self) -> int:
        """删除全部推送历史记录。"""
        db = get_database()
        async with db.get_session() as session:
            stmt = delete(PushHistoryORM).execution_options(synchronize_session=False)
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

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
            stmt = select(PushHistoryORM).order_by(desc(_history_last_activity_expr()))
            if status:
                stmt = stmt.where(PushHistoryORM.status == status)
            stmt = _apply_history_keyword_filters(stmt, keywords)
            stmt = stmt.offset(offset).limit(limit)
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

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
            stmt = select(PushHistoryORM).where(PushHistoryORM.user_id == user_id)
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
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

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
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(PushHistoryORM, history_id)
            if not orm:
                return False
            await session.delete(orm)
            await session.commit()
            return True

    async def delete_many(self, history_ids: list[int]) -> int:
        """批量删除推送历史。"""
        ids = sorted(
            {int(history_id) for history_id in history_ids if int(history_id) > 0}
        )
        if not ids:
            return 0

        db = get_database()
        async with db.get_session() as session:
            stmt = delete(PushHistoryORM).where(PushHistoryORM.id.in_(ids))
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

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

    @staticmethod
    def _to_entity(orm: PushHistoryORM) -> PushHistory:
        """将 ORM 模型转换为领域实体"""
        return PushHistory(
            id=orm.id,
            sub_id=orm.sub_id,
            user_id=orm.user_id,
            feed_id=orm.feed_id,
            source_type=orm.source_type or "feed",
            source_key=orm.source_key,
            content=orm.content,
            raw_xml=orm.raw_xml,
            media_urls=orm.media_urls,
            handler_trace=orm.handler_trace,
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
            user_id=history.user_id,
            feed_id=history.feed_id,
            source_type=history.source_type or "feed",
            source_key=history.source_key,
            content=history.content,
            raw_xml=history.raw_xml,
            media_urls=history.media_urls,
            handler_trace=history.handler_trace,
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
