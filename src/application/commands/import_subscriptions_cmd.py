"""导入订阅命令

处理用户导入订阅配置的业务用例。
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.entities.feed import Feed
from ...domain.entities.subscription import Subscription
from ...domain.repositories.feed_repository import FeedRepository
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ...domain.repositories.user_repository import UserRepository
from ...domain.value_objects.feed_url import FeedUrl
from ...infrastructure.config import validate_interval_value
from ..dto.result_dto import CommandResult

IMPORT_UPLOAD_WAIT_SECONDS = 5 * 60


@dataclass
class ImportItemResult:
    """导入单项结果"""

    link: str
    success: bool
    message: str
    subscription_id: int | None = None


@dataclass
class ImportResult:
    """导入结果"""

    total: int
    success_count: int
    failure_count: int
    skipped_count: int
    items: list[ImportItemResult]
    errors: list[str]
    warnings: list[str]


class ImportSubscriptionsCommand:
    """导入订阅命令

    处理用户导入订阅配置的业务用例。
    """

    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        feed_repo: FeedRepository,
        user_repo: UserRepository | None = None,
    ):
        self._subscription_repo = subscription_repo
        self._feed_repo = feed_repo
        self._user_repo = user_repo

    async def execute(
        self,
        content: str,
        user_id: str,
        target_session: str | None = None,
        platform_name: str | None = None,
        skip_existing: bool = True,
    ) -> CommandResult:
        """执行导入命令

        Args:
            content: TOML 格式的订阅配置文本
            user_id: 用户 ID
            target_session: 推送目标会话（可选，默认使用用户当前会话）
            platform_name: 平台类型名（可选）
            skip_existing: 是否跳过已存在的订阅

        Returns:
            CommandResult: 命令执行结果
        """
        from ...application.services.subscription_serializer import (
            parse_subscriptions_toml,
        )

        payload = parse_subscriptions_toml(content)

        if payload.errors and not payload.records:
            return CommandResult(
                success=False,
                message=f"解析失败: {'; '.join(payload.errors[:3])}",
            )

        if not payload.records:
            return CommandResult(
                success=False,
                message="没有找到有效的订阅记录",
            )

        normalized_user_id = str(user_id or "").strip()
        if self._user_repo is not None and normalized_user_id:
            await self._user_repo.get_or_create(normalized_user_id)
            user_id = normalized_user_id

        items: list[ImportItemResult] = []
        success_count = 0
        failure_count = 0
        skipped_count = 0

        for record in payload.records:
            item = await self._process_single(
                record=record,
                user_id=user_id,
                target_session=target_session,
                platform_name=platform_name,
                skip_existing=skip_existing,
            )
            items.append(item)
            if item.success:
                success_count += 1
            elif "已存在" in item.message:
                skipped_count += 1
            else:
                failure_count += 1

        result = ImportResult(
            total=len(payload.records),
            success_count=success_count,
            failure_count=failure_count,
            skipped_count=skipped_count,
            items=items,
            errors=payload.errors,
            warnings=payload.warnings,
        )

        if success_count == len(payload.records):
            return CommandResult(
                success=True,
                message=f"成功导入 {success_count} 个订阅",
                data=result,
            )
        elif success_count > 0 or skipped_count > 0:
            return CommandResult(
                success=True,
                message=f"部分成功: {success_count} 个导入, {skipped_count} 个跳过, {failure_count} 个失败",
                data=result,
            )
        else:
            return CommandResult(
                success=False,
                message=f"全部失败: {failure_count} 个订阅导入失败",
                data=result,
            )

    async def _process_single(
        self,
        record: object,
        user_id: str,
        target_session: str | None,
        platform_name: str | None,
        skip_existing: bool,
    ) -> ImportItemResult:
        """处理单个导入记录

        Args:
            record: 导入记录
            user_id: 用户 ID
            target_session: 目标会话
            platform_name: 平台名
            skip_existing: 是否跳过已存在

        Returns:
            ImportItemResult: 单项结果
        """
        link = record.link

        try:
            # 验证 URL
            feed_url = FeedUrl(link)

            # 查找或创建 Feed
            feed = await self._feed_repo.get_by_link(feed_url.normalized())
            if feed is None:
                feed = Feed(link=feed_url.normalized(), title=record.feed_title or "")
                feed = await self._feed_repo.save(feed)

            # 检查是否已订阅（按 用户 + Feed + 目标会话 查重）
            existing = await self._subscription_repo.get_by_user_feed_session(
                user_id, feed.id, target_session
            )
            if existing:
                if skip_existing:
                    return ImportItemResult(
                        link=link,
                        success=False,
                        message=f"已存在订阅 (ID: {existing.id})",
                    )
                # 更新现有订阅的设置
                for key, value in record.options.items():
                    if key == "interval":
                        value = validate_interval_value(
                            value,
                            allow_inherit=True,
                            field_name="interval",
                        )
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                existing = await self._subscription_repo.save(existing)
                return ImportItemResult(
                    link=link,
                    success=True,
                    message=f"已更新订阅 (ID: {existing.id})",
                    subscription_id=existing.id,
                )

            # 创建新订阅
            subscription = Subscription(
                user_id=user_id,
                feed_id=feed.id,
                target_session=target_session,
                platform_name=platform_name,
                title=record.options.get("title", ""),
                tags=record.options.get("tags", ""),
            )

            # 应用导入的选项
            for key, value in record.options.items():
                if key == "interval":
                    value = validate_interval_value(
                        value,
                        allow_inherit=True,
                        field_name="interval",
                    )
                if hasattr(subscription, key) and key not in ("title", "tags"):
                    setattr(subscription, key, value)

            subscription = await self._subscription_repo.save(subscription)

            return ImportItemResult(
                link=link,
                success=True,
                message=f"导入成功 (ID: {subscription.id})",
                subscription_id=subscription.id,
            )

        except ValueError as e:
            return ImportItemResult(
                link=link,
                success=False,
                message=f"无效的 URL: {e}",
            )
        except Exception as e:
            return ImportItemResult(
                link=link,
                success=False,
                message=f"导入失败: {e}",
            )
