"""
订阅 Feed 命令

处理用户订阅 RSS 源的业务用例。
"""

from ...domain.entities.feed import Feed
from ...domain.entities.handlers import parse_handlers_input
from ...domain.entities.subscription import SUPPORTED_HANDLERS_MODES
from ...domain.repositories.feed_repository import FeedRepository
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ...domain.repositories.user_repository import UserRepository
from ...domain.value_objects.feed_url import FeedUrl
from ...infrastructure.config import FeedFetchSettings, validate_interval_value
from ...infrastructure.utils import get_logger
from ..dto.result_dto import CommandResult
from ..dto.subscription_dto import SubscriptionDTO
from ..ports import FeedFetcherFactory

logger = get_logger()


def _format_fetch_error(error: object) -> str:
    """格式化抓取错误，尽量保留 HTTP 状态与底层原因。"""
    if error is None:
        return "未知抓取错误"

    error_name = str(getattr(error, "error_name", "") or "抓取错误")
    status = str(getattr(error, "status", "") or "").strip()
    base_error = getattr(error, "base_error", None)
    detail_parts: list[str] = []

    if status:
        detail_parts.append(status)
    if base_error is not None:
        detail_parts.append(str(base_error))

    if detail_parts:
        detail = "; ".join(part for part in detail_parts if part)
        return f"{error_name} ({detail})"
    return error_name


def _display_fetch_url(web_feed: object, fallback_url: str) -> str:
    candidate = getattr(web_feed, "url", None)
    if isinstance(candidate, str) and candidate.strip():
        return candidate
    return fallback_url


class SubscribeFeedCommand:
    """
    订阅 Feed 命令

    处理用户订阅 RSS 源的业务用例。
    """

    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        feed_repo: FeedRepository,
        fetch_settings: FeedFetchSettings | None = None,
        fetcher_factory: FeedFetcherFactory | None = None,
        user_repo: UserRepository | None = None,
    ):
        self._subscription_repo = subscription_repo
        self._feed_repo = feed_repo
        self._fetch_settings = fetch_settings or FeedFetchSettings()
        self._fetcher_factory = fetcher_factory
        self._user_repo = user_repo

    async def execute(
        self,
        url: str,
        user_id: str,
        target_session: str | None = None,
        platform_name: str | None = None,
        session_defaults: dict[str, int | str] | None = None,
    ) -> CommandResult:
        """
        执行订阅命令

        Args:
            url: RSS 源 URL
            user_id: 用户 ID
            target_session: 推送目标会话（可选）
            platform_name: 平台类型名（可选）
            session_defaults: 会话默认配置（可选）

        Returns:
            CommandResult: 命令执行结果
        """
        if not url:
            return CommandResult(
                success=False,
                message="请提供 RSS 链接，用法：/sub <RSS 链接>",
            )

        if not url.startswith(("http://", "https://")):
            return CommandResult(
                success=False,
                message="请提供有效的 RSS 链接（需以 http 或 https 开头）",
            )

        try:
            feed_url = FeedUrl(url)
        except ValueError as e:
            return CommandResult(success=False, message=str(e))

        normalized_url = feed_url.normalized()
        logger.debug(
            "执行订阅抓取: original_url=%s, normalized_url=%s, user_id=%s, target_session=%s, platform=%s",
            url,
            normalized_url,
            user_id,
            target_session,
            platform_name,
        )

        if self._fetcher_factory is None:
            return CommandResult(
                success=False,
                message="订阅失败：RSS 抓取器未配置",
            )

        # 抓取 Feed 获取标题
        fetcher = self._fetcher_factory(
            timeout=self._fetch_settings.timeout,
            proxy=self._fetch_settings.proxy,
        )
        try:
            web_feed = await fetcher.fetch(normalized_url)
        except Exception as e:
            logger.warning("订阅抓取失败: %s", e)
            return CommandResult(
                success=False,
                message=f"订阅失败：无法获取 RSS 内容 ({e})",
            )
        finally:
            await fetcher.close()

        if web_feed.error:
            display_url = _display_fetch_url(web_feed, normalized_url)
            logger.debug(
                "订阅抓取返回错误: normalized_url=%s, final_url=%s, error_name=%s, status=%s",
                normalized_url,
                display_url,
                getattr(web_feed.error, "error_name", ""),
                getattr(web_feed.error, "status", None),
            )
            return CommandResult(
                success=False,
                message=(
                    "订阅失败："
                    f"{_format_fetch_error(web_feed.error)}"
                    f" | url={display_url}"
                ),
            )

        if web_feed.rss_d is None:
            display_url = _display_fetch_url(web_feed, normalized_url)
            logger.debug(
                "订阅抓取响应无法解析 RSS: normalized_url=%s, final_url=%s, status=%s",
                normalized_url,
                display_url,
                getattr(web_feed, "status", 0),
            )
            return CommandResult(
                success=False,
                message=f"订阅失败：无法解析 RSS 内容 | url={display_url}",
            )

        title = web_feed.rss_d.feed.get("title", url)

        normalized_user_id = str(user_id or "").strip()
        if self._user_repo is not None and normalized_user_id:
            await self._user_repo.get_or_create(normalized_user_id)
            user_id = normalized_user_id

        # 查找或创建 Feed
        feed = await self._feed_repo.get_by_link(normalized_url)
        if feed is None:
            feed = Feed(link=normalized_url, title=title)
            feed = await self._feed_repo.save(feed)
        elif not feed.title and title:
            feed.title = title
            feed = await self._feed_repo.save(feed)

        # 检查重复订阅（同用户 + 同 Feed + 同目标会话）
        existing = await self._subscription_repo.get_by_user_feed_session(
            user_id, feed.id, target_session
        )
        if existing:
            return CommandResult(
                success=False,
                message=f"您已经订阅了此源：{title}",
            )

        # 创建订阅
        from ...domain.entities.subscription import Subscription

        subscription = Subscription(
            user_id=user_id,
            feed_id=feed.id,
            target_session=target_session,
            platform_name=platform_name,
        )
        subscription = await self._subscription_repo.save(subscription)

        # 应用会话默认设置
        if session_defaults:
            update_payload = {}
            removed_keys = {
                "translate",
                "translate_target_lang",
                "use_sub_config",
                "use_user_config",
            }
            for key, raw_value in session_defaults.items():
                if key in removed_keys:
                    continue
                if key in {"title", "tags"}:
                    update_payload[key] = str(raw_value)
                elif key == "handlers_mode":
                    normalized = str(raw_value or "").strip().lower()
                    if normalized in SUPPORTED_HANDLERS_MODES:
                        update_payload[key] = normalized
                elif key == "handlers":
                    try:
                        update_payload[key] = parse_handlers_input(raw_value)
                    except ValueError:
                        pass
                else:
                    try:
                        if key == "interval":
                            update_payload[key] = validate_interval_value(
                                raw_value,
                                allow_inherit=False,
                                field_name="interval",
                            )
                        else:
                            update_payload[key] = int(raw_value)
                    except (ValueError, TypeError):
                        pass
            if update_payload:
                try:
                    await self._subscription_repo.update_options(
                        subscription.id, user_id, **update_payload
                    )
                except ValueError as exc:
                    return CommandResult(success=False, message=str(exc))

        return CommandResult(
            success=True,
            message=(
                f"订阅成功!\n"
                f"源标题：{title}\n"
                f"订阅 ID: {subscription.id}\n"
                f"推送目标：{target_session or '未设置'}"
            ),
            data=SubscriptionDTO(
                id=subscription.id,
                user_id=subscription.user_id,
                feed_id=subscription.feed_id,
                title=subscription.title,
                tags=subscription.tags,
                target_session=subscription.target_session,
                platform_name=subscription.platform_name,
                state=subscription.state,
                created_at=subscription.created_at,
                updated_at=subscription.updated_at,
            ),
        )
