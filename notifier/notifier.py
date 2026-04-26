"""
RSS-to-AstrBot Notifier
Message notify orchestration for RSS updates.
"""

from __future__ import annotations

from datetime import datetime

import aiohttp

from ..config import cfg
from ..db import Feed, PushHistory, Sub, User
from ..parsing import get_formatter_for_platform, parse_entry
from ..translation import TranslationManager
from ..utils.log_utils import logger
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
        self._user_cache: dict[str, User] = {}
        self._stats = {
            "pending_count": 0,
            "success_count": 0,
            "failed_count": 0,
        }
        # 主动初始化翻译管理器（避免懒加载导致的延迟）
        _ = self.translation_manager

    @property
    def translation_manager(self) -> TranslationManager | None:
        """Lazy initialization of translation manager."""
        if self._translation_manager is None and cfg:
            # Get translation config from cfg
            trans_config = cfg.translation
            logger.debug(
                f"Notifier.translation_manager: 创建翻译管理器，"
                f"provider={trans_config.provider}, auto_translate={trans_config.auto_translate}, "
                f"proxy={'configured' if self.proxy else '无'}"
            )
            # Create aiohttp session with proxy if configured
            if self.proxy:
                self._translation_session = aiohttp.ClientSession(proxy=self.proxy)
            else:
                self._translation_session = aiohttp.ClientSession()

            self._translation_manager = TranslationManager(self._translation_session)
            logger.debug(
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
        self._user_cache.clear()

    async def _get_user(self, user_id: str) -> User:
        """Get or create a User, caching results within this Notifier instance."""
        if user_id not in self._user_cache:
            self._user_cache[user_id] = await User.get_or_create(user_id)
        return self._user_cache[user_id]

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
                user = await self._get_user(sub.user_id)
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
        user = await self._get_user(sub.user_id)
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
            translate_enabled = 1 if cfg.translation.auto_translate else 0

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
        # 创建推送历史记录（pending 状态）
        history = None
        if self.feed:
            media_urls = [url for _, url in media_items] if media_items else []
            history = await PushHistory.create(
                sub_id=sub.id or 0,
                user_id=sub.user_id,
                feed_id=self.feed.id or 0,
                content=content,
                media_urls=media_urls,
                entry_title=entry_parsed.title or "",
                entry_link=entry_parsed.link or "",
                entry_guid=entry_parsed.guid,
                feed_title=self.feed.title,
                feed_link=self.feed.link,
                platform_name=sub.platform_name,
                target_session=session_id,
                status="pending",
            )
            self._stats["pending_count"] += 1

        sent = await sender.send_to_user(
            session_id,
            content,
            media_items if media_items else None,
            prepared_media=prepared_media,
            context=self._build_context(sub),
        )

        if history:
            if sent.ok:
                # 推送成功
                await PushHistory.update_status(
                    history_id=history.id or 0,
                    status="success",
                    http_status=sent.http_status,
                    response_detail=sent.detail,
                )
                self._stats["success_count"] += 1
            else:
                # 推送失败
                fail_reason = sent.detail or "unknown"
                await PushHistory.update_status(
                    history_id=history.id or 0,
                    status="failed",
                    http_status=sent.http_status,
                    response_detail=sent.detail,
                    fail_reason=fail_reason,
                )
                # 增加重试计数
                await PushHistory.increment_retry(
                    history_id=history.id or 0,
                    fail_reason=fail_reason,
                )
                self._stats["failed_count"] += 1

                if sent.needs_rebind:
                    await self._mark_binding_needed(sub.user_id)
                    logger.warning(
                        "推送失败，需要用户重新绑定目标: sub=%s, session=%s, entry=%s, link=%s, detail=%s",
                        sub.id,
                        session_id,
                        entry_parsed.title,
                        entry_parsed.link,
                        sent.detail,
                    )
                else:
                    logger.warning(
                        "推送失败(非绑定问题): sub=%s, session=%s, entry=%s, link=%s, transient=%s, detail=%s",
                        sub.id,
                        session_id,
                        entry_parsed.title,
                        entry_parsed.link,
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
    async def _mark_binding_needed(user_id: str) -> None:
        try:
            await User.mark_binding_notice(user_id)
        except Exception as ex:
            logger.error("标记用户绑定提示失败: %s, %s", user_id, ex)
