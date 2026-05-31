"""V2 迁移：移除 rsshub_sub 表中的 link_preview 遗留字段

历史背景：
- link_preview 是已废弃的遗留字段，不再在 ORM 模型中定义
- 旧版本数据库中该字段带有 NOT NULL 约束
- 当 ORM 尝试插入新订阅时，SQLite 会因缺少该字段而失败

修复方案：
- 检查 rsshub_sub 表中是否存在 link_preview 列
- 如果存在，使用 ALTER TABLE DROP COLUMN 安全删除
- 如果不存在（新安装），跳过操作

相关 Issue: #58
"""

from __future__ import annotations

from ...utils import get_logger

logger = get_logger()


async def upgrade(conn) -> None:
    """执行 V2 迁移：删除 link_preview 列"""

    async def _table_exists(table: str) -> bool:
        """检查表是否存在"""
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return result.fetchone() is not None

    async def _column_exists(table: str, column: str) -> bool:
        """检查列是否存在"""
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        return any(str(row[1]) == column for row in result.fetchall())

    # 检查 rsshub_sub 表是否存在
    if not await _table_exists("rsshub_sub"):
        logger.info("迁移 V2: rsshub_sub 表不存在，跳过")
        return

    # 检查 link_preview 列是否存在
    if not await _column_exists("rsshub_sub", "link_preview"):
        logger.info("迁移 V2: link_preview 列不存在，无需删除")
        return

    # 删除 link_preview 列
    try:
        await conn.exec_driver_sql("ALTER TABLE rsshub_sub DROP COLUMN link_preview")
        logger.info("迁移 V2: 成功删除 rsshub_sub.link_preview 列")
    except Exception as e:
        logger.error("迁移 V2: 删除 link_preview 列失败: %s", e)
        raise

    logger.info("迁移 V2 完成: 移除 link_preview 遗留字段")
