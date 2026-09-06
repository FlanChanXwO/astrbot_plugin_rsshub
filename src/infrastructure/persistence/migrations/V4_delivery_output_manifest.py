# ruff: noqa: N999  # 迁移发现器要求使用 V{version}_{name}.py 命名。
"""V4：为可靠批次增加输出身份清单。"""

from __future__ import annotations


async def upgrade(conn) -> None:
    """以加法迁移补齐批次输出清单。"""
    table = await conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='rsshub_delivery_batch'"
    )
    if table.fetchone() is None:
        return
    columns = await conn.exec_driver_sql("PRAGMA table_info(rsshub_delivery_batch)")
    if "output_manifest" in {str(row[1]) for row in columns.fetchall()}:
        return
    await conn.exec_driver_sql(
        "ALTER TABLE rsshub_delivery_batch "
        "ADD COLUMN output_manifest JSON NOT NULL DEFAULT '[]'"
    )
