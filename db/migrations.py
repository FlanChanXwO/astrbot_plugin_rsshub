"""RSS-to-AstrBot Database Migrations

数据库迁移管理模块，处理 schema 版本升级和兼容性维护。
"""

from __future__ import annotations

from ..utils.log_utils import logger

# SQLite 标识符验证正则
_SQLITE_IDENTIFIER_RE = None


def _get_sqlite_identifier_re():
    """Lazy import re module."""
    global _SQLITE_IDENTIFIER_RE
    if _SQLITE_IDENTIFIER_RE is None:
        import re

        _SQLITE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    return _SQLITE_IDENTIFIER_RE


def _sqlite_table_info_sql(table: str) -> str:
    """Build PRAGMA table_info SQL with a validated table identifier."""
    if not _get_sqlite_identifier_re().fullmatch(table):
        raise ValueError(f"Invalid sqlite table identifier: {table!r}")
    return f'PRAGMA table_info("{table}")'


def _is_text_compatible_sqlite_type(column_type: str) -> bool:
    """Return True when a SQLite declared type has TEXT affinity."""
    normalized = (column_type or "").upper()
    return any(token in normalized for token in ("TEXT", "CHAR", "CLOB"))


async def _get_column_type(conn, table: str, column: str) -> str:
    """获取指定表的列类型"""
    rows = (await conn.exec_driver_sql(_sqlite_table_info_sql(table))).fetchall()
    for row in rows:
        if row[1] == column:
            return row[2].upper()
    return ""


async def ensure_schema_compat(conn) -> None:
    """为旧数据库补齐迁移过程尚未纳入的新增列，并处理 user_id 类型迁移。

    这是主迁移入口函数，会在数据库初始化时自动调用。
    """

    async def _has_column(table: str, column: str) -> bool:
        rows = (await conn.exec_driver_sql(_sqlite_table_info_sql(table))).fetchall()
        return any(row[1] == column for row in rows)

    # ========== 新增列兼容（旧版本迁移）==========

    # v1.0.0+ 新增 target_session 列
    if not await _has_column("rsshub_sub", "target_session"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_sub ADD COLUMN target_session TEXT"
        )
        logger.info("迁移: 添加 rsshub_sub.target_session 列")

    # v1.0.0+ 新增 default_target_session 列
    if not await _has_column("rsshub_user", "default_target_session"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_user ADD COLUMN default_target_session TEXT"
        )
        logger.info("迁移: 添加 rsshub_user.default_target_session 列")

    # v1.0.0+ 新增 needs_binding_notice 列
    if not await _has_column("rsshub_user", "needs_binding_notice"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_user ADD COLUMN "
            "needs_binding_notice INTEGER NOT NULL DEFAULT 0"
        )
        logger.info("迁移: 添加 rsshub_user.needs_binding_notice 列")

    # v1.0.0+ 新增 platform_name 列
    if not await _has_column("rsshub_sub", "platform_name"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_sub ADD COLUMN platform_name TEXT"
        )
        logger.info("迁移: 添加 rsshub_sub.platform_name 列")

    # v1.1.0+ 新增翻译相关列
    if not await _has_column("rsshub_user", "translate"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_user ADD COLUMN translate INTEGER NOT NULL DEFAULT -100"
        )
        logger.info("迁移: 添加 rsshub_user.translate 列")

    if not await _has_column("rsshub_user", "translate_target_lang"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_user ADD COLUMN translate_target_lang TEXT"
        )
        logger.info("迁移: 添加 rsshub_user.translate_target_lang 列")

    if not await _has_column("rsshub_sub", "translate"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_sub ADD COLUMN translate INTEGER NOT NULL DEFAULT -100"
        )
        logger.info("迁移: 添加 rsshub_sub.translate 列")

    if not await _has_column("rsshub_sub", "translate_target_lang"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_sub ADD COLUMN translate_target_lang TEXT"
        )
        logger.info("迁移: 添加 rsshub_sub.translate_target_lang 列")

    # v1.1.0+ 新增配置继承架构列
    if not await _has_column("rsshub_user", "use_user_config"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_user ADD COLUMN use_user_config INTEGER NOT NULL DEFAULT 0"
        )
        logger.info("迁移: 添加 rsshub_user.use_user_config 列")

    if not await _has_column("rsshub_sub", "use_sub_config"):
        await conn.exec_driver_sql(
            "ALTER TABLE rsshub_sub ADD COLUMN use_sub_config INTEGER NOT NULL DEFAULT 0"
        )
        logger.info("迁移: 添加 rsshub_sub.use_sub_config 列")

    # v1.1.0+ 替换 INHERIT_VALUE (-100) 为实际默认值
    await _migrate_inherit_values_to_defaults(conn)

    # ========== 复杂迁移 ==========

    # User ID 类型迁移: INTEGER -> TEXT
    await _migrate_user_id_to_text(conn)


# noinspection SqlNoDataSourceInspection
async def _migrate_user_id_to_text(conn) -> None:
    """将 user_id 列从 INTEGER 迁移到 TEXT 类型。

    SQLite 不支持直接 ALTER COLUMN，需要重建表。
    迁移过程中会保留索引和触发器。
    """

    async def _table_exists(table: str) -> bool:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return result.fetchone() is not None

    async def _get_indexes(table: str) -> list[dict]:
        """获取表的所有索引定义（除主键索引外）。"""
        result = await conn.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        )
        rows = result.fetchall()
        indexes = []
        for row in rows:
            name, sql = row[0], row[1]
            # 跳过 SQLite 自动创建的索引（如 sqlite_autoindex_*）
            if name and sql and not name.startswith("sqlite_autoindex"):
                indexes.append({"name": name, "sql": sql})
        return indexes

    async def _get_triggers(table: str) -> list[dict]:
        """获取表的所有触发器定义。"""
        result = await conn.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (table,),
        )
        rows = result.fetchall()
        return [{"name": row[0], "sql": row[1]} for row in rows if row[1]]

    # 检查 rsshub_user.id 列类型
    if not await _table_exists("rsshub_user"):
        return

    user_id_type = await _get_column_type(conn, "rsshub_user", "id")
    if _is_text_compatible_sqlite_type(user_id_type):
        # TEXT affinity types in SQLite are already compatible (e.g. TEXT/VARCHAR).
        return

    if user_id_type != "INTEGER":
        logger.warning(f"rsshub_user.id 列类型为 {user_id_type}，无法自动迁移到 TEXT")
        return

    logger.info("开始迁移 user_id 从 INTEGER 到 TEXT...")

    # 备份索引和触发器
    user_indexes = await _get_indexes("rsshub_user")
    sub_indexes = await _get_indexes("rsshub_sub")
    failed_indexes = await _get_indexes("rsshub_failed_notification")

    user_triggers = await _get_triggers("rsshub_user")
    sub_triggers = await _get_triggers("rsshub_sub")
    failed_triggers = await _get_triggers("rsshub_failed_notification")

    logger.debug(
        "备份索引：user=%s, sub=%s, failed=%s",
        len(user_indexes),
        len(sub_indexes),
        len(failed_indexes),
    )
    logger.debug(
        "备份触发器：user=%s, sub=%s, failed=%s",
        len(user_triggers),
        len(sub_triggers),
        len(failed_triggers),
    )

    # conn 已从 _engine.begin() 传入，已在事务中，直接执行 SQL
    try:
        # === 迁移 rsshub_user 表 ===
        # 1. 创建新表（从当前表结构复制）
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
                translate INTEGER NOT NULL DEFAULT -100,
                translate_target_lang TEXT,
                default_target_session TEXT,
                needs_binding_notice INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. 迁移数据
        await conn.exec_driver_sql("""
            INSERT INTO rsshub_user_new
            SELECT CAST(id AS TEXT), state, lang, sub_limit, interval, notify,
                   send_mode,
                   length_limit, link_preview, display_author,
                   display_via, display_title,
                   display_entry_tags, style, display_media, -100, NULL,
                   default_target_session,
                   needs_binding_notice, created_at, updated_at
            FROM rsshub_user
        """)

        # 3. 删除旧表，重命名新表
        await conn.exec_driver_sql("DROP TABLE rsshub_user")
        await conn.exec_driver_sql("ALTER TABLE rsshub_user_new RENAME TO rsshub_user")

        # 4. 重建索引
        for idx in user_indexes:
            try:
                await conn.exec_driver_sql(idx["sql"])
                logger.debug(f"重建索引: {idx['name']}")
            except Exception as e:
                logger.warning(f"重建索引 {idx['name']} 失败: {e}")

        # 5. 重建触发器
        for trig in user_triggers:
            try:
                await conn.exec_driver_sql(trig["sql"])
                logger.debug(f"重建触发器: {trig['name']}")
            except Exception as e:
                logger.warning(f"重建触发器 {trig['name']} 失败: {e}")

        logger.info("rsshub_user 表迁移完成")

        # === 迁移 rsshub_sub 表 ===
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
                translate INTEGER NOT NULL DEFAULT -100,
                translate_target_lang TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES rsshub_user (id),
                FOREIGN KEY (feed_id) REFERENCES rsshub_feed (id)
            )
        """)

        # 2. 迁移数据
        await conn.exec_driver_sql("""
            INSERT INTO rsshub_sub_new
            SELECT id, state, CAST(user_id AS TEXT), feed_id, title, tags,
                   target_session,
                   platform_name, interval, notify, send_mode,
                   length_limit, link_preview,
                   display_author, display_via, display_title, display_entry_tags, style,
                   display_media, -100, NULL, created_at, updated_at
            FROM rsshub_sub
        """)

        # 3. 删除旧表，重命名新表
        await conn.exec_driver_sql("DROP TABLE rsshub_sub")
        await conn.exec_driver_sql("ALTER TABLE rsshub_sub_new RENAME TO rsshub_sub")

        # 4. 重建索引
        for idx in sub_indexes:
            try:
                await conn.exec_driver_sql(idx["sql"])
                logger.debug(f"重建索引: {idx['name']}")
            except Exception as e:
                logger.warning(f"重建索引 {idx['name']} 失败: {e}")

        # 5. 重建触发器
        for trig in sub_triggers:
            try:
                await conn.exec_driver_sql(trig["sql"])
                logger.debug(f"重建触发器: {trig['name']}")
            except Exception as e:
                logger.warning(f"重建触发器 {trig['name']} 失败: {e}")

        logger.info("rsshub_sub 表迁移完成")

        # === 迁移 rsshub_failed_notification 表 ===
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
            "ALTER TABLE rsshub_failed_notification_new RENAME TO "
            "rsshub_failed_notification"
        )

        # 4. 重建索引
        for idx in failed_indexes:
            try:
                await conn.exec_driver_sql(idx["sql"])
                logger.debug(f"重建索引: {idx['name']}")
            except Exception as e:
                logger.warning(f"重建索引 {idx['name']} 失败: {e}")

        # 5. 重建触发器
        for trig in failed_triggers:
            try:
                await conn.exec_driver_sql(trig["sql"])
                logger.debug(f"重建触发器: {trig['name']}")
            except Exception as e:
                logger.warning(f"重建触发器 {trig['name']} 失败: {e}")

        logger.info("rsshub_failed_notification 表迁移完成")

    except Exception:
        # 异常由外层事务处理回滚
        logger.error("user_id 类型迁移失败")
        raise

    logger.info("user_id 类型迁移完成 (INTEGER -> TEXT)")


# noinspection SqlNoDataSourceInspection
async def _migrate_inherit_values_to_defaults(conn) -> None:
    """将 INHERIT_VALUE (-100) 替换为实际默认值（v1.1.0+）"""
    INHERIT_VALUE = -100

    # Sub 表默认值映射
    SUB_DEFAULTS = {
        "interval": 5,
        "notify": 1,
        "send_mode": 0,
        "length_limit": 0,
        "link_preview": 0,
        "display_author": 0,
        "display_via": 0,
        "display_title": 0,
        "display_entry_tags": -1,
        "style": 0,
        "display_media": 0,
        "translate": 0,
    }

    # User 表默认值映射
    USER_DEFAULTS = {
        "interval": 5,
        "notify": 1,
        "send_mode": 0,
        "length_limit": 0,
        "link_preview": 0,
        "display_author": 0,
        "display_via": 0,
        "display_title": 0,
        "display_entry_tags": -1,
        "style": 0,
        "display_media": 0,
        "translate": 0,
    }

    try:
        # 检查是否需要迁移（通过检查是否存在 -100 的值）
        result = await conn.exec_driver_sql(
            "SELECT COUNT(*) FROM rsshub_sub WHERE notify = ? LIMIT 1",
            (INHERIT_VALUE,)
        )
        count = result.scalar()

        if count == 0:
            # 没有需要迁移的数据
            return

        logger.info("开始迁移 INHERIT_VALUE (-100) 到实际默认值...")

        # 迁移 Sub 表
        for column, default_value in SUB_DEFAULTS.items():
            await conn.exec_driver_sql(
                f"UPDATE rsshub_sub SET {column} = ? WHERE {column} = ?",
                (default_value, INHERIT_VALUE)
            )

        logger.info("Sub 表默认值迁移完成")

        # 迁移 User 表
        for column, default_value in USER_DEFAULTS.items():
            await conn.exec_driver_sql(
                f"UPDATE rsshub_user SET {column} = ? WHERE {column} = ?",
                (default_value, INHERIT_VALUE)
            )

        logger.info("User 表默认值迁移完成")

    except Exception as e:
        logger.error(f"默认值迁移失败: {e}")
        raise
