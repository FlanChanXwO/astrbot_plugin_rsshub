"""推送历史仓库接口

定义推送历史实体的持久化操作规范。具体实现由基础设施层提供。
"""

from typing import Protocol

from ..entities.push_history import PushHistory


class PushHistoryRepository(Protocol):
    """推送历史仓库接口

    定义推送历史实体的持久化操作规范。具体实现由基础设施层提供。
    """

    async def get_by_id(self, history_id: int) -> PushHistory | None:
        """根据ID获取推送历史

        Args:
            history_id: 推送历史唯一标识

        Returns:
            PushHistory对象，不存在时返回None
        """
        ...

    async def get_by_sub(
        self, sub_id: int, limit: int | None = None, status: str | None = None
    ) -> list[PushHistory]:
        """获取订阅的推送历史

        Args:
            sub_id: 订阅唯一标识
            limit: 限制数量（可选）
            status: 状态过滤（可选）

        Returns:
            推送历史列表
        """
        ...

    async def exists_success_by_scope_and_guid(
        self,
        *,
        source_type: str,
        user_id: str,
        target_session: str,
        entry_guid: str,
        source_key: str | None = None,
    ) -> bool:
        """检查指定作用域内是否存在成功的相同 GUID 推送记录。"""
        ...

    async def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        keywords: list[str] | None = None,
    ) -> list[PushHistory]:
        """获取所有推送历史

        Args:
            limit: 限制数量
            offset: 偏移量
            status: 状态过滤（可选）
            keywords: 关键词过滤（可选）

        Returns:
            推送历史列表
        """
        ...

    async def get_by_user(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        target_session: str | None = None,
        status: str | None = None,
        keywords: list[str] | None = None,
    ) -> list[PushHistory]:
        """获取用户的推送历史

        Args:
            user_id: 用户唯一标识
            limit: 限制数量
            offset: 偏移量
            target_session: 目标会话过滤（可选）
            status: 状态过滤（可选）
            keywords: 关键词过滤（可选）

        Returns:
            推送历史列表
        """
        ...

    async def count_by_user(
        self,
        user_id: str,
        target_session: str | None = None,
        status: str | None = None,
        keywords: list[str] | None = None,
    ) -> int:
        """统计用户推送历史条数，可按目标会话和状态过滤。"""
        ...

    async def count_all(
        self,
        status: str | None = None,
        keywords: list[str] | None = None,
    ) -> int:
        """统计全部推送历史条数，可按状态和关键词过滤。"""
        ...

    async def count_retryable_failures(self) -> int:
        """统计仍可重试的失败记录数。

        固定语义：
        - status in ("failed", "retrying")
        - retry_count < max_retries
        """
        ...

    async def get_pending_for_retry(self, limit: int = 100) -> list[PushHistory]:
        """获取需要重试的推送记录

        Args:
            limit: 限制数量

        Returns:
            需要重试的推送历史列表
        """
        ...

    async def get_and_mark_retrying(self, limit: int = 100) -> list[PushHistory]:
        """原子获取并标记待重试记录，防止多 worker 重复拉取。

        Args:
            limit: 限制数量

        Returns:
            被标记为 retrying 的推送历史列表
        """
        ...

    async def save(self, history: PushHistory) -> PushHistory:
        """保存推送历史

        Args:
            history: 推送历史实体

        Returns:
            保存后的推送历史实体
        """
        ...

    async def delete(self, history_id: int) -> bool:
        """删除推送历史

        Args:
            history_id: 推送历史唯一标识

        Returns:
            是否删除成功
        """
        ...

    async def delete_many(self, history_ids: list[int]) -> int:
        """批量删除推送历史。

        Args:
            history_ids: 要删除的推送历史 ID 列表

        Returns:
            实际删除的记录数量
        """
        ...

    async def delete_old_records(self, days: int = 30) -> int:
        """删除指定天数前的历史记录

        Args:
            days: 保留天数

        Returns:
            删除的记录数量
        """
        ...

    async def delete_all(self) -> int:
        """删除全部推送历史记录。

        Returns:
            删除的记录数量
        """
        ...

    async def get_stats(self) -> dict[str, int]:
        """获取推送统计信息

        Returns:
            统计信息字典，包含 total, pending, success, failed
        """
        ...
