"""测试订阅命令

处理测试订阅推送的业务用例。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
except Exception:  # pragma: no cover - lightweight test fallback

    class AstrMessageEvent:  # type: ignore[no-redef]
        unified_msg_origin: str = ""


from ...domain.entities.content_types import AudioContent, VideoContent
from ...domain.repositories.feed_repository import FeedRepository
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ..dto.feed_dto import FeedDTO
from ..dto.result_dto import CommandResult
from ..dto.subscription_dto import SubscriptionDTO
from ..ports import FeedFetcher, FeedParser
from ..services.content_handlers import EntryContentContext
from ..services.feed_polling_service import FeedPollingService, FeedReadResult
from ..services.html_parser import HTMLParser
from ..services.notification_dispatcher import NotificationDispatcher, SendTarget


@dataclass
class TestResult:
    """测试结果"""

    feed_info: FeedDTO | None
    entry_count: int
    sample_entries: list[dict]


class TestSubscriptionCommand:
    """测试订阅命令

    处理测试订阅推送的业务用例。
    获取 Feed 并返回示例条目，不存储到数据库。
    """

    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        feed_repo: FeedRepository,
        fetcher: FeedFetcher | None = None,
        parser: FeedParser | None = None,
        polling_service: FeedPollingService | None = None,
        notification_dispatcher: NotificationDispatcher | None = None,
    ):
        self._subscription_repo = subscription_repo
        self._feed_repo = feed_repo
        self._fetcher = fetcher
        self._parser = parser
        self._polling_service = polling_service
        self._notification_dispatcher = notification_dispatcher

    async def execute(
        self,
        sub_id: int,
        user_id: str,
        sample_count: int = 3,
    ) -> CommandResult:
        """执行测试订阅命令

        Args:
            sub_id: 订阅 ID
            user_id: 用户 ID
            sample_count: 返回的示例条目数量

        Returns:
            CommandResult: 命令执行结果
        """
        # 1. 验证订阅存在且属于用户
        subscription = await self._subscription_repo.get_by_id(sub_id)
        if not subscription:
            return CommandResult(
                success=False,
                message=f"订阅不存在 (ID: {sub_id})",
            )

        if subscription.user_id != user_id:
            return CommandResult(
                success=False,
                message="无权操作此订阅",
            )

        # 2. 获取 Feed
        feed = await self._feed_repo.get_by_id(subscription.feed_id)
        if not feed:
            return CommandResult(
                success=False,
                message=f"Feed 不存在 (ID: {subscription.feed_id})",
            )

        # 3. 抓取并解析 Feed
        read_result = await self._fetch_entries(feed.link)
        if not read_result.success:
            return CommandResult(success=False, message=read_result.message)

        web_feed = read_result.web_feed
        entries = read_result.entries
        if not entries:
            return CommandResult(
                success=False,
                message="Feed 中没有条目",
            )

        # 5. 构建结果
        feed_meta = self._feed_meta(web_feed)
        feed_dto = FeedDTO(
            id=feed.id,
            link=feed.link,
            title=feed.title or feed_meta.get("title", "未知"),
            state=feed.state,
            etag=feed.etag,
            last_modified=feed.last_modified,
            created_at=feed.created_at,
            updated_at=feed.updated_at,
        )

        # 提取示例条目
        sample_entries = []
        for entry in entries[:sample_count]:
            sample_entries.append(
                {
                    "title": entry.title,
                    "link": entry.link,
                    "summary": entry.summary[:200] + "..."
                    if entry.summary and len(entry.summary) > 200
                    else entry.summary,
                    "author": entry.author,
                    "published": entry.published.isoformat()
                    if entry.published
                    else None,
                }
            )

        result = TestResult(
            feed_info=feed_dto,
            entry_count=len(entries),
            sample_entries=sample_entries,
        )

        subscription_dto = SubscriptionDTO(
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
        )

        return CommandResult(
            success=True,
            message=f"测试成功! Feed 共有 {len(entries)} 个条目",
            data={
                "subscription": subscription_dto,
                "test_result": result,
            },
        )

    async def execute_target(
        self,
        target: str,
        user_id: str,
        target_session: str,
        platform_name: str,
        start: int = 1,
        end: int = 1,
        event: AstrMessageEvent | object | None = None,
    ) -> CommandResult:
        """按订阅 ID 或 URL 测试并真实推送到当前会话。"""
        if start <= 0 or end <= 0 or end < start:
            return CommandResult(success=False, message="条目范围无效，编号从 1 开始")

        if not target_session:
            return CommandResult(success=False, message="当前会话为空，无法推送")

        feed_url = ""
        feed_title = ""
        feed = None
        subscription = None
        if target.isdigit():
            subscription = await self._subscription_repo.get_by_id(int(target))
            if not subscription:
                return CommandResult(
                    success=False,
                    message=f"订阅不存在 (ID: {target})",
                )
            if subscription.user_id != user_id:
                return CommandResult(success=False, message="无权操作此订阅")
            feed = await self._feed_repo.get_by_id(subscription.feed_id)
            if not feed:
                return CommandResult(success=False, message="订阅对应的 Feed 不存在")
            feed_url = feed.link
            feed_title = str(feed.title or "").strip()
        else:
            parsed = urlparse(target)
            if parsed.scheme not in {"http", "https"}:
                return CommandResult(
                    success=False, message="目标必须是订阅 ID 或 http/https URL"
                )
            feed_url = target

        read_result = await self._fetch_entries(feed_url)
        if not read_result.success:
            return CommandResult(success=False, message=read_result.message)

        entries = read_result.entries
        if not entries:
            return CommandResult(success=False, message="Feed 中没有条目")
        if end > len(entries):
            return CommandResult(
                success=False,
                message=f"条目范围超出上限，当前仅有 {len(entries)} 条",
            )

        selected = entries[start - 1 : end]
        if self._notification_dispatcher is None:
            return CommandResult(success=False, message="推送服务未初始化")

        pushed = 0
        entered_chain = 0
        skipped = 0
        failed = 0
        failure_reasons: list[str] = []
        for entry in selected:
            title = entry.title or ""
            raw_content = entry.content or entry.summary or ""
            parsed = await HTMLParser(raw_content, feed_link=feed_url).parse()
            plain_summary = parsed.html_tree.get_plain().strip()
            if any(isinstance(m, (AudioContent, VideoContent)) for m in parsed.media):
                plain_summary = FeedPollingService._remove_media_placeholders(
                    plain_summary
                )
            entry_link = getattr(entry, "link", "") or feed_url
            feed_meta = self._feed_meta(read_result.web_feed)
            effective_feed_title = (
                feed_title or str(feed_meta.get("title", "") or "").strip() or feed_url
            )
            author = str(getattr(entry, "author", "") or "").strip()
            media_urls = [m.url for m in parsed.media if getattr(m, "url", "")]
            media_urls.extend(
                str(enclosure.url)
                for enclosure in (getattr(entry, "enclosures", None) or [])
                if getattr(enclosure, "url", "")
            )
            media_urls = list(dict.fromkeys(media_urls))
            media_items = FeedPollingService._media_items_from_parsed(parsed.media)
            tags = tuple(getattr(entry, "tags", []) or ())
            content = await FeedPollingService._format_dispatch_content_async(
                title=title,
                body=plain_summary,
                link=entry_link,
                feed_title=effective_feed_title,
                feed_link=feed_url,
                author=author,
                tags=tags,
            )

            if subscription is not None and feed is not None:
                stats = (
                    await self._notification_dispatcher.dispatch_to_feed_subscribers(
                        feed_id=feed.id,
                        content=content,
                        entry_title=title,
                        entry_link=entry_link,
                        feed_title=effective_feed_title,
                        feed_link=feed_url,
                        media_urls=media_urls,
                        media_items=media_items,
                        entry_guid=str(
                            getattr(entry, "guid", "") or entry_link or title
                        ),
                        subscription_ids=[subscription.id],
                        raw_entry=EntryContentContext(
                            title=title,
                            summary=str(entry.summary or raw_content or "").strip(),
                            content=str(raw_content or "").strip(),
                            link=entry_link,
                            author=author,
                            feed_title=effective_feed_title,
                            feed_link=feed_url,
                            raw_xml=str(getattr(entry, "raw_xml", "") or "").strip(),
                            media_urls=tuple(media_urls),
                            media_items=tuple(media_items),
                            layout=tuple(parsed.layout),
                        ),
                        include_inactive_subscription_ids=True,
                        bypass_success_dedup=True,
                        event=event,
                        include_error_detail=True,
                    )
                )
                if stats.get("success", 0) > 0 or stats.get("pending", 0) > 0:
                    entered_chain += 1
                    if stats.get("success", 0) > 0:
                        pushed += 1
                    skipped += stats.get("skipped", 0)
                    continue
                if stats.get("failed", 0) > 0:
                    entered_chain += 1
                    failed += stats.get("failed", 0)
                    reason = str(stats.get("last_error") or "").strip()
                    if reason:
                        failure_reasons.append(reason)
                    continue
                if stats.get("skipped", 0) > 0:
                    entered_chain += 1
                    skipped += stats.get("skipped", 0)
                    continue
                continue

            send_result = await self._notification_dispatcher.send_to_session(
                target=SendTarget(
                    user_id=user_id,
                    platform_name=platform_name,
                    target_session=target_session,
                    sub_id=0,
                ),
                content=content,
                media_urls=media_urls,
                media_items=media_items,
                layout=list(parsed.layout),
                job_description=f"sub_test target={target}",
                channel_title=effective_feed_title,
                channel_link=feed_url,
                entry_title=title,
                entry_link=entry_link,
            )
            if send_result.get("ok"):
                pushed += 1
            else:
                reason = str(send_result.get("error") or "").strip()
                if reason:
                    failure_reasons.append(reason)

        if subscription is not None:
            if entered_chain == 0:
                return CommandResult(
                    success=False,
                    message=(
                        "测试推送未进入正式发送链路，可能因通知关闭、被 handler 过滤或条目已去重"
                    ),
                )
            if pushed == 0 and failed > 0:
                reason = f": {failure_reasons[0]}" if failure_reasons else ""
                return CommandResult(
                    success=False,
                    message=f"测试推送发送失败{reason}",
                )
            note = ""
            if pushed == 0 and skipped > 0:
                note = "（本次未实际发送，可能因通知关闭、被 handler 过滤或条目已去重）"
            return CommandResult(
                success=True,
                message=(
                    f"已触发测试推送: {entered_chain}/{len(selected)} 条进入正式链路"
                    f"（成功 {pushed} 条，最新 {len(selected)} 条）{note}"
                ),
            )
        if pushed == 0 and failure_reasons:
            return CommandResult(
                success=False,
                message=f"测试推送发送失败: {failure_reasons[0]}",
            )
        return CommandResult(
            success=pushed > 0,
            message=f"已触发测试推送: {pushed}/{len(selected)} 条成功（最新 {len(selected)} 条）",
        )

    async def execute_by_url(
        self,
        url: str,
        sample_count: int = 3,
    ) -> CommandResult:
        """通过 URL 测试 Feed（不需要订阅）

        Args:
            url: Feed URL
            sample_count: 返回的示例条目数量

        Returns:
            CommandResult: 命令执行结果
        """
        # 1. 抓取并解析 Feed
        read_result = await self._fetch_entries(url)
        if not read_result.success:
            return CommandResult(success=False, message=read_result.message)

        web_feed = read_result.web_feed
        entries = read_result.entries
        if not entries:
            return CommandResult(
                success=False,
                message="Feed 中没有条目",
            )

        # 3. 构建结果
        feed_meta = self._feed_meta(web_feed)
        now = datetime.now(timezone.utc)
        feed_dto = FeedDTO(
            id=0,  # 临时 ID
            link=url,
            title=feed_meta.get("title", "未知"),
            created_at=now,
            updated_at=now,
        )

        # 提取示例条目
        sample_entries = []
        for entry in entries[:sample_count]:
            sample_entries.append(
                {
                    "title": entry.title,
                    "link": entry.link,
                    "summary": entry.summary[:200] + "..."
                    if entry.summary and len(entry.summary) > 200
                    else entry.summary,
                    "author": entry.author,
                    "published": entry.published.isoformat()
                    if entry.published
                    else None,
                }
            )

        result = TestResult(
            feed_info=feed_dto,
            entry_count=len(entries),
            sample_entries=sample_entries,
        )

        return CommandResult(
            success=True,
            message=f"测试成功! Feed 共有 {len(entries)} 个条目",
            data={"test_result": result},
        )

    async def _fetch_entries(self, url: str) -> FeedReadResult:
        if self._polling_service is not None:
            return await self._polling_service.fetch_feed_entries(url, verbose=True)

        if self._fetcher is None or self._parser is None:
            raise RuntimeError("TestSubscriptionCommand requires feed read ports")

        try:
            web_feed = await self._fetcher.fetch(url)
        except Exception as e:
            return FeedReadResult(
                success=False,
                status="fetch_error",
                message=f"抓取失败: {e}",
                error=str(e),
            )

        if web_feed.error:
            return FeedReadResult(
                success=False,
                status="fetch_error",
                message=f"抓取失败: {web_feed.error}",
                web_feed=web_feed,
                error=str(web_feed.error),
            )

        try:
            entries, parse_error = self._parser.parse(web_feed.content)
        except Exception as e:
            return FeedReadResult(
                success=False,
                status="parse_error",
                message=f"解析失败: {e}",
                web_feed=web_feed,
                error=str(e),
            )

        if parse_error:
            return FeedReadResult(
                success=False,
                status="parse_error",
                message=f"解析失败: {parse_error}",
                web_feed=web_feed,
                error=parse_error,
            )

        return FeedReadResult(
            success=True,
            status="fetched",
            message=f"抓取完成，发现 {len(entries)} 个条目",
            entries=entries,
            web_feed=web_feed,
        )

    @staticmethod
    def _feed_meta(web_feed) -> dict:
        rss_d = getattr(web_feed, "rss_d", None)
        feed_meta = getattr(rss_d, "feed", {}) if rss_d else {}
        return feed_meta if hasattr(feed_meta, "get") else {}
