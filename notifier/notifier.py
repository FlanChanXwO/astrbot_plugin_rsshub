"""
RSS-to-AstrBot Notifier
Message notify orchestration for RSS updates.
"""

from __future__ import annotations

from astrbot.api import logger

from ..db import Feed, Sub, User
from ..parsing import PostFormatter, parse_entry
from .senders import (
    ChannelInfo,
    MessageSender,
    NotifierContext,
    get_sender_for_platform_name,
)


class Notifier:
    """RSS update notifier orchestrating formatting and platform sender strategy."""

    def __init__(
        self,
        feed: Feed | None = None,
        subs: list[Sub] | None = None,
        entries: list | None = None,
        reason: str | None = None,
        timeout_seconds: int = 30,
        proxy: str = "",
        download_media_before_send: bool = True,
    ):
        self.feed = feed
        self.subs = subs or []
        self.entries = entries or []
        self.reason = reason
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.proxy = proxy or ""
        self.download_media_before_send = bool(download_media_before_send)

    def _build_context(self, sub: Sub) -> NotifierContext:
        """构建通知上下文"""
        channel = ChannelInfo(
            title=self.feed.title if self.feed else "",
            link=self.feed.link if self.feed else "",
        )
        return NotifierContext(
            channel=channel,
            platform_name=sub.platform_name or "",
        )

    async def notify_all(self) -> None:
        if not self.subs:
            return

        if self.reason and self.feed:
            await self._notify_error()
            return

        for entry in self.entries:
            await self._notify_entry(entry)

    async def _notify_error(self) -> None:
        if not self.feed or not self.reason:
            return

        message = (
            "RSS源监控失败\n\n"
            f"源: {self.feed.title}\n"
            f"链接: {self.feed.link}\n"
            f"原因: {self.reason}\n\n"
            "已自动停用该源。"
        )

        for sub in self.subs:
            try:
                user = await User.get_or_create(sub.user_id)
                session_id = self._resolve_target_session(sub, user)
                if not session_id:
                    await self._mark_binding_needed(sub.user_id)
                    logger.warning(
                        "错误通知缺少推送目标: sub=%s, user=%s",
                        sub.id,
                        sub.user_id,
                    )
                    continue

                sender = get_sender_for_platform_name(sub.platform_name)
                sender.configure_runtime(
                    timeout_seconds=self.timeout_seconds,
                    proxy=self.proxy,
                )
                context = self._build_context(sub)
                result = await sender.send_to_user(
                    session_id,
                    message,
                    context=context,
                )
                if not result.ok:
                    if result.needs_rebind:
                        await self._mark_binding_needed(sub.user_id)
                    logger.warning(
                        "错误通知发送失败: sub=%s, session=%s, rebind=%s, transient=%s, detail=%s",
                        sub.id,
                        session_id,
                        result.needs_rebind,
                        result.transient,
                        result.detail,
                    )
                else:
                    logger.debug("已发送错误通知给用户 %s", sub.user_id)
            except Exception as err:
                logger.error("发送错误通知失败: %s", err)

    async def _notify_entry(self, entry) -> None:
        if not self.feed:
            return

        try:
            entry_parsed = await parse_entry(entry, self.feed.link)

            formatter = PostFormatter(
                html=entry_parsed.content or entry_parsed.summary,
                title=entry_parsed.title,
                feed_title=self.feed.title,
                link=entry_parsed.link,
                author=entry_parsed.author,
                tags=entry_parsed.tags,
                feed_link=self.feed.link,
                enclosures=entry_parsed.enclosures,
            )

            for sub in self.subs:
                try:
                    await self._send_to_subscriber(sub, formatter, entry_parsed)
                except Exception as err:
                    logger.error(
                        "发送更新通知给订阅者 %s 失败: %s",
                        sub.user_id,
                        err,
                    )

        except Exception as err:
            logger.error("处理条目通知失败: %s", err, exc_info=True)

    async def _send_to_subscriber(
        self, sub: Sub, formatter: PostFormatter, entry_parsed
    ) -> None:
        user = await User.get_or_create(sub.user_id)
        effective = Sub.resolve_effective_options(sub, user)

        if effective["notify"] == 0:
            return

        formatted = await formatter.get_formatted_post(
            sub_title=sub.title,
            tags=sub.tags.split(" ") if sub.tags else [],
            send_mode=effective["send_mode"],
            length_limit=effective["length_limit"],
            link_preview=effective["link_preview"],
            display_author=effective["display_author"],
            display_via=effective["display_via"],
            display_title=effective["display_title"],
            display_entry_tags=effective["display_entry_tags"],
            style=effective["style"],
            display_media=effective["display_media"],
        )

        if not formatted:
            return

        content, need_media, _need_link_preview = formatted

        media_items: list[tuple[str, str]] = []
        if need_media and formatter.media:
            for media in formatter.media:
                media_items.append((media.type, media.url))

        prepared_media = None
        if media_items and self.download_media_before_send:
            MessageSender.configure_runtime(
                timeout_seconds=self.timeout_seconds,
                proxy=self.proxy,
            )
            MessageSender.configure_behavior(download_media_before_send=True)
            prepared_media = await MessageSender.prepare_media(media_items)

        session_id = self._resolve_target_session(sub, user)
        if not session_id:
            await self._mark_binding_needed(sub.user_id)
            logger.warning("订阅缺少推送目标: sub=%s, user=%s", sub.id, sub.user_id)
            return

        sender_platform_name = (sub.platform_name or "").strip()
        if not sender_platform_name and session_id:
            sender_platform_name = session_id.split(":", 1)[0]

        sender = get_sender_for_platform_name(sender_platform_name)
        logger.debug(
            "Push strategy selected: platform=%s, sender=%s, has_media=%s, prepared_media=%s, session=%s",
            sender_platform_name or sub.platform_name,
            sender.__name__,
            bool(media_items),
            bool(prepared_media),
            session_id,
        )
        sender.configure_runtime(
            timeout_seconds=self.timeout_seconds,
            proxy=self.proxy,
        )
        sender.configure_behavior(
            download_media_before_send=(
                self.download_media_before_send and prepared_media is None
            )
        )
        sent = await sender.send_to_user(
            session_id,
            content,
            media_items if media_items else None,
            prepared_media=prepared_media,
            context=self._build_context(sub),
        )
        if not sent.ok:
            if sent.needs_rebind:
                await self._mark_binding_needed(sub.user_id)
                logger.warning(
                    "推送失败，需要用户重新绑定目标: sub=%s, session=%s, detail=%s",
                    sub.id,
                    session_id,
                    sent.detail,
                )
            else:
                logger.warning(
                    "推送失败(非绑定问题): sub=%s, session=%s, transient=%s, detail=%s",
                    sub.id,
                    session_id,
                    sent.transient,
                    sent.detail,
                )
            return

        logger.debug("已发送更新通知给用户 %s: %s", sub.user_id, entry_parsed.title)

    @staticmethod
    def _resolve_target_session(sub: Sub, user: User) -> str | None:
        if sub.target_session:
            return sub.target_session
        if user.default_target_session:
            return user.default_target_session
        return None

    @staticmethod
    async def _mark_binding_needed(user_id: int) -> None:
        try:
            await User.mark_binding_notice(user_id)
        except Exception as ex:
            logger.error("标记用户绑定提示失败: %s, %s", user_id, ex)
