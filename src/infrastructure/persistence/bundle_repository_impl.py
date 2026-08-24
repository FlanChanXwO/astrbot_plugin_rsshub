"""Bundle owner 与有序成员的 SQLite 仓储实现。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, text, update
from sqlmodel import asc, or_, select

from ...domain.entities.bundle import Bundle
from ...domain.entities.bundle_feed import BundleFeed
from ...domain.entities.delivery import DeliveryOwner
from ...domain.entities.handlers import dump_handlers, handlers_json
from ...domain.repositories.delivery_repository import (
    DeliveryOwnerNotFoundError,
    DeliveryRepository,
)
from .database import DatabaseManager, get_database
from .delivery_repository_impl import DeliveryRepositoryImpl
from .models import BundleFeedORM, BundleORM, FeedORM


class BundleRepositoryImpl:
    """Bundle owner/member 的持久化实现。"""

    def __init__(
        self,
        database: DatabaseManager | None = None,
        *,
        delivery_repository: DeliveryRepository | None = None,
    ) -> None:
        self._database = database
        self._delivery_repository = delivery_repository

    @property
    def _db(self) -> DatabaseManager:
        return self._database or get_database()

    @property
    def _delivery(self) -> DeliveryRepository:
        return self._delivery_repository or DeliveryRepositoryImpl(self._db)

    async def get_by_id(self, bundle_id: int) -> Bundle | None:
        async with self._db.get_session() as session:
            orm = await session.get(BundleORM, bundle_id)
            return self._to_entity(orm) if orm else None

    async def get_by_user(self, user_id: str) -> list[Bundle]:
        async with self._db.get_session() as session:
            result = await session.execute(
                select(BundleORM)
                .where(BundleORM.user_id == user_id)
                .order_by(asc(BundleORM.id))
            )
            return [self._to_entity(orm) for orm in result.scalars().all()]

    async def get_all_active(self) -> list[Bundle]:
        async with self._db.get_session() as session:
            result = await session.execute(
                select(BundleORM)
                .where(BundleORM.state == 1)
                .order_by(asc(BundleORM.id))
            )
            return [self._to_entity(orm) for orm in result.scalars().all()]

    async def list_due(self, now: datetime) -> list[Bundle]:
        async with self._db.get_session() as session:
            result = await session.execute(
                select(BundleORM)
                .where(
                    BundleORM.state == 1,
                    or_(
                        BundleORM.next_check_time.is_(None),
                        BundleORM.next_check_time <= now,
                    ),
                )
                .order_by(asc(BundleORM.next_check_time), asc(BundleORM.id))
            )
            return [self._to_entity(orm) for orm in result.scalars().all()]

    async def update_next_check_time(
        self,
        bundle_id: int,
        next_check_time: datetime,
    ) -> Bundle | None:
        """只更新仍启用 Bundle 的计划时间，避免覆盖并发状态变更。"""
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                result = await session.execute(
                    update(BundleORM)
                    .where(BundleORM.id == bundle_id, BundleORM.state == 1)
                    .values(next_check_time=next_check_time)
                )
                await session.commit()
                if not result.rowcount:
                    return None
                orm = await session.get(BundleORM, bundle_id)
                return self._to_entity(orm) if orm is not None else None
            except BaseException:
                await session.rollback()
                raise

    async def save(self, bundle: Bundle) -> Bundle:
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                if bundle.id is not None:
                    orm = await session.get(BundleORM, bundle.id)
                else:
                    orm = None

                if bundle.state == 1:
                    member_count = (
                        int(
                            (
                                await session.execute(
                                    select(func.count())
                                    .select_from(BundleFeedORM)
                                    .where(BundleFeedORM.bundle_id == bundle.id)
                                )
                            ).scalar_one()
                        )
                        if bundle.id is not None
                        else 0
                    )
                    if member_count < 2:
                        raise ValueError("启用 Bundle 至少需要两个不同 Feed")
                    if bundle.next_check_time is None:
                        # 启用时立即建立滚动计划；Scheduler 后续只沿既有计划点推进。
                        bundle.next_check_time = datetime.now(timezone.utc)

                if orm is None:
                    orm = self._to_orm(bundle)
                    session.add(orm)
                else:
                    self._apply_entity(orm, bundle)
                await session.commit()
                await session.refresh(orm)
                return self._to_entity(orm)
            except BaseException:
                await session.rollback()
                raise

    async def delete(self, bundle_id: int) -> bool:
        return await self._delivery.delete_owner(
            DeliveryOwner(owner_type="bundle", owner_id=bundle_id)
        )

    async def list_members(self, bundle_id: int) -> list[BundleFeed]:
        async with self._db.get_session() as session:
            result = await session.execute(
                select(BundleFeedORM)
                .where(BundleFeedORM.bundle_id == bundle_id)
                .order_by(asc(BundleFeedORM.position), asc(BundleFeedORM.id))
            )
            return [self._to_member_entity(orm) for orm in result.scalars().all()]

    async def add_member(
        self,
        bundle_id: int,
        feed_id: int,
        *,
        position: int | None = None,
    ) -> BundleFeed:
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                bundle = await session.get(BundleORM, bundle_id)
                if bundle is None:
                    raise DeliveryOwnerNotFoundError(
                        f"Bundle owner 不存在: {bundle_id}"
                    )
                if await session.get(FeedORM, feed_id) is None:
                    raise ValueError(f"Feed 不存在: {feed_id}")

                result = await session.execute(
                    select(BundleFeedORM)
                    .where(BundleFeedORM.bundle_id == bundle_id)
                    .order_by(asc(BundleFeedORM.position), asc(BundleFeedORM.id))
                )
                members = list(result.scalars().all())
                if feed_id in {member.feed_id for member in members}:
                    raise ValueError("Bundle 成员 Feed 不能重复")
                insert_position = len(members) if position is None else position
                if insert_position < 0 or insert_position > len(members):
                    raise ValueError("Bundle 成员 position 超出范围")

                offset = len(members) + 1
                for index, member in enumerate(members):
                    member.position = offset + index
                await session.flush()
                new_member = BundleFeedORM(
                    bundle_id=bundle_id,
                    feed_id=feed_id,
                    position=offset + len(members),
                )
                session.add(new_member)
                await session.flush()
                ordered_members = [
                    *members[:insert_position],
                    new_member,
                    *members[insert_position:],
                ]
                for index, member in enumerate(ordered_members):
                    member.position = index
                await session.commit()
                await session.refresh(new_member)
                return self._to_member_entity(new_member)
            except BaseException:
                await session.rollback()
                raise

    async def replace_members(
        self,
        bundle_id: int,
        feed_ids: Sequence[int],
    ) -> list[BundleFeed]:
        await self._delivery.replace_bundle_members(bundle_id, feed_ids)
        return await self.list_members(bundle_id)

    async def remove_member(self, bundle_feed_id: int) -> bool:
        return await self._delivery.remove_bundle_member(bundle_feed_id)

    async def move_member(self, bundle_feed_id: int, position: int) -> list[BundleFeed]:
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                member = await session.get(BundleFeedORM, bundle_feed_id)
                if member is None:
                    await session.commit()
                    return []
                result = await session.execute(
                    select(BundleFeedORM)
                    .where(BundleFeedORM.bundle_id == member.bundle_id)
                    .order_by(asc(BundleFeedORM.position), asc(BundleFeedORM.id))
                )
                members = list(result.scalars().all())
                if position < 0 or position >= len(members):
                    raise ValueError("Bundle 成员 position 超出范围")
                ordered_members = [
                    item for item in members if item.id != bundle_feed_id
                ]
                moving_member = next(
                    item for item in members if item.id == bundle_feed_id
                )
                ordered_members.insert(position, moving_member)

                offset = len(members) + 1
                for index, item in enumerate(members):
                    item.position = offset + index
                await session.flush()
                for index, item in enumerate(ordered_members):
                    item.position = index
                await session.commit()
                return [self._to_member_entity(item) for item in ordered_members]
            except BaseException:
                await session.rollback()
                raise

    @staticmethod
    def _to_entity(orm: BundleORM) -> Bundle:
        return Bundle(
            id=orm.id,
            user_id=orm.user_id,
            name=orm.name,
            target_sessions=orm.target_sessions,
            interval=orm.interval,
            state=orm.state,
            next_check_time=orm.next_check_time,
            notify=orm.notify,
            send_mode=orm.send_mode,
            length_limit=orm.length_limit,
            display_author=orm.display_author,
            display_via=orm.display_via,
            display_title=orm.display_title,
            display_entry_tags=orm.display_entry_tags,
            style=orm.style,
            display_media=orm.display_media,
            handlers=dump_handlers(orm.handlers),
            send_card=orm.send_card,
            template_id=orm.template_id,
            card_send_original_content=orm.card_send_original_content,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _to_member_entity(orm: BundleFeedORM) -> BundleFeed:
        return BundleFeed(
            id=orm.id,
            bundle_id=orm.bundle_id,
            feed_id=orm.feed_id,
            position=orm.position,
            entry_hashes=orm.entry_hashes,
            etag=orm.etag,
            last_modified=orm.last_modified,
            last_check_status=orm.last_check_status,
            last_checked_at=orm.last_checked_at,
        )

    @staticmethod
    def _to_orm(bundle: Bundle) -> BundleORM:
        return BundleORM(
            id=bundle.id,
            user_id=bundle.user_id,
            name=bundle.name,
            target_sessions=bundle.target_sessions,
            interval=bundle.interval,
            state=bundle.state,
            next_check_time=bundle.next_check_time,
            notify=bundle.notify,
            send_mode=bundle.send_mode,
            length_limit=bundle.length_limit,
            display_author=bundle.display_author,
            display_via=bundle.display_via,
            display_title=bundle.display_title,
            display_entry_tags=bundle.display_entry_tags,
            style=bundle.style,
            display_media=bundle.display_media,
            handlers=handlers_json(bundle.handlers),
            send_card=bundle.send_card,
            template_id=bundle.template_id,
            card_send_original_content=bundle.card_send_original_content,
            created_at=bundle.created_at,
            updated_at=bundle.updated_at,
        )

    @staticmethod
    def _apply_entity(orm: BundleORM, bundle: Bundle) -> None:
        values = BundleRepositoryImpl._to_orm(bundle)
        for field in (
            "user_id",
            "name",
            "target_sessions",
            "interval",
            "state",
            "next_check_time",
            "notify",
            "send_mode",
            "length_limit",
            "display_author",
            "display_via",
            "display_title",
            "display_entry_tags",
            "style",
            "display_media",
            "handlers",
            "send_card",
            "template_id",
            "card_send_original_content",
            "created_at",
            "updated_at",
        ):
            setattr(orm, field, getattr(values, field))


_bundle_repository: BundleRepositoryImpl | None = None


def get_bundle_repository() -> BundleRepositoryImpl:
    """返回进程内共享的 Bundle 仓储。"""
    global _bundle_repository
    if _bundle_repository is None:
        _bundle_repository = BundleRepositoryImpl()
    return _bundle_repository
