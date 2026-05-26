"""数据库连接管理模块

提供数据库引擎和会话管理，使用 SQLAlchemy + aiosqlite。
迁移在初始化时自动执行。

使用示例:
    from .database import get_database

    db = get_database()
    await db.init("/path/to/db.sqlite")
    async with db.get_session() as session:
        ...
    await db.close()
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import registry
from sqlmodel import SQLModel

from ..utils import get_logger
from .migrations import (
    cleanup_legacy_translation_tables,
    ensure_profile_schema,
    ensure_push_history_schema,
    ensure_user_rows,
    run_migrations,
)

logger = get_logger()

_plugin_registry = registry()


class RSSHubBaseModel(SQLModel, registry=_plugin_registry):
    """插件基础模型，共享注册表。"""

    pass


class DatabaseManager:
    """数据库管理器，封装引擎和会话工厂。

    禁止直接导出实例，使用 get_database() 获取单例。
    """

    def __init__(self):
        self._engine: Any | None = None
        self._session_maker: async_sessionmaker[AsyncSession] | None = None
        self._db_path: str | None = None

    @property
    def engine(self) -> Any:
        """获取数据库引擎。"""
        if self._engine is None:
            raise RuntimeError("数据库未初始化")
        return self._engine

    @property
    def is_initialized(self) -> bool:
        """检查数据库是否已初始化。"""
        return self._engine is not None and self._session_maker is not None

    async def init(self, db_path: str) -> None:
        """初始化数据库连接并运行迁移。

        Args:
            db_path: SQLite 数据库文件路径
        """
        if self._engine is not None:
            logger.warning("数据库已初始化，跳过重复初始化")
            return

        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
        )
        self._session_maker = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # 创建表（如果不存在）并运行迁移
        async with self._engine.begin() as conn:
            await conn.run_sync(RSSHubBaseModel.metadata.create_all)
            await run_migrations(conn)
            await cleanup_legacy_translation_tables(conn)
            await ensure_profile_schema(conn)
            await ensure_push_history_schema(conn)
            await ensure_user_rows(conn)

        logger.info("RSS 数据库初始化完成: %s", db_path)

    async def close(self) -> None:
        """关闭数据库连接。"""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_maker = None
            logger.info("RSS 数据库连接已关闭")

    def get_session(self) -> AsyncSession:
        """获取数据库会话。

        Returns:
            AsyncSession 上下文管理器

        Raises:
            RuntimeError: 数据库未初始化
        """
        if self._session_maker is None:
            raise RuntimeError("数据库未初始化，请先调用 init()")
        return self._session_maker()

    def get_orm_registry(self) -> registry:
        """获取 SQLAlchemy ORM 注册表。

        Returns:
            registry 实例
        """
        return _plugin_registry


# 内部缓存，禁止直接导出
db_manager_instance: DatabaseManager | None = None


def get_database() -> DatabaseManager:
    """获取数据库管理器单例。

    Returns:
        DatabaseManager 实例
    """
    global db_manager_instance
    if db_manager_instance is None:
        db_manager_instance = DatabaseManager()
    return db_manager_instance
