from __future__ import annotations

import hashlib
from urllib.parse import unquote, urlsplit

from astrbot.api import logger
from astrbot.api.message_components import Image, Plain, Record, Video

from .base import MessageSender
from .media_downloader import get_or_download_media_to_cache
from .types import PreparedMedia, SendResult


class TelegramMessageSender(MessageSender):
    """Telegram sender strategy with media-first chain ordering."""

    @staticmethod
    def _hash_for_log(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]

    @classmethod
    async def _ensure_local_media_for_telegram(
        cls,
        prepared_media: list[PreparedMedia],
    ) -> list[PreparedMedia]:
        """Prefer local files for media that Telegram needs to probe metadata for."""
        normalized: list[PreparedMedia] = []
        for item in prepared_media:
            if item.download_failed or item.local_path is not None:
                normalized.append(item)
                continue
            if item.media_type not in {"video", "audio"}:
                normalized.append(item)
                continue

            try:
                local_path = await get_or_download_media_to_cache(
                    url=item.original_url,
                    timeout_seconds=cls._get_timeout_seconds(),
                    proxy=cls._get_proxy(),
                )
                normalized.append(
                    PreparedMedia(
                        media_type=item.media_type,
                        original_url=item.original_url,
                        local_path=local_path,
                        download_failed=False,
                    )
                )
            except Exception as ex:
                logger.warning(
                    "Telegram local-media prepare failed: type=%s, url_hash=%s, err=%s",
                    item.media_type,
                    cls._hash_for_log(item.original_url),
                    ex,
                )
                normalized.append(item)

        return normalized

    @classmethod
    def _debug_media_resolution(cls, prepared_media: list[PreparedMedia]) -> None:
        for item in prepared_media:
            if item.media_type not in {"video", "audio"}:
                continue
            if item.local_path is not None:
                logger.debug(
                    "Telegram media resolved: type=%s, source=local_path, hash=%s",
                    item.media_type,
                    cls._hash_for_log(str(item.local_path)),
                )
            else:
                logger.debug(
                    "Telegram media resolved: type=%s, source=url, hash=%s",
                    item.media_type,
                    cls._hash_for_log(item.original_url),
                )

    @staticmethod
    def _uri_to_local_path(file_value: str) -> str:
        if not file_value.startswith("file:///"):
            return file_value

        parsed = urlsplit(file_value)
        path = unquote(parsed.path or "")
        # On Windows, file:///C:/... is parsed as /C:/...
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            return path[1:]
        return path

    @classmethod
    def _normalize_component_file_value(cls, component: Image | Video | Record) -> None:
        file_value = getattr(component, "file", None)
        if isinstance(file_value, str):
            component.file = cls._uri_to_local_path(file_value)

    @classmethod
    def _normalize_components_for_telegram(
        cls,
        image_components: list[Image | Video | Record],
        tail_components: list[Image | Video | Record],
    ) -> None:
        for component in image_components:
            cls._normalize_component_file_value(component)

        for component in tail_components:
            cls._normalize_component_file_value(component)

    @classmethod
    async def send_to_user(
        cls,
        session_id: str,
        message: str,
        media: list[tuple[str, str]] | None = None,
        prepared_media: list[PreparedMedia] | None = None,
        context: object | None = None,
    ) -> SendResult:
        logger.debug(
            "Telegram sender strategy: media-first chain, session=%s, has_media=%s, prepared_media=%s",
            session_id,
            bool(media),
            bool(prepared_media),
        )

        try:
            effective_prepared = prepared_media
            if effective_prepared is None and media:
                effective_prepared = await cls.prepare_media(media)

            image_components = []
            tail_components = []
            failed_media_urls: list[str] = []

            if effective_prepared:
                effective_prepared = await cls._ensure_local_media_for_telegram(
                    effective_prepared
                )
                cls._debug_media_resolution(effective_prepared)
                (
                    image_components,
                    tail_components,
                    failed_media_urls,
                ) = await cls._build_media_components(effective_prepared)
                cls._normalize_components_for_telegram(
                    image_components,
                    tail_components,
                )

            message = cls._append_failed_media_links(message, failed_media_urls)

            # Telegram: always place all media components before text.
            media_first_chain = []
            media_first_chain.extend(image_components)
            media_first_chain.extend(tail_components)
            if message:
                media_first_chain.append(Plain(message))

            if media_first_chain:
                send_result = await cls._send_chain(session_id, media_first_chain)
                if send_result.ok:
                    return send_result

                logger.warning(
                    "Telegram media-first chain failed, fallback split send: session=%s, detail=%s",
                    session_id,
                    send_result.detail,
                )
                # Keep media ahead of text in fallback path as well.
                for component in image_components:
                    media_result = await cls._send_chain(session_id, [component])
                    if not media_result.ok:
                        return media_result

                for component in tail_components:
                    media_result = await cls._send_chain(session_id, [component])
                    if not media_result.ok:
                        return media_result

                if message:
                    return await cls._send_chain(session_id, [Plain(message)])
                return SendResult(ok=True)

            if message:
                return await cls._send_chain(session_id, [Plain(message)])

            return SendResult(ok=False, detail="empty_message")

        except Exception as err:
            if media:
                logger.warning(
                    "Telegram media push failed, fallback to plain text: session=%s, error=%s, media_count=%s",
                    session_id,
                    err,
                    len(media),
                )
                if message:
                    return await cls._send_chain(session_id, [Plain(message)])
            return SendResult(
                ok=False,
                transient=cls._is_transient_network_error(err),
                detail=str(err),
            )
