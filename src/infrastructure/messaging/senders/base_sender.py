"""基础消息发送器

提供跨平台消息发送的默认实现。
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.star_tools import StarTools

from ....domain.entities.content_types import is_generated_media_url
from ....shared.constants import (
    MEDIA_CACHE_TTL_SECONDS_DEFAULT,
    QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT,
    QQ_OFFICIAL_DEGRADE_STRATEGY_OPTIONS,
    QQ_OFFICIAL_MEDIA_THRESHOLD_DEFAULT,
    QQ_OFFICIAL_PLATFORMS,
    STYLE_ORIGINAL,
    TELEGRAM_PHOTO_MAX_BYTES,
)
from ...pipeline import MessageComponent, MessageFormatter
from ...utils import get_logger
from ...utils.lock import locked
from ...utils.media_type_detector import detect_media_file, detect_media_hint
from .types import MediaVariant, MessageContext, PreparedMedia, SendRequest, SendResult

if TYPE_CHECKING:
    pass

logger = get_logger()
MAX_SEND_ERROR_DETAIL_LENGTH = 512


@dataclass
class _MediaFallbackOutcome:
    ok: bool
    failures: list[SendResult]


class DefaultMessageSender:
    """默认跨平台发送器策略

    提供基础的消息发送和媒体处理功能。
    组件排序统一由 MessageFormatter 决定，此处只负责发送。
    """

    _timeout_seconds: int = 30
    _proxy: str = ""
    _image_relay_base_url: str = ""
    _media_relay_base_url: str = ""
    _media_download_concurrency: int = 1
    _video_transcode: bool = False
    _video_transcode_timeout: int = 120
    _gif_transcode: bool = False
    _gif_transcode_timeout: int = 60
    _telegram_photo_max_bytes: int = TELEGRAM_PHOTO_MAX_BYTES
    _qq_official_media_threshold: int = QQ_OFFICIAL_MEDIA_THRESHOLD_DEFAULT
    _qq_official_degrade_strategy: str = QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT

    _formatter: MessageFormatter = MessageFormatter()

    @classmethod
    def configure_runtime(
        cls,
        *,
        timeout_seconds: int,
        proxy: str = "",
        image_relay_base_url: str = "",
        media_relay_base_url: str = "",
        media_download_concurrency: int = 1,
    ) -> None:
        """配置运行时参数"""
        DefaultMessageSender._timeout_seconds = max(1, int(timeout_seconds))
        DefaultMessageSender._proxy = proxy or ""
        DefaultMessageSender._image_relay_base_url = image_relay_base_url or ""
        DefaultMessageSender._media_relay_base_url = media_relay_base_url or ""
        try:
            concurrency = int(media_download_concurrency or 1)
        except (TypeError, ValueError):
            concurrency = 1
        DefaultMessageSender._media_download_concurrency = max(1, concurrency)

    @classmethod
    def configure_behavior(
        cls,
        *,
        video_transcode: bool = False,
        video_transcode_timeout: int = 120,
        gif_transcode: bool = False,
        gif_transcode_timeout: int = 60,
        telegram_photo_max_bytes: int = TELEGRAM_PHOTO_MAX_BYTES,
        onebot_napcat_stream_mode: str = "fallback",
        qq_official_media_threshold: int = QQ_OFFICIAL_MEDIA_THRESHOLD_DEFAULT,
        qq_official_degrade_strategy: str = QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT,
    ) -> None:
        """配置发送行为"""
        cls._video_transcode = bool(video_transcode)
        cls._video_transcode_timeout = max(1, int(video_transcode_timeout))
        cls._gif_transcode = bool(gif_transcode)
        cls._gif_transcode_timeout = max(1, int(gif_transcode_timeout))
        cls._telegram_photo_max_bytes = max(1, int(telegram_photo_max_bytes))
        cls._onebot_napcat_stream_mode_default = str(
            onebot_napcat_stream_mode or "fallback"
        )
        cls._qq_official_media_threshold = max(0, int(qq_official_media_threshold))
        strategy = str(
            qq_official_degrade_strategy or QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT
        )
        if strategy not in QQ_OFFICIAL_DEGRADE_STRATEGY_OPTIONS:
            strategy = QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT
        cls._qq_official_degrade_strategy = strategy

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
    def _get_image_relay_base_url(cls) -> str:
        value = getattr(cls, "_image_relay_base_url", None)
        if value is None:
            value = getattr(DefaultMessageSender, "_image_relay_base_url", None)
        return str(value or "")

    @classmethod
    def _get_media_relay_base_url(cls) -> str:
        value = getattr(cls, "_media_relay_base_url", None)
        if value is None:
            value = getattr(DefaultMessageSender, "_media_relay_base_url", None)
        return str(value or "")

    @classmethod
    def _get_media_download_concurrency(cls) -> int:
        value = getattr(cls, "_media_download_concurrency", 1)
        try:
            return max(1, int(value or 1))
        except (TypeError, ValueError):
            return 1

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

    @classmethod
    def _resolve_gif_transcode_decision(
        cls,
        *,
        media_type: str,
        media_url: str,
    ) -> tuple[str, bool]:
        """按声明类型和 URL hint 决定是否把本项交给下载后 GIF 转换链路。"""
        normalized_type = str(media_type or "").strip().lower()
        hint = detect_media_hint(url=media_url, declared_media_type=normalized_type)
        effective_type = normalized_type
        if normalized_type == "video" or hint.media_type == "video":
            effective_type = "video"
        detection_fallback_candidate = normalized_type in {"image", "file"} and (
            hint.media_type == "file" or hint.source in {"declared", "fallback"}
        )
        try_convert_gif = cls._should_transcode_gif() and (
            effective_type == "video" or detection_fallback_candidate
        )
        return effective_type, try_convert_gif

    @staticmethod
    def _ffmpeg_source_for_log() -> str:
        """返回当前 FFmpeg 来源，供 GIF 转换决策日志排查使用。"""
        try:
            from ...utils.ffmpeg_helper import FFmpegTool

            ffmpeg_path = FFmpegTool.ensure_ffmpeg_ready(auto_install=True)
            if ffmpeg_path is None:
                return "unavailable"
            return str(getattr(FFmpegTool, "_ffmpeg_exe_cache_source", "") or "unknown")
        except Exception as ex:
            return f"unavailable:{type(ex).__name__}"

    @classmethod
    def _get_telegram_photo_max_bytes(cls) -> int:
        return max(
            1, int(getattr(cls, "_telegram_photo_max_bytes", TELEGRAM_PHOTO_MAX_BYTES))
        )

    @classmethod
    def _get_qq_official_media_threshold(cls) -> int:
        return max(
            0,
            int(
                getattr(
                    cls,
                    "_qq_official_media_threshold",
                    QQ_OFFICIAL_MEDIA_THRESHOLD_DEFAULT,
                )
            ),
        )

    @classmethod
    def _get_qq_official_degrade_strategy(cls) -> str:
        strategy = str(
            getattr(
                cls,
                "_qq_official_degrade_strategy",
                QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT,
            )
            or QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT
        )
        if strategy not in QQ_OFFICIAL_DEGRADE_STRATEGY_OPTIONS:
            return QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT
        return strategy

    async def _maybe_transcode_video_to_mp4(
        self, media_path: Path
    ) -> tuple[Path, bool]:
        """按当前媒体缓存策略转 MP4，并返回输出是否为本次发送临时文件。"""
        if not self._should_transcode_video():
            return media_path, False
        if media_path.suffix.lower() == ".gif":
            return media_path, False
        try:
            from ...media.media_downloader import MediaDownloader
            from ...utils.ffmpeg_helper import FFmpegTool

            cache_enabled = bool(getattr(MediaDownloader, "_CACHE_ENABLED", True))
            transcoded_path = await FFmpegTool.transcode_to_mp4(
                media_path,
                timeout_seconds=self._get_video_transcode_timeout(),
                auto_install_ffmpeg=True,
                cache_enabled=cache_enabled,
                cache_ttl_seconds=int(
                    getattr(
                        MediaDownloader,
                        "_CACHE_TTL_SECONDS",
                        MEDIA_CACHE_TTL_SECONDS_DEFAULT,
                    )
                ),
            )
            if transcoded_path and transcoded_path.exists():
                return transcoded_path, not cache_enabled
        except Exception as ex:
            logger.warning(
                "prepare_transcode_video: Video transcode failed, using original "
                "media: path=%s, err=%s",
                media_path,
                ex,
            )
        return media_path, False

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

    @classmethod
    def _stage_error_detail(cls, stage: str, detail: str | None) -> str:
        normalized_stage = str(stage or "").strip()
        normalized_detail = str(detail or "").strip() or "send_failed"
        if not normalized_stage:
            return cls._normalize_error_detail(normalized_detail)
        prefix = f"{normalized_stage}:"
        if normalized_detail.startswith(prefix):
            return cls._normalize_error_detail(normalized_detail)
        return cls._normalize_error_detail(f"{prefix} {normalized_detail}")

    @classmethod
    def _result_with_stage(cls, result: SendResult, stage: str) -> SendResult:
        if result.ok:
            return result
        return SendResult(
            ok=False,
            needs_rebind=result.needs_rebind,
            transient=result.transient,
            detail=cls._stage_error_detail(stage, result.detail),
            http_status=result.http_status,
        )

    async def prepare_media(
        self,
        media: list[tuple[str, str]] | None,
        timeout: int = 30,
        proxy: str = "",
    ) -> list[PreparedMedia]:
        """预处理媒体文件"""
        if not media:
            return []

        prepared: list[PreparedMedia | None] = []
        seen_urls: set[str] = set()
        remote_jobs: list[tuple[int, str, str]] = []

        from ...media import MediaDownloader

        downloader = MediaDownloader()

        for media_type, media_url in media:
            if not media_url:
                continue
            if media_type not in {"image", "audio", "video", "file"}:
                continue

            if is_generated_media_url(media_url):
                prepared.append(self._prepare_generated_media(media_type, media_url))
                seen_urls.add(media_url)
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
            if self._get_media_download_concurrency() > 1:
                prepared.append(None)
                remote_jobs.append((len(prepared) - 1, media_type, media_url))
                continue

            prepared.append(
                await self._prepare_remote_media_item(
                    downloader,
                    media_type=media_type,
                    media_url=media_url,
                    timeout=timeout,
                    proxy=proxy,
                )
            )

        if remote_jobs:
            semaphore = asyncio.Semaphore(self._get_media_download_concurrency())

            async def run_job(index: int, media_type: str, media_url: str):
                async with semaphore:
                    return index, await self._prepare_remote_media_item(
                        downloader,
                        media_type=media_type,
                        media_url=media_url,
                        timeout=timeout,
                        proxy=proxy,
                    )

            results = await asyncio.gather(
                *(
                    run_job(index, media_type, media_url)
                    for index, media_type, media_url in remote_jobs
                )
            )
            for index, item in results:
                prepared[index] = item

        return [item for item in prepared if item is not None]

    async def _prepare_remote_media_item(
        self,
        downloader,
        *,
        media_type: str,
        media_url: str,
        timeout: int,
        proxy: str,
    ) -> PreparedMedia:
        try:
            effective_media_type, try_convert_gif = (
                self._resolve_gif_transcode_decision(
                    media_type=media_type,
                    media_url=media_url,
                )
            )
            ffmpeg_source = self._ffmpeg_source_for_log() if try_convert_gif else "skip"
            logger.debug(
                "prepare_media gif decision: sender=%s, media_type=%s, "
                "effective_media_type=%s, gif_transcode=%s, try_convert_gif=%s, "
                "ffmpeg_source=%s, url=%s",
                self.__class__.__name__,
                media_type,
                effective_media_type,
                self._should_transcode_gif(),
                try_convert_gif,
                ffmpeg_source,
                media_url,
            )
            relay_kwargs = self._media_downloader_relay_kwargs()
            if hasattr(downloader, "get_or_download_prepared"):
                prepared_item = await downloader.get_or_download_prepared(
                    url=media_url,
                    timeout_seconds=timeout,
                    proxy=proxy,
                    media_type=effective_media_type,
                    try_convert_gif=try_convert_gif,
                    gif_transcode_timeout=self._get_gif_transcode_timeout(),
                    **relay_kwargs,
                )
                if (
                    effective_media_type == "video"
                    and prepared_item.media_type == "video"
                    and prepared_item.local_path is not None
                ):
                    (
                        local_path,
                        transcode_owned,
                    ) = await self._maybe_transcode_video_to_mp4(
                        prepared_item.local_path
                    )
                    if local_path != prepared_item.local_path:
                        detection = detect_media_file(local_path)
                        prepared_item.local_path = local_path
                        prepared_item.media_type = detection.media_type or "video"
                        prepared_item.detected_mime = detection.mime
                        prepared_item.detected_suffix = detection.suffix
                        prepared_item.detection_source = detection.source
                        if transcode_owned:
                            prepared_item.mark_owned_path(local_path)
                        prepared_item.add_variant(
                            MediaVariant(
                                variant="transcoded",
                                media_type=prepared_item.media_type,
                                path=local_path,
                                mime=detection.mime,
                                suffix=detection.suffix,
                                size_bytes=self._safe_file_size(local_path),
                            )
                        )
                prepared_item.ensure_primary_variant()
                return prepared_item

            local_path = await downloader.get_or_download(
                url=media_url,
                timeout_seconds=timeout,
                proxy=proxy,
                media_type=effective_media_type,
                try_convert_gif=try_convert_gif,
                gif_transcode_timeout=self._get_gif_transcode_timeout(),
                **relay_kwargs,
            )
            transcode_owned = False
            if effective_media_type == "video":
                local_path, transcode_owned = await self._maybe_transcode_video_to_mp4(
                    local_path
                )
            detection = detect_media_file(local_path)
            effective_media_type = (
                detection.media_type
                if detection.media_type in {"image", "video", "audio"}
                else effective_media_type
            )
            prepared_item = PreparedMedia(
                media_type=effective_media_type,
                original_url=media_url,
                local_path=local_path,
                detected_mime=detection.mime,
                detected_suffix=detection.suffix,
                detection_source=detection.source,
            )
            if effective_media_type == "video" and transcode_owned:
                prepared_item.mark_owned_path(local_path)
            prepared_item.ensure_primary_variant()
            return prepared_item
        except Exception as ex:
            logger.warning(
                "prepare_media: Prepare media failed: stage=download_or_validation, "
                "type=%s, url=%s, err=%s",
                media_type,
                media_url,
                ex,
            )
            return PreparedMedia(
                media_type=media_type,
                original_url=media_url,
                download_failed=True,
            )

    def _media_downloader_relay_kwargs(self) -> dict[str, str]:
        return {
            "image_relay_base_url": self._get_image_relay_base_url(),
            "media_relay_base_url": self._get_media_relay_base_url(),
        }

    @staticmethod
    def _prepare_generated_media(
        media_type: str,
        media_url: str,
        local_path: Path | None = None,
        *,
        owned: bool = False,
    ) -> PreparedMedia:
        """把插件本地生成媒体转成 PreparedMedia，不经过 HTTP 下载。"""
        from ...rendering import resolve_table_image_path

        local_path = local_path or resolve_table_image_path(media_url)
        if local_path is None or not local_path.exists():
            return PreparedMedia(
                media_type=media_type,
                original_url=media_url,
                download_failed=True,
                generated=True,
            )

        detection = detect_media_file(local_path)
        effective_media_type = (
            detection.media_type
            if detection.media_type in {"image", "video", "audio"}
            else media_type
        )
        prepared = PreparedMedia(
            media_type=effective_media_type,
            original_url=media_url,
            local_path=local_path,
            detected_mime=detection.mime,
            detected_suffix=detection.suffix,
            detection_source=detection.source,
            generated=True,
        )
        prepared.ensure_primary_variant()
        if owned:
            prepared.mark_owned_path(local_path)
        return prepared

    @staticmethod
    def _generated_layout_local_paths(request: SendRequest) -> dict[str, Path]:
        """从 layout 收集 generated media 的本地路径，优先于稳定 cache 标识解析。"""
        paths: dict[str, Path] = {}
        for fragment in request.layout or []:
            url = str(getattr(fragment, "url", "") or "").strip()
            local_path = str(getattr(fragment, "local_path", "") or "").strip()
            if not url or not local_path or not is_generated_media_url(url):
                continue
            paths.setdefault(url, Path(local_path))
        return paths

    @staticmethod
    def _should_own_generated_local_path(media_url: str, local_path: Path) -> bool:
        """禁用表格图缓存时 layout 会携带一次性临时图，发送后应清理。"""
        from ...rendering import is_ephemeral_generated_media_path

        return is_ephemeral_generated_media_path(media_url, local_path)

    @staticmethod
    def _copy_generated_local_path_for_send(
        media_url: str,
        local_path: Path,
    ) -> Path | None:
        suffix = local_path.suffix or ".png"
        tmp_file = tempfile.NamedTemporaryFile(
            prefix="rsshub_generated_send_",
            suffix=suffix,
            delete=False,
        )
        copy_path = Path(tmp_file.name)
        tmp_file.close()
        try:
            shutil.copy2(local_path, copy_path)
            return copy_path
        except Exception as ex:
            try:
                copy_path.unlink(missing_ok=True)
            except OSError as cleanup_ex:
                logger.debug(
                    "Generated media copy cleanup failed: path=%s, err=%s",
                    copy_path,
                    cleanup_ex,
                )
            logger.warning(
                "generated_media_temp_copy_failed: url=%s, source=%s, dest=%s, "
                "err_type=%s, err=%s",
                media_url,
                local_path,
                copy_path,
                type(ex).__name__,
                ex,
            )
            return None

    def _apply_generated_layout_local_paths(
        self,
        request: SendRequest,
        prepared_media: list[PreparedMedia] | None,
        *,
        mark_owned: bool,
    ) -> list[PreparedMedia] | None:
        local_paths = self._generated_layout_local_paths(request)
        if not local_paths or not prepared_media:
            return prepared_media

        updated: list[PreparedMedia] = []
        for item in prepared_media:
            local_path = local_paths.get(str(item.original_url or ""))
            if local_path is None or not local_path.exists():
                updated.append(item)
                continue
            owned = mark_owned and self._should_own_generated_local_path(
                item.original_url,
                local_path,
            )
            if owned:
                copied_path = self._copy_generated_local_path_for_send(
                    item.original_url,
                    local_path,
                )
                if copied_path is None:
                    updated.append(
                        PreparedMedia(
                            media_type=item.media_type,
                            original_url=item.original_url,
                            download_failed=True,
                            generated=True,
                        )
                    )
                    continue
                local_path = copied_path
            updated.append(
                self._prepare_generated_media(
                    item.media_type,
                    item.original_url,
                    local_path=local_path,
                    owned=owned,
                )
            )
        return updated

    @staticmethod
    def _cleanup_owned_paths(prepared_media: list[PreparedMedia] | None) -> None:
        """仅清理 PreparedMedia 显式标记的本次调用临时文件。"""
        if not prepared_media:
            return
        seen: set[Path] = set()
        for item in prepared_media:
            for raw_path in item.owned_paths:
                path = Path(raw_path)
                if path in seen:
                    continue
                seen.add(path)
                try:
                    path.unlink(missing_ok=True)
                except OSError as ex:
                    logger.debug(
                        "Prepared media temp cleanup failed: path=%s, err=%s",
                        path,
                        ex,
                    )

    @staticmethod
    def _safe_file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

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
        return [
            item.original_url
            for item in prepared_media
            if item.download_failed and not item.generated
        ]

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
        effective_prepared = self._apply_generated_layout_local_paths(
            request,
            effective_prepared,
            mark_owned=request.prepared_media is None,
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
        components = self._formatter.build_components(
            prepared_media=prepared_media,
            text=self._message_with_unavailable_generated_fallbacks(
                request,
                prepared_media,
            ),
            failed_urls=effective_failed_urls,
            platform=platform
            if platform is not None
            else (context.platform_name if context else ""),
        )
        return self._attach_generated_fallbacks(components, request)

    @staticmethod
    def _is_media_component(component: MessageComponent) -> bool:
        return component.kind in {"media", "tail"}

    def _component_to_chain(self, component: MessageComponent) -> list:
        return self._formatter._components_to_chain([component])

    @staticmethod
    def _candidate_to_component(candidate) -> MessageComponent:
        if candidate.action == "file":
            return MessageComponent(
                kind="tail",
                media_type="file",
                file=candidate.file,
                original_url=candidate.original_url,
                name=candidate.name,
            )
        return MessageComponent(
            kind="media",
            media_type=candidate.media_type,
            file=candidate.file,
            original_url=candidate.original_url,
            name=candidate.name,
        )

    def _component_to_file_candidate(self, component: MessageComponent):
        from ..media_send_planner import SEND_ACTION_FILE, MediaSendCandidate

        return MediaSendCandidate(
            action=SEND_ACTION_FILE,
            media_type="file",
            file=component.file,
            original_url=component.original_url,
            name=component.name or Path(component.file).name or "attachment",
            stage="send_file",
        )

    def _apply_first_send_candidates(
        self,
        components: list[MessageComponent],
        prepared_media_by_url: dict[str, PreparedMedia] | None,
        *,
        platform: str,
    ) -> list[MessageComponent]:
        """发送前按平台策略把组件改写为第一个可发送候选。"""
        if not prepared_media_by_url:
            return components

        from ..media_send_planner import MediaSendPlanner

        rewritten: list[MessageComponent] = []
        link_only_urls: list[str] = []
        for component in components:
            if component.kind != "media" or not component.original_url:
                rewritten.append(component)
                continue
            prepared = prepared_media_by_url.get(component.original_url)
            if prepared is None:
                rewritten.append(component)
                continue
            candidates = MediaSendPlanner.candidates_for(
                prepared,
                platform=platform,
            )
            first_candidate = next(
                (candidate for candidate in candidates if candidate.action != "link"),
                None,
            )
            if first_candidate is None:
                if any(candidate.action == "link" for candidate in candidates):
                    link_only_urls.append(component.original_url)
                    continue
                rewritten.append(component)
                continue
            rewritten.append(
                replace(
                    self._candidate_to_component(first_candidate),
                    fallback_text=component.fallback_text,
                )
            )
        if link_only_urls:
            rewritten = self._append_link_only_urls_to_components(
                rewritten,
                link_only_urls,
                platform=platform,
            )
        return rewritten

    def _append_link_only_urls_to_components(
        self,
        components: list[MessageComponent],
        urls: list[str],
        *,
        platform: str,
    ) -> list[MessageComponent]:
        """把预判不可上传的媒体链接合并到正文，避免继续撞平台上传。"""
        updated: list[MessageComponent] = []
        appended = False
        for component in components:
            if component.kind == "text" and not appended:
                updated.append(
                    replace(
                        component,
                        text=self._append_failed_links(component.text, urls),
                    )
                )
                appended = True
                continue
            updated.append(component)
        if not appended:
            updated.append(
                MessageComponent(
                    kind="text",
                    text=self._append_failed_links("", urls),
                )
            )
        return self._formatter._sorter.sort_components(updated, platform=platform)

    async def _send_media_candidate(
        self,
        session_id: str,
        candidate,
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        if candidate.action == "link":
            return SendResult(ok=False, detail="link_candidate")
        component = self._candidate_to_component(candidate)
        chain = self._component_to_chain(component)
        if not chain:
            return SendResult(ok=False, detail="empty_candidate")
        return await self._send_chain(session_id, chain, use_markdown=use_markdown)

    async def _send_component_fallback_candidates(
        self,
        session_id: str,
        component: MessageComponent,
        *,
        prepared_media_by_url: dict[str, PreparedMedia] | None = None,
        platform: str | None = None,
        skip_first_file: str = "",
        use_markdown: bool | None = None,
    ) -> _MediaFallbackOutcome:
        """按平台候选链为一个失败媒体继续尝试兜底发送。"""
        from ..media_send_planner import MediaSendPlanner

        prepared = (
            prepared_media_by_url.get(component.original_url)
            if prepared_media_by_url and component.original_url
            else None
        )
        if prepared is not None:
            candidates = MediaSendPlanner.candidates_for(
                prepared,
                platform=platform,
            )
        else:
            candidates = [self._component_to_file_candidate(component)]

        failures: list[SendResult] = []
        for candidate in candidates:
            if candidate.action == "link":
                continue
            if (
                skip_first_file
                and candidate.file == skip_first_file
                and (
                    (
                        candidate.action == "media"
                        and candidate.media_type == component.media_type
                    )
                    or (component.kind == "tail" and candidate.action == "file")
                )
            ):
                continue
            result = await self._send_media_candidate(
                session_id,
                candidate,
                use_markdown=use_markdown,
            )
            if result.ok:
                return _MediaFallbackOutcome(ok=True, failures=failures)
            self._merge_send_failure(
                failures,
                result,
                stage=candidate.stage or f"send_{candidate.action}",
            )
        return _MediaFallbackOutcome(ok=False, failures=failures)

    def _append_failed_links(self, text: str, failed_urls: list[str]) -> str:
        return self._formatter._append_failed_links(text, failed_urls)

    @staticmethod
    def _generated_fallbacks_by_url(request: SendRequest) -> dict[str, str]:
        """收集 generated media 的纯文本降级；成功发图时不会展示。"""
        fallbacks: dict[str, str] = {}
        for fragment in request.layout or []:
            url = str(fragment.url or "").strip()
            fallback = str(getattr(fragment, "fallback_text", "") or "").strip()
            if url and fallback and is_generated_media_url(url):
                fallbacks.setdefault(url, fallback)
        return fallbacks

    @staticmethod
    def _append_text_fallbacks(text: str, fallback_texts: list[str]) -> str:
        base = str(text or "").strip()
        parts = [base] if base else []
        seen = {base} if base else set()
        for fallback in fallback_texts:
            normalized = str(fallback or "").strip()
            if not normalized or normalized in seen or normalized in base:
                continue
            parts.append(normalized)
            seen.add(normalized)
        return "\n\n".join(parts)

    def _message_with_unavailable_generated_fallbacks(
        self,
        request: SendRequest,
        prepared_media: list[PreparedMedia] | None,
    ) -> str:
        fallback_by_url = self._generated_fallbacks_by_url(request)
        if not fallback_by_url or not prepared_media:
            return request.message

        fallback_texts: list[str] = []
        for item in prepared_media:
            url = str(item.original_url or "").strip()
            if not item.download_failed:
                continue
            if not (item.generated or is_generated_media_url(url)):
                continue
            fallback = fallback_by_url.get(url, "")
            if fallback:
                fallback_texts.append(fallback)
        return self._append_text_fallbacks(request.message, fallback_texts)

    def _message_with_all_generated_fallbacks(self, request: SendRequest) -> str:
        return self._append_text_fallbacks(
            request.message,
            list(self._generated_fallbacks_by_url(request).values()),
        )

    def _attach_generated_fallbacks(
        self,
        components: list[MessageComponent],
        request: SendRequest,
    ) -> list[MessageComponent]:
        fallback_by_url = self._generated_fallbacks_by_url(request)
        if not fallback_by_url:
            return components
        attached: list[MessageComponent] = []
        for component in components:
            fallback = fallback_by_url.get(component.original_url, "")
            if fallback and not component.fallback_text:
                attached.append(replace(component, fallback_text=fallback))
            else:
                attached.append(component)
        return attached

    async def _retry_text_with_generated_fallbacks(
        self,
        request: SendRequest,
        failed_result: SendResult,
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        fallback_text = self._message_with_all_generated_fallbacks(request)
        if (
            not fallback_text
            or fallback_text.strip() == str(request.message or "").strip()
        ):
            return failed_result

        from astrbot.api.message_components import Plain

        retry_result = await self._send_chain(
            request.session_id,
            [Plain(fallback_text)],
            use_markdown=use_markdown,
        )
        if retry_result.ok:
            return retry_result
        return failed_result

    @staticmethod
    def _is_original_style(context: MessageContext | None) -> bool:
        return int(getattr(context, "style", 0) or 0) == STYLE_ORIGINAL

    def _layout_to_components(
        self,
        request: SendRequest,
        *,
        prepared_media_by_url: dict[str, PreparedMedia] | None = None,
    ) -> list[MessageComponent]:
        from ...utils.media_dispatch import MediaDispatchResolver

        components: list[MessageComponent] = []
        for fragment in request.layout or []:
            kind = str(fragment.kind or "").strip()
            if kind == "text":
                text = str(fragment.text or "").strip()
                if text:
                    components.append(MessageComponent(kind="text", text=text))
                continue
            if kind in {"image", "video", "audio", "file"} and fragment.url:
                fallback_text = str(
                    getattr(fragment, "fallback_text", "") or ""
                ).strip()
                info = MediaDispatchResolver.resolve_layout_fragment(
                    fragment,
                    prepared_media_by_url=prepared_media_by_url,
                )
                if not info.media_type:
                    if fallback_text and is_generated_media_url(fragment.url):
                        components.append(
                            MessageComponent(kind="text", text=fallback_text)
                        )
                    continue
                components.append(
                    MessageComponent(
                        kind=info.component_kind,
                        media_type=info.media_type,
                        file=info.file,
                        original_url=info.original_url,
                        name=info.name,
                        fallback_text=fallback_text,
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
        if is_generated_media_url(url):
            return
        if url and url not in failed_urls:
            failed_urls.append(url)

    @staticmethod
    def _record_failed_media_fallback(
        failed_urls: list[str],
        failed_fallbacks: list[str],
        component: MessageComponent,
    ) -> None:
        url = str(component.original_url or "").strip()
        fallback = str(component.fallback_text or "").strip()
        if fallback and is_generated_media_url(url):
            if fallback not in failed_fallbacks:
                failed_fallbacks.append(fallback)
            return
        DefaultMessageSender._record_failed_url(failed_urls, component)

    @staticmethod
    def _merge_send_failure(
        failures: list[SendResult],
        result: SendResult,
        *,
        stage: str | None = None,
    ) -> None:
        if not result.ok:
            if stage:
                result = DefaultMessageSender._result_with_stage(result, stage)
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

    @staticmethod
    def _counts_degraded_media_delivery_as_success(platform: str | None) -> bool:
        """QQ Official 降级已送达时不应触发轮询补推。"""
        return str(platform or "").strip().lower() in QQ_OFFICIAL_PLATFORMS

    async def _send_components_media_first(
        self,
        session_id: str,
        components: list[MessageComponent],
        *,
        default_text: str = "",
        use_markdown: bool | None = None,
        prepared_media_by_url: dict[str, PreparedMedia] | None = None,
        platform: str | None = None,
    ) -> SendResult:
        media_components = [
            component for component in components if self._is_media_component(component)
        ]
        text_components = [
            component for component in components if component.kind == "text"
        ]

        failed_urls: list[str] = []
        failed_fallbacks: list[str] = []
        failures: list[SendResult] = []
        degraded_delivery_ok = False

        for component in media_components:
            chain = self._component_to_chain(component)
            if not chain:
                continue
            result = await self._send_chain(
                session_id,
                chain,
                use_markdown=use_markdown,
            )
            if not result.ok:
                self._merge_send_failure(
                    failures,
                    result,
                    stage=f"send_{component.media_type or component.kind}",
                )
                fallback = await self._send_component_fallback_candidates(
                    session_id,
                    component,
                    prepared_media_by_url=prepared_media_by_url,
                    platform=platform,
                    skip_first_file=component.file,
                    use_markdown=use_markdown,
                )
                failures.extend(fallback.failures)
                if fallback.ok:
                    degraded_delivery_ok = True
                else:
                    self._record_failed_media_fallback(
                        failed_urls,
                        failed_fallbacks,
                        component,
                    )

        text = "\n".join(
            component.text for component in text_components if component.text
        ).strip()
        if not text:
            text = default_text
        text = self._append_text_fallbacks(text, failed_fallbacks)
        text = self._append_failed_links(text, failed_urls)

        if text:
            from astrbot.api.message_components import Plain

            result = await self._send_chain(
                session_id,
                [Plain(text)],
                use_markdown=use_markdown,
            )
            if result.ok and (failed_urls or failed_fallbacks):
                degraded_delivery_ok = True
            self._merge_send_failure(failures, result, stage="send_text")
        elif not media_components:
            return SendResult(ok=False, detail="empty_message")

        if (
            failures
            and degraded_delivery_ok
            and self._counts_degraded_media_delivery_as_success(platform)
        ):
            return SendResult(ok=True)
        return self._partial_send_result(failures)

    async def _send_components_in_order(
        self,
        session_id: str,
        components: list[MessageComponent],
        *,
        combine_image_text: bool,
        default_text: str = "",
        use_markdown: bool | None = None,
        prepared_media_by_url: dict[str, PreparedMedia] | None = None,
        platform: str | None = None,
    ) -> SendResult:
        failures: list[SendResult] = []
        failed_urls: list[str] = []
        failed_fallbacks: list[str] = []
        pending_image: MessageComponent | None = None
        sent_any = False

        async def send_component(component: MessageComponent) -> None:
            nonlocal sent_any
            chain = self._component_to_chain(component)
            if not chain:
                return
            sent_any = True
            result = await self._send_chain(
                session_id,
                chain,
                use_markdown=use_markdown,
            )
            if not result.ok:
                self._merge_send_failure(
                    failures,
                    result,
                    stage=f"send_{component.media_type or component.kind}",
                )
                if self._is_media_component(component):
                    fallback = await self._send_component_fallback_candidates(
                        session_id,
                        component,
                        prepared_media_by_url=prepared_media_by_url,
                        platform=platform,
                        skip_first_file=component.file,
                        use_markdown=use_markdown,
                    )
                    failures.extend(fallback.failures)
                    if not fallback.ok:
                        self._record_failed_media_fallback(
                            failed_urls,
                            failed_fallbacks,
                            component,
                        )

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
                    result = await self._send_chain(
                        session_id,
                        chain,
                        use_markdown=use_markdown,
                    )
                    if not result.ok:
                        self._merge_send_failure(
                            failures,
                            result,
                            stage="send_image_text",
                        )
                        fallback = await self._send_component_fallback_candidates(
                            session_id,
                            paired_image,
                            prepared_media_by_url=prepared_media_by_url,
                            platform=platform,
                            skip_first_file=paired_image.file,
                            use_markdown=use_markdown,
                        )
                        failures.extend(fallback.failures)
                        if not fallback.ok:
                            self._record_failed_media_fallback(
                                failed_urls,
                                failed_fallbacks,
                                paired_image,
                            )
                continue

            await flush_pending_image()
            await send_component(component)

        await flush_pending_image()
        if not sent_any and default_text:
            from astrbot.api.message_components import Plain

            result = await self._send_chain(
                session_id,
                [Plain(default_text)],
                use_markdown=use_markdown,
            )
            self._merge_send_failure(failures, result, stage="send_text")
        elif not sent_any:
            return SendResult(ok=False, detail="empty_message")

        fallback_text = self._append_text_fallbacks("", failed_fallbacks)
        fallback_text = self._append_failed_links(fallback_text, failed_urls)
        if fallback_text:
            from astrbot.api.message_components import Plain

            result = await self._send_chain(
                session_id,
                [Plain(fallback_text)],
                use_markdown=use_markdown,
            )
            self._merge_send_failure(failures, result, stage="send_text_fallback")
        return self._partial_send_result(failures)

    @locked("'global_web'")
    async def _send_chain(
        self,
        session_id: str,
        chain: list,
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        """发送消息链（使用全局网络锁）"""
        message_chain = MessageChain(chain=chain)
        if use_markdown is not None:
            message_chain.use_markdown(use_markdown)

        try:
            sent = await StarTools.send_message(session_id, message_chain)
            if sent:
                logger.debug("Message send success: session=%s", session_id)
                return SendResult(ok=True)
            else:
                logger.warning("Message send returned False: session=%s", session_id)
                return SendResult(
                    ok=False,
                    needs_rebind=True,
                    detail=self._stage_error_detail(
                        "platform_send",
                        "platform_or_session",
                    ),
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
                detail=self._stage_error_detail("platform_send", str(ex)),
            )

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送消息给用户（默认实现）

        组件排序由 MessageFormatter 统一处理。
        """
        effective_prepared: list[PreparedMedia] | None = None
        cleanup_owned = request.prepared_media is None
        try:
            session_id = request.session_id
            platform = context.platform_name if context else ""

            effective_prepared = await self._prepare_effective_media(request, context)

            failed_urls: list[str] = []
            if effective_prepared:
                failed_urls = self._collect_failed_urls(effective_prepared)

            chain = self._formatter.build_chain(
                prepared_media=effective_prepared,
                text=self._message_with_unavailable_generated_fallbacks(
                    request,
                    effective_prepared,
                ),
                failed_urls=failed_urls,
                platform=platform,
            )

            if not chain:
                return SendResult(ok=False, detail="empty_message")

            result = await self._send_chain(session_id, chain)
            if result.ok:
                return result
            return await self._retry_text_with_generated_fallbacks(request, result)

        except Exception as err:
            logger.error(
                "Send to user failed: session=%s, error=%s", request.session_id, err
            )
            return SendResult(
                ok=False,
                transient=self._is_transient_network_error(err),
                detail=self._stage_error_detail("send_to_user", str(err)),
            )
        finally:
            if cleanup_owned:
                self._cleanup_owned_paths(effective_prepared)

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
