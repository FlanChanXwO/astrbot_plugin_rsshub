from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from astrbot.api import logger
from astrbot.api.message_components import File, Image, Plain, Record, Video
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.star_tools import StarTools

from .media_downloader import get_or_download_media_to_cache
from .media_paths import normalize_local_media_file_value
from .types import PreparedMedia, SendResult


class MessageSender:
    """Default cross-platform sender strategy."""

    _timeout_seconds: int = 30
    _proxy: str = ""
    _download_media_before_send: bool = True

    @classmethod
    def configure_runtime(cls, *, timeout_seconds: int, proxy: str = "") -> None:
        cls._timeout_seconds = max(1, int(timeout_seconds))
        cls._proxy = proxy or ""

    @classmethod
    def configure_behavior(cls, *, download_media_before_send: bool) -> None:
        cls._download_media_before_send = bool(download_media_before_send)

    @classmethod
    def _get_timeout_seconds(cls) -> int:
        return max(1, int(getattr(cls, "_timeout_seconds", 30)))

    @classmethod
    def _get_proxy(cls) -> str:
        return str(getattr(cls, "_proxy", "") or "")

    @classmethod
    def _should_download_media_before_send(cls) -> bool:
        return bool(getattr(cls, "_download_media_before_send", True))

    @classmethod
    async def prepare_media(
        cls,
        media: list[tuple[str, str]] | None,
    ) -> list[PreparedMedia]:
        if not media:
            return []

        prepared: list[PreparedMedia] = []
        seen_urls: set[str] = set()

        cache_by_url: dict[str, Path] = {}
        failure_by_url: dict[str, bool] = {}
        for media_type, media_url in media:
            if not media_url:
                continue
            if media_type not in {"image", "audio", "video", "file"}:
                continue

            if media_url in seen_urls:
                prepared.append(
                    PreparedMedia(
                        media_type=media_type,
                        original_url=media_url,
                        local_path=cache_by_url.get(media_url),
                        download_failed=failure_by_url.get(media_url, False),
                    )
                )
                continue

            seen_urls.add(media_url)

            if not cls._should_download_media_before_send():
                prepared.append(
                    PreparedMedia(media_type=media_type, original_url=media_url)
                )
                failure_by_url[media_url] = False
                continue

            try:
                local_path = await get_or_download_media_to_cache(
                    url=media_url,
                    timeout_seconds=cls._get_timeout_seconds(),
                    proxy=cls._get_proxy(),
                )
                prepared.append(
                    PreparedMedia(
                        media_type=media_type,
                        original_url=media_url,
                        local_path=local_path,
                    )
                )
                cache_by_url[media_url] = local_path
                failure_by_url[media_url] = False
            except Exception as ex:
                prepared.append(
                    PreparedMedia(
                        media_type=media_type,
                        original_url=media_url,
                        local_path=None,
                        download_failed=True,
                    )
                )
                failure_by_url[media_url] = True
                logger.warning(
                    "Prepare media failed: type=%s, url=%s, err_type=%s, err=%r",
                    media_type,
                    media_url,
                    type(ex).__name__,
                    ex,
                )

        return prepared

    @staticmethod
    async def _send_text_media_split(
        session_id: str,
        message: str,
        image_components: list,
        tail_components: list,
    ) -> SendResult:
        if message:
            text_result = await MessageSender._send_chain(session_id, [Plain(message)])
            if not text_result.ok:
                return text_result

        for component in image_components:
            media_result = await MessageSender._send_chain(session_id, [component])
            if not media_result.ok:
                return media_result

        for component in tail_components:
            media_result = await MessageSender._send_chain(session_id, [component])
            if not media_result.ok:
                return media_result

        return SendResult(ok=True)

    @staticmethod
    async def _send_single_chain(
        session_id: str,
        image_components: list,
        message: str,
        tail_components: list,
    ) -> SendResult:
        chain = []
        chain.extend(image_components)
        if message:
            chain.append(Plain(message))
        chain.extend(tail_components)
        if not chain:
            return SendResult(ok=False, detail="empty_message")
        return await MessageSender._send_chain(session_id, chain)

    @classmethod
    async def _build_media_components(
        cls,
        prepared_media: list[PreparedMedia],
    ) -> tuple[list, list, list[str]]:
        image_components = []
        tail_components = []
        failed_media_urls: list[str] = []
        image_count = 0

        for item in prepared_media:
            media_type = item.media_type
            media_url = item.original_url
            local_path = item.local_path
            if item.download_failed:
                failed_media_urls.append(media_url)
                continue

            # Cache file may be pruned externally; refresh just-in-time to avoid ENOENT.
            if local_path is not None and not local_path.exists():
                logger.warning(
                    "Cached media missing before send, re-download: type=%s, url=%s, path=%s",
                    media_type,
                    media_url,
                    local_path,
                )
                try:
                    local_path = await get_or_download_media_to_cache(
                        url=media_url,
                        timeout_seconds=cls._get_timeout_seconds(),
                        proxy=cls._get_proxy(),
                    )
                except Exception as ex:
                    logger.warning(
                        "Re-download missing media failed: type=%s, url=%s, err=%s",
                        media_type,
                        media_url,
                        ex,
                    )
                    failed_media_urls.append(media_url)
                    continue

            local_file_path = str(local_path.resolve()) if local_path else ""
            local_file_uri = local_path.resolve().as_uri() if local_path else ""
            if local_path is not None:
                logger.debug(
                    "Prepared local media path: type=%s, url=%s, resolved=%s, exists=%s",
                    media_type,
                    media_url,
                    local_file_path,
                    local_path.exists(),
                )
            media_file_value = local_file_uri if local_path else media_url

            if media_type == "image":
                if image_count >= 9:
                    continue
                image_components.append(Image(file=media_file_value, url=media_url))
                image_count += 1
            elif media_type == "video":
                # 视频放在消息上方（与图片一致）
                image_components.append(Video(file=media_file_value))
            elif media_type == "audio":
                tail_components.append(Record(file=media_file_value, text="audio"))
            elif media_type == "file":
                parsed = urlparse(media_url)
                filename = unquote(parsed.path.rsplit("/", 1)[-1]) or "attachment"
                tail_components.append(
                    File(
                        name=filename, file=local_file_path or media_url, url=media_url
                    )
                )

        return image_components, tail_components, failed_media_urls

    @staticmethod
    def _append_failed_media_links(message: str, failed_media_urls: list[str]) -> str:
        if not failed_media_urls:
            return message

        unique_urls: list[str] = []
        seen: set[str] = set()
        for url in failed_media_urls:
            if url and url not in seen:
                unique_urls.append(url)
                seen.add(url)

        if not unique_urls:
            return message

        lines = [message] if message else []
        lines.append("媒体原始链接:")
        lines.extend(unique_urls)
        return "\n".join(lines)

    @staticmethod
    def _collect_normalizable_components(items: list) -> list[object]:
        collected: list[object] = []

        def _walk(value: object) -> None:
            if value is None:
                return
            if isinstance(value, (list, tuple)):
                for nested in value:
                    _walk(nested)
                return
            nodes = getattr(value, "nodes", None)
            if isinstance(nodes, list):
                _walk(nodes)
                return
            content = getattr(value, "content", None)
            if isinstance(content, list):
                _walk(content)
            file_value = getattr(value, "file", None)
            if isinstance(file_value, str):
                collected.append(value)

        _walk(items)
        return collected

    @classmethod
    def _normalize_chain_media_files(cls, chain: list, session_id: str) -> list:
        for component in cls._collect_normalizable_components(chain):
            file_value = getattr(component, "file", None)
            if not isinstance(file_value, str) or not file_value:
                continue
            if file_value.startswith(("http://", "https://", "base64://")):
                continue
            try:
                resolved = normalize_local_media_file_value(file_value)
                exists = Path(resolved).exists()
            except Exception as ex:
                logger.warning(
                    "Sender media normalize failed: session=%s, component=%s, file=%s, err=%s",
                    session_id,
                    type(component).__name__,
                    file_value,
                    ex,
                )
                continue
            if resolved != file_value:
                setattr(component, "file", resolved)
            logger.debug(
                "Sender media normalized: session=%s, component=%s, original=%s, normalized=%s, exists=%s",
                session_id,
                type(component).__name__,
                file_value,
                resolved,
                exists,
            )
        return chain

    @staticmethod
    def _format_media_urls(media: list[tuple[str, str]] | None) -> str:
        if not media:
            return "[]"
        urls = [url for _, url in media if url]
        return "[" + ", ".join(urls) + "]"

    @staticmethod
    def _is_transient_network_error(err: Exception) -> bool:
        text = f"{type(err).__name__}: {err}"
        keywords = (
            "ClientConnectorError",
            "Cannot connect to host",
            "Temporary failure",
            "TimeoutError",
            "ConnectionResetError",
            "Network is unreachable",
            "指定的网络名不再可用",
        )
        return any(keyword in text for keyword in keywords)

    @classmethod
    async def _send_chain(cls, session_id: str, chain: list) -> SendResult:
        normalized_chain = cls._normalize_chain_media_files(chain, session_id)
        if normalized_chain is None:
            normalized_chain = []
        message_chain = MessageChain(chain=normalized_chain)
        sent = await StarTools.send_message(session_id, message_chain)
        if not sent:
            return SendResult(ok=False, needs_rebind=True, detail="platform_or_session")
        return SendResult(ok=True)

    @classmethod
    async def send_to_user(
        cls,
        session_id: str,
        message: str,
        media: list[tuple[str, str]] | None = None,
        prepared_media: list[PreparedMedia] | None = None,
        context: object | None = None,
    ) -> SendResult:
        try:
            logger.debug(
                "Default sender path: session=%s, media=%s, prepared_media=%s, context=%s",
                session_id,
                bool(media),
                bool(prepared_media),
                context is not None,
            )
            image_components = []
            tail_components = []
            failed_media_urls: list[str] = []
            effective_prepared = prepared_media
            if effective_prepared is None and media:
                effective_prepared = await cls.prepare_media(media)

            if effective_prepared:
                (
                    image_components,
                    tail_components,
                    failed_media_urls,
                ) = await cls._build_media_components(effective_prepared)
                message = cls._append_failed_media_links(message, failed_media_urls)

            if image_components or tail_components:
                logger.debug(
                    "Default sender trying single-chain: session=%s, images=%s, tail=%s",
                    session_id,
                    len(image_components),
                    len(tail_components),
                )
                single_chain_result = await cls._send_single_chain(
                    session_id,
                    image_components,
                    message,
                    tail_components,
                )
                if single_chain_result.ok:
                    logger.debug(
                        "Default sender single-chain success: session=%s", session_id
                    )
                    return single_chain_result

                logger.warning(
                    "Single-chain send failed, fallback split send: session=%s, detail=%s",
                    session_id,
                    single_chain_result.detail,
                )
                return await cls._send_text_media_split(
                    session_id,
                    message,
                    image_components,
                    tail_components,
                )

            if message:
                return await cls._send_chain(session_id, [Plain(message)])

            return SendResult(ok=False, detail="empty_message")

        except Exception as err:
            if media:
                logger.warning(
                    "Media push failed, fallback to plain text: session=%s, error=%s, media_urls=%s",
                    session_id,
                    err,
                    cls._format_media_urls(media),
                )
                try:
                    fallback_chain = [Plain(message)] if message else []
                    if not fallback_chain:
                        return SendResult(
                            ok=False,
                            transient=cls._is_transient_network_error(err),
                            detail=str(err),
                        )
                    fallback_result = await cls._send_chain(session_id, fallback_chain)
                    if fallback_result.ok:
                        return SendResult(
                            ok=True,
                            transient=True,
                            detail="media_failed_text_fallback",
                        )
                    return fallback_result
                except Exception as fallback_ex:
                    return SendResult(
                        ok=False,
                        transient=cls._is_transient_network_error(fallback_ex),
                        detail=str(fallback_ex),
                    )

            return SendResult(
                ok=False,
                transient=cls._is_transient_network_error(err),
                detail=str(err),
            )

    @staticmethod
    async def send_to_group(
        platform: str,
        group_id: str,
        message: str,
        media: list[tuple[str, str]] | None = None,
    ) -> SendResult:
        try:
            session_id = f"{platform}:GroupMessage:{group_id}"
            return await MessageSender.send_to_user(session_id, message, media)
        except Exception as err:
            logger.error("Send group message failed: %s", err, exc_info=True)
            return SendResult(
                ok=False,
                transient=MessageSender._is_transient_network_error(err),
                detail=str(err),
            )
