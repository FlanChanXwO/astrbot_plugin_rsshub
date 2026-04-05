from __future__ import annotations

from astrbot.api.message_components import Plain, Video

from .base import MessageSender
from .types import PreparedMedia, SendResult


class TelegramMessageSender(MessageSender):
    """Telegram optimized sender: attach text with first video as caption-like chain."""

    @classmethod
    async def send_to_user(
        cls,
        session_id: str,
        message: str,
        media: list[tuple[str, str]] | None = None,
        prepared_media: list[PreparedMedia] | None = None,
    ) -> SendResult:
        if not media and not prepared_media:
            return await super().send_to_user(session_id, message, media)

        effective_prepared = prepared_media
        if effective_prepared is None and media:
            effective_prepared = await cls.prepare_media(media)
        if not effective_prepared:
            return await super().send_to_user(session_id, message, media)

        (
            image_components,
            tail_components,
            failed_media_urls,
        ) = await cls._build_media_components(effective_prepared)
        message = cls._append_failed_media_links(message, failed_media_urls)
        telegram_video = None
        remaining_tail = []

        for component in tail_components:
            if telegram_video is None and isinstance(component, Video):
                telegram_video = component
                continue
            remaining_tail.append(component)

        if telegram_video is not None:
            initial_chain = [telegram_video]
            if message:
                initial_chain.append(Plain(message))
            result = await cls._send_chain(session_id, initial_chain)
            if not result.ok:
                return result

            for component in image_components:
                item_result = await cls._send_chain(session_id, [component])
                if not item_result.ok:
                    return item_result

            for component in remaining_tail:
                item_result = await cls._send_chain(session_id, [component])
                if not item_result.ok:
                    return item_result

            return SendResult(ok=True)

        return await super().send_to_user(
            session_id,
            message,
            media,
            prepared_media=effective_prepared,
        )
