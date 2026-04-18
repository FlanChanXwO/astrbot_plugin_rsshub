from __future__ import annotations

from pathlib import Path

from astrbot.api import logger
from astrbot.api.message_components import File, Image, Plain, Record, Video

from .base import MessageSender
from .media_paths import normalize_local_media_file_value, resolve_local_file_path
from .types import NotifierContext, PreparedMedia, SendResult


class QQOfficialMessageSender(MessageSender):
    """QQ Official sender: handles multi-image limitation by sending separately.

    Strategy:
    - Single image: send together with text
    - Multiple images: send images one by one, then send text separately
    - Video: send video first, then send text description separately
    """

    @classmethod
    def _log_media_component_file_check(
        cls, component: object, session_id: str
    ) -> None:
        file_value = str(getattr(component, "file", "") or "")
        local_path = resolve_local_file_path(file_value)
        resolved_path = local_path or file_value
        if not resolved_path:
            return
        if isinstance(component, str):
            return
        if isinstance(component, (Plain,)):
            return
        if file_value.startswith(("http://", "https://", "base64://")):
            return
        try:
            exists = Path(resolved_path).exists()
        except Exception as ex:
            logger.warning(
                "QQOfficial media path check failed: session=%s, component=%s, file=%s, resolved=%s, err=%s",
                session_id,
                type(component).__name__,
                file_value,
                resolved_path,
                ex,
            )
            return
        logger.debug(
            "QQOfficial media path check: session=%s, component=%s, file=%s, resolved=%s, exists=%s",
            session_id,
            type(component).__name__,
            file_value,
            resolved_path,
            exists,
        )

    @classmethod
    def _normalize_media_component_file(
        cls, component: object, session_id: str
    ) -> None:
        if not isinstance(component, (Image, Video, File, Record)):
            return
        file_value = str(getattr(component, "file", "") or "")
        if not file_value:
            return
        if file_value.startswith(("http://", "https://", "base64://")):
            return
        try:
            resolved = normalize_local_media_file_value(file_value)
            if resolved != file_value:
                component.file = resolved
                logger.debug(
                    "QQOfficial media file normalized: session=%s, component=%s, original=%s, normalized=%s",
                    session_id,
                    type(component).__name__,
                    file_value,
                    resolved,
                )
        except Exception as ex:
            logger.warning(
                "QQOfficial media file normalize failed: session=%s, component=%s, file=%s, err=%s",
                session_id,
                type(component).__name__,
                file_value,
                ex,
            )

    @classmethod
    def _sanitize_nonexistent_local_media(
        cls,
        chain: list,
        session_id: str,
    ) -> tuple[list, list[str]]:
        sanitized: list = []
        missing_sources: list[str] = []
        for component in chain:
            if isinstance(component, Plain):
                sanitized.append(component)
                continue
            file_value = str(getattr(component, "file", "") or "")
            if not file_value:
                sanitized.append(component)
                continue
            if file_value.startswith(("http://", "https://", "base64://")):
                sanitized.append(component)
                continue
            resolved_candidate = resolve_local_file_path(file_value) or file_value
            try:
                exists = Path(resolved_candidate).exists()
            except Exception:
                exists = False
            if exists:
                sanitized.append(component)
                continue
            source_for_fallback = str(getattr(component, "url", "") or file_value)
            missing_sources.append(source_for_fallback)
            logger.warning(
                "QQOfficial media dropped before send: session=%s, component=%s, file=%s, resolved=%s, fallback=%s",
                session_id,
                type(component).__name__,
                file_value,
                resolved_candidate,
                source_for_fallback,
            )
        return sanitized, missing_sources

    @classmethod
    def _prepare_chain_for_send(
        cls,
        chain: list,
        session_id: str,
    ) -> tuple[list, list[str]]:
        cls._normalize_chain_media_files(chain, session_id)
        cls._log_chain_media_files(chain, session_id)
        return cls._sanitize_nonexistent_local_media(chain, session_id)

    @classmethod
    def _normalize_chain_media_files(cls, chain: list, session_id: str) -> list:
        for component in chain:
            cls._normalize_media_component_file(component, session_id)
        return chain

    @classmethod
    def _log_chain_media_files(cls, chain: list, session_id: str) -> None:
        for component in chain:
            if isinstance(component, (Image, Video)):
                cls._log_media_component_file_check(component, session_id)

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
                video_components = [c for c in image_components if isinstance(c, Video)]
                image_components = [c for c in image_components if isinstance(c, Image)]

                message = cls._append_failed_media_links(message, failed_media_urls)

            total_images = len(image_components)
            has_video = len(video_components) > 0

            # Strategy: Video first (if any), then images, then text
            # For single image: combine with text
            # For multiple images: send separately, then text

            # 1. Send video first if exists (video + text in one chain)
            if has_video:
                for video in video_components:
                    prepared_chain, missing_sources = cls._prepare_chain_for_send(
                        [video],
                        session_id,
                    )
                    if missing_sources:
                        message = cls._append_failed_media_links(
                            message, missing_sources
                        )
                    if not prepared_chain:
                        continue
                    video_result = await cls._send_chain(session_id, prepared_chain)
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
                prepared_chain, missing_sources = cls._prepare_chain_for_send(
                    chain,
                    session_id,
                )
                if missing_sources:
                    message = cls._append_failed_media_links(message, missing_sources)
                    prepared_chain = [
                        c for c in prepared_chain if not isinstance(c, Plain)
                    ]
                    if message:
                        prepared_chain.append(Plain(message))
                if not prepared_chain:
                    return SendResult(ok=False, detail="empty_message")
                return await cls._send_chain(session_id, prepared_chain)

            elif total_images > 1:
                # Multiple images: send one by one
                for img in image_components:
                    prepared_chain, missing_sources = cls._prepare_chain_for_send(
                        [img],
                        session_id,
                    )
                    if missing_sources:
                        message = cls._append_failed_media_links(
                            message, missing_sources
                        )
                    if not prepared_chain:
                        continue
                    img_result = await cls._send_chain(session_id, prepared_chain)
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
                    prepared_text_chain, missing_sources = cls._prepare_chain_for_send(
                        text_chain,
                        session_id,
                    )
                    if missing_sources:
                        message = cls._append_failed_media_links(
                            message, missing_sources
                        )
                        prepared_text_chain = [
                            c for c in prepared_text_chain if not isinstance(c, Plain)
                        ]
                        if message:
                            prepared_text_chain.append(Plain(message))
                    if not prepared_text_chain:
                        return SendResult(ok=True)
                    return await cls._send_chain(session_id, prepared_text_chain)

                return SendResult(ok=True)

            else:
                # No images, just text and tail components
                chain = []
                if message:
                    chain.append(Plain(message))
                chain.extend(tail_components)
                prepared_chain, missing_sources = cls._prepare_chain_for_send(
                    chain,
                    session_id,
                )
                if missing_sources:
                    message = cls._append_failed_media_links(message, missing_sources)
                    prepared_chain = [
                        c for c in prepared_chain if not isinstance(c, Plain)
                    ]
                    if message:
                        prepared_chain.append(Plain(message))
                if not prepared_chain:
                    return SendResult(ok=False, detail="empty_message")
                return await cls._send_chain(session_id, prepared_chain)

        except Exception as err:
            err_text = repr(err)
            logger.warning(
                "QQOfficial send failed: session=%s, err_type=%s, err=%r",
                session_id,
                type(err).__name__,
                err,
                exc_info=True,
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
