"""Shared retry helper for processing failed notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING

from astrbot.api import logger

from ..db import FailedNotification
from ..notifier.senders import (
    ChannelInfo,
    NotifierContext,
    get_sender_for_platform_name,
)

if TYPE_CHECKING:
    from ..utils.config import PluginConfig


async def process_failed_notification(
    notif: FailedNotification,
    *,
    config: PluginConfig | None = None,
    timeout_seconds: int = 30,
    proxy: str = "",
    max_retries: int = 3,
) -> tuple[bool, str | None]:
    """Process a single failed notification retry.

    Args:
        notif: The failed notification to retry
        config: Plugin configuration
        timeout_seconds: Request timeout for sender
        proxy: Proxy URL for sender
        max_retries: Maximum retry count (from config)

    Returns:
        Tuple of (success: bool, error_detail: str | None)
    """
    # Skip if already exhausted (defensive check)
    if notif.retry_count >= max_retries:
        logger.debug(
            "Skipping exhausted notification: notif=%s, retries=%s/%s",
            notif.id,
            notif.retry_count,
            max_retries,
        )
        return False, "max_retries_exhausted"

    try:
        # Reconstruct media items
        media_items = None
        if notif.media_urls:
            media_items = [("image", url) for url in notif.media_urls]

        # Determine sender
        sender_platform_name = (notif.platform_name or "").strip()
        if not sender_platform_name and notif.target_session:
            sender_platform_name = notif.target_session.split(":", 1)[0]

        sender = get_sender_for_platform_name(sender_platform_name, config)
        sender.configure_runtime(
            timeout_seconds=timeout_seconds,
            proxy=proxy,
        )

        # Build context
        context = NotifierContext(
            channel=ChannelInfo(
                title=notif.feed_title or "",
                link=notif.feed_link or "",
            ),
            platform_name=notif.platform_name or "",
        )

        # Try to send
        sent = await sender.send_to_user(
            session_id=notif.target_session,
            message=notif.content,
            media=media_items,
            context=context,
        )

        if sent.ok:
            await FailedNotification.delete(notif.id)
            logger.info("Retry succeeded, removed from queue: notif=%s", notif.id)
            return True, None
        else:
            await FailedNotification.increment_retry(notif.id, fail_reason=sent.detail)
            logger.warning(
                "Retry failed: notif=%s, retries=%s, detail=%s",
                notif.id,
                notif.retry_count + 1,
                sent.detail,
            )
            return False, sent.detail

    except Exception as ex:
        await FailedNotification.increment_retry(notif.id, fail_reason=str(ex))
        logger.error("Retry processing failed: notif=%s, error=%s", notif.id, ex)
        return False, str(ex)


async def process_failed_notifications_batch(
    notifications: list[FailedNotification],
    *,
    config: PluginConfig | None = None,
    timeout_seconds: int = 30,
    proxy: str = "",
    max_retries: int = 3,
) -> dict[str, int]:
    """Process a batch of failed notifications.

    Args:
        notifications: List of failed notifications to retry
        config: Plugin configuration
        timeout_seconds: Request timeout for sender
        proxy: Proxy URL for sender
        max_retries: Maximum retry count (for logging exhausted notifications)

    Returns:
        Statistics dict with 'succeeded', 'failed', 'exhausted' counts
    """
    stats = {"succeeded": 0, "failed": 0, "exhausted": 0}

    for notif in notifications:
        success, _ = await process_failed_notification(
            notif,
            config=config,
            timeout_seconds=timeout_seconds,
            proxy=proxy,
            max_retries=max_retries,
        )

        if success:
            stats["succeeded"] += 1
        else:
            stats["failed"] += 1
            if notif.retry_count + 1 >= max_retries:
                stats["exhausted"] += 1
                logger.warning(
                    "Failed notification exhausted retries: notif=%s", notif.id
                )

    return stats
