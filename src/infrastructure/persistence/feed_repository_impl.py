"""Feed 仓库实现

基于 SQLModel/SQLAlchemy 实现 FeedRepository 接口。
负责 Feed 实体的持久化操作。
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import select

from ...domain.entities.feed import Feed
from ...domain.repositories.feed_repository import FeedRepository
from ..utils import get_logger
from .database import get_database
from .models import FeedORM

logger = get_logger()


class FeedRepositoryImpl:
    """Feed 仓库实现类"""

    async def get_by_id(self, feed_id: int) -> Feed | None:
        """根据ID获取Feed"""
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(FeedORM, feed_id)
            return self._to_entity(orm) if orm else None

    async def get_by_ids(self, feed_ids: list[int]) -> list[Feed]:
        """根据ID批量获取Feed"""
        ids = list(dict.fromkeys(feed_ids))
        if not ids:
            return []

        db = get_database()
        async with db.get_session() as session:
            stmt = select(FeedORM).where(FeedORM.id.in_(ids))
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def get_by_link(self, link: str) -> Feed | None:
        """根据链接获取Feed"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(FeedORM).where(FeedORM.link == link)
            result = await session.execute(stmt)
            orm = result.scalar_one_or_none()
            return self._to_entity(orm) if orm else None

    async def get_or_create(self, link: str, title: str = "") -> Feed:
        """获取或创建Feed"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(FeedORM).where(FeedORM.link == link)
            result = await session.execute(stmt)
            orm = result.scalar_one_or_none()

            if not orm:
                orm = FeedORM(link=link, title=title[:1024] if title else link)
                session.add(orm)
                await session.commit()
                await session.refresh(orm)
                logger.info("创建新Feed: %s", link)

            return self._to_entity(orm)

    async def save(self, feed: Feed) -> Feed:
        """保存Feed"""
        db = get_database()
        async with db.get_session() as session:
            orm: FeedORM | None = None

            # Update existing row when ID already exists; avoid duplicate PK insert.
            if feed.id is not None:
                orm = await session.get(FeedORM, feed.id)
                if orm is not None:
                    orm.state = feed.state
                    orm.link = feed.link
                    orm.title = feed.title
                    orm.entry_hashes = feed.entry_hashes
                    orm.etag = feed.etag
                    orm.last_modified = feed.last_modified
                    orm.created_at = feed.created_at
                    orm.updated_at = feed.updated_at

            if orm is None:
                orm = self._to_orm(feed)
                session.add(orm)

            await session.commit()
            await session.refresh(orm)
            return self._to_entity(orm)

    async def get_all(self) -> list[Feed]:
        """获取所有Feed"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(FeedORM)
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def get_all_active(self) -> list[Feed]:
        """获取所有启用的Feed"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(FeedORM).where(FeedORM.state == 1)
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def delete_many(self, feed_ids: list[int]) -> int:
        """批量删除 Feed。"""
        ids = sorted({int(feed_id) for feed_id in feed_ids if int(feed_id) > 0})
        if not ids:
            return 0

        db = get_database()
        async with db.get_session() as session:
            stmt = delete(FeedORM).where(FeedORM.id.in_(ids))
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    @staticmethod
    def _to_entity(orm: FeedORM) -> Feed:
        """将 ORM 模型转换为领域实体"""
        return Feed(
            id=orm.id,
            state=orm.state,
            link=orm.link,
            title=orm.title,
            entry_hashes=orm.entry_hashes,
            etag=orm.etag,
            last_modified=orm.last_modified,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _to_orm(feed: Feed) -> FeedORM:
        """将领域实体转换为 ORM 模型"""
        return FeedORM(
            id=feed.id,
            state=feed.state,
            link=feed.link,
            title=feed.title,
            entry_hashes=feed.entry_hashes,
            etag=feed.etag,
            last_modified=feed.last_modified,
            created_at=feed.created_at,
            updated_at=feed.updated_at,
        )


_feed_repo_instance: FeedRepositoryImpl | None = None


def get_feed_repository() -> FeedRepository:
    """获取 Feed 仓库实例"""
    global _feed_repo_instance
    if _feed_repo_instance is None:
        _feed_repo_instance = FeedRepositoryImpl()
    return _feed_repo_instance
