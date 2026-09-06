"""
获取订阅列表查询

处理获取用户订阅列表的查询。
"""

from pydantic import BaseModel, Field

from ...domain.repositories.subscription_repository import SubscriptionRepository
from ..dto.subscription_dto import SubscriptionDTO


class SubscriptionsResult(BaseModel):
    """
    订阅列表查询结果
    """

    subscriptions: list[SubscriptionDTO] = Field(
        default_factory=list, description="订阅列表"
    )
    total: int = Field(default=0, description="总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")

    class Config:
        frozen = True


class GetSubscriptionsQuery:
    """
    获取订阅列表查询

    处理获取用户订阅列表的查询。
    """

    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
    ):
        self._subscription_repo = subscription_repo

    async def execute(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> SubscriptionsResult:
        """
        执行查询

        Args:
            user_id: 用户 ID
            page: 页码（从 1 开始）
            page_size: 每页数量

        Returns:
            SubscriptionsResult: 查询结果
        """
        # 需要从 persistence 层获取订阅并加载关联的 Feed
        from sqlmodel import select

        from ...infrastructure.persistence.database import get_database
        from ...infrastructure.persistence.models import FeedORM, SubORM

        db = get_database()
        async with db.get_session() as session:
            stmt = (
                select(SubORM)
                .where(SubORM.user_id == user_id)
                .order_by(SubORM.id.asc())
            )
            result = await session.execute(stmt)
            sub_orms = list(result.scalars().all())

            # 批量加载关联的 Feed
            feed_ids = [sub.feed_id for sub in sub_orms]
            feeds: dict[int, FeedORM] = {}
            if feed_ids:
                feed_stmt = select(FeedORM).where(FeedORM.id.in_(feed_ids))
                feed_result = await session.execute(feed_stmt)
                feeds = {f.id: f for f in feed_result.scalars().all()}

            sub_dtos = [
                SubscriptionDTO(
                    id=sub.id,
                    user_id=sub.user_id,
                    feed_id=sub.feed_id,
                    title=sub.title,
                    feed_title=feeds[sub.feed_id].title
                    if sub.feed_id in feeds
                    else None,
                    feed_link=feeds[sub.feed_id].link if sub.feed_id in feeds else None,
                    tags=sub.tags,
                    target_session=sub.target_session,
                    platform_name=sub.platform_name,
                    state=sub.state,
                    send_card=sub.send_card,
                    template_id=sub.template_id,
                    card_send_original_content=sub.card_send_original_content,
                    created_at=sub.created_at,
                    updated_at=sub.updated_at,
                )
                for sub in sub_orms
            ]

        return SubscriptionsResult(
            subscriptions=sub_dtos,
            total=len(sub_dtos),
            page=page,
            page_size=page_size,
        )
