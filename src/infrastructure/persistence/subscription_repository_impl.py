"""订阅仓库实现

基于 SQLModel/SQLAlchemy 实现 SubscriptionRepository 接口。
负责订阅实体的持久化操作。
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import asc, or_, select

from ...domain.entities.handlers import dump_handlers, handlers_json
from ...domain.entities.subscription import Subscription
from ..utils import get_logger
from .database import get_database
from .models import FeedORM, SubORM

logger = get_logger()


class SubscriptionRepositoryImpl:
    """订阅仓库实现类"""

    async def get_by_id(self, sub_id: int) -> Subscription | None:
        """根据ID获取订阅"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(SubORM).where(SubORM.id == sub_id)
            result = await session.execute(stmt)
            orm = result.scalar_one_or_none()
            return self._to_entity(orm) if orm else None

    async def get_by_user(self, user_id: str) -> list[Subscription]:
        """获取用户的所有订阅"""
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(SubORM).where(SubORM.user_id == user_id).order_by(asc(SubORM.id))
            )
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def get_by_user_feed_session(
        self, user_id: str, feed_id: int, target_session: str | None
    ) -> Subscription | None:
        """根据用户、Feed 与目标会话获取订阅。

        订阅按 (user_id, feed_id, target_session) 唯一，同一用户在不同会话可对
        同一 Feed 各订阅一份，因此查重必须带上 target_session。

        数据库未对这三列加唯一约束，旧库或并发可能残留重复行；此处用 limit(1) +
        first() 防御，命中任一匹配即可，避免 scalar_one_or_none 在重复时抛
        MultipleResultsFound。
        """
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(SubORM)
                .where(
                    SubORM.user_id == user_id,
                    SubORM.feed_id == feed_id,
                    SubORM.target_session == target_session,
                )
                .order_by(asc(SubORM.id))
                .limit(1)
            )
            result = await session.execute(stmt)
            orm = result.scalars().first()
            return self._to_entity(orm) if orm else None

    async def get_all_active(self) -> list[Subscription]:
        """获取所有启用的订阅"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(SubORM).where(SubORM.state == 1).order_by(asc(SubORM.id))
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def list_for_dashboard(
        self,
        *,
        user_ids: list[str] | None = None,
        feed_ids: list[int] | None = None,
        feed_links: list[str] | None = None,
        sub_ids: list[int] | None = None,
        keywords: list[str] | None = None,
    ) -> list[Subscription]:
        """Dashboard 订阅列表筛选查询。"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(SubORM).join(
                FeedORM, FeedORM.id == SubORM.feed_id, isouter=True
            )
            has_filters = any(
                values for values in (user_ids, feed_ids, feed_links, sub_ids, keywords)
            )

            if not has_filters:
                stmt = stmt.where(SubORM.state == 1)

            if user_ids:
                stmt = stmt.where(SubORM.user_id.in_(user_ids))
            if feed_ids:
                stmt = stmt.where(SubORM.feed_id.in_(feed_ids))
            if feed_links:
                stmt = stmt.where(FeedORM.link.in_(feed_links))
            if sub_ids:
                stmt = stmt.where(SubORM.id.in_(sub_ids))
            if keywords:
                stmt = stmt.where(
                    or_(
                        *[
                            or_(
                                SubORM.title.ilike(f"%{keyword}%"),
                                SubORM.tags.ilike(f"%{keyword}%"),
                                SubORM.user_id.ilike(f"%{keyword}%"),
                                FeedORM.title.ilike(f"%{keyword}%"),
                                FeedORM.link.ilike(f"%{keyword}%"),
                            )
                            for keyword in keywords
                        ]
                    )
                )

            stmt = stmt.order_by(asc(SubORM.id))
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def get_active_by_feed_id(self, feed_id: int) -> list[Subscription]:
        """获取指定Feed的所有启用订阅"""
        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(SubORM)
                .where(SubORM.feed_id == feed_id, SubORM.state == 1)
                .order_by(asc(SubORM.id))
            )
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def save(self, subscription: Subscription) -> Subscription:
        """保存订阅"""
        db = get_database()
        async with db.get_session() as session:
            orm = self._to_orm(subscription)
            session.add(orm)
            await session.commit()
            await session.refresh(orm)
            return self._to_entity(orm)

    async def delete(self, subscription: Subscription) -> None:
        """删除订阅"""
        db = get_database()
        async with db.get_session() as session:
            if subscription.id is None:
                return
            db_sub = await session.get(SubORM, subscription.id)
            if db_sub:
                await session.delete(db_sub)
                await session.commit()

    async def delete_all_by_user(self, user_id: str) -> int:
        """删除用户的所有订阅"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(SubORM).where(SubORM.user_id == user_id)
            result = await session.execute(stmt)
            subs = list(result.scalars().all())
            count = len(subs)
            for sub in subs:
                await session.delete(sub)
            if count > 0:
                await session.commit()
            return count

    async def delete_all_by_feed_ids(self, feed_ids: list[int]) -> int:
        """删除指定 Feed 的所有订阅。"""
        ids = sorted({int(feed_id) for feed_id in feed_ids if int(feed_id) > 0})
        if not ids:
            return 0

        db = get_database()
        async with db.get_session() as session:
            stmt = delete(SubORM).where(SubORM.feed_id.in_(ids))
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def update_options(
        self, sub_id: int, user_id: str, **kwargs
    ) -> Subscription | None:
        """更新订阅配置选项"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(SubORM).where(
                SubORM.id == sub_id,
                SubORM.user_id == user_id,
            )
            result = await session.execute(stmt)
            orm = result.scalar_one_or_none()
            if not orm:
                return None
            for key, value in kwargs.items():
                if key == "handlers":
                    orm.handlers = handlers_json(value)
                    continue
                if key == "handlers_mode":
                    orm.handlers_mode = str(value or "").strip().lower()
                    continue
                if hasattr(orm, key):
                    setattr(orm, key, value)
            session.add(orm)
            await session.commit()
            await session.refresh(orm)
            return self._to_entity(orm)

    @staticmethod
    def _to_entity(orm: SubORM) -> Subscription:
        """将 ORM 模型转换为领域实体"""
        return Subscription(
            id=orm.id,
            state=orm.state,
            user_id=orm.user_id,
            feed_id=orm.feed_id,
            title=orm.title,
            tags=orm.tags,
            target_session=orm.target_session,
            platform_name=orm.platform_name,
            interval=orm.interval,
            next_check_time=orm.next_check_time,
            notify=orm.notify,
            send_mode=orm.send_mode,
            handlers_mode=orm.handlers_mode,
            handlers=dump_handlers(orm.handlers),
            length_limit=orm.length_limit,
            display_author=orm.display_author,
            display_via=orm.display_via,
            display_title=orm.display_title,
            display_entry_tags=orm.display_entry_tags,
            style=orm.style,
            display_media=orm.display_media,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _to_orm(sub: Subscription) -> SubORM:
        """将领域实体转换为 ORM 模型"""
        return SubORM(
            id=sub.id,
            state=sub.state,
            user_id=sub.user_id,
            feed_id=sub.feed_id,
            title=sub.title,
            tags=sub.tags,
            target_session=sub.target_session,
            platform_name=sub.platform_name,
            interval=sub.interval,
            next_check_time=sub.next_check_time,
            notify=sub.notify,
            send_mode=sub.send_mode,
            handlers_mode=sub.handlers_mode,
            handlers=handlers_json(sub.get_handlers()),
            length_limit=sub.length_limit,
            display_author=sub.display_author,
            display_via=sub.display_via,
            display_title=sub.display_title,
            display_entry_tags=sub.display_entry_tags,
            style=sub.style,
            display_media=sub.display_media,
            created_at=sub.created_at,
            updated_at=sub.updated_at,
        )


_sub_repo_instance: SubscriptionRepositoryImpl | None = None


def get_subscription_repository() -> SubscriptionRepositoryImpl:
    """获取订阅仓库实例"""
    global _sub_repo_instance
    if _sub_repo_instance is None:
        _sub_repo_instance = SubscriptionRepositoryImpl()
    return _sub_repo_instance
