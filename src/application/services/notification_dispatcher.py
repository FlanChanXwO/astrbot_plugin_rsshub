"""
通知分发服务

负责将 RSS 条目分发给订阅用户。
属于应用服务，负责编排领域服务和基础设施。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

try:
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
except Exception:  # pragma: no cover - lightweight test fallback

    class AstrMessageEvent:  # type: ignore[no-redef]
        unified_msg_origin: str = ""


from ...domain.entities.content_types import LayoutFragment, is_generated_media_url
from ...domain.entities.push_history import PushHistory
from ...domain.repositories.push_history_repository import PushHistoryRepository
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ...domain.repositories.user_repository import UserRepository
from ...infrastructure.config import BasicSettings, SubscriptionDefaults
from ...infrastructure.pipeline import (
    EffectivePushOptions,
    EntryFormatInput,
    EntryTextFormatter,
    MessageFormatter,
)
from ...infrastructure.utils import get_logger
from ...shared.constants import (
    INHERIT_VALUE,
    SEND_MODE_AUTO,
    SEND_MODE_DIRECT,
    SEND_MODE_LINK_ONLY,
    STYLE_ORIGINAL,
)
from ..ports import MessageContext, MessageSenderProvider, SendRequest
from .content_handlers import ContentHandlerRuntime, EntryContentContext
from .session_push_queue import PushJob, SessionPushQueue

logger = get_logger()
_message_formatter = MessageFormatter()
_entry_text_formatter = EntryTextFormatter()

# 不可恢复错误关键词（匹配时不计入重试，直接标记为 failed）
UNRECOVERABLE_ERROR_PATTERNS: tuple[str, ...] = (
    "no target session",
    "target session is empty",
    "invalid session",
    "session not found",
    "user banned",
    "user is banned",
    "permission denied",
    "no permission",
    "forbidden",
    "not found",
    "invalid target",
)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".m3u8")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac")
SUPPORTED_MEDIA_TYPES = {"image", "audio", "video", "file"}


@dataclass(frozen=True)
class SendTarget:
    """Minimal runtime target for a push operation."""

    user_id: str
    platform_name: str | None
    target_session: str | None
    sub_id: int | None = None


@dataclass(frozen=True)
class PreparedSubscriptionDispatch:
    """Resolved per-subscription payload ready for dedup and send."""

    subscription: Any
    processed_entry: EntryContentContext | None
    handler_trace: list[dict[str, Any]] | None
    effective_title: str
    effective_link: str
    effective_content: str
    effective_send_mode: int
    effective_style: int
    effective_media_urls: list[str] | None
    effective_media_items: list[tuple[str, str]] | None
    effective_layout: list[LayoutFragment] | None
    persisted_media_urls: list[str] | None


def is_unrecoverable_error(error: str) -> bool:
    """判断错误是否为不可恢复类型（永久性失败，不应重试）"""
    if not error:
        return False
    lower_error = error.lower()
    return any(pattern in lower_error for pattern in UNRECOVERABLE_ERROR_PATTERNS)


def infer_media_type(url: str) -> str:
    """Infer the message component type for a media URL.

    RSSHub often wraps source media as `...?url=<encoded source>`, so check both
    the visible path and wrapped URL query values before falling back to image.
    """
    candidates = [url]
    try:
        parsed = urlparse(url)
        candidates.append(unquote(parsed.path or ""))
        candidates.extend(parse_qs(parsed.query).get("url", []))
    except Exception:
        pass

    for candidate in candidates:
        lowered = unquote(candidate).lower()
        parsed_path = urlparse(lowered).path if "://" in lowered else lowered
        if parsed_path.endswith(IMAGE_EXTENSIONS):
            return "image"
        if parsed_path.endswith(VIDEO_EXTENSIONS):
            return "video"
        if parsed_path.endswith(AUDIO_EXTENSIONS):
            return "audio"

    return "image"


def normalize_media_items(
    media_urls: list[str] | None = None,
    media_items: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Build sender media tuples, preserving explicit types before URL inference."""
    normalized: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    def append(media_type: str, url: str) -> None:
        media_url = str(url or "").strip()
        if not media_url or media_url in seen_urls:
            return
        effective_type = str(media_type or "").strip().lower()
        if effective_type not in SUPPORTED_MEDIA_TYPES:
            effective_type = infer_media_type(media_url)
        normalized.append((effective_type, media_url))
        seen_urls.add(media_url)

    for media_type, media_url in media_items or []:
        append(media_type, media_url)

    for media_url in media_urls or []:
        append(infer_media_type(media_url), media_url)

    return normalized


def append_media_links_to_text(
    text: str,
    media_items: list[tuple[str, str]] | None = None,
    media_urls: list[str] | None = None,
) -> str:
    """Append original media URLs to text for failure-facing output."""
    normalized = normalize_media_items(media_urls=media_urls, media_items=media_items)
    normalized = [
        (media_type, url)
        for media_type, url in normalized
        if not is_generated_media_url(url)
    ]
    if not normalized:
        return text
    urls = [url for _media_type, url in normalized]
    if text and "媒体原始链接:" in text:
        existing_lines = {line.strip() for line in text.splitlines() if line.strip()}
        if "媒体原始链接:" in existing_lines and all(
            url in existing_lines for url in urls
        ):
            return text
    return _message_formatter._append_failed_links(text, urls)


def strip_appended_media_links_from_text(
    text: str,
    media_items: list[tuple[str, str]] | None = None,
    media_urls: list[str] | None = None,
) -> str:
    """Remove the failure-facing media URL suffix before retry send."""
    if not text:
        return text
    normalized = normalize_media_items(media_urls=media_urls, media_items=media_items)
    normalized = [
        (media_type, url)
        for media_type, url in normalized
        if not is_generated_media_url(url)
    ]
    if not normalized:
        return text

    suffix_lines = ["媒体原始链接:", *[url for _media_type, url in normalized]]
    lines = text.splitlines()
    if len(lines) < len(suffix_lines):
        return text
    if lines[-len(suffix_lines) :] != suffix_lines:
        return text

    trimmed_lines = lines[: -len(suffix_lines)]
    while trimmed_lines and not trimmed_lines[-1].strip():
        trimmed_lines.pop()
    return "\n".join(trimmed_lines)


def build_agent_entry_guid(
    *,
    source_key: str,
    user_id: str,
    target_session: str,
    title: str,
    link: str,
    xml: str,
    media_items: list[tuple[str, str]] | None = None,
) -> str:
    """Build a stable idempotency key for agent-originated pushes."""
    normalized_media = normalize_media_items(media_items=media_items)
    payload = "\n".join(
        [
            source_key.strip(),
            user_id.strip(),
            target_session.strip(),
            title.strip(),
            link.strip(),
            xml.strip(),
            *[f"{media_type}:{url}" for media_type, url in normalized_media],
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"agent:{digest}"


class NotificationDispatcher:
    """
    通知分发服务

    负责将 RSS 条目分发给订阅用户。
    """

    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        push_history_repo: PushHistoryRepository,
        sender_provider: MessageSenderProvider,
        user_repo: UserRepository | None = None,
        push_job_queue: SessionPushQueue | None = None,
        content_handler_runtime: ContentHandlerRuntime | None = None,
        subscription_defaults: SubscriptionDefaults | None = None,
        basic_settings: BasicSettings | None = None,
    ):
        self._subscription_repo = subscription_repo
        self._user_repo = user_repo
        self._push_history_repo = push_history_repo
        self._sender_provider = sender_provider
        self._push_job_queue = push_job_queue or SessionPushQueue()
        self._content_handler_runtime = (
            content_handler_runtime or ContentHandlerRuntime()
        )
        self._default_push_options = self._options_from_subscription_defaults(
            subscription_defaults or SubscriptionDefaults()
        )
        self._default_send_mode = self._send_mode_from_subscription_defaults(
            subscription_defaults or SubscriptionDefaults()
        )
        self._basic_settings = basic_settings or BasicSettings()

    @staticmethod
    def _target_from_subscription(subscription) -> SendTarget:
        return SendTarget(
            user_id=subscription.user_id,
            platform_name=subscription.platform_name,
            target_session=subscription.target_session,
            sub_id=subscription.id,
        )

    @staticmethod
    def _feed_source_key(feed_id: int, sub_id: int | None) -> str:
        return f"feed:{feed_id}:sub:{sub_id or 0}"

    async def _ensure_user(self, user_id: str | None) -> Any | None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id or self._user_repo is None:
            return None
        return await self._user_repo.get_or_create(normalized_user_id)

    @staticmethod
    def _normalize_send_mode_value(value: Any) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return SEND_MODE_AUTO
        if normalized in {SEND_MODE_LINK_ONLY, SEND_MODE_AUTO, SEND_MODE_DIRECT}:
            return normalized
        return SEND_MODE_AUTO

    @staticmethod
    def _send_mode_from_subscription_defaults(defaults: SubscriptionDefaults) -> int:
        value = getattr(defaults, "send_mode", "自动")
        if isinstance(value, str):
            return {
                "仅链接": SEND_MODE_LINK_ONLY,
                "自动": SEND_MODE_AUTO,
                "直接发送": SEND_MODE_DIRECT,
            }.get(
                value.strip(),
                SEND_MODE_AUTO,
            )
        return NotificationDispatcher._normalize_send_mode_value(value)

    @staticmethod
    def _options_from_subscription_defaults(
        defaults: SubscriptionDefaults,
    ) -> EffectivePushOptions:
        def display_value(
            value: Any, mapping: dict[str, int], fallback: int = 0
        ) -> int:
            if isinstance(value, str):
                return mapping.get(value.strip(), fallback)
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        return EffectivePushOptions(
            notify=bool(getattr(defaults, "notify", True)),
            length_limit=max(0, int(getattr(defaults, "length_limit", 0) or 0)),
            display_author=display_value(
                getattr(defaults, "display_author", "自动"),
                {"禁用": -1, "自动": 0, "强制": 1},
            ),
            display_via=display_value(
                getattr(defaults, "display_via", "自动"),
                {"完全禁用": -2, "仅链接": -1, "自动": 0, "强制": 1},
            ),
            display_title=display_value(
                getattr(defaults, "display_title", "自动"),
                {"禁用": -1, "自动": 0, "强制": 1},
            ),
            display_entry_tags=bool(getattr(defaults, "display_entry_tags", False)),
            style=display_value(
                getattr(defaults, "style", "auto"),
                {
                    "auto": 0,
                    "classic": 0,
                    "RSStT": 0,
                    "rssrt": 1,
                    "RSSRT": 1,
                    "flowerss": 0,
                    "original": 2,
                },
            ),
            display_media=bool(getattr(defaults, "display_media", True)),
        )

    def _resolve_send_mode(self, subscription: Any = None, user: Any = None) -> int:
        if subscription is not None:
            sub_value = getattr(subscription, "send_mode", INHERIT_VALUE)
            if sub_value != INHERIT_VALUE:
                return self._normalize_send_mode_value(sub_value)
        if user is not None:
            user_value = getattr(user, "send_mode", INHERIT_VALUE)
            if user_value != INHERIT_VALUE:
                return self._normalize_send_mode_value(user_value)
        return self._default_send_mode

    def _resolve_effective_push_options(
        self,
        subscription: Any = None,
        user: Any = None,
    ) -> EffectivePushOptions:
        defaults = self._default_push_options
        return EffectivePushOptions(
            notify=bool(
                self._resolve_option("notify", subscription, user, int(defaults.notify))
            ),
            length_limit=max(
                0,
                int(
                    self._resolve_option(
                        "length_limit", subscription, user, defaults.length_limit
                    )
                    or 0
                ),
            ),
            display_author=int(
                self._resolve_option(
                    "display_author", subscription, user, defaults.display_author
                )
                or 0
            ),
            display_via=int(
                self._resolve_option(
                    "display_via", subscription, user, defaults.display_via
                )
                or 0
            ),
            display_title=int(
                self._resolve_option(
                    "display_title", subscription, user, defaults.display_title
                )
                or 0
            ),
            display_entry_tags=bool(
                self._resolve_option(
                    "display_entry_tags",
                    subscription,
                    user,
                    0 if defaults.display_entry_tags else -1,
                )
                != -1
            ),
            style=int(
                self._resolve_option("style", subscription, user, defaults.style) or 0
            ),
            display_media=bool(
                self._resolve_option(
                    "display_media",
                    subscription,
                    user,
                    0 if defaults.display_media else -1,
                )
                != -1
            ),
        )

    @staticmethod
    def _resolve_option(
        key: str,
        subscription: Any = None,
        user: Any = None,
        default: Any = None,
    ) -> Any:
        for owner in (subscription, user):
            if owner is None or not hasattr(owner, key):
                continue
            value = getattr(owner, key)
            if value != INHERIT_VALUE:
                return value
        return default

    @staticmethod
    def _build_link_only_content(*, entry_title: str, entry_link: str) -> str:
        title = str(entry_title or "").strip()
        link = str(entry_link or "").strip()
        if title and link:
            return f"{title}\n{link}"
        return title or link

    def _default_failed_queue_max_retries(self) -> int:
        return max(0, int(self._basic_settings.failed_queue_max_retries or 0))

    async def _resolve_initial_failure_max_retries(self) -> int:
        default_limit = self._default_failed_queue_max_retries()
        if default_limit <= 0:
            return 0

        capacity = max(0, int(self._basic_settings.failed_queue_capacity or 0))
        if capacity <= 0:
            return 0

        count_retryable = getattr(
            self._push_history_repo,
            "count_retryable_failures",
            getattr(self._push_history_repo, "count_retryable", None),
        )
        if not callable(count_retryable):
            return default_limit

        try:
            active_retryable = await count_retryable()
            active_count = int(active_retryable)
        except Exception:
            active_count = 0
        return default_limit if active_count < capacity else 0

    @staticmethod
    def _payload_signature(
        prepared: PreparedSubscriptionDispatch,
    ) -> tuple[str, str, int, str, tuple[tuple[str, str], ...]]:
        return (
            str(prepared.subscription.target_session or ""),
            str(prepared.subscription.platform_name or ""),
            int(prepared.effective_send_mode),
            str(prepared.effective_content or ""),
            tuple(
                normalize_media_items(
                    media_urls=prepared.effective_media_urls,
                    media_items=prepared.effective_media_items,
                )
            ),
        )

    async def _save_skipped_history(
        self,
        *,
        subscription: Any,
        feed_id: int,
        processed_entry: EntryContentContext | None,
        persisted_media_urls: list[str] | None,
        handler_trace: list[dict[str, Any]] | None,
        effective_title: str,
        effective_link: str,
        effective_content: str,
        entry_guid: str | None,
        feed_title: str,
        feed_link: str,
        reason: str,
    ) -> None:
        history = PushHistory(
            sub_id=subscription.id,
            user_id=subscription.user_id,
            feed_id=feed_id,
            source_type="feed",
            source_key=self._feed_source_key(feed_id, subscription.id),
            content=effective_content,
            raw_xml=(
                str(processed_entry.raw_xml or "").strip()
                if processed_entry is not None
                else None
            )
            or None,
            media_urls=persisted_media_urls or None,
            handler_trace=handler_trace,
            entry_title=effective_title,
            entry_link=effective_link,
            entry_guid=entry_guid,
            feed_title=feed_title,
            feed_link=feed_link,
            platform_name=subscription.platform_name,
            target_session=subscription.target_session,
            status="skipped",
            retry_count=0,
            max_retries=0,
        )
        history.mark_skipped(reason)
        await self._push_history_repo.save(history)

    async def dispatch_to_feed_subscribers(
        self,
        feed_id: int,
        content: str,
        entry_title: str,
        entry_link: str,
        feed_title: str = "",
        feed_link: str = "",
        media_urls: list[str] | None = None,
        media_items: list[tuple[str, str]] | None = None,
        entry_guid: str | None = None,
        subscription_ids: list[int] | None = None,
        raw_entry: EntryContentContext | None = None,
        include_inactive_subscription_ids: bool = False,
        bypass_success_dedup: bool = False,
        event: AstrMessageEvent | Any | None = None,
        include_error_detail: bool = False,
    ) -> dict[str, Any]:
        """
        将条目分发给 Feed 的所有订阅者

        Args:
            feed_id: Feed ID
            content: 格式化后的消息内容
            entry_title: 条目标题
            entry_link: 条目链接
            feed_title: Feed 标题
            feed_link: Feed 链接
            media_urls: 媒体 URL 列表
            media_items: 已知类型的媒体列表，格式为 (image/audio/video/file, url)
            entry_guid: 条目 GUID
            subscription_ids: 限定分发的订阅 ID；为空时分发到所有活跃订阅

        Returns:
            统计信息字典 {success: x, failed: y, pending: y, skipped: z}
        """
        stats: dict[str, Any] = {"success": 0, "failed": 0, "pending": 0, "skipped": 0}

        def record_error_detail(error: object) -> None:
            if not include_error_detail:
                return
            text = str(error or "").strip()
            if text and not stats.get("last_error"):
                stats["last_error"] = text

        # 1. 获取 Feed 的所有启用订阅
        subscriptions = await self._subscription_repo.get_active_by_feed_id(feed_id)
        if subscription_ids is not None:
            wanted = set(subscription_ids)
            subscriptions = [sub for sub in subscriptions if sub.id in wanted]
            if include_inactive_subscription_ids:
                loaded_ids = {sub.id for sub in subscriptions}
                missing_ids = wanted - loaded_ids
                for sub_id in missing_ids:
                    sub = await self._subscription_repo.get_by_id(sub_id)
                    if sub is None or sub.feed_id != feed_id:
                        continue
                    subscriptions.append(sub)
        if not subscriptions:
            if subscription_ids is None:
                logger.debug("Feed %s 没有活跃的订阅", feed_id)
            else:
                logger.debug(
                    "Feed %s 没有匹配的活跃订阅: %s",
                    feed_id,
                    subscription_ids,
                )
            return stats

        logger.info(
            "分发条目到 %s 个订阅者: feed_id=%s, title=%s",
            len(subscriptions),
            feed_id,
            entry_title[:50],
        )

        normalized_media = normalize_media_items(
            media_urls=media_urls,
            media_items=media_items,
        )
        persisted_media_urls = [url for _media_type, url in normalized_media]
        prepared_dispatches: list[PreparedSubscriptionDispatch] = []

        # 2. 为每个订阅解析最终 payload；handler skip 在此阶段直接落审计记录。
        for sub in subscriptions:
            try:
                user = await self._ensure_user(sub.user_id)
                processed_entry = raw_entry
                handler_trace: list[dict[str, Any]] | None = None
                handler_allowed = True
                handler_reason = ""
                if raw_entry is not None:
                    handler_result = (
                        await self._content_handler_runtime.process_entry_with_trace(
                            subscription=sub,
                            user=user,
                            entry=raw_entry,
                            session_id=str(sub.target_session or "").strip() or None,
                            event=event,
                            target_session=str(sub.target_session or "").strip()
                            or None,
                            platform_name=str(sub.platform_name or "").strip() or None,
                            user_id=str(sub.user_id or "").strip() or None,
                        )
                    )
                    processed_entry = handler_result.entry
                    handler_allowed = handler_result.allow
                    handler_reason = handler_result.reason
                    handler_trace = list(handler_result.trace) or None

                effective_title = (
                    processed_entry.title
                    if processed_entry is not None
                    else entry_title
                )
                effective_link = (
                    processed_entry.link if processed_entry is not None else entry_link
                )
                effective_options = self._resolve_effective_push_options(sub, user)
                effective_content = await self._format_effective_entry_content(
                    fallback_content=content,
                    raw_entry=processed_entry,
                    entry_title=effective_title,
                    entry_link=effective_link,
                    feed_title=feed_title,
                    feed_link=feed_link,
                    options=effective_options,
                )
                if not effective_options.notify:
                    await self._save_skipped_history(
                        subscription=sub,
                        feed_id=feed_id,
                        processed_entry=processed_entry,
                        persisted_media_urls=(
                            persisted_media_urls
                            if effective_options.display_media and persisted_media_urls
                            else None
                        ),
                        handler_trace=handler_trace,
                        effective_title=effective_title,
                        effective_link=effective_link,
                        effective_content=effective_content,
                        entry_guid=entry_guid,
                        feed_title=feed_title,
                        feed_link=feed_link,
                        reason="notify disabled",
                    )
                    logger.debug("订阅 %s 已关闭通知，跳过条目推送", sub.id)
                    stats["skipped"] += 1
                    continue
                if not handler_allowed:
                    await self._save_skipped_history(
                        subscription=sub,
                        feed_id=feed_id,
                        processed_entry=processed_entry,
                        persisted_media_urls=(
                            persisted_media_urls
                            if effective_options.display_media and persisted_media_urls
                            else None
                        ),
                        handler_trace=handler_trace,
                        effective_title=effective_title,
                        effective_link=effective_link,
                        effective_content=effective_content,
                        entry_guid=entry_guid,
                        feed_title=feed_title,
                        feed_link=feed_link,
                        reason=handler_reason,
                    )
                    logger.info(
                        "订阅 %s 条目被 handler 跳过: %s",
                        sub.id,
                        handler_reason,
                    )
                    stats["skipped"] += 1
                    continue
                effective_send_mode = self._resolve_send_mode(sub, user)
                effective_media_urls = media_urls
                effective_media_items = media_items
                effective_layout = (
                    list(processed_entry.layout)
                    if processed_entry is not None and processed_entry.layout
                    else None
                )
                if not effective_options.display_media:
                    effective_media_urls = None
                    effective_media_items = None
                    effective_layout = None
                if effective_send_mode == SEND_MODE_LINK_ONLY:
                    effective_content = self._build_link_only_content(
                        entry_title=effective_title,
                        entry_link=effective_link,
                    )
                    effective_media_urls = None
                    effective_media_items = None
                    effective_layout = None
                effective_layout = self._limit_original_layout_text(
                    effective_layout,
                    style=effective_options.style,
                    length_limit=effective_options.length_limit,
                )

                # 发送前指纹保护（dispatch_guard）
                # 检查是否已有相同 entry_guid 的成功推送记录
                if entry_guid and not bypass_success_dedup:
                    already_sent = (
                        await self._push_history_repo.exists_success_by_scope_and_guid(
                            source_type="feed",
                            source_key=self._feed_source_key(feed_id, sub.id),
                            user_id=sub.user_id,
                            target_session=str(sub.target_session or ""),
                            entry_guid=entry_guid,
                        )
                    )
                    if already_sent:
                        await self._save_skipped_history(
                            subscription=sub,
                            feed_id=feed_id,
                            processed_entry=processed_entry,
                            persisted_media_urls=(
                                persisted_media_urls
                                if effective_options.display_media
                                and persisted_media_urls
                                else None
                            ),
                            handler_trace=handler_trace,
                            effective_title=effective_title,
                            effective_link=effective_link,
                            effective_content=effective_content,
                            entry_guid=entry_guid,
                            feed_title=feed_title,
                            feed_link=feed_link,
                            reason="dispatch guard: already successful entry_guid",
                        )
                        logger.debug(
                            "订阅 %s 已成功推送过条目 %s，跳过", sub.id, entry_guid
                        )
                        stats["skipped"] += 1
                        continue

                prepared_dispatches.append(
                    PreparedSubscriptionDispatch(
                        subscription=sub,
                        processed_entry=processed_entry,
                        handler_trace=handler_trace,
                        effective_title=effective_title,
                        effective_link=effective_link,
                        effective_content=effective_content,
                        effective_send_mode=effective_send_mode,
                        effective_style=effective_options.style,
                        effective_media_urls=effective_media_urls,
                        effective_media_items=effective_media_items,
                        effective_layout=effective_layout,
                        persisted_media_urls=(
                            persisted_media_urls
                            if effective_options.display_media and persisted_media_urls
                            else None
                        ),
                    )
                )

            except Exception as e:
                logger.error(
                    "分发到订阅 %s 失败: %s",
                    sub.id,
                    e,
                    exc_info=True,
                )
                stats["failed"] += 1
                record_error_detail(e)

        if self._basic_settings.deduplicate_multi_bot and prepared_dispatches:
            grouped: dict[
                tuple[str, str, int, str, tuple[tuple[str, str], ...]],
                list[PreparedSubscriptionDispatch],
            ] = {}
            for prepared in prepared_dispatches:
                grouped.setdefault(self._payload_signature(prepared), []).append(
                    prepared
                )

            suppressed_sub_ids: set[int] = set()
            for items in grouped.values():
                if len(items) <= 1:
                    continue
                winner = min(items, key=lambda item: int(item.subscription.id or 0))
                winner_sub_id = int(winner.subscription.id or 0)
                for prepared in items:
                    sub_id = int(prepared.subscription.id or 0)
                    if sub_id == winner_sub_id:
                        continue
                    suppressed_sub_ids.add(sub_id)
                    reason = f"multi-bot dedup: reused sub_id={winner_sub_id}"
                    await self._save_skipped_history(
                        subscription=prepared.subscription,
                        feed_id=feed_id,
                        processed_entry=prepared.processed_entry,
                        persisted_media_urls=prepared.persisted_media_urls,
                        handler_trace=prepared.handler_trace,
                        effective_title=prepared.effective_title,
                        effective_link=prepared.effective_link,
                        effective_content=prepared.effective_content,
                        entry_guid=entry_guid,
                        feed_title=feed_title,
                        feed_link=feed_link,
                        reason=reason,
                    )
                    logger.info(
                        "订阅 %s 命中多 BOT 去重，复用主订阅 %s",
                        sub_id,
                        winner_sub_id,
                    )
                    stats["skipped"] += 1

            prepared_dispatches = [
                prepared
                for prepared in prepared_dispatches
                if int(prepared.subscription.id or 0) not in suppressed_sub_ids
            ]

        # 3. 为候选订阅创建推送历史并发送
        for prepared in prepared_dispatches:
            sub = prepared.subscription
            try:
                history = PushHistory(
                    sub_id=sub.id,
                    user_id=sub.user_id,
                    feed_id=feed_id,
                    source_type="feed",
                    source_key=self._feed_source_key(feed_id, sub.id),
                    content=prepared.effective_content,
                    raw_xml=(
                        str(prepared.processed_entry.raw_xml or "").strip()
                        if prepared.processed_entry is not None
                        else None
                    )
                    or None,
                    media_urls=prepared.persisted_media_urls,
                    handler_trace=prepared.handler_trace,
                    entry_title=prepared.effective_title,
                    entry_link=prepared.effective_link,
                    entry_guid=entry_guid,
                    feed_title=feed_title,
                    feed_link=feed_link,
                    platform_name=sub.platform_name,
                    target_session=sub.target_session,
                    status="pending",
                    retry_count=0,
                    max_retries=self._default_failed_queue_max_retries(),
                )

                # 保存到数据库
                history = await self._push_history_repo.save(history)

                # 4. 调用消息发送器发送消息
                result = await self.send_to_session(
                    target=self._target_from_subscription(sub),
                    content=prepared.effective_content,
                    media_urls=prepared.effective_media_urls,
                    media_items=prepared.effective_media_items,
                    layout=prepared.effective_layout,
                    job_description=f"feed={feed_id}, sub={sub.id}",
                    channel_title=feed_title,
                    channel_link=feed_link,
                    entry_title=prepared.effective_title,
                    entry_link=prepared.effective_link,
                    feed_id=feed_id,
                    sub_id=sub.id,
                    send_mode=prepared.effective_send_mode,
                    style=prepared.effective_style,
                )

                # 5. 更新推送状态
                if result["ok"]:
                    history.mark_success()
                    stats["success"] += 1
                elif result.get("cancelled"):
                    history.mark_stopped(
                        result.get("error", "Stopped by System or Command")
                    )
                    history.max_retries = 0
                    stats["success"] += 1
                else:
                    record_error_detail(result.get("error"))
                    history.max_retries = (
                        await self._resolve_initial_failure_max_retries()
                    )
                    # 首次失败不增加重试计数
                    history.record_first_failure(result.get("error"))
                    history.content = append_media_links_to_text(
                        history.content,
                        media_urls=prepared.persisted_media_urls,
                        media_items=prepared.effective_media_items,
                    )
                    if history.can_retry():
                        stats["pending"] += 1
                    else:
                        stats["failed"] += 1

                await self._push_history_repo.save(history)

            except Exception as e:
                logger.error("发送订阅 %s 失败: %s", sub.id, e, exc_info=True)
                stats["failed"] += 1
                record_error_detail(e)

        logger.info(
            "分发完成: success=%s, failed=%s, pending=%s, skipped=%s",
            stats["success"],
            stats["failed"],
            stats["pending"],
            stats["skipped"],
        )
        return stats

    async def dispatch_agent_entry(
        self,
        *,
        source_key: str,
        target: SendTarget,
        content: str,
        raw_xml: str = "",
        entry_title: str,
        entry_link: str = "",
        feed_title: str = "",
        feed_link: str = "",
        media_urls: list[str] | None = None,
        media_items: list[tuple[str, str]] | None = None,
        entry_guid: str,
        layout: list[LayoutFragment] | None = None,
        send_mode: int | None = SEND_MODE_AUTO,
        style: int = 0,
    ) -> dict[str, Any]:
        """Dispatch one agent-originated push while preserving history and retries."""
        normalized_media = normalize_media_items(
            media_urls=media_urls,
            media_items=media_items,
        )
        persisted_media_urls = [url for _media_type, url in normalized_media]
        target_session = str(target.target_session or "").strip()
        if not target_session:
            return {"ok": False, "error": "No target session", "deduplicated": False}
        await self._ensure_user(target.user_id)

        already_sent = await self._push_history_repo.exists_success_by_scope_and_guid(
            source_type="agent",
            source_key=source_key,
            user_id=target.user_id,
            target_session=target_session,
            entry_guid=entry_guid,
        )
        if already_sent:
            return {
                "ok": True,
                "deduplicated": True,
                "stats": {"success": 0, "failed": 0, "pending": 0},
            }

        history = PushHistory(
            sub_id=None,
            user_id=target.user_id,
            feed_id=None,
            source_type="agent",
            source_key=source_key,
            content=content,
            raw_xml=str(raw_xml or "").strip() or None,
            media_urls=persisted_media_urls or None,
            entry_title=entry_title,
            entry_link=entry_link,
            entry_guid=entry_guid,
            feed_title=feed_title,
            feed_link=feed_link,
            platform_name=target.platform_name,
            target_session=target.target_session,
            status="pending",
            retry_count=0,
            max_retries=self._default_failed_queue_max_retries(),
        )
        history = await self._push_history_repo.save(history)

        result = await self.send_to_session(
            target=target,
            content=content,
            media_urls=media_urls,
            media_items=media_items,
            layout=layout,
            job_description=f"agent={source_key}, history={history.id}",
            channel_title=feed_title,
            channel_link=feed_link,
            entry_title=entry_title,
            entry_link=entry_link,
            feed_id=None,
            sub_id=None,
            send_mode=send_mode,
            style=style,
        )

        stats = {"success": 0, "failed": 0, "pending": 0}
        if result["ok"]:
            history.mark_success()
            stats["success"] = 1
        elif result.get("cancelled"):
            history.mark_stopped(result.get("error", "Stopped by System or Command"))
            history.max_retries = 0
            stats["success"] = 1
        else:
            history.max_retries = await self._resolve_initial_failure_max_retries()
            history.record_first_failure(result.get("error"))
            history.content = append_media_links_to_text(
                history.content,
                media_items=normalized_media,
            )
            stats["pending" if history.can_retry() else "failed"] = 1

        await self._push_history_repo.save(history)
        return {
            "ok": result["ok"],
            "deduplicated": False,
            "stats": stats,
            "history_id": history.id,
        }

    async def send_to_session(
        self,
        *,
        target: SendTarget,
        content: str,
        media_urls: list[str] | None,
        media_items: list[tuple[str, str]] | None = None,
        layout: list[LayoutFragment] | None = None,
        job_description: str = "",
        channel_title: str = "",
        channel_link: str = "",
        entry_title: str = "",
        entry_link: str = "",
        feed_id: int | None = None,
        sub_id: int | None = None,
        send_mode: int | None = None,
        style: int = 0,
        sender_strategy: Any = None,
    ) -> dict[str, Any]:
        return await self._send_to_session(
            target=target,
            content=content,
            media_urls=media_urls,
            media_items=media_items,
            layout=layout,
            job_description=job_description,
            channel_title=channel_title,
            channel_link=channel_link,
            entry_title=entry_title,
            entry_link=entry_link,
            feed_id=feed_id,
            sub_id=sub_id,
            send_mode=send_mode,
            style=style,
            sender_strategy=sender_strategy,
        )

    async def _send_to_session(
        self,
        *,
        target: SendTarget,
        content: str,
        media_urls: list[str] | None,
        media_items: list[tuple[str, str]] | None = None,
        layout: list[LayoutFragment] | None = None,
        job_description: str = "",
        channel_title: str = "",
        channel_link: str = "",
        entry_title: str = "",
        entry_link: str = "",
        feed_id: int | None = None,
        sub_id: int | None = None,
        send_mode: int | None = None,
        style: int = 0,
        sender_strategy: Any = None,
    ) -> dict[str, Any]:
        """
        发送通知到指定目标

        Args:
            target: 推送目标
            content: 消息内容
            media_urls: 媒体 URL 列表
            media_items: 已知类型的媒体列表，格式为 (image/audio/video/file, url)
            job_description: 任务描述，用于队列和日志

        Returns:
            发送结果 {"ok": bool, "error": str}
        """
        try:
            # 获取平台对应的发送器
            sender = self._sender_provider.get(target.platform_name)

            # 构建目标会话 ID
            target_session = target.target_session
            if not target_session:
                logger.warning("推送目标 %s 没有目标会话", target.user_id)
                return {"ok": False, "error": "No target session"}

            # 准备媒体；优先保留 HTML/RSS 已解析出的准确类型。
            normalized_media = normalize_media_items(
                media_urls=media_urls,
                media_items=media_items,
            )

            async def _send(job: PushJob):
                logger.debug(
                    "开始 RSS 推送任务: job_id=%s, session=%s, sub=%s",
                    job.job_id,
                    target_session,
                    target.sub_id,
                )
                return await sender.send_to_user(
                    SendRequest(
                        session_id=target_session,
                        message=content,
                        media=normalized_media if normalized_media else None,
                        layout=layout,
                    ),
                    context=MessageContext(
                        channel_title=channel_title,
                        channel_link=channel_link,
                        entry_title=entry_title,
                        entry_link=entry_link,
                        platform_name=target.platform_name or "",
                        send_mode=self._normalize_send_mode_value(send_mode),
                        style=style,
                        sender_strategy=sender_strategy,
                    ),
                )

            job_result = await self._push_job_queue.enqueue(
                target_session,
                _send,
                description=job_description,
                feed_id=feed_id,
                feed_title=channel_title or "",
                sub_id=sub_id,
            )

            if job_result.cancelled:
                logger.info(
                    "RSS 推送任务已取消: job_id=%s, session=%s, sub=%s",
                    job_result.job_id,
                    target_session,
                    target.sub_id,
                )
                return {
                    "ok": False,
                    "cancelled": True,
                    "error": f"Cancelled by System or Command (job_id={job_result.job_id})",
                    "job_id": job_result.job_id,
                }

            if not job_result.ok or job_result.value is None:
                return {
                    "ok": False,
                    "error": job_result.error or "Push job failed",
                    "job_id": job_result.job_id,
                }

            result = job_result.value
            logger.debug(
                "RSS 推送任务完成: job_id=%s, session=%s, ok=%s",
                job_result.job_id,
                target_session,
                result.ok,
            )
            return {
                "ok": result.ok,
                "error": result.detail if not result.ok else "",
                "job_id": job_result.job_id,
            }

        except Exception as e:
            logger.error("发送通知失败: %s", e, exc_info=True)
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _limit_original_layout_text(
        layout: list[LayoutFragment] | None,
        *,
        style: int,
        length_limit: int,
    ) -> list[LayoutFragment] | None:
        if style != STYLE_ORIGINAL or not layout or length_limit <= 0:
            return layout

        limited: list[LayoutFragment] = []
        remaining = length_limit
        for fragment in layout:
            kind = str(fragment.kind or "").strip()
            if kind != "text":
                limited.append(fragment)
                continue

            text = str(fragment.text or "")
            if not text or remaining <= 0:
                continue
            if len(text) > remaining:
                text = _entry_text_formatter._truncate(text, remaining)
            limited.append(
                LayoutFragment(
                    kind=fragment.kind,
                    text=text,
                    media_type=fragment.media_type,
                    url=fragment.url,
                    local_path=fragment.local_path,
                    name=fragment.name,
                    fallback_text=fragment.fallback_text,
                )
            )
            remaining -= len(text)

        return limited

    @staticmethod
    async def _format_effective_entry_content(
        *,
        fallback_content: str,
        raw_entry: EntryContentContext | None,
        entry_title: str,
        entry_link: str,
        feed_title: str,
        feed_link: str,
        options: EffectivePushOptions,
    ) -> str:
        if raw_entry is None:
            cleaned = await _entry_text_formatter.clean_text(fallback_content)
            if options.length_limit > 0:
                cleaned = _entry_text_formatter._truncate(
                    cleaned,
                    options.length_limit,
                )
            return cleaned
        return await _entry_text_formatter.format_entry(
            EntryFormatInput(
                title=raw_entry.title or entry_title,
                content=raw_entry.content or raw_entry.summary,
                summary=raw_entry.summary,
                link=raw_entry.link or entry_link,
                author=raw_entry.author,
                feed_title=raw_entry.feed_title or feed_title,
                feed_link=raw_entry.feed_link or feed_link,
                tags=tuple(getattr(raw_entry, "tags", ()) or ()),
            ),
            options,
        )

    async def dispatch_pending_retries(self, limit: int = 100) -> dict[str, int]:
        """
        分发待重试的推送

        Args:
            limit: 最大处理数量

        Returns:
            统计信息字典 {success: x, failed: y, skipped: z}
        """
        stats = {"success": 0, "failed": 0, "skipped": 0}

        # 原子获取并标记为 retrying，防止多 worker 重复拉取同一批记录
        pending = await self._push_history_repo.get_and_mark_retrying(limit)
        if not pending:
            return stats

        logger.info("处理 %s 个待重试推送", len(pending))

        for history in pending:
            try:
                target: SendTarget | None = None
                if history.source_type == "agent":
                    target = SendTarget(
                        user_id=history.user_id,
                        platform_name=history.platform_name,
                        target_session=history.target_session,
                        sub_id=None,
                    )
                else:
                    sub = await self._subscription_repo.get_by_id(
                        int(history.sub_id or 0)
                    )
                    if not sub or sub.state != 1:
                        logger.debug(
                            "订阅 %s 不存在或已禁用，跳过重试",
                            history.sub_id,
                        )
                        history.mark_failed("Subscription not available")
                        await self._push_history_repo.save(history)
                        stats["skipped"] += 1
                        continue
                    target = self._target_from_subscription(sub)

                # 重新发送
                result = await self.send_to_session(
                    target=target,
                    content=strip_appended_media_links_from_text(
                        history.content,
                        media_urls=history.media_urls,
                    ),
                    media_urls=history.media_urls,
                    job_description=f"retry history={history.id}",
                    channel_title=history.feed_title,
                    channel_link=history.feed_link,
                    entry_title=history.entry_title,
                    entry_link=history.entry_link,
                    feed_id=history.feed_id,
                    sub_id=history.sub_id,
                    send_mode=(
                        SEND_MODE_AUTO if history.source_type == "agent" else None
                    ),
                )

                error_msg = result.get("error", "")
                if result["ok"]:
                    history.content = strip_appended_media_links_from_text(
                        history.content,
                        media_urls=history.media_urls,
                    )
                    history.mark_success()
                    stats["success"] += 1
                elif result.get("cancelled"):
                    history.mark_stopped(
                        result.get("error", "Stopped by System or Command")
                    )
                    history.max_retries = 0
                    stats["success"] += 1
                elif is_unrecoverable_error(error_msg):
                    # 不可恢复错误：直接标记为最终失败，不再重试
                    history.record_first_failure(error_msg)
                    history.content = append_media_links_to_text(
                        history.content,
                        media_urls=history.media_urls,
                    )
                    # 覆盖 max_retries 为 0，防止 can_retry 仍返回 True
                    history.max_retries = 0
                    stats["failed"] += 1
                    logger.warning(
                        "订阅 %s 推送失败（不可恢复）: %s",
                        history.sub_id,
                        error_msg,
                    )
                else:
                    # 可恢复错误：记录重试失败，增加计数
                    history.record_retry_failure(error_msg)
                    history.content = append_media_links_to_text(
                        history.content,
                        media_urls=history.media_urls,
                    )
                    stats["failed"] += 1

                await self._push_history_repo.save(history)

            except Exception as e:
                logger.error("重试推送 %s 失败: %s", history.id, e)
                history.record_retry_failure(str(e))
                await self._push_history_repo.save(history)
                stats["failed"] += 1

        logger.info(
            "重试完成: success=%s, failed=%s, skipped=%s",
            stats["success"],
            stats["failed"],
            stats["skipped"],
        )
        return stats

    async def retry_push_history_once(self, history_id: int) -> dict[str, Any]:
        """手动重试单条推送历史，并更新原历史行。"""
        history = await self._push_history_repo.get_by_id(history_id)
        if history is None:
            return {"ok": False, "error": "Push history not found"}

        history.content = strip_appended_media_links_from_text(
            history.content,
            media_urls=history.media_urls,
        )
        history.retry_count = 0
        history.max_retries = 0
        history.fail_reason = None
        history.completed_at = None
        history.mark_retrying()
        history = await self._push_history_repo.save(history)

        try:
            target = await self._target_from_history(
                history,
                allow_stored_feed_target=True,
            )
            if target is None:
                error_msg = "Subscription not available"
                history.mark_failed(error_msg)
                history.content = append_media_links_to_text(
                    history.content,
                    media_urls=history.media_urls,
                )
                history.completed_at = history.updated_at
                await self._push_history_repo.save(history)
                return {"ok": False, "error": error_msg, "history": history}

            result = await self.send_to_session(
                target=target,
                content=strip_appended_media_links_from_text(
                    history.content,
                    media_urls=history.media_urls,
                ),
                media_urls=history.media_urls,
                job_description=f"manual retry history={history.id}",
                channel_title=history.feed_title,
                channel_link=history.feed_link,
                entry_title=history.entry_title,
                entry_link=history.entry_link,
                feed_id=history.feed_id,
                sub_id=history.sub_id,
                send_mode=(SEND_MODE_AUTO if history.source_type == "agent" else None),
            )

            error_msg = result.get("error", "")
            if result["ok"]:
                history.content = strip_appended_media_links_from_text(
                    history.content,
                    media_urls=history.media_urls,
                )
                history.mark_success()
                await self._push_history_repo.save(history)
                return {"ok": True, "message": "重试发送成功", "history": history}

            if result.get("cancelled"):
                history.mark_stopped(
                    result.get("error", "Stopped by System or Command")
                )
            else:
                history.mark_failed(error_msg)
                history.completed_at = history.updated_at
                history.content = append_media_links_to_text(
                    history.content,
                    media_urls=history.media_urls,
                )
                if is_unrecoverable_error(error_msg):
                    history.max_retries = 0
            await self._push_history_repo.save(history)
            return {
                "ok": False,
                "error": history.fail_reason or error_msg or "Retry failed",
                "history": history,
            }
        except Exception as e:
            logger.error("手动重试推送 %s 失败: %s", history.id, e)
            history.mark_failed(str(e))
            history.completed_at = history.updated_at
            history.content = append_media_links_to_text(
                history.content,
                media_urls=history.media_urls,
            )
            await self._push_history_repo.save(history)
            return {"ok": False, "error": str(e), "history": history}

    async def _target_from_history(
        self,
        history: PushHistory,
        *,
        allow_stored_feed_target: bool,
    ) -> SendTarget | None:
        if history.source_type == "agent" or allow_stored_feed_target:
            if history.platform_name and history.target_session:
                return SendTarget(
                    user_id=history.user_id,
                    platform_name=history.platform_name,
                    target_session=history.target_session,
                    sub_id=history.sub_id if history.source_type != "agent" else None,
                )

        if history.source_type == "agent":
            return SendTarget(
                user_id=history.user_id,
                platform_name=history.platform_name,
                target_session=history.target_session,
                sub_id=None,
            )

        sub = await self._subscription_repo.get_by_id(int(history.sub_id or 0))
        if not sub or sub.state != 1:
            logger.debug("订阅 %s 不存在或已禁用，跳过重试", history.sub_id)
            return None
        return self._target_from_subscription(sub)

    async def get_push_stats(self) -> dict[str, int]:
        """
        获取推送统计信息

        Returns:
            统计信息字典
        """
        return await self._push_history_repo.get_stats()

    async def cleanup_old_records(self, days: int = 30) -> int:
        """
        清理指定天数前的历史记录

        Args:
            days: 保留天数

        Returns:
            删除的记录数量
        """
        return await self._push_history_repo.delete_old_records(days)
