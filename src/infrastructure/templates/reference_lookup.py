"""卡片模板的数据库引用查询。"""

from __future__ import annotations

from sqlmodel import select

from ..persistence.database import DatabaseManager
from ..persistence.models import BundleORM, SubORM


class DatabaseCardTemplateReferenceLookup:
    """查询 Subscription 与 Bundle 保存的模板引用。"""

    def __init__(self, database: DatabaseManager) -> None:
        self._database = database

    async def is_template_in_use(self, template_id: str) -> bool:
        """任一 owner 保存该模板 ID 时返回 True。"""
        async with self._database.get_session() as session:
            subscription = await session.execute(
                select(SubORM.id).where(SubORM.template_id == template_id).limit(1)
            )
            if subscription.scalar_one_or_none() is not None:
                return True
            bundle = await session.execute(
                select(BundleORM.id)
                .where(BundleORM.template_id == template_id)
                .limit(1)
            )
            return bundle.scalar_one_or_none() is not None
