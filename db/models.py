# ruff: noqa: UP037
"""RSS-to-AstrBot Database Models"""

import os
from datetime import datetime, timedelta
from typing import TypedDict

from sqlalchemy import JSON, Column, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import registry, selectinload
from sqlmodel import Field, Relationship, SQLModel

from ..utils.log_utils import logger
from .migrations import ensure_schema_compat


class FailedQueueStats(TypedDict):
    """Failed notification queue statistics."""

    total: int
    pending: int
    exhausted: int


_plugin_registry = registry()


class RSSHubModel(SQLModel, registry=_plugin_registry):
    pass


INHERIT_VALUE = -100
EFFECTIVE_OPTION_KEYS = (
    "send_mode",
    "length_limit",
    "link_preview",
    "display_author",
    "display_via",
    "display_title",
    "display_entry_tags",
    "style",
    "display_media",
    "translate",
    "translate_target_lang",
)


class User(RSSHubModel, table=True):
    """用户模型，存储用户信息及其默认订阅选项。"""

    __tablename__ = "rsshub_user"
    id: str = Field(default=None, primary_key=True, description="用户ID")
    state: int = Field(
        default=0, description="用户状态: -1=封禁, 0=访客, 1=用户, 100=管理员"
    )

    interval: int | None = Field(default=None, description="监控间隔")
    notify: int = Field(default=1, description="是否通知: 0=禁用, 1=启用")
    send_mode: int = Field(
        default=0, description="发送模式: -1=仅链接, 0=自动, 1=Telegraph, 2=直接消息"
    )
    length_limit: int = Field(default=0, description="长度限制")
    link_preview: int = Field(default=0, description="链接预览: 0=自动, 1=强制启用")
    display_author: int = Field(
        default=0, description="显示作者: -1=禁用, 0=自动, 1=强制"
    )
    display_via: int = Field(
        default=0, description="显示来源: -2=完全禁用, -1=仅链接, 0=自动, 1=强制"
    )
    display_title: int = Field(
        default=0, description="显示标题: -1=禁用, 0=自动, 1=强制"
    )
    display_entry_tags: int = Field(default=-1, description="显示标签")
    style: int = Field(default=0, description="样式: 0=RSStT, 1=flowerss")
    display_media: int = Field(default=0, description="显示媒体: -1=禁用, 0=启用")
    translate: int = Field(
        default=INHERIT_VALUE, description="翻译: -100=继承, 0=禁用, 1=启用"
    )
    translate_target_lang: str | None = Field(
        default=None, max_length=16, description="翻译目标语言"
    )
    default_target_session: str | None = Field(
        default=None,
        max_length=255,
        description="默认推送目标会话(unified_msg_origin)",
    )
    needs_binding_notice: int = Field(default=0, description="是否需要提示绑定推送目标")
    use_user_config: bool = Field(
        default=False,
        description="是否使用用户自身配置: true=使用User表, false=继承全局配置",
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        description="更新时间",
    )

    subs: list["Sub"] = Relationship(back_populates="user")


class Feed(RSSHubModel, table=True):
    """Feed模型，存储RSS源信息。"""

    __tablename__ = "rsshub_feed"
    id: int | None = Field(default=None, primary_key=True)
    state: int = Field(default=1, description="Feed状态: 0=停用, 1=启用")
    link: str = Field(max_length=4096, unique=True, description="Feed链接")
    title: str = Field(max_length=1024, description="Feed标题")
    entry_hashes: list | None = Field(
        default=None, sa_column=Column(JSON), description="条目哈希"
    )
    etag: str | None = Field(default=None, max_length=128, description="ETag")
    last_modified: datetime | None = Field(default=None, description="最后修改时间")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )

    subs: list["Sub"] = Relationship(back_populates="feed")


class Sub(RSSHubModel, table=True):
    """订阅模型，存储用户订阅信息。"""

    __tablename__ = "rsshub_sub"
    id: int | None = Field(default=None, primary_key=True)
    state: int = Field(default=1, description="订阅状态: 0=停用, 1=启用")

    user_id: str = Field(foreign_key="rsshub_user.id", description="用户ID")
    feed_id: int = Field(foreign_key="rsshub_feed.id", description="FeedID")

    title: str = Field(default="", max_length=1024, description="订阅标题")
    tags: str = Field(default="", max_length=255, description="标签")
    target_session: str | None = Field(
        default=None,
        max_length=255,
        description="订阅推送目标会话(unified_msg_origin)",
    )
    platform_name: str | None = Field(
        default=None,
        max_length=64,
        description="平台类型名(如 telegram, aiocqhttp)，用于选择最优发送策略",
    )

    interval: int | None = Field(default=None, description="监控间隔")
    next_check_time: datetime | None = Field(default=None, description="下次检查时间")
    notify: int = Field(default=INHERIT_VALUE, description="是否通知")
    send_mode: int = Field(default=INHERIT_VALUE, description="发送模式")
    length_limit: int = Field(default=INHERIT_VALUE, description="长度限制")
    link_preview: int = Field(default=INHERIT_VALUE, description="链接预览")
    display_author: int = Field(default=INHERIT_VALUE, description="显示作者")
    display_via: int = Field(default=INHERIT_VALUE, description="显示来源")
    display_title: int = Field(default=INHERIT_VALUE, description="显示标题")
    display_entry_tags: int = Field(default=INHERIT_VALUE, description="显示标签")
    style: int = Field(default=INHERIT_VALUE, description="样式")
    display_media: int = Field(default=INHERIT_VALUE, description="显示媒体")
    translate: int = Field(default=INHERIT_VALUE, description="翻译")
    translate_target_lang: str | None = Field(
        default=None, max_length=16, description="翻译目标语言"
    )
    use_sub_config: bool = Field(
        default=False,
        description="是否使用订阅自身配置: true=使用Sub表, false=继承上层",
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )

    user: "User" = Relationship(back_populates="subs")
    feed: "Feed" = Relationship(back_populates="subs")


class TranslationCache(RSSHubModel, table=True):
    """Translation cache for RSS entries."""

    __tablename__ = "rsshub_translation_cache"
    id: int | None = Field(default=None, primary_key=True)
    hash: str = Field(max_length=64, unique=True, index=True, description="原文哈希")
    provider: str = Field(max_length=32, description="翻译器类型")
    target_lang: str = Field(max_length=16, description="目标语言")
    translated_text: str = Field(default="", description="翻译后的文本")
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="创建时间"
    )


class PushHistory(RSSHubModel, table=True):
    """推送历史记录表，记录每次推送的完整信息和状态。"""

    __tablename__ = "rsshub_push_history"
    id: int | None = Field(default=None, primary_key=True)
    sub_id: int = Field(foreign_key="rsshub_sub.id", description="订阅ID")
    user_id: str = Field(foreign_key="rsshub_user.id", description="用户ID")
    feed_id: int = Field(foreign_key="rsshub_feed.id", description="FeedID")

    # 推送内容
    content: str = Field(default="", description="格式化后的消息内容")
    media_urls: list[str] | None = Field(
        default=None, sa_column=Column(JSON), description="媒体URL列表"
    )

    # 条目信息
    entry_title: str = Field(default="", max_length=1024, description="条目标题")
    entry_link: str = Field(default="", max_length=4096, description="条目链接")
    entry_guid: str | None = Field(default=None, max_length=512, description="条目GUID")

    # Feed信息
    feed_title: str = Field(default="", max_length=1024, description="Feed标题")
    feed_link: str = Field(default="", max_length=4096, description="Feed链接")

    # 推送目标
    platform_name: str | None = Field(
        default=None, max_length=64, description="平台名称"
    )
    target_session: str | None = Field(
        default=None, max_length=255, description="目标会话"
    )

    # 推送状态
    status: str | None = Field(
        default=None, max_length=16, description="状态: pending/success/failed"
    )

    # 重试机制
    retry_count: int = Field(default=0, description="重试次数")
    max_retries: int = Field(default=3, description="最大重试次数")
    fail_reason: str | None = Field(
        default=None, max_length=512, description="失败原因"
    )

    # 时间戳
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        description="更新时间",
    )
    completed_at: datetime | None = Field(default=None, description="完成时间")


class MigrationRecord(RSSHubModel, table=True):
    """数据库迁移版本记录表，用于追踪已应用的迁移版本。"""

    __tablename__ = "rsshub_migration_record"
    version: str = Field(primary_key=True, max_length=32, description="迁移版本号")
    applied_at: datetime = Field(
        default_factory=datetime.utcnow, description="应用时间"
    )
    description: str = Field(default="", max_length=256, description="迁移描述")


_engine = None
_session_maker = None


async def init_db(db_path: str) -> None:
    """初始化数据库。"""
    global _engine, _session_maker

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    _session_maker = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with _engine.begin() as conn:
        await conn.run_sync(RSSHubModel.metadata.create_all)
        await ensure_schema_compat(conn)

    logger.info(f"RSS数据库初始化完成: {db_path}")


async def close_db() -> None:
    """关闭数据库连接。"""
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("RSS数据库连接已关闭")


def get_session() -> AsyncSession:
    """获取数据库会话。"""
    if _session_maker is None:
        raise RuntimeError("数据库未初始化")
    return _session_maker()


def resolve_effective_options(
    sub: "Sub",
    user: "User",
    cfg: object | None = None,
) -> dict[str, int | str | None]:
    """解析订阅生效选项（三层配置继承架构）。

    配置优先级：
    1. 如果 sub.use_sub_config = True: 使用 Sub 表配置
    2. 如果 sub.use_sub_config = False 且 user.use_user_config = True: 使用 User 表配置
    3. 如果 sub.use_sub_config = False 且 user.use_user_config = False: 使用全局配置(cfg)

    Args:
        sub: 订阅对象
        user: 用户对象
        cfg: 全局配置对象（ConfigProxy）

    Returns:
        生效的配置选项字典
    """
    from ..config import cfg as global_cfg

    # 如果没有传入 cfg，使用全局 cfg
    if cfg is None:
        cfg = global_cfg

    options: dict[str, int | str | None] = {}

    # notify 不受 use_sub_config 影响，始终从下到上级联继承
    if sub.notify != INHERIT_VALUE:
        options["notify"] = sub.notify
    elif user.use_user_config:
        options["notify"] = user.notify
    elif cfg and hasattr(cfg, "notify"):
        options["notify"] = cfg.notify
    else:
        options["notify"] = user.notify

    for key in EFFECTIVE_OPTION_KEYS:
        if sub.use_sub_config:
            # 使用订阅自身配置
            options[key] = getattr(sub, key)
        elif user.use_user_config:
            # 使用用户配置
            options[key] = getattr(user, key)
        else:
            # 使用全局配置
            if cfg and hasattr(cfg, key):
                options[key] = getattr(cfg, key)
            else:
                # 如果全局配置没有，使用用户配置作为回退
                options[key] = getattr(user, key)
    return options


class SubMethods:
    """Sub辅助方法。"""

    @classmethod
    async def create(
        cls,
        user_id: str,
        feed_id: int,
        target_session: str | None = None,
        platform_name: str | None = None,
    ) -> Sub:
        async with get_session() as session:
            sub = Sub(
                user_id=user_id,
                feed_id=feed_id,
                target_session=target_session,
                platform_name=platform_name,
            )
            session.add(sub)
            await session.commit()
            await session.refresh(sub)
            return sub

    @staticmethod
    async def get_by_user(user_id: str) -> list[Sub]:
        """获取用户的所有订阅（包括禁用状态）"""
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .where(Sub.user_id == user_id)
                .options(selectinload(Sub.feed))
                .order_by(Sub.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    async def get_all_active() -> list[Sub]:
        """Return all active subscriptions across users/sessions (admin scope)."""
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .where(Sub.state == 1)
                .options(selectinload(Sub.feed))
                .order_by(Sub.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    async def get_all_active_paged(
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Sub], int]:
        """Return paged active subscriptions with total count for admin scope."""
        page = max(1, int(page))
        page_size = max(1, int(page_size))
        offset = (page - 1) * page_size

        async with get_session() as session:
            from sqlmodel import select

            total_stmt = select(func.count()).select_from(Sub).where(Sub.state == 1)
            total = int((await session.execute(total_stmt)).scalar_one() or 0)

            stmt = (
                select(Sub)
                .where(Sub.state == 1)
                .options(selectinload(Sub.feed))
                .order_by(Sub.id.asc())
                .offset(offset)
                .limit(page_size)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all()), total

    @staticmethod
    async def get_active_by_feed_id(feed_id: int) -> list[Sub]:
        """Return all active subscriptions for one feed."""
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .where(Sub.feed_id == feed_id, Sub.state == 1)
                .options(selectinload(Sub.feed), selectinload(Sub.user))
                .order_by(Sub.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @classmethod
    async def get_by_id(cls, sub_id: int) -> Sub | None:
        """根据ID查询订阅（包含禁用状态的订阅）"""
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .where(Sub.id == sub_id)
                .options(selectinload(Sub.feed), selectinload(Sub.user))
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @classmethod
    async def get_by_ids(cls, sub_ids: list[int]) -> dict[int, Sub]:
        """Batch load subscriptions by IDs to avoid N+1 queries.

        Args:
            sub_ids: List of subscription IDs

        Returns:
            Mapping of {sub_id: Sub} for found active subscriptions
        """
        if not sub_ids:
            return {}

        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .where(Sub.id.in_(sub_ids), Sub.state == 1)
                .options(selectinload(Sub.feed), selectinload(Sub.user))
            )
            result = await session.execute(stmt)
            subs = result.scalars().all()
            return {sub.id: sub for sub in subs if sub.id is not None}

    @staticmethod
    async def get_by_id_and_user(sub_id: int, user_id: str) -> Sub | None:
        async with get_session() as session:
            from sqlmodel import select

            stmt = select(Sub).where(Sub.id == sub_id, Sub.user_id == user_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def get_by_user_and_link(
        user_id: str,
        feed_link: str,
        target_session: str | None = None,
    ) -> Sub | None:
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .join(Feed)
                .where(Sub.user_id == user_id, Feed.link == feed_link)
            )
            if target_session is not None:
                stmt = stmt.where(Sub.target_session == target_session)
            result = await session.execute(stmt)
            sub = result.scalar_one_or_none()
            if sub and sub.feed_id:
                sub.feed = await session.get(Feed, sub.feed_id)
            return sub

    @staticmethod
    async def get_by_platform_and_link(
        platform_name: str,
        feed_link: str,
        target_session: str | None = None,
    ) -> Sub | None:
        """Get subscription by platform and feed link.

        This method can be used to query subscriptions by platform name and URL.
        """
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .join(Feed)
                .where(
                    Sub.platform_name == platform_name,
                    Sub.state == 1,
                    Feed.link == feed_link,
                )
            )
            if target_session is not None:
                stmt = stmt.where(Sub.target_session == target_session)
            # Order by creation time to get the earliest one
            stmt = stmt.order_by(Sub.created_at.asc())
            result = await session.execute(stmt)
            sub = result.scalar_one_or_none()
            if sub and sub.feed_id:
                sub.feed = await session.get(Feed, sub.feed_id)
            return sub

    @staticmethod
    async def get_by_platform(platform_name: str) -> list[Sub]:
        """Return all active subscriptions for a specific platform."""
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .where(Sub.platform_name == platform_name, Sub.state == 1)
                .options(selectinload(Sub.feed))
                .order_by(Sub.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    async def get_by_platform_paged(
        platform_name: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Sub], int]:
        """Return paged active subscriptions for a specific platform with total count.

        Args:
            platform_name: Platform name to filter by
            page: Page number (1-based)
            page_size: Number of items per page

        Returns:
            Tuple of (subscriptions list, total count)
        """
        page = max(1, int(page))
        page_size = max(1, int(page_size))
        offset = (page - 1) * page_size

        async with get_session() as session:
            from sqlmodel import select

            total_stmt = (
                select(func.count())
                .select_from(Sub)
                .where(Sub.platform_name == platform_name, Sub.state == 1)
            )
            total = int((await session.execute(total_stmt)).scalar_one() or 0)

            stmt = (
                select(Sub)
                .where(Sub.platform_name == platform_name, Sub.state == 1)
                .options(selectinload(Sub.feed))
                .order_by(Sub.id.asc())
                .offset(offset)
                .limit(page_size)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all()), total

    @staticmethod
    async def delete(sub: Sub) -> None:
        async with get_session() as session:
            db_sub = await session.get(Sub, sub.id)
            if db_sub:
                await session.delete(db_sub)
                await session.commit()

    @staticmethod
    async def delete_all_by_user(user_id: str) -> int:
        async with get_session() as session:
            from sqlmodel import select

            stmt = select(Sub).where(Sub.user_id == user_id)
            result = await session.execute(stmt)
            subs = list(result.scalars().all())
            count = len(subs)
            for sub in subs:
                await session.delete(sub)
            if count > 0:
                await session.commit()
            return count

    @staticmethod
    async def update_options(sub_id: int, user_id: str, **kwargs) -> Sub | None:
        async with get_session() as session:
            from sqlmodel import select

            stmt = select(Sub).where(Sub.id == sub_id, Sub.user_id == user_id)
            result = await session.execute(stmt)
            sub = result.scalar_one_or_none()
            if not sub:
                return None
            for key, value in kwargs.items():
                if hasattr(sub, key):
                    setattr(sub, key, value)
            session.add(sub)
            await session.commit()
            await session.refresh(sub)
            return sub


class UserMethods:
    """User辅助方法。"""

    @classmethod
    async def get_or_create(cls, user_id: str) -> User:
        async with get_session() as session:
            user = await session.get(User, user_id)
            if not user:
                user = User(id=user_id)
                session.add(user)
                await session.commit()
                await session.refresh(user)
            return user

    @staticmethod
    async def update_defaults(user_id: str, **kwargs) -> User:
        async with get_session() as session:
            user = await session.get(User, user_id)
            if not user:
                user = User(id=user_id)
            for key, value in kwargs.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    @staticmethod
    async def set_default_target(user_id: str, target_session: str) -> User:
        return await UserMethods.update_defaults(
            user_id,
            default_target_session=target_session,
            needs_binding_notice=0,
        )

    @staticmethod
    async def mark_binding_notice(user_id: str) -> User:
        return await UserMethods.update_defaults(user_id, needs_binding_notice=1)

    @staticmethod
    async def consume_binding_notice(user_id: str) -> bool:
        async with get_session() as session:
            user = await session.get(User, user_id)
            if not user or user.needs_binding_notice == 0:
                return False
            user.needs_binding_notice = 0
            session.add(user)
            await session.commit()
            return True


class FeedMethods:
    """Feed辅助方法。"""

    @classmethod
    async def get_or_create(cls, link: str, title: str = "") -> Feed:
        async with get_session() as session:
            from sqlmodel import select

            stmt = select(Feed).where(Feed.link == link)
            result = await session.execute(stmt)
            feed = result.scalar_one_or_none()

            if not feed:
                feed = Feed(link=link, title=title[:1024] if title else link)
                session.add(feed)
                await session.commit()
                await session.refresh(feed)
            return feed

    @classmethod
    async def get_by_id(cls, feed_id: int) -> Feed | None:
        async with get_session() as session:
            return await session.get(Feed, feed_id)


class PushHistoryMethods:
    """推送历史记录管理方法。"""

    @classmethod
    async def create(
        cls,
        sub_id: int,
        user_id: str,
        feed_id: int,
        content: str,
        media_urls: list[str] | None = None,
        entry_title: str = "",
        entry_link: str = "",
        entry_guid: str | None = None,
        feed_title: str = "",
        feed_link: str = "",
        platform_name: str | None = None,
        target_session: str | None = None,
        status: str = "pending",
        max_retries: int = 3,
    ) -> PushHistory:
        """创建推送历史记录。"""
        async with get_session() as session:
            history = PushHistory(
                sub_id=sub_id,
                user_id=user_id,
                feed_id=feed_id,
                content=content,
                media_urls=media_urls or [],
                entry_title=entry_title,
                entry_link=entry_link,
                entry_guid=entry_guid,
                feed_title=feed_title,
                feed_link=feed_link,
                platform_name=platform_name,
                target_session=target_session,
                status=status,
                max_retries=max_retries,
            )
            session.add(history)
            await session.commit()
            await session.refresh(history)
            return history

    @classmethod
    async def update_status(
        cls,
        history_id: int,
        status: str,
        fail_reason: str | None = None,
        http_status: int | None = None,
        response_detail: str | None = None,
    ) -> PushHistory | None:
        """更新推送状态。

        Args:
            history_id: 推送历史记录ID
            status: 推送状态 (success/failed/pending)
            fail_reason: 失败原因（可选）
            http_status: HTTP状态码（可选，用于兼容性）
            response_detail: 响应详情（可选，用于兼容性）
        """
        from datetime import datetime

        async with get_session() as session:
            history = await session.get(PushHistory, history_id)
            if not history:
                return None

            history.status = status
            if fail_reason is not None:
                history.fail_reason = fail_reason
            # http_status and response_detail are accepted for compatibility
            # but not stored in current schema (no corresponding columns)

            if status in ("success", "failed"):
                history.completed_at = datetime.utcnow()

            session.add(history)
            await session.commit()
            await session.refresh(history)
            return history

    @classmethod
    async def increment_retry(
        cls,
        history_id: int,
        fail_reason: str | None = None,
    ) -> PushHistory | None:
        """增加重试次数并更新失败原因。"""
        async with get_session() as session:
            history = await session.get(PushHistory, history_id)
            if not history:
                return None

            history.retry_count += 1
            if fail_reason:
                history.fail_reason = fail_reason
            session.add(history)
            await session.commit()
            await session.refresh(history)
            return history

    @staticmethod
    async def get_pending_for_retry(
        limit: int = 100,
    ) -> list[PushHistory]:
        """获取需要重试的推送记录（status=failed 且 retry_count < max_retries）。"""
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(PushHistory)
                .where(
                    PushHistory.status == "failed",
                    PushHistory.retry_count < PushHistory.max_retries,
                )
                .order_by(PushHistory.created_at.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    async def get_by_sub(
        sub_id: int,
        limit: int | None = None,
        status: str | None = None,
    ) -> list[PushHistory]:
        """获取订阅的推送历史。"""
        async with get_session() as session:
            from sqlmodel import select

            stmt = select(PushHistory).where(PushHistory.sub_id == sub_id)
            if status:
                stmt = stmt.where(PushHistory.status == status)
            stmt = stmt.order_by(PushHistory.created_at.desc())
            if limit:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    async def delete_old_records(days: int = 30) -> int:
        """删除指定天数前的历史记录。"""
        from datetime import datetime

        from sqlalchemy import delete

        cutoff_date = datetime.utcnow() - timedelta(days=days)

        async with get_session() as session:
            stmt = (
                delete(PushHistory)
                .where(PushHistory.created_at < cutoff_date)
                .execution_options(synchronize_session=False)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    @staticmethod
    async def get_stats() -> dict[str, int]:
        """获取推送统计信息。"""
        async with get_session() as session:
            from sqlmodel import func, select

            # 总数
            total_stmt = select(func.count()).select_from(PushHistory)
            total = (await session.execute(total_stmt)).scalar_one() or 0

            # 按状态统计
            status_counts = {}
            for status in ["pending", "success", "failed"]:
                stmt = (
                    select(func.count())
                    .select_from(PushHistory)
                    .where(PushHistory.status == status)
                )
                count = (await session.execute(stmt)).scalar_one() or 0
                status_counts[status] = int(count)

            return {
                "total": int(total),
                **status_counts,
            }


class TranslationCacheMethods:
    """Translation cache helper methods."""

    @staticmethod
    async def get_by_hash(hash: str) -> TranslationCache | None:
        """Get cached translation by hash."""
        async with get_session() as session:
            from sqlmodel import select

            stmt = select(TranslationCache).where(TranslationCache.hash == hash)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @classmethod
    async def save(
        cls,
        hash: str,
        provider: str,
        target_lang: str,
        translated_text: str,
    ) -> TranslationCache:
        """Save or update translation cache."""
        async with get_session() as session:
            from sqlmodel import select

            # Try to get existing
            stmt = select(TranslationCache).where(TranslationCache.hash == hash)
            result = await session.execute(stmt)
            cache = result.scalar_one_or_none()

            if cache:
                # Update existing
                cache.translated_text = translated_text
                cache.provider = provider
                cache.target_lang = target_lang
            else:
                # Create new
                cache = TranslationCache(
                    hash=hash,
                    provider=provider,
                    target_lang=target_lang,
                    translated_text=translated_text,
                )
                session.add(cache)

            await session.commit()
            await session.refresh(cache)
            return cache

    @staticmethod
    async def delete_by_hash(hash: str) -> bool:
        """Delete cache entry by hash."""
        async with get_session() as session:
            cache = await session.get(TranslationCache, hash)
            if cache:
                await session.delete(cache)
                await session.commit()
                return True
            return False

    @staticmethod
    async def cleanup_old_entries(limit: int = 5000) -> int:
        """Clean up old translation cache entries beyond limit.

        Args:
            limit: Maximum number of entries to keep

        Returns:
            Number of deleted entries
        """
        async with get_session() as session:
            from sqlalchemy import delete
            from sqlmodel import select

            # Get count
            count_stmt = select(func.count()).select_from(TranslationCache)
            total = (await session.execute(count_stmt)).scalar_one() or 0

            if total <= limit:
                return 0

            # Delete oldest entries
            to_delete = total - limit
            subq = (
                select(TranslationCache.id)
                .order_by(TranslationCache.created_at.asc())
                .limit(to_delete)
                .subquery()
            )
            delete_stmt = (
                delete(TranslationCache)
                .where(TranslationCache.id.in_(subq))
                .execution_options(synchronize_session=False)
            )
            result = await session.execute(delete_stmt)
            await session.commit()
            return result.rowcount or 0


class WebUIMethods:
    """Helper methods used by plugin webui."""

    @staticmethod
    async def list_subscriptions(limit: int = 500) -> list[Sub]:
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .where(Sub.state == 1)
                .options(selectinload(Sub.feed), selectinload(Sub.user))
                .order_by(Sub.id.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    async def get_subscription(sub_id: int) -> Sub | None:
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .where(Sub.id == sub_id, Sub.state == 1)
                .options(selectinload(Sub.feed), selectinload(Sub.user))
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def delete_subscription(sub_id: int) -> bool:
        async with get_session() as session:
            row = await session.get(Sub, sub_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


User.get_or_create = staticmethod(UserMethods.get_or_create)
User.update_defaults = staticmethod(UserMethods.update_defaults)
User.set_default_target = staticmethod(UserMethods.set_default_target)
User.mark_binding_notice = staticmethod(UserMethods.mark_binding_notice)
User.consume_binding_notice = staticmethod(UserMethods.consume_binding_notice)
Feed.get_or_create = staticmethod(FeedMethods.get_or_create)
Feed.get_by_id = staticmethod(FeedMethods.get_by_id)
Sub.create = staticmethod(SubMethods.create)
Sub.get_by_user = staticmethod(SubMethods.get_by_user)
Sub.get_all_active = staticmethod(SubMethods.get_all_active)
Sub.get_all_active_paged = staticmethod(SubMethods.get_all_active_paged)
Sub.get_active_by_feed_id = staticmethod(SubMethods.get_active_by_feed_id)
Sub.get_by_id = staticmethod(SubMethods.get_by_id)
Sub.get_by_ids = staticmethod(SubMethods.get_by_ids)
Sub.get_by_id_and_user = staticmethod(SubMethods.get_by_id_and_user)
Sub.get_by_user_and_link = staticmethod(SubMethods.get_by_user_and_link)
Sub.get_by_platform_and_link = staticmethod(SubMethods.get_by_platform_and_link)
Sub.get_by_platform = staticmethod(SubMethods.get_by_platform)
Sub.get_by_platform_paged = staticmethod(SubMethods.get_by_platform_paged)
Sub.delete = staticmethod(SubMethods.delete)
Sub.delete_all_by_user = staticmethod(SubMethods.delete_all_by_user)
Sub.update_options = staticmethod(SubMethods.update_options)
Sub.resolve_effective_options = staticmethod(resolve_effective_options)
Sub.list_for_webui = staticmethod(WebUIMethods.list_subscriptions)
Sub.get_for_webui = staticmethod(WebUIMethods.get_subscription)
Sub.delete_for_webui = staticmethod(WebUIMethods.delete_subscription)
PushHistory.create = staticmethod(PushHistoryMethods.create)
PushHistory.update_status = staticmethod(PushHistoryMethods.update_status)
PushHistory.increment_retry = staticmethod(PushHistoryMethods.increment_retry)
PushHistory.get_pending_for_retry = staticmethod(
    PushHistoryMethods.get_pending_for_retry
)
PushHistory.get_by_sub = staticmethod(PushHistoryMethods.get_by_sub)
PushHistory.delete_old_records = staticmethod(PushHistoryMethods.delete_old_records)
PushHistory.get_stats = staticmethod(PushHistoryMethods.get_stats)
TranslationCache.get_by_hash = staticmethod(TranslationCacheMethods.get_by_hash)
TranslationCache.save = staticmethod(TranslationCacheMethods.save)
TranslationCache.delete_by_hash = staticmethod(TranslationCacheMethods.delete_by_hash)
TranslationCache.cleanup_old_entries = staticmethod(
    TranslationCacheMethods.cleanup_old_entries
)
