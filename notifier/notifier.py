"""
RSS-to-AstrBot Notifier
Message notify orchestration for RSS updates.
"""

from __future__ import annotations

from datetime import datetime

import aiohttp

from ..config import cfg
from ..db import FailedNotification, Feed, Sub, User
from ..parsing import get_formatter_for_platform, parse_entry
from ..translation import TranslationManager
from ..utils.log_utils import logger
from ..utils.retry_helper import process_failed_notification
from .senders import (
    ChannelInfo,
    MessageSender,
    NotifierContext,
    get_sender_for_platform_name,
)


class Notifier:
    """RSS update notifier orchestrating formatting and platform sender strategy."""

    @staticmethod
    def _format_debug_datetime(value: datetime | None) -> str:
        if value is None:
            return ""
        return value.isoformat(sep=" ", timespec="seconds")

    def _build_debug_payload(self, entry_parsed) -> str:
        debug_lines = [
            "",
            "---",
            "[debug]",
            f"guid: {entry_parsed.guid or '(empty)'}",
            f"id: {entry_parsed.entry_id or '(empty)'}",
            f"link: {entry_parsed.link or '(empty)'}",
            "published: "
            f"{self._format_debug_datetime(entry_parsed.published) or '(empty)'}",
            "updated: "
            f"{self._format_debug_datetime(entry_parsed.updated) or '(empty)'}",
        ]
        return "\n".join(debug_lines)

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
        self._translation_manager: TranslationManager | None = None
        self._translation_session: aiohttp.ClientSession | None = None
        self._stats = {
            "enqueue_failed_count": 0,
            "failed_drop_count": 0,
            "failed_process_count": 0,
            "failed_process_success_count": 0,
            "failed_process_retry_count": 0,
            "failed_process_exhausted_count": 0,
        }

    @property
    def translation_manager(self) -> TranslationManager | None:
        """Lazy initialization of translation manager."""
        if self._translation_manager is None and cfg:
            # Get translation config from cfg
            trans_config = cfg.translation
            logger.info(
                f"Notifier.translation_manager: 创建翻译管理器，"
                f"provider={trans_config.provider}, auto_translate={trans_config.auto_translate}, "
                f"proxy={self.proxy or '无'}"
            )
            # Create aiohttp session with proxy if configured
            if self.proxy:
                self._translation_session = aiohttp.ClientSession(proxy=self.proxy)
                logger.info(f"Notifier: 创建带代理的翻译 session: {self.proxy}")
            else:
                self._translation_session = aiohttp.ClientSession()
                logger.warning("Notifier: 创建不带代理的翻译 session (proxy 为空)")

            self._translation_manager = TranslationManager(self._translation_session)
            logger.info(
                f"Notifier: 翻译管理器创建完成，enabled={self._translation_manager.is_enabled}, "
                f"session={self._translation_session is not None}"
            )
        elif self._translation_manager is None and not cfg:
            logger.warning("Notifier: 无法创建翻译管理器，cfg 未初始化")
        return self._translation_manager

    async def close(self) -> None:
        """Close the translation session."""
        if self._translation_session and not self._translation_session.closed:
            await self._translation_session.close()
            logger.debug("Notifier: Translation session closed")

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

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
                        "错误通知发送失败：sub=%s, session=%s, rebind=%s, "
                        "transient=%s, detail=%s",
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

            for sub in self.subs:
                try:
                    await self._send_to_subscriber(sub, entry_parsed)
                except Exception as err:
                    logger.error(
                        "发送更新通知给订阅者 %s 失败: %s",
                        sub.user_id,
                        err,
                    )

        except Exception as err:
            logger.error("处理条目通知失败: %s", err, exc_info=True)

    async def _send_to_subscriber(self, sub: Sub, entry_parsed) -> None:
        user = await User.get_or_create(sub.user_id)
        session_id = self._resolve_target_session(sub, user)
        sender_platform_name = (sub.platform_name or "").strip()
        if not sender_platform_name and session_id:
            sender_platform_name = session_id.split(":", 1)[0]

        effective = Sub.resolve_effective_options(sub, user)

        if effective["notify"] == 0:
            return

        # Determine if translation should be applied
        # translate=1: enable, 0: disable,
        # -100: inherit from global auto_translate
        translate_enabled = effective.get("translate", -100)
        if translate_enabled == -100:
            # Inherit from global auto_translate setting
            translate_enabled = (
                1 if cfg.translation.auto_translate else 0
            )

        logger.debug(
            f"Notifier._send_to_subscriber: translate_enabled={translate_enabled}, "
            f"effective_translate={effective.get('translate')}, "
            f"has_translation_manager={self.translation_manager is not None}"
        )

        formatter_cls = get_formatter_for_platform(sender_platform_name)
        formatter = formatter_cls(
            html=entry_parsed.content or entry_parsed.summary,
            title=entry_parsed.title,
            feed_title=self.feed.title,
            link=entry_parsed.link,
            author=entry_parsed.author,
            tags=entry_parsed.tags,
            feed_link=self.feed.link,
            enclosures=entry_parsed.enclosures,
        )

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
            translate=translate_enabled,
            translate_target_lang=effective.get("translate_target_lang"),
            translation_manager=self.translation_manager,
        )

        if not formatted:
            return

        content, need_media, _need_link_preview = formatted
        if cfg and cfg.debug_payload:
            content = f"{content}\n{self._build_debug_payload(entry_parsed)}"

        media_items: list[tuple[str, str]] = []
        if need_media and formatter.media:
            for media in formatter.media:
                media_items.append((media.type, media.url))

        session_id = self._resolve_target_session(sub, user)
        if not session_id:
            await self._mark_binding_needed(sub.user_id)
            logger.warning("订阅缺少推送目标: sub=%s, user=%s", sub.id, sub.user_id)
            return

        sender_platform_name = (sub.platform_name or "").strip()
        if not sender_platform_name and session_id:
            sender_platform_name = session_id.split(":", 1)[0]

        sender = get_sender_for_platform_name(sender_platform_name)
        should_pre_download = self.download_media_before_send

        prepared_media = None
        if media_items and should_pre_download:
            MessageSender.configure_runtime(
                timeout_seconds=self.timeout_seconds,
                proxy=self.proxy,
            )
            # Configure transcode settings from cfg
            gif_transcode_enabled = cfg.ffmpeg.gif_transcode if cfg else False
            gif_transcode_timeout = cfg.ffmpeg.gif_transcode_timeout if cfg else 60
            video_transcode_enabled = cfg.ffmpeg.video_transcode if cfg else False
            video_transcode_timeout = cfg.ffmpeg.video_transcode_timeout if cfg else 120
            logger.info(
                "Configuring sender transcode: gif=%s/%ss, video=%s/%ss",
                gif_transcode_enabled,
                gif_transcode_timeout,
                video_transcode_enabled,
                video_transcode_timeout,
            )
            MessageSender.configure_behavior(
                download_media_before_send=True,
                gif_transcode_enabled=gif_transcode_enabled,
                gif_transcode_timeout=gif_transcode_timeout,
                video_transcode_enabled=video_transcode_enabled,
                video_transcode_timeout=video_transcode_timeout,
            )
            prepared_media = await MessageSender.prepare_media(media_items)

        logger.debug(
            "Push strategy selected: platform=%s, sender=%s, has_media=%s, "
            "prepared_media=%s, session=%s",
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
        # Configure sender with transcode settings
        gif_transcode_enabled = cfg.ffmpeg.gif_transcode if cfg else False
        gif_transcode_timeout = cfg.ffmpeg.gif_transcode_timeout if cfg else 60
        video_transcode_enabled = cfg.ffmpeg.video_transcode if cfg else False
        video_transcode_timeout = cfg.ffmpeg.video_transcode_timeout if cfg else 120
        sender.configure_behavior(
            download_media_before_send=(should_pre_download and prepared_media is None),
            gif_transcode_enabled=gif_transcode_enabled,
            gif_transcode_timeout=gif_transcode_timeout,
            video_transcode_enabled=video_transcode_enabled,
            video_transcode_timeout=video_transcode_timeout,
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
                # Enqueue for retry when platform is available again
                await self._enqueue_failed_notification(
                    sub=sub,
                    user=user,
                    content=content,
                    media_items=media_items,
                    entry_title=entry_parsed.title,
                    entry_link=entry_parsed.link,
                    fail_reason=f"platform_or_session: {sent.detail}",
                )
            else:
                logger.warning(
                    "推送失败(非绑定问题): sub=%s, session=%s, transient=%s, detail=%s",
                    sub.id,
                    session_id,
                    sent.transient,
                    sent.detail,
                )
                # For transient errors, also enqueue for retry
                if sent.transient:
                    await self._enqueue_failed_notification(
                        sub=sub,
                        user=user,
                        content=content,
                        media_items=media_items,
                        entry_title=entry_parsed.title,
                        entry_link=entry_parsed.link,
                        fail_reason=f"transient: {sent.detail}",
                    )
            return

        # Success - check if there are pending retries for this subscription
        await self._process_failed_queue(sub, user)

        logger.debug("已发送更新通知给用户 %s: %s", sub.user_id, entry_parsed.title)

    @staticmethod
    def _resolve_target_session(sub: Sub, user: User) -> str | None:
        if sub.target_session:
            return sub.target_session
        if user.default_target_session:
            return user.default_target_session
        return None

    @staticmethod
    async def _mark_binding_needed(user_id: str) -> None:
        try:
            await User.mark_binding_notice(user_id)
        except Exception as ex:
            logger.error("标记用户绑定提示失败: %s, %s", user_id, ex)

    async def _enqueue_failed_notification(
        self,
        sub: Sub,
        user: User,
        content: str,
        media_items: list[tuple[str, str]] | None,
        entry_title: str | None,
        entry_link: str | None,
        fail_reason: str,
    ) -> None:
        """Enqueue a failed notification for retry."""
        try:
            # Get max capacity from cfg (default 50)
            max_capacity = cfg.failed_queue_capacity if cfg else 50

            # Skip if queue is disabled (capacity <= 0)
            if max_capacity <= 0:
                logger.debug(
                    "Failed notification queue disabled (capacity=%s), "
                    "dropping message",
                    max_capacity,
                )
                self._stats["failed_drop_count"] += 1
                return

            # Use cheaper capacity check to reduce DB load
            is_full = await FailedNotification.is_at_capacity(sub.id, max_capacity)
            if is_full:
                logger.warning(
                    "Failed notification queue full for sub=%s, dropping message",
                    sub.id,
                )
                self._stats["failed_drop_count"] += 1
                return

            # Build media URLs list
            media_urls = None
            if media_items:
                media_urls = [url for _, url in media_items if url]

            # Build options dict
            options = {}
            if sub.options:
                options = sub.options

            await FailedNotification.enqueue(
                sub_id=sub.id,
                user_id=sub.user_id,
                content=content,
                media_urls=media_urls,
                entry_title=entry_title,
                entry_link=entry_link,
                feed_title=self.feed.title if self.feed else None,
                feed_link=self.feed.link if self.feed else None,
                platform_name=sub.platform_name,
                target_session=sub.target_session or user.default_target_session,
                options=options,
                fail_reason=fail_reason,
            )
            self._stats["enqueue_failed_count"] += 1
            logger.info(
                "Enqueued failed notification for retry: sub=%s, reason=%s",
                sub.id,
                fail_reason,
            )
        except Exception as ex:
            self._stats["failed_drop_count"] += 1
            logger.error("Failed to enqueue notification: %s", ex)

    async def _process_failed_queue(
        self,
        sub: Sub,
        user: User,
    ) -> None:
        """Process pending failed notifications for this subscription."""
        try:
            # Get max retries from cfg
            max_retries = cfg.failed_queue_max_retries if cfg else 3

            # Process in bounded batches to avoid long blocking bursts
            pending = await FailedNotification.get_by_sub(sub.id, limit=10)
            if not pending:
                return

            logger.info(
                "Processing %d pending failed notifications for sub=%s",
                len(pending),
                sub.id,
            )

            for notif in pending:
                self._stats["failed_process_count"] += 1
                success, _detail = await process_failed_notification(
                    notif,
                    timeout_seconds=self.timeout_seconds,
                    proxy=self.proxy,
                    max_retries=max_retries,
                )
                if success:
                    self._stats["failed_process_success_count"] += 1
                    continue

                next_retry = notif.retry_count + 1
                if next_retry >= max_retries:
                    self._stats["failed_process_exhausted_count"] += 1
                else:
                    self._stats["failed_process_retry_count"] += 1

        except Exception as ex:
            logger.error("Failed to process failed queue for sub=%s: %s", sub.id, ex)
