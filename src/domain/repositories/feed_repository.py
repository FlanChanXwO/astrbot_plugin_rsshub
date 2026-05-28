"""
Feed 仓库接口

定义 Feed 实体的持久化操作规范。具体实现由基础设施层提供。
"""

from typing import Protocol

from ..entities.feed import Feed


class FeedRepository(Protocol):
    """
    Feed 仓库接口

    定义 Feed 实体的持久化操作规范。具体实现由基础设施层提供。
    """

    async def get_by_id(self, feed_id: int) -> Feed | None:
        """
        根据ID获取Feed

        Args:
            feed_id: Feed唯一标识

        Returns:
            Feed对象，不存在时返回None
        """
        ...

    async def get_by_ids(self, feed_ids: list[int]) -> list[Feed]:
        """
        根据ID批量获取Feed

        Args:
            feed_ids: Feed唯一标识列表

        Returns:
            Feed对象列表
        """
        ...

    async def get_by_link(self, link: str) -> Feed | None:
        """
        根据链接获取Feed

        Args:
            link: Feed链接URL

        Returns:
            Feed对象，不存在时返回None
        """
        ...

    async def get_or_create(self, link: str, title: str = "") -> Feed:
        """
        获取或创建Feed

        Args:
            link: Feed链接URL
            title: Feed标题（可选）

        Returns:
            Feed对象（已存在或新创建）
        """
        ...

    async def save(self, feed: Feed) -> Feed:
        """
        保存Feed

        Args:
            feed: Feed实体

        Returns:
            保存后的Feed实体
        """
        ...

    async def get_all(self) -> list[Feed]:
        """
        获取所有Feed

        Returns:
            Feed对象列表
        """
        ...

    async def get_all_active(self) -> list[Feed]:
        """
        获取所有启用的Feed

        Returns:
            Feed对象列表
        """
        ...

    async def delete_many(self, feed_ids: list[int]) -> int:
        """
        批量删除 Feed。

        Args:
            feed_ids: Feed ID 列表

        Returns:
            实际删除的 Feed 数量
        """
        ...
