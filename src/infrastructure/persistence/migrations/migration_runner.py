"""数据库迁移运行器

支持版本化迁移，通过扫描 migrations/ 目录下的脚本文件，
根据 MigrationRecord 表中记录的版本号，自动执行未应用的迁移。

迁移脚本命名规范:
    V{数字}_{描述}.py
    例如: V1_init.py

迁移脚本必须实现:
    async def upgrade(conn) -> None:
        '''执行迁移逻辑'''
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....shared.constants import INHERIT_VALUE, STATE_ENABLED, USER_STATE_USER
from ...utils import get_logger

logger = get_logger()

# 匹配迁移文件名: V1_init.py
_MIGRATION_PATTERN = re.compile(r"^V(\d+)_.+\.py$")


def _extract_version(filename: str) -> int:
    """从迁移文件名提取版本号数字。

    Args:
        filename: 迁移文件名

    Returns:
        版本号整数

    Raises:
        ValueError: 文件名格式不符合规范
    """
    match = _MIGRATION_PATTERN.match(filename)
    if not match:
        raise ValueError(
            f"无效的迁移文件名: {filename}, 期望格式: V{{数字}}_{{描述}}.py"
        )
    return int(match.group(1))


@dataclass(frozen=True, slots=True)
class MigrationScript:
    """迁移脚本信息"""

    version: int
    name: str
    module_name: str
    upgrade: Callable[..., Any] | None = None


class MigrationRunner:
    """数据库迁移运行器

    负责扫描、排序和执行数据库迁移脚本。

    使用示例:
        runner = MigrationRunner()
        await runner.run_all(conn)
    """

    _scripts: list[MigrationScript] | None = None

    def __init__(self, package: str = __package__):
        """初始化迁移运行器。

        Args:
            package: 迁移脚本所在的 Python 包名
        """
        self._package = package

    def _discover_scripts(self) -> list[MigrationScript]:
        """扫描并加载所有迁移脚本。

        Returns:
            按版本号排序的迁移脚本列表
        """
        scripts: list[MigrationScript] = []

        try:
            package = importlib.import_module(self._package)
            package_path = Path(package.__file__).parent
        except (ImportError, AttributeError):
            logger.warning("迁移包 %s 不存在或未找到 __file__", self._package)
            return []

        for _, module_name, is_pkg in pkgutil.iter_modules([str(package_path)]):
            if is_pkg:
                continue

            try:
                version = _extract_version(module_name + ".py")
            except ValueError:
                # 忽略不符合命名规范的文件
                continue

            # 动态导入迁移模块
            full_module_name = f"{self._package}.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
            except Exception as ex:
                logger.error("加载迁移脚本 %s 失败: %s", full_module_name, ex)
                continue

            upgrade = getattr(module, "upgrade", None)
            if upgrade is None:
                logger.warning(
                    "迁移脚本 %s 缺少 upgrade 函数，已跳过", full_module_name
                )
                continue

            scripts.append(
                MigrationScript(
                    version=version,
                    name=module_name,
                    module_name=full_module_name,
                    upgrade=upgrade,
                )
            )

        # 按版本号排序
        scripts.sort(key=lambda s: s.version)

        # 检查版本号是否重复
        seen_versions: set[int] = set()
        for script in scripts:
            if script.version in seen_versions:
                raise ValueError(f"迁移版本号重复: V{script.version}")
            seen_versions.add(script.version)

        return scripts

    @property
    def scripts(self) -> list[MigrationScript]:
        """获取已排序的迁移脚本列表（延迟加载）"""
        if self._scripts is None:
            self._scripts = self._discover_scripts()
        return self._scripts

    def get_pending_versions(self, applied_versions: set[int]) -> list[MigrationScript]:
        """获取待执行的迁移脚本列表。

        Args:
            applied_versions: 已应用的版本号集合

        Returns:
            待执行的迁移脚本列表
        """
        return [s for s in self.scripts if s.version not in applied_versions]

    async def _get_applied_versions(self, conn) -> set[int]:
        """从数据库获取已应用的迁移版本号。

        Args:
            conn: 数据库连接对象

        Returns:
            已应用的版本号集合
        """
        # 先检查 migration_record 表是否存在
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rsshub_migration_record'"
        )
        if result.fetchone() is None:
            return set()

        result = await conn.exec_driver_sql(
            "SELECT version FROM rsshub_migration_record"
        )
        applied: set[int] = set()
        for row in result.fetchall():
            version_str = str(row[0])
            try:
                applied.add(int(version_str))
            except ValueError:
                logger.debug("忽略非整数迁移记录: %s", version_str)
                continue

        return applied

    async def _record_migration(
        self, conn, version: int, description: str = ""
    ) -> None:
        """记录迁移版本到数据库。

        Args:
            conn: 数据库连接对象
            version: 版本号
            description: 迁移描述
        """
        await conn.exec_driver_sql(
            """
            INSERT OR REPLACE INTO rsshub_migration_record (version, applied_at, description)
            VALUES (?, datetime('now'), ?)
            """,
            (str(version), description),
        )

    async def run_all(self, conn) -> list[int]:
        """执行所有待迁移的脚本。

        Args:
            conn: 数据库连接对象（应在事务中）

        Returns:
            已执行的版本号列表
        """
        applied = await self._get_applied_versions(conn)
        pending = self.get_pending_versions(applied)

        if not pending:
            logger.info("数据库已是最新版本，无需迁移")
            return []

        executed: list[int] = []
        for script in pending:
            logger.info("执行迁移 V%s: %s", script.version, script.name)
            try:
                await script.upgrade(conn)
                await self._record_migration(conn, script.version, script.name)
                executed.append(script.version)
                logger.info("迁移 V%s 执行成功", script.version)
            except Exception:
                logger.error("迁移 V%s (%s) 执行失败", script.version, script.name)
                raise

        logger.info("数据库迁移完成，本次执行 %d 个迁移", len(executed))
        return executed

    async def run_to(self, conn, target_version: int) -> list[int]:
        """执行迁移到指定版本号。

        Args:
            conn: 数据库连接对象
            target_version: 目标版本号

        Returns:
            已执行的版本号列表
        """
        applied = await self._get_applied_versions(conn)
        pending = self.get_pending_versions(applied)

        executed: list[int] = []
        for script in pending:
            if script.version > target_version:
                break
            logger.info("执行迁移 V%s: %s", script.version, script.name)
            try:
                await script.upgrade(conn)
                await self._record_migration(conn, script.version, script.name)
                executed.append(script.version)
                logger.info("迁移 V%s 执行成功", script.version)
            except Exception:
                logger.error("迁移 V%s (%s) 执行失败", script.version, script.name)
                raise

        return executed

    def list_all(self) -> list[tuple[int, str, str]]:
        """列出所有迁移脚本信息。

        Returns:
            [(版本号, 名称, 模块名), ...]
        """
        return [(s.version, s.name, s.module_name) for s in self.scripts]


async def run_migrations(conn) -> list[int]:
    """便捷函数：执行所有待迁移脚本。

    Args:
        conn: 数据库连接对象

    Returns:
        已执行的版本号列表
    """
    runner = MigrationRunner()
    return await runner.run_all(conn)


async def ensure_push_history_schema(conn) -> list[str]:
    """补齐 push_history 兼容字段。

    旧库可能已经记录过迁移版本，但实际表结构仍缺少 agent push 所需列。
    这里在每次启动时做一次轻量自愈，保证运行时查询不会因缺列直接失败。
    """

    async def _table_exists(table: str) -> bool:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return result.fetchone() is not None

    async def _column_names(table: str) -> set[str]:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        return {str(row[1]) for row in result.fetchall()}

    if not await _table_exists("rsshub_push_history"):
        return []

    applied: list[str] = []
    columns = await _column_names("rsshub_push_history")
    required_columns = {
        "source_type": "ALTER TABLE rsshub_push_history ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'feed'",
        "source_key": "ALTER TABLE rsshub_push_history ADD COLUMN source_key VARCHAR(255)",
        "raw_xml": "ALTER TABLE rsshub_push_history ADD COLUMN raw_xml TEXT",
        "handler_trace": "ALTER TABLE rsshub_push_history ADD COLUMN handler_trace JSON",
    }
    for column, sql in required_columns.items():
        if column in columns:
            continue
        await conn.exec_driver_sql(sql)
        applied.append(column)
        logger.info(
            "数据库 schema 自愈: 为 rsshub_push_history 添加缺失字段 %s", column
        )
    return applied


async def ensure_profile_schema(conn) -> list[str]:
    """补齐当前用户/订阅配置表运行必需字段。

    v2 发布前曾压缩开发期迁移脚本。已有测试库可能已经记录 V1，
    但实际 `rsshub_sub` 表仍缺少后续基线字段；这里保留轻量自愈，
    避免查询 ORM 当前模型时因缺列失败。
    """

    async def _table_exists(table: str) -> bool:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return result.fetchone() is not None

    async def _column_names(table: str) -> set[str]:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        return {str(row[1]) for row in result.fetchall()}

    async def _fill_nulls(table: str, columns: set[str], defaults: dict[str, Any]) -> list[str]:
        fixed: list[str] = []
        for column, default in defaults.items():
            if column not in columns:
                continue
            result = await conn.exec_driver_sql(
                f"UPDATE {table} SET {column} = ? WHERE {column} IS NULL",
                (default,),
            )
            if result.rowcount and result.rowcount > 0:
                fixed.append(f"{table}.{column}.nulls")
        return fixed

    applied: list[str] = []

    if await _table_exists("rsshub_user"):
        user_columns = await _column_names("rsshub_user")
        if "handlers" not in user_columns:
            await conn.exec_driver_sql(
                "ALTER TABLE rsshub_user ADD COLUMN handlers TEXT NOT NULL DEFAULT '[]'"
            )
            applied.append("rsshub_user.handlers")
            logger.info("数据库 schema 自愈: 为 rsshub_user 添加 handlers 字段")
            user_columns.add("handlers")
        fixed = await _fill_nulls(
            "rsshub_user",
            user_columns,
            {
                "state": USER_STATE_USER,
                "interval": INHERIT_VALUE,
                "notify": INHERIT_VALUE,
                "send_mode": INHERIT_VALUE,
                "handlers": "[]",
                "length_limit": INHERIT_VALUE,
                "display_author": INHERIT_VALUE,
                "display_via": INHERIT_VALUE,
                "display_title": INHERIT_VALUE,
                "display_entry_tags": INHERIT_VALUE,
                "style": INHERIT_VALUE,
                "display_media": INHERIT_VALUE,
                "needs_binding_notice": 0,
            },
        )
        if fixed:
            applied.extend(fixed)
            logger.info("数据库 schema 自愈: 修正 rsshub_user 的 NULL 配置字段")
        if {"created_at", "updated_at"}.issubset(user_columns):
            await conn.exec_driver_sql(
                "UPDATE rsshub_user SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
            )
            await conn.exec_driver_sql(
                "UPDATE rsshub_user SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
            )

    if await _table_exists("rsshub_sub"):
        sub_columns = await _column_names("rsshub_sub")
        if "handlers" not in sub_columns:
            await conn.exec_driver_sql(
                "ALTER TABLE rsshub_sub ADD COLUMN handlers TEXT NOT NULL DEFAULT '[]'"
            )
            applied.append("rsshub_sub.handlers")
            logger.info("数据库 schema 自愈: 为 rsshub_sub 添加 handlers 字段")
            sub_columns.add("handlers")
        if "handlers_mode" not in sub_columns:
            await conn.exec_driver_sql(
                "ALTER TABLE rsshub_sub ADD COLUMN handlers_mode TEXT NOT NULL DEFAULT 'inherit'"
            )
            await conn.exec_driver_sql(
                """
                UPDATE rsshub_sub
                SET handlers_mode = CASE
                    WHEN handlers IS NULL THEN 'inherit'
                    WHEN json_valid(handlers) AND json_array_length(handlers) = 0 THEN 'inherit'
                    WHEN NOT json_valid(handlers) AND REPLACE(
                        REPLACE(
                            REPLACE(
                                REPLACE(TRIM(COALESCE(handlers, '[]')), ' ', ''),
                                CHAR(10),
                                ''
                            ),
                            CHAR(13),
                            ''
                        ),
                        CHAR(9),
                        ''
                    ) IN ('', '[]') THEN 'inherit'
                    ELSE 'override'
                END
                """
            )
            applied.append("rsshub_sub.handlers_mode")
            logger.info("数据库 schema 自愈: 为 rsshub_sub 添加 handlers_mode 字段")
            sub_columns.add("handlers_mode")
        fixed = await _fill_nulls(
            "rsshub_sub",
            sub_columns,
            {
                "state": STATE_ENABLED,
                "title": "",
                "tags": "",
                "interval": INHERIT_VALUE,
                "notify": INHERIT_VALUE,
                "send_mode": INHERIT_VALUE,
                "handlers": "[]",
                "handlers_mode": "inherit",
                "length_limit": INHERIT_VALUE,
                "display_author": INHERIT_VALUE,
                "display_via": INHERIT_VALUE,
                "display_title": INHERIT_VALUE,
                "display_entry_tags": INHERIT_VALUE,
                "style": INHERIT_VALUE,
                "display_media": INHERIT_VALUE,
            },
        )
        if fixed:
            applied.extend(fixed)
            logger.info("数据库 schema 自愈: 修正 rsshub_sub 的 NULL 配置字段")
        if {"created_at", "updated_at"}.issubset(sub_columns):
            await conn.exec_driver_sql(
                "UPDATE rsshub_sub SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
            )
            await conn.exec_driver_sql(
                "UPDATE rsshub_sub SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
            )

    return applied


async def cleanup_legacy_translation_tables(conn) -> list[str]:
    """删除已废弃的翻译缓存相关表。

    旧版本曾包含翻译/内容处理链路，SQLite 中可能残留相关表。
    这里在每次启动时幂等清理，避免历史脏库长期保留无用结构。
    """

    legacy_tables = (
        "rsshub_translation_cache",
        "rsshub_translate_cache",
        "rsshub_translation_history",
        "rsshub_translate_history",
    )

    dropped: list[str] = []
    for table in legacy_tables:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if result.fetchone() is None:
            continue
        await conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        dropped.append(table)
        logger.info("数据库 schema 自愈: 删除旧翻译缓存表 %s", table)
    return dropped
