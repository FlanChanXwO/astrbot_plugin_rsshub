"""批量取消订阅命令

处理批量取消订阅 RSS 源的业务用例。
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.entities.delivery import DeliveryOwner
from ...domain.repositories.delivery_repository import DeliveryDeletionBlockedError
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ..dto.result_dto import CommandResult


@dataclass
class BatchUnsubscribeItem:
    """批量取消订阅单项结果"""

    sub_id: int
    success: bool
    message: str


@dataclass
class BatchUnsubscribeResult:
    """批量取消订阅结果"""

    total: int
    success_count: int
    failure_count: int
    items: list[BatchUnsubscribeItem]


class BatchUnsubscribeCommand:
    """批量取消订阅命令

    处理用户批量取消订阅 RSS 源的业务用例。
    """

    def __init__(self, subscription_repo: SubscriptionRepository, delivery_repo=None):
        self._subscription_repo = subscription_repo
        self._delivery_repo = delivery_repo

    async def execute(
        self,
        sub_ids: list[int],
        user_id: str,
    ) -> CommandResult:
        """执行批量取消订阅命令

        Args:
            sub_ids: 订阅 ID 列表
            user_id: 用户 ID

        Returns:
            CommandResult: 命令执行结果
        """
        if not sub_ids:
            return CommandResult(
                success=False,
                message="未提供订阅 ID",
            )

        items: list[BatchUnsubscribeItem] = []
        success_count = 0
        failure_count = 0

        for sub_id in sub_ids:
            item = await self._process_single(sub_id, user_id)
            items.append(item)
            if item.success:
                success_count += 1
            else:
                failure_count += 1

        result = BatchUnsubscribeResult(
            total=len(sub_ids),
            success_count=success_count,
            failure_count=failure_count,
            items=items,
        )

        if success_count == len(sub_ids):
            return CommandResult(
                success=True,
                message=f"成功取消 {success_count} 个订阅",
                data=result,
            )
        elif success_count > 0:
            return CommandResult(
                success=True,
                message=f"部分成功: {success_count} 个成功, {failure_count} 个失败",
                data=result,
            )
        else:
            return CommandResult(
                success=False,
                message=f"全部失败: {failure_count} 个订阅取消失败",
                data=result,
            )

    async def _process_single(
        self,
        sub_id: int,
        user_id: str,
    ) -> BatchUnsubscribeItem:
        """处理单个取消订阅

        Args:
            sub_id: 订阅 ID
            user_id: 用户 ID

        Returns:
            BatchUnsubscribeItem: 单项结果
        """
        subscription = await self._subscription_repo.get_by_id(sub_id)
        if not subscription:
            return BatchUnsubscribeItem(
                sub_id=sub_id,
                success=False,
                message=f"订阅不存在 (ID: {sub_id})",
            )

        if subscription.user_id != user_id:
            return BatchUnsubscribeItem(
                sub_id=sub_id,
                success=False,
                message="无权操作此订阅",
            )

        if self._delivery_repo is not None:
            try:
                await self._delivery_repo.delete_owner(
                    DeliveryOwner(owner_type="subscription", owner_id=sub_id)
                )
            except DeliveryDeletionBlockedError as exc:
                return BatchUnsubscribeItem(
                    sub_id=sub_id,
                    success=False,
                    message=(
                        f"可靠投递数据尚未消费，不能取消订阅: {exc.blocker_counts}"
                    ),
                )
        else:
            await self._subscription_repo.delete(subscription)

        return BatchUnsubscribeItem(
            sub_id=sub_id,
            success=True,
            message=f"已取消订阅 (ID: {sub_id})",
        )

    async def execute_all(
        self,
        user_id: str,
    ) -> CommandResult:
        """取消用户的所有订阅

        Args:
            user_id: 用户 ID

        Returns:
            CommandResult: 命令执行结果
        """
        subscriptions = await self._subscription_repo.get_by_user(user_id)
        if not subscriptions:
            return CommandResult(
                success=False,
                message="没有可取消的订阅",
            )

        sub_ids = [sub.id for sub in subscriptions]
        return await self.execute(sub_ids, user_id)
