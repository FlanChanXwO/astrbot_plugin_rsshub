from __future__ import annotations

import hashlib
from pathlib import Path

from astrbot.api import logger
from astrbot.api.message_components import File, Image, Plain, Record, Video

from .base import MessageSender
from .media_downloader import get_or_download_media_to_cache
from .types import PreparedMedia, SendResult


class TelegramMessageSender(MessageSender):
    """Telegram sender strategy with media-first chain ordering."""

    TELEGRAM_MAX_PHOTO_SIZE = 10 * 1024 * 1024
    TELEGRAM_MAX_OTHER_MEDIA_SIZE = 50 * 1024 * 1024

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
            if item.media_type not in {"image", "video", "audio"}:
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

    @classmethod
    def _component_file_size(
        cls,
        component: Image | Video | Record | File,
    ) -> int | None:
        file_value = getattr(component, "file", None)
        if not isinstance(file_value, str) or not file_value:
            return None
        if file_value.startswith("http://") or file_value.startswith("https://"):
            return None
        path = Path(file_value)
        if not path.exists() or not path.is_file():
            return None
        try:
            return path.stat().st_size
        except OSError:
            return None

    @classmethod
    def _apply_telegram_media_size_limits(
        cls,
        image_components: list[Image | Video | Record | File],
        tail_components: list[Image | Video | Record | File],
        failed_media_urls: list[str],
    ) -> tuple[
        list[Image | Video | Record | File],
        list[Image | Video | Record | File],
    ]:
        normalized_images: list[Image | Video | Record | File] = []
        normalized_tail: list[Image | Video | Record | File] = []

        for component in image_components:
            if not isinstance(component, Image):
                normalized_images.append(component)
                continue
            size = cls._component_file_size(component)
            if size is None or size <= cls.TELEGRAM_MAX_PHOTO_SIZE:
                normalized_images.append(component)
                continue

            # Oversized photo falls back to document send path (up to 50MB).
            if size <= cls.TELEGRAM_MAX_OTHER_MEDIA_SIZE and isinstance(
                component.file, str
            ):
                normalized_tail.append(
                    File(
                        name=Path(component.file).name or "image",
                        file=component.file,
                        url=component.url or "",
                    )
                )
            else:
                if component.url:
                    failed_media_urls.append(component.url)

        for component in tail_components:
            if not isinstance(component, (Video, Record)):
                normalized_tail.append(component)
                continue
            size = cls._component_file_size(component)
            if size is None or size <= cls.TELEGRAM_MAX_OTHER_MEDIA_SIZE:
                normalized_tail.append(component)
                continue

            original_url = getattr(component, "url", "")
            if isinstance(original_url, str) and original_url:
                failed_media_urls.append(original_url)

        return normalized_images, normalized_tail

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
                cls._normalize_chain_media_files(image_components, session_id)
                cls._normalize_chain_media_files(tail_components, session_id)
                image_components, tail_components = (
                    cls._apply_telegram_media_size_limits(
                        image_components,
                        tail_components,
                        failed_media_urls,
                    )
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
