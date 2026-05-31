"""
订阅仓库接口

定义订阅实体的持久化操作规范。具体实现由基础设施层提供。
"""

from typing import Protocol

from ..entities.subscription import Subscription


class SubscriptionRepository(Protocol):
    """
    订阅仓库接口

    定义订阅实体的持久化操作规范。具体实现由基础设施层提供。
    """

    async def get_by_id(self, sub_id: int) -> Subscription | None:
        """
        根据ID获取订阅

        Args:
            sub_id: 订阅唯一标识

        Returns:
            Subscription对象，不存在时返回None
        """
        ...

    async def get_by_user(self, user_id: str) -> list[Subscription]:
        """
        获取用户的所有订阅

        Args:
            user_id: 用户唯一标识

        Returns:
            订阅列表
        """
        ...

    async def get_by_user_feed_session(
        self, user_id: str, feed_id: int, target_session: str | None
    ) -> Subscription | None:
        """
        根据用户、Feed 与目标会话获取订阅

        订阅按 (user_id, feed_id, target_session) 唯一：同一用户在不同会话
        （如不同群聊）可对同一 Feed 各自订阅一份，因此查重必须带上会话。

        Args:
            user_id: 用户唯一标识
            feed_id: Feed唯一标识
            target_session: 目标会话标识（可为 None）

        Returns:
            Subscription对象，不存在时返回None
        """
        ...

    async def get_all_active(self) -> list[Subscription]:
        """
        获取所有启用的订阅

        Returns:
            订阅列表
        """
        ...

    async def list_for_dashboard(
        self,
        *,
        user_ids: list[str] | None = None,
        feed_ids: list[int] | None = None,
        feed_links: list[str] | None = None,
        sub_ids: list[int] | None = None,
        keywords: list[str] | None = None,
    ) -> list[Subscription]:
        """
        Dashboard 订阅列表筛选查询。

        Args:
            user_ids: 精确匹配用户 ID，任一命中即可
            feed_ids: 精确匹配 Feed ID，任一命中即可
            feed_links: 精确匹配 Feed 链接，任一命中即可
            sub_ids: 精确匹配订阅 ID，任一命中即可
            keywords: 标题/Feed/标签/用户 ID 模糊匹配关键词，任一命中即可

        Returns:
            订阅列表
        """
        ...

    async def get_active_by_feed_id(self, feed_id: int) -> list[Subscription]:
        """
        获取指定Feed的所有启用订阅

        Args:
            feed_id: Feed唯一标识

        Returns:
            订阅列表
        """
        ...

    async def save(self, subscription: Subscription) -> Subscription:
        """
        保存订阅

        Args:
            subscription: 订阅实体

        Returns:
            保存后的订阅实体
        """
        ...

    async def delete(self, subscription: Subscription) -> None:
        """
        删除订阅

        Args:
            subscription: 订阅实体
        """
        ...

    async def delete_all_by_user(self, user_id: str) -> int:
        """
        删除用户的所有订阅

        Args:
            user_id: 用户唯一标识

        Returns:
            删除的订阅数量
        """
        ...

    async def delete_all_by_feed_ids(self, feed_ids: list[int]) -> int:
        """
        删除指定 Feed 的所有订阅。

        Args:
            feed_ids: Feed ID 列表

        Returns:
            删除的订阅数量
        """
        ...

    async def update_options(
        self, sub_id: int, user_id: str, **kwargs
    ) -> Subscription | None:
        """
        更新订阅配置选项

        Args:
            sub_id: 订阅唯一标识
            user_id: 用户唯一标识
            **kwargs: 要更新的字段

        Returns:
            更新后的订阅实体，不存在时返回None
        """
        ...
