# ruff: noqa: UP037
"""RSS-to-AstrBot Database Models
基于 RSS-to-Telegram-Bot 移植，使用 SQLModel 替代 tortoise-orm
"""

import os
from datetime import datetime

from sqlalchemy import JSON, Column, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import registry, selectinload
from sqlmodel import Field, Relationship, SQLModel

from astrbot.api import logger

_plugin_registry = registry()


class RSSHubModel(SQLModel, registry=_plugin_registry):
    pass


INHERIT_VALUE = -100
EFFECTIVE_OPTION_KEYS = (
    "notify",
    "send_mode",
    "length_limit",
    "link_preview",
    "display_author",
    "display_via",
    "display_title",
    "display_entry_tags",
    "style",
    "display_media",
)


async def _get_column_type(conn, table: str, column: str) -> str:
    """获取指定表的列类型"""
    rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
    for row in rows:
        if row[1] == column:
            return row[2].upper()
    return ""


class User(RSSHubModel, table=True):
    """用户模型，存储用户信息及其默认订阅选项。"""

    __tablename__ = "rsshub_user"
    id: str = Field(default=None, primary_key=True, description="用户ID")
    state: int = Field(
        default=0, description="用户状态: -1=封禁, 0=访客, 1=用户, 100=管理员"
    )
    lang: str = Field(default="zh-Hans", max_length=16, description="偏好语言")
    sub_limit: int | None = Field(default=None, description="订阅数量限制")

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
    default_target_session: str | None = Field(
        default=None,
        max_length=255,
        description="默认推送目标会话(unified_msg_origin)",
    )
    needs_binding_notice: int = Field(default=0, description="是否需要提示绑定推送目标")

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
    interval: int | None = Field(default=None, description="监控间隔")
    entry_hashes: list[str] | None = Field(
        default=None, sa_column=Column(JSON), description="条目哈希"
    )
    etag: str | None = Field(default=None, max_length=128, description="ETag")
    last_modified: datetime | None = Field(default=None, description="最后修改时间")
    error_count: int = Field(default=0, description="错误计数")
    next_check_time: datetime | None = Field(default=None, description="下次检查时间")

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

    title: str | None = Field(default=None, max_length=1024, description="订阅标题")
    tags: str | None = Field(default=None, max_length=255, description="标签")
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

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )

    user: "User" = Relationship(back_populates="subs")
    feed: "Feed" = Relationship(back_populates="subs")


class MonitorSchedule(RSSHubModel, table=True):
    """Per-subscription monitor schedule state for interval-based polling."""

    __tablename__ = "rsshub_monitor_schedule"
    sub_id: int = Field(default=None, primary_key=True, description="Subscription ID")
    next_check_time: datetime | None = Field(
        default=None, description="Next check time"
    )
    error_count: int = Field(default=0, description="Consecutive error count")
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class FailedNotification(RSSHubModel, table=True):
    """Failed notification queue for retry when platform is unavailable."""

    __tablename__ = "rsshub_failed_notification"
    id: int | None = Field(default=None, primary_key=True)
    sub_id: int = Field(foreign_key="rsshub_sub.id", description="Subscription ID")
    user_id: str = Field(foreign_key="rsshub_user.id", description="User ID")

    # Message content (JSON serialized)
    content: str = Field(default="", description="Message content")
    media_urls: list[str] | None = Field(
        default=None, sa_column=Column(JSON), description="Media URLs"
    )
    entry_title: str | None = Field(
        default=None, max_length=1024, description="Entry title"
    )
    entry_link: str | None = Field(
        default=None, max_length=4096, description="Entry link"
    )

    # Context info
    feed_title: str | None = Field(
        default=None, max_length=1024, description="Feed title"
    )
    feed_link: str | None = Field(
        default=None, max_length=4096, description="Feed link"
    )
    platform_name: str | None = Field(
        default=None, max_length=64, description="Platform name"
    )
    target_session: str | None = Field(
        default=None, max_length=255, description="Target session"
    )

    # Options (JSON serialized)
    options: dict | None = Field(
        default=None, sa_column=Column(JSON), description="Subscription options"
    )

    # Retry tracking
    retry_count: int = Field(default=0, description="Retry attempts")
    fail_reason: str | None = Field(
        default=None, max_length=255, description="Last failure reason"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="First failure time"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        description="Last retry time",
    )


class Option(RSSHubModel, table=True):
    """选项模型，存储管理员设置的选项。"""

    __tablename__ = "rsshub_option"
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(max_length=255, unique=True, description="选项键")
    value: str | None = Field(default=None, description="选项值")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


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
        await _ensure_schema_compat(conn)

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
) -> dict[str, int]:
    """解析订阅生效选项：订阅值优先，-100 继承用户默认。"""
    options: dict[str, int] = {}
    for key in EFFECTIVE_OPTION_KEYS:
        sub_val = getattr(sub, key)
        options[key] = getattr(user, key) if sub_val == INHERIT_VALUE else sub_val
    return options


async def _ensure_schema_compat(conn) -> None:
    """为旧数据库补齐迁移过程尚未纳入的新增列，并处理 user_id 类型迁移。"""

    async def _has_column(table: str, column: str) -> bool:
        rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
        return any(row[1] == column for row in rows)

    # 新增列兼容（旧版本迁移）
    if not await _has_column("rsshub_sub", "target_session"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_sub ADD COLUMN target_session TEXT"
        )

    if not await _has_column("rsshub_user", "default_target_session"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_user ADD COLUMN default_target_session TEXT"
        )

    if not await _has_column("rsshub_user", "needs_binding_notice"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_user ADD COLUMN needs_binding_notice INTEGER NOT NULL DEFAULT 0"
        )

    if not await _has_column("rsshub_sub", "platform_name"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_sub ADD COLUMN platform_name TEXT"
        )

    # User ID 类型迁移: INTEGER -> TEXT
    await _migrate_user_id_to_text(conn)


async def _migrate_user_id_to_text(conn) -> None:
    """将 user_id 列从 INTEGER 迁移到 TEXT 类型。

    SQLite 不支持直接 ALTER COLUMN，需要重建表。
    """

    async def _table_exists(table: str) -> bool:
        result = await conn.exec_driver_sql(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
        )
        return result.fetchone() is not None

    # 检查 rsshub_user.id 列类型
    if not await _table_exists("rsshub_user"):
        return

    user_id_type = await _get_column_type(conn, "rsshub_user", "id")
    if user_id_type == "TEXT":
        # 已经是 TEXT 类型，无需迁移
        return

    if user_id_type != "INTEGER":
        logger.warning(f"rsshub_user.id 列类型为 {user_id_type}，无法自动迁移到 TEXT")
        return

    logger.info("开始迁移 user_id 从 INTEGER 到 TEXT...")

    # 使用 SQLAlchemy 事务上下文管理器
    async with conn.begin():
        try:
            # 1. 创建新表
            await conn.exec_driver_sql("""
                CREATE TABLE rsshub_user_new (
                    id TEXT PRIMARY KEY,
                    state INTEGER NOT NULL DEFAULT 0,
                    lang TEXT NOT NULL DEFAULT 'zh-Hans',
                    sub_limit INTEGER,
                    interval INTEGER,
                    notify INTEGER NOT NULL DEFAULT 1,
                    send_mode INTEGER NOT NULL DEFAULT 0,
                    length_limit INTEGER NOT NULL DEFAULT 0,
                    link_preview INTEGER NOT NULL DEFAULT 0,
                    display_author INTEGER NOT NULL DEFAULT 0,
                    display_via INTEGER NOT NULL DEFAULT 0,
                    display_title INTEGER NOT NULL DEFAULT 0,
                    display_entry_tags INTEGER NOT NULL DEFAULT -1,
                    style INTEGER NOT NULL DEFAULT 0,
                    display_media INTEGER NOT NULL DEFAULT 0,
                    default_target_session TEXT,
                    needs_binding_notice INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. 迁移数据
            await conn.exec_driver_sql("""
                INSERT INTO rsshub_user_new
                SELECT CAST(id AS TEXT), state, lang, sub_limit, interval, notify, send_mode,
                       length_limit, link_preview, display_author, display_via, display_title,
                       display_entry_tags, style, display_media, default_target_session,
                       needs_binding_notice, created_at, updated_at
                FROM rsshub_user
            """)

            # 3. 删除旧表，重命名新表
            await conn.exec_driver_sql("DROP TABLE rsshub_user")
            await conn.exec_driver_sql("ALTER TABLE rsshub_user_new RENAME TO rsshub_user")

            logger.info("rsshub_user 表迁移完成")

            # 迁移 rsshub_sub 表
            # 1. 创建新表
            await conn.exec_driver_sql("""
                CREATE TABLE rsshub_sub_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    state INTEGER NOT NULL DEFAULT 1,
                    user_id TEXT NOT NULL,
                    feed_id INTEGER NOT NULL,
                    title TEXT,
                    tags TEXT,
                    target_session TEXT,
                    platform_name TEXT,
                    interval INTEGER,
                    notify INTEGER NOT NULL DEFAULT -100,
                    send_mode INTEGER NOT NULL DEFAULT -100,
                    length_limit INTEGER NOT NULL DEFAULT -100,
                    link_preview INTEGER NOT NULL DEFAULT -100,
                    display_author INTEGER NOT NULL DEFAULT -100,
                    display_via INTEGER NOT NULL DEFAULT -100,
                    display_title INTEGER NOT NULL DEFAULT -100,
                    display_entry_tags INTEGER NOT NULL DEFAULT -100,
                    style INTEGER NOT NULL DEFAULT -100,
                    display_media INTEGER NOT NULL DEFAULT -100,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES rsshub_user (id),
                    FOREIGN KEY (feed_id) REFERENCES rsshub_feed (id)
                )
            """)

            # 2. 迁移数据
            await conn.exec_driver_sql("""
                INSERT INTO rsshub_sub_new
                SELECT id, state, CAST(user_id AS TEXT), feed_id, title, tags, target_session,
                       platform_name, interval, notify, send_mode, length_limit, link_preview,
                       display_author, display_via, display_title, display_entry_tags, style,
                       display_media, created_at, updated_at
                FROM rsshub_sub
            """)

            # 3. 删除旧表，重命名新表
            await conn.exec_driver_sql("DROP TABLE rsshub_sub")
            await conn.exec_driver_sql("ALTER TABLE rsshub_sub_new RENAME TO rsshub_sub")

            logger.info("rsshub_sub 表迁移完成")

            # 迁移 rsshub_failed_notification 表
            # 1. 创建新表
            await conn.exec_driver_sql("""
                CREATE TABLE rsshub_failed_notification_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sub_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    media_urls TEXT,
                    entry_title TEXT,
                    entry_link TEXT,
                    feed_title TEXT,
                    feed_link TEXT,
                    platform_name TEXT,
                    target_session TEXT,
                    options TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    fail_reason TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sub_id) REFERENCES rsshub_sub (id),
                    FOREIGN KEY (user_id) REFERENCES rsshub_user (id)
                )
            """)

            # 2. 迁移数据
            await conn.exec_driver_sql("""
                INSERT INTO rsshub_failed_notification_new
                SELECT id, sub_id, CAST(user_id AS TEXT), content, media_urls, entry_title,
                       entry_link, feed_title, feed_link, platform_name, target_session,
                       options, retry_count, fail_reason, created_at, updated_at
                FROM rsshub_failed_notification
            """)

            # 3. 删除旧表，重命名新表
            await conn.exec_driver_sql("DROP TABLE rsshub_failed_notification")
            await conn.exec_driver_sql(
                "ALTER TABLE rsshub_failed_notification_new RENAME TO rsshub_failed_notification"
            )

            logger.info("rsshub_failed_notification 表迁移完成")

        except Exception:
            # 事务会自动回滚，只需重新抛出异常
            logger.error("user_id 类型迁移失败，事务已回滚")
            raise

    logger.info("user_id 类型迁移完成 (INTEGER -> TEXT)")


class SubMethods:
    """Sub辅助方法。"""

    @staticmethod
    async def create(
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
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(Sub)
                .where(Sub.user_id == user_id, Sub.state == 1)
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

    @staticmethod
    async def get_by_id(sub_id: int) -> Sub | None:
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
    async def get_by_ids(sub_ids: list[int]) -> dict[int, Sub]:
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

            stmt = select(Sub).where(Sub.id.in_(sub_ids), Sub.state == 1)
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
        """Get subscription by platform and feed link (for shared data mode).

        When platform_shared_data is enabled, subscriptions are shared across
        all BOTs in the same platform.
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
                if db_sub.id is not None:
                    monitor = await session.get(MonitorSchedule, db_sub.id)
                    if monitor is not None:
                        await session.delete(monitor)
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
                if sub.id is not None:
                    monitor = await session.get(MonitorSchedule, sub.id)
                    if monitor is not None:
                        await session.delete(monitor)
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

    @staticmethod
    async def get_or_create(user_id: str) -> User:
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

    @staticmethod
    async def get_or_create(link: str, title: str = "") -> Feed:
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

    @staticmethod
    async def get_by_id(feed_id: int) -> Feed | None:
        async with get_session() as session:
            return await session.get(Feed, feed_id)


class MonitorScheduleMethods:
    """MonitorSchedule helper methods."""

    @staticmethod
    async def get(sub_id: int) -> MonitorSchedule | None:
        async with get_session() as session:
            return await session.get(MonitorSchedule, sub_id)

    @staticmethod
    async def get_or_create(sub_id: int) -> MonitorSchedule:
        async with get_session() as session:
            row = await session.get(MonitorSchedule, sub_id)
            if row is None:
                row = MonitorSchedule(sub_id=sub_id)
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return row

    @staticmethod
    async def upsert(
        sub_id: int,
        *,
        next_check_time: datetime | None,
        error_count: int,
    ) -> MonitorSchedule:
        async with get_session() as session:
            row = await session.get(MonitorSchedule, sub_id)
            if row is None:
                row = MonitorSchedule(sub_id=sub_id)
            row.next_check_time = next_check_time
            row.error_count = error_count
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @staticmethod
    async def delete(sub_id: int) -> None:
        async with get_session() as session:
            row = await session.get(MonitorSchedule, sub_id)
            if row is not None:
                await session.delete(row)
                await session.commit()


class FailedNotificationMethods:
    """FailedNotification helper methods for retry queue management."""

    @staticmethod
    async def enqueue(
        sub_id: int,
        user_id: str,
        content: str,
        media_urls: list[str] | None = None,
        entry_title: str | None = None,
        entry_link: str | None = None,
        feed_title: str | None = None,
        feed_link: str | None = None,
        platform_name: str | None = None,
        target_session: str | None = None,
        options: dict | None = None,
        fail_reason: str | None = None,
    ) -> FailedNotification:
        """Add a failed notification to the queue."""
        async with get_session() as session:
            notif = FailedNotification(
                sub_id=sub_id,
                user_id=user_id,
                content=content,
                media_urls=media_urls or [],
                entry_title=entry_title,
                entry_link=entry_link,
                feed_title=feed_title,
                feed_link=feed_link,
                platform_name=platform_name,
                target_session=target_session,
                options=options or {},
                fail_reason=fail_reason,
            )
            session.add(notif)
            await session.commit()
            await session.refresh(notif)
            return notif

    @staticmethod
    async def get_pending(
        limit: int = 100,
        max_retries: int = 3,
    ) -> list[FailedNotification]:
        """Get pending failed notifications for retry."""
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(FailedNotification)
                .where(FailedNotification.retry_count < max_retries)
                .order_by(FailedNotification.created_at.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    async def get_by_sub(
        sub_id: int, limit: int | None = None
    ) -> list[FailedNotification]:
        """Get failed notifications for a subscription, ordered by creation time.

        Args:
            sub_id: Subscription ID
            limit: Maximum number of notifications to fetch (for bounded processing)
        """
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(FailedNotification)
                .where(FailedNotification.sub_id == sub_id)
                .order_by(FailedNotification.created_at.asc())
            )
            if limit is not None and limit > 0:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    async def count_by_sub(sub_id: int) -> int:
        """Count failed notifications for a subscription."""
        async with get_session() as session:
            from sqlmodel import func, select

            stmt = (
                select(func.count())
                .select_from(FailedNotification)
                .where(FailedNotification.sub_id == sub_id)
            )
            result = await session.execute(stmt)
            return int(result.scalar_one() or 0)

    @staticmethod
    async def is_at_capacity(sub_id: int, capacity: int) -> bool:
        """Check if the failed notification queue is at capacity.

        Uses a cheaper existence check (LIMIT capacity+1) instead of full COUNT
        to reduce DB load under high volume.

        Args:
            sub_id: Subscription ID
            capacity: Maximum capacity

        Returns:
            True if queue has reached or exceeded capacity
        """
        async with get_session() as session:
            from sqlmodel import select

            stmt = (
                select(FailedNotification.id)
                .where(FailedNotification.sub_id == sub_id)
                .limit(capacity + 1)
            )
            result = await session.execute(stmt)
            rows = result.all()
            return len(rows) > capacity

    @staticmethod
    async def count_by_sub_ids(sub_ids: list[int]) -> dict[int, int]:
        """Count failed notifications for multiple subscriptions in a single query.

        Returns a mapping of {sub_id: count} to avoid N+1 query patterns.
        """
        if not sub_ids:
            return {}

        async with get_session() as session:
            from sqlmodel import func, select

            stmt = (
                select(
                    FailedNotification.sub_id,
                    func.count().label("count"),
                )
                .where(FailedNotification.sub_id.in_(sub_ids))
                .group_by(FailedNotification.sub_id)
            )
            result = await session.execute(stmt)
            rows = result.all()
            return {row[0]: row[1] for row in rows}

    @staticmethod
    async def increment_retry(notif_id: int, fail_reason: str | None = None) -> None:
        """Increment retry count for a notification."""
        async with get_session() as session:
            notif = await session.get(FailedNotification, notif_id)
            if notif:
                notif.retry_count += 1
                if fail_reason:
                    notif.fail_reason = fail_reason
                session.add(notif)
                await session.commit()

    @staticmethod
    async def delete(notif_id: int) -> None:
        """Delete a notification from the queue (on success or max retries)."""
        async with get_session() as session:
            notif = await session.get(FailedNotification, notif_id)
            if notif:
                await session.delete(notif)
                await session.commit()

    @staticmethod
    async def delete_by_sub(sub_id: int) -> int:
        """Delete all notifications for a subscription using SQL DELETE WHERE."""
        async with get_session() as session:
            from sqlalchemy import delete

            stmt = (
                delete(FailedNotification)
                .where(FailedNotification.sub_id == sub_id)
                .execution_options(synchronize_session=False)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    @staticmethod
    async def delete_exceeded(max_retries: int = 3) -> int:
        """Delete notifications that exceeded max retries using SQL DELETE WHERE."""
        async with get_session() as session:
            from sqlalchemy import delete

            stmt = (
                delete(FailedNotification)
                .where(FailedNotification.retry_count >= max_retries)
                .execution_options(synchronize_session=False)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    @staticmethod
    async def get_stats(max_retries: int = 3) -> dict:
        """Get queue statistics.

        Args:
            max_retries: Maximum retry count threshold. Notifications with
                        retry_count < max_retries are considered pending.
                        Should match the system's configured max retries.
        """
        async with get_session() as session:
            from sqlmodel import func, select

            total_stmt = select(func.count()).select_from(FailedNotification)
            total = (await session.execute(total_stmt)).scalar_one() or 0

            pending_stmt = (
                select(func.count())
                .select_from(FailedNotification)
                .where(FailedNotification.retry_count < max_retries)
            )
            pending = (await session.execute(pending_stmt)).scalar_one() or 0

            return {
                "total": int(total),
                "pending": int(pending),
                "exhausted": int(total) - int(pending),
            }


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
            monitor = await session.get(MonitorSchedule, sub_id)
            if monitor is not None:
                await session.delete(monitor)
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
MonitorSchedule.get = staticmethod(MonitorScheduleMethods.get)
MonitorSchedule.get_or_create = staticmethod(MonitorScheduleMethods.get_or_create)
MonitorSchedule.upsert = staticmethod(MonitorScheduleMethods.upsert)
MonitorSchedule.delete = staticmethod(MonitorScheduleMethods.delete)
FailedNotification.enqueue = staticmethod(FailedNotificationMethods.enqueue)
FailedNotification.get_pending = staticmethod(FailedNotificationMethods.get_pending)
FailedNotification.get_by_sub = staticmethod(FailedNotificationMethods.get_by_sub)
FailedNotification.get_count_by_sub = staticmethod(
    FailedNotificationMethods.count_by_sub
)
FailedNotification.get_count_by_sub_ids = staticmethod(
    FailedNotificationMethods.count_by_sub_ids
)
FailedNotification.increment_retry = staticmethod(
    FailedNotificationMethods.increment_retry
)
FailedNotification.delete = staticmethod(FailedNotificationMethods.delete)
FailedNotification.delete_by_sub = staticmethod(FailedNotificationMethods.delete_by_sub)
FailedNotification.delete_exceeded = staticmethod(
    FailedNotificationMethods.delete_exceeded
)
FailedNotification.get_stats = staticmethod(FailedNotificationMethods.get_stats)
