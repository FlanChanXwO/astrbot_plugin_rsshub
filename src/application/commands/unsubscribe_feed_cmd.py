"""
取消订阅命令

处理用户取消订阅 RSS 源的业务用例。
"""

from ...domain.entities.delivery import DeliveryOwner
from ...domain.repositories.delivery_repository import DeliveryDeletionBlockedError
from ...domain.repositories.feed_repository import FeedRepository
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ..dto.result_dto import CommandResult


class UnsubscribeFeedCommand:
    """
    取消订阅命令

    处理用户取消订阅 RSS 源的业务用例。
    """

    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        feed_repo: FeedRepository,
        delivery_repo=None,
    ):
        self._subscription_repo = subscription_repo
        self._feed_repo = feed_repo
        self._delivery_repo = delivery_repo

    async def execute(
        self,
        sub_id: int,
        user_id: str,
        current_session: str = "",
        is_admin: bool = False,
    ) -> CommandResult:
        """
        执行取消订阅命令

        Args:
            sub_id: 订阅 ID
            user_id: 用户 ID
            current_session: 当前会话 ID
            is_admin: 是否为管理员

        Returns:
            CommandResult: 命令执行结果
        """
        subscription = await self._subscription_repo.get_by_id(sub_id)
        if not subscription:
            return CommandResult(
                success=False,
                message=f"订阅不存在 (ID: {sub_id})",
            )

        # 权限检查：管理员可删除任意订阅；非管理员需是订阅者或同一目标会话
        if not is_admin:
            is_owner = subscription.user_id == user_id
            is_current_session = bool(subscription.target_session) and (
                subscription.target_session == current_session
            )
            if not (is_owner or is_current_session):
                return CommandResult(
                    success=False,
                    message="无权限删除该订阅",
                )

        # 获取 Feed 信息用于展示
        feed = await self._feed_repo.get_by_id(subscription.feed_id)
        feed_title = feed.title if feed else "未知"
        feed_link = feed.link if feed else ""
        custom_title = f" ({subscription.title})" if subscription.title else ""

        if self._delivery_repo is not None:
            try:
                await self._delivery_repo.delete_owner(
                    DeliveryOwner(owner_type="subscription", owner_id=sub_id)
                )
            except DeliveryDeletionBlockedError as exc:
                return CommandResult(
                    success=False,
                    message=f"可靠投递数据尚未消费，不能取消订阅: {exc.blocker_counts}",
                )
        else:
            await self._subscription_repo.delete(subscription)

        lines = [
            "已取消的订阅列表（当前会话）:",
            "共 1 个订阅",
            f"1. [{sub_id}] ✗ {feed_title}{custom_title}",
        ]
        if feed_link:
            lines.append(f"    {feed_link}")

        return CommandResult(
            success=True,
            message="\n".join(lines),
        )

    async def execute_by_url(
        self,
        url: str,
        user_id: str,
        current_session: str = "",
        is_admin: bool = False,
    ) -> CommandResult:
        """按 URL 取消订阅（删除当前用户/会话可见的同源订阅）。"""
        feed = await self._feed_repo.get_by_link(url)
        if not feed:
            return CommandResult(success=False, message=f"未找到该订阅源: {url}")

        subscriptions = await self._subscription_repo.get_by_user(user_id)
        matched = [sub for sub in subscriptions if sub.feed_id == feed.id]
        if not matched and is_admin:
            all_subs = await self._subscription_repo.get_all_active()
            matched = [sub for sub in all_subs if sub.feed_id == feed.id]

        if not matched:
            return CommandResult(success=False, message=f"未找到可取消的订阅: {url}")

        deleted = 0
        for sub in matched:
            if not is_admin:
                is_owner = sub.user_id == user_id
                is_current_session = bool(sub.target_session) and (
                    sub.target_session == current_session
                )
                if not (is_owner or is_current_session):
                    continue
            if self._delivery_repo is not None:
                try:
                    await self._delivery_repo.delete_owner(
                        DeliveryOwner(owner_type="subscription", owner_id=sub.id)
                    )
                except DeliveryDeletionBlockedError:
                    continue
            else:
                await self._subscription_repo.delete(sub)
            deleted += 1

        if deleted == 0:
            return CommandResult(success=False, message="无权限删除该订阅")

        return CommandResult(success=True, message=f"已取消订阅 {deleted} 条: {url}")
