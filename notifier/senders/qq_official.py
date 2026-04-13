from __future__ import annotations

from astrbot.api import logger
from astrbot.api.message_components import Image, Plain, Video

from .base import MessageSender
from .types import NotifierContext, PreparedMedia, SendResult


class QQOfficialMessageSender(MessageSender):
    """QQ Official sender: handles multi-image limitation by sending separately.

    Strategy:
    - Single image: send together with text
    - Multiple images: send images one by one, then send text separately
    - Video: send video first, then send text description separately
    """

    @classmethod
    async def send_to_user(
        cls,
        session_id: str,
        message: str,
        media: list[tuple[str, str]] | None = None,
        prepared_media: list[PreparedMedia] | None = None,
        context: NotifierContext | None = None,
    ) -> SendResult:
        """发送消息到用户。

        Args:
            session_id: 目标会话ID
            message: 消息内容
            media: 媒体列表
            prepared_media: 预处理的媒体
            context: 通知上下文
        """
        logger.debug(
            "QQOfficial sender strategy: session=%s, has_media=%s, prepared_media=%s",
            session_id,
            bool(media),
            bool(prepared_media),
        )

        try:
            effective_prepared = prepared_media
            if effective_prepared is None and media:
                effective_prepared = await cls.prepare_media(media)

            # Build media components
            image_components = []
            video_components = []
            tail_components = []
            failed_media_urls: list[str] = []

            if effective_prepared:
                (
                    image_components,
                    tail_components,
                    failed_media_urls,
                ) = await cls._build_media_components(effective_prepared)

                # Separate videos from image_components
                video_components = [
                    c for c in image_components if isinstance(c, Video)
                ]
                image_components = [
                    c for c in image_components if isinstance(c, Image)
                ]

                message = cls._append_failed_media_links(message, failed_media_urls)

            total_images = len(image_components)
            has_video = len(video_components) > 0

            # Strategy: Video first (if any), then images, then text
            # For single image: combine with text
            # For multiple images: send separately, then text

            # 1. Send video first if exists (video + text in one chain)
            if has_video:
                for video in video_components:
                    video_result = await cls._send_chain(session_id, [video])
                    if not video_result.ok:
                        logger.warning(
                            "QQOfficial video send failed: session=%s, err=%s",
                            session_id,
                            video_result.detail,
                        )
                        return video_result
                    # Small delay after video
                    import asyncio
                    await asyncio.sleep(0.5)

            # 2. Send images based on count
            if total_images == 1:
                # Single image: combine with text
                chain = [image_components[0]]
                if message:
                    chain.append(Plain(message))
                chain.extend(tail_components)
                return await cls._send_chain(session_id, chain)

            elif total_images > 1:
                # Multiple images: send one by one
                for img in image_components:
                    img_result = await cls._send_chain(session_id, [img])
                    if not img_result.ok:
                        logger.warning(
                            "QQOfficial image send failed: session=%s, err=%s",
                            session_id,
                            img_result.detail,
                        )
                        return img_result
                    # Small delay between images
                    import asyncio
                    await asyncio.sleep(0.3)

                # Then send text separately
                if message or tail_components:
                    text_chain = []
                    if message:
                        text_chain.append(Plain(message))
                    text_chain.extend(tail_components)
                    return await cls._send_chain(session_id, text_chain)

                return SendResult(ok=True)

            else:
                # No images, just text and tail components
                chain = []
                if message:
                    chain.append(Plain(message))
                chain.extend(tail_components)
                if not chain:
                    return SendResult(ok=False, detail="empty_message")
                return await cls._send_chain(session_id, chain)

        except Exception as err:
            err_text = str(err)
            logger.warning(
                "QQOfficial send failed: session=%s, err=%s",
                session_id,
                err,
            )

            # Fallback: convert media to links in text
            fallback_urls: list[str] = []
            if media:
                fallback_urls.extend([url for _, url in media if url])
            fallback_text = cls._append_failed_media_links(message, fallback_urls)

            logger.warning(
                "QQOfficial falling back to text: session=%s, prev_err=%s",
                session_id,
                err_text,
            )

            try:
                fallback_result = await cls._send_chain(
                    session_id, [Plain(fallback_text or "RSS update")]
                )
                if fallback_result.ok:
                    return SendResult(
                        ok=True,
                        transient=False,
                        detail="qq_official_failed_text_fallback",
                    )
                return fallback_result
            except Exception as fallback_ex:
                return SendResult(
                    ok=False,
                    transient=cls._is_transient_network_error(fallback_ex),
                    detail=str(fallback_ex),
                )
