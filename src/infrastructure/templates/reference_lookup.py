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

    async def get_template_references(
        self, template_id: str
    ) -> list[dict[str, object]]:
        """返回引用模板的 Subscription/Bundle owner 摘要。"""
        references: list[dict[str, object]] = []
        async with self._database.get_session() as session:
            subscriptions = await session.execute(
                select(SubORM.id, SubORM.user_id).where(
                    SubORM.template_id == template_id
                )
            )
            references.extend(
                {
                    "owner_type": "subscription",
                    "owner_id": owner_id,
                    "user_id": user_id,
                }
                for owner_id, user_id in subscriptions.all()
            )
            bundles = await session.execute(
                select(BundleORM.id, BundleORM.user_id).where(
                    BundleORM.template_id == template_id
                )
            )
            references.extend(
                {
                    "owner_type": "bundle",
                    "owner_id": owner_id,
                    "user_id": user_id,
                }
                for owner_id, user_id in bundles.all()
            )
        return references
