"""基础消息发送器

提供跨平台消息发送的默认实现。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.star_tools import StarTools

from ....shared.constants import STYLE_ORIGINAL
from ...pipeline import MessageComponent, MessageFormatter
from ...utils import get_logger
from ...utils.lock import locked
from .types import MessageContext, PreparedMedia, SendRequest, SendResult

if TYPE_CHECKING:
    pass

logger = get_logger()
MAX_SEND_ERROR_DETAIL_LENGTH = 512


class DefaultMessageSender:
    """默认跨平台发送器策略

    提供基础的消息发送和媒体处理功能。
    组件排序统一由 MessageFormatter 决定，此处只负责发送。
    """

    _timeout_seconds: int = 30
    _proxy: str = ""
    _video_transcode: bool = False
    _video_transcode_timeout: int = 120
    _gif_transcode: bool = False
    _gif_transcode_timeout: int = 60

    _formatter: MessageFormatter = MessageFormatter()

    @classmethod
    def configure_runtime(cls, *, timeout_seconds: int, proxy: str = "") -> None:
        """配置运行时参数"""
        DefaultMessageSender._timeout_seconds = max(1, int(timeout_seconds))
        DefaultMessageSender._proxy = proxy or ""

    @classmethod
    def configure_behavior(
        cls,
        *,
        video_transcode: bool = False,
        video_transcode_timeout: int = 120,
        gif_transcode: bool = False,
        gif_transcode_timeout: int = 60,
    ) -> None:
        """配置发送行为"""
        cls._video_transcode = bool(video_transcode)
        cls._video_transcode_timeout = max(1, int(video_transcode_timeout))
        cls._gif_transcode = bool(gif_transcode)
        cls._gif_transcode_timeout = max(1, int(gif_transcode_timeout))

    @classmethod
    def _get_timeout_seconds(cls) -> int:
        return max(1, int(getattr(cls, "_timeout_seconds", 30)))

    @classmethod
    def _get_proxy(cls) -> str:
        proxy = getattr(cls, "_proxy", None)
        if proxy is None:
            proxy = getattr(DefaultMessageSender, "_proxy", None)
        return str(proxy or "")

    @classmethod
    def _should_transcode_video(cls) -> bool:
        return bool(getattr(cls, "_video_transcode", False))

    @classmethod
    def _get_video_transcode_timeout(cls) -> int:
        return max(1, int(getattr(cls, "_video_transcode_timeout", 120)))

    @classmethod
    def _should_transcode_gif(cls) -> bool:
        return bool(getattr(cls, "_gif_transcode", False))

    @classmethod
    def _get_gif_transcode_timeout(cls) -> int:
        return max(1, int(getattr(cls, "_gif_transcode_timeout", 60)))

    async def _maybe_transcode_video_to_mp4(self, media_path: Path) -> Path:
        if not self._should_transcode_video():
            return media_path
        if media_path.suffix.lower() == ".gif":
            return media_path
        try:
            from ...utils.ffmpeg_helper import FFmpegTool

            transcoded_path = await FFmpegTool.transcode_to_mp4(
                media_path,
                timeout_seconds=self._get_video_transcode_timeout(),
                auto_install_ffmpeg=True,
            )
            if transcoded_path and transcoded_path.exists():
                return transcoded_path
        except Exception as ex:
            logger.warning(
                "Video transcode failed, using original media: path=%s, err=%s",
                media_path,
                ex,
            )
        return media_path

    @staticmethod
    def _normalize_error_detail(detail: str | None) -> str:
        text = str(detail or "").strip()
        if not text:
            return ""
        if len(text) <= MAX_SEND_ERROR_DETAIL_LENGTH:
            return text
        if MAX_SEND_ERROR_DETAIL_LENGTH <= 3:
            return text[:MAX_SEND_ERROR_DETAIL_LENGTH]
        return text[: MAX_SEND_ERROR_DETAIL_LENGTH - 3] + "..."

    async def prepare_media(
        self,
        media: list[tuple[str, str]] | None,
        timeout: int = 30,
        proxy: str = "",
    ) -> list[PreparedMedia]:
        """预处理媒体文件"""
        if not media:
            return []

        prepared: list[PreparedMedia] = []
        seen_urls: set[str] = set()

        from ...media import MediaDownloader

        downloader = MediaDownloader()

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
                    )
                )
                continue

            seen_urls.add(media_url)

            try:
                local_path = await downloader.get_or_download(
                    url=media_url,
                    timeout_seconds=timeout,
                    proxy=proxy,
                    try_convert_gif=media_type == "video"
                    and self._should_transcode_gif(),
                    gif_transcode_timeout=self._get_gif_transcode_timeout(),
                )
                if media_type == "video":
                    local_path = await self._maybe_transcode_video_to_mp4(local_path)
                prepared.append(
                    PreparedMedia(
                        media_type=media_type,
                        original_url=media_url,
                        local_path=local_path,
                    )
                )
            except Exception as ex:
                prepared.append(
                    PreparedMedia(
                        media_type=media_type,
                        original_url=media_url,
                        download_failed=True,
                    )
                )
                logger.warning(
                    "Prepare media failed: type=%s, url=%s, err=%s",
                    media_type,
                    media_url,
                    ex,
                )

        return prepared

    @staticmethod
    def _is_transient_network_error(err: Exception) -> bool:
        """判断是否为临时网络错误（可重试）"""
        text = f"{type(err).__name__}: {err}"
        keywords = (
            "ClientConnectorError",
            "Cannot connect to host",
            "TimeoutError",
            "ConnectionResetError",
            "Network is unreachable",
        )
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _collect_failed_urls(
        prepared_media: list[PreparedMedia],
    ) -> list[str]:
        """从 PreparedMedia 中收集下载失败的 URL"""
        return [item.original_url for item in prepared_media if item.download_failed]

    async def _prepare_effective_media(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> list[PreparedMedia] | None:
        timeout = self._get_timeout_seconds()
        proxy = self._get_proxy()

        effective_prepared = request.prepared_media
        if effective_prepared is None and request.media:
            effective_prepared = await self.prepare_media(
                request.media, timeout=timeout, proxy=proxy
            )
        return effective_prepared

    def _build_components(
        self,
        request: SendRequest,
        prepared_media: list[PreparedMedia] | None,
        context: MessageContext | None = None,
        *,
        failed_urls: list[str] | None = None,
        platform: str | None = None,
    ) -> list[MessageComponent]:
        effective_failed_urls = (
            list(failed_urls)
            if failed_urls is not None
            else self._collect_failed_urls(prepared_media or [])
        )
        return self._formatter.build_components(
            prepared_media=prepared_media,
            text=request.message,
            failed_urls=effective_failed_urls,
            platform=platform
            if platform is not None
            else (context.platform_name if context else ""),
        )

    @staticmethod
    def _is_media_component(component: MessageComponent) -> bool:
        return component.kind in {"media", "tail"}

    def _component_to_chain(self, component: MessageComponent) -> list:
        return self._formatter._components_to_chain([component])

    def _append_failed_links(self, text: str, failed_urls: list[str]) -> str:
        return self._formatter._append_failed_links(text, failed_urls)

    @staticmethod
    def _is_original_style(context: MessageContext | None) -> bool:
        return int(getattr(context, "style", 0) or 0) == STYLE_ORIGINAL

    def _layout_to_components(
        self,
        request: SendRequest,
    ) -> list[MessageComponent]:
        components: list[MessageComponent] = []
        for fragment in request.layout or []:
            kind = str(fragment.kind or "").strip()
            if kind == "text":
                text = str(fragment.text or "").strip()
                if text:
                    components.append(MessageComponent(kind="text", text=text))
                continue
            if kind in {"image", "video"} and fragment.url:
                components.append(
                    MessageComponent(
                        kind="media",
                        media_type=kind,
                        file=str(fragment.url),
                        original_url=str(fragment.url),
                    )
                )
                continue
            if kind in {"audio", "file"} and fragment.url:
                components.append(
                    MessageComponent(
                        kind="tail",
                        media_type=kind,
                        file=str(fragment.url),
                        original_url=str(fragment.url),
                        name=str(fragment.name or ""),
                    )
                )
        return components

    def _chain_from_components(self, components: list[MessageComponent]) -> list:
        return self._formatter._components_to_chain(components)

    @staticmethod
    def _record_failed_url(
        failed_urls: list[str],
        component: MessageComponent,
    ) -> None:
        url = str(component.original_url or "").strip()
        if url and url not in failed_urls:
            failed_urls.append(url)

    @staticmethod
    def _merge_send_failure(
        failures: list[SendResult],
        result: SendResult,
    ) -> None:
        if not result.ok:
            failures.append(result)

    def _partial_send_result(self, failures: list[SendResult]) -> SendResult:
        if not failures:
            return SendResult(ok=True)
        first = failures[0]
        detail = self._normalize_error_detail(
            f"partial send: {first.detail or 'send_failed'}"
        )
        return SendResult(
            ok=False,
            needs_rebind=any(item.needs_rebind for item in failures),
            transient=any(item.transient for item in failures),
            detail=detail,
            http_status=first.http_status,
        )

    async def _send_components_media_first(
        self,
        session_id: str,
        components: list[MessageComponent],
        *,
        default_text: str = "",
    ) -> SendResult:
        media_components = [
            component for component in components if self._is_media_component(component)
        ]
        text_components = [
            component for component in components if component.kind == "text"
        ]

        failed_urls: list[str] = []
        failures: list[SendResult] = []

        for component in media_components:
            chain = self._component_to_chain(component)
            if not chain:
                continue
            result = await self._send_chain(session_id, chain)
            if not result.ok:
                self._record_failed_url(failed_urls, component)
                self._merge_send_failure(failures, result)

        text = "\n".join(
            component.text for component in text_components if component.text
        ).strip()
        if not text:
            text = default_text
        text = self._append_failed_links(text, failed_urls)

        if text:
            from astrbot.api.message_components import Plain

            result = await self._send_chain(session_id, [Plain(text)])
            self._merge_send_failure(failures, result)
        elif not media_components:
            return SendResult(ok=False, detail="empty_message")

        return self._partial_send_result(failures)

    async def _send_components_in_order(
        self,
        session_id: str,
        components: list[MessageComponent],
        *,
        combine_image_text: bool,
        default_text: str = "",
    ) -> SendResult:
        failures: list[SendResult] = []
        failed_urls: list[str] = []
        pending_image: MessageComponent | None = None
        sent_any = False

        async def send_component(component: MessageComponent) -> None:
            nonlocal sent_any
            chain = self._component_to_chain(component)
            if not chain:
                return
            sent_any = True
            result = await self._send_chain(session_id, chain)
            if not result.ok:
                if self._is_media_component(component):
                    self._record_failed_url(failed_urls, component)
                self._merge_send_failure(failures, result)

        async def flush_pending_image() -> None:
            nonlocal pending_image
            if pending_image is not None:
                await send_component(pending_image)
                pending_image = None

        for component in components:
            if (
                combine_image_text
                and component.kind == "media"
                and component.media_type == "image"
            ):
                await flush_pending_image()
                pending_image = component
                continue

            if (
                combine_image_text
                and component.kind == "text"
                and pending_image is not None
            ):
                paired_image = pending_image
                chain = self._chain_from_components([paired_image, component])
                pending_image = None
                if chain:
                    sent_any = True
                    result = await self._send_chain(session_id, chain)
                    if not result.ok:
                        self._record_failed_url(failed_urls, paired_image)
                        self._merge_send_failure(failures, result)
                continue

            await flush_pending_image()
            await send_component(component)

        await flush_pending_image()
        if not sent_any and default_text:
            from astrbot.api.message_components import Plain

            result = await self._send_chain(session_id, [Plain(default_text)])
            self._merge_send_failure(failures, result)
        elif not sent_any:
            return SendResult(ok=False, detail="empty_message")
        return self._partial_send_result(failures)

    @locked("'global_web'")
    async def _send_chain(self, session_id: str, chain: list) -> SendResult:
        """发送消息链（使用全局网络锁）"""
        message_chain = MessageChain(chain=chain)

        try:
            sent = await StarTools.send_message(session_id, message_chain)
            if sent:
                logger.debug("Message send success: session=%s", session_id)
                return SendResult(ok=True)
            else:
                logger.warning("Message send returned False: session=%s", session_id)
                return SendResult(
                    ok=False, needs_rebind=True, detail="platform_or_session"
                )
        except Exception as ex:
            logger.error(
                "Message send raised exception: session=%s, error=%s",
                session_id,
                ex,
                exc_info=True,
            )
            return SendResult(
                ok=False,
                transient=True,
                detail=self._normalize_error_detail(str(ex)),
            )

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送消息给用户（默认实现）

        组件排序由 MessageFormatter 统一处理。
        """
        try:
            session_id = request.session_id
            platform = context.platform_name if context else ""

            effective_prepared = await self._prepare_effective_media(request, context)

            failed_urls: list[str] = []
            if effective_prepared:
                failed_urls = self._collect_failed_urls(effective_prepared)

            chain = self._formatter.build_chain(
                prepared_media=effective_prepared,
                text=request.message,
                failed_urls=failed_urls,
                platform=platform,
            )

            if not chain:
                return SendResult(ok=False, detail="empty_message")

            return await self._send_chain(session_id, chain)

        except Exception as err:
            logger.error(
                "Send to user failed: session=%s, error=%s", request.session_id, err
            )
            return SendResult(
                ok=False,
                transient=self._is_transient_network_error(err),
                detail=self._normalize_error_detail(str(err)),
            )

    async def send_to_group(
        self,
        platform: str,
        group_id: str,
        message: str = "",
        media: list[tuple[str, str]] | None = None,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送消息到群组"""
        request = SendRequest(
            session_id=f"{platform}:GroupMessage:{group_id}",
            message=message,
            media=media,
        )
        return await self.send_to_user(request, context=context)
