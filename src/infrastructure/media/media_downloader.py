"""媒体下载与缓存模块

提供媒体文件异步下载、缓存管理和格式转换功能。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import aiohttp

from astrbot.core.utils.http_ssl import build_tls_connector

from ...shared.constants import (
    GIF_COMPRESS_TARGET_MAX_BYTES,
    MEDIA_CACHE_TTL_SECONDS_DEFAULT,
)
from ..utils import get_plugin_cache_dir
from ..utils.ffmpeg_helper import FFmpegTool
from ..utils.logger import get_logger
from ..utils.media_integrity import validate_media_file
from ..utils.media_type_detector import (
    MEDIA_TYPE_SUFFIXES,
    detect_media_bytes,
    detect_media_file,
    detect_media_hint,
    guess_suffix_from_url,
    suffix_from_content_type,
    suffix_from_file_header,
    suffix_from_query,
)

logger = get_logger()

_MEDIA_FORMAT_SUFFIXES = MEDIA_TYPE_SUFFIXES
_MEDIA_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_DIAGNOSTIC_RESPONSE_HEADERS: tuple[str, ...] = (
    "server",
    "cf-ray",
    "cf-cache-status",
    "content-type",
    "content-length",
)


def _build_relay_url(base: str | None, original_url: str) -> str:
    """把原始媒体 URL 包装成反代地址；base 为空（含 None）时原样返回。

    支持 https://wsrv.nl/ 与 https://wsrv.nl/?url= 两种形式：以 '=' 结尾视为
    前缀直接追加编码后的原始 URL；含 '?' 时用 '&url=' 追加；否则归一为
    '<base>/?url=<encoded>'。
    """
    base = (base or "").strip()
    if not base:
        return original_url
    encoded = quote(original_url, safe="")
    if base.endswith("="):
        return base + encoded
    if "?" in base:
        return base + "&url=" + encoded
    return base.rstrip("/") + "/?url=" + encoded


def _select_relay_base(
    media_type: str | None,
    image_relay_base_url: str | None,
    media_relay_base_url: str | None,
) -> str:
    """图片优先走图片反代；图片反代未配置或非图片走通用媒体反代；都未配置返回空串。

    两个 base 入参允许为 None（视作未配置）。
    """
    img = (image_relay_base_url or "").strip()
    media = (media_relay_base_url or "").strip()
    if media_type == "image":
        return img or media
    return media


class MediaDownloader:
    """媒体下载器，支持缓存管理和格式转换。"""

    _CACHE_ENABLED: bool = True
    _CACHE_TTL_SECONDS: int = MEDIA_CACHE_TTL_SECONDS_DEFAULT
    _CACHE_GC_INTERVAL_SECONDS: int = 5 * 60
    _CACHE_GC_GRACE_SECONDS: int = 10 * 60
    _CACHE_MEDIA_SUFFIXES: tuple[str, ...] = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".mp4",
        ".webm",
        ".mov",
        ".mkv",
        ".avi",
        ".mp3",
        ".ogg",
        ".wav",
        ".m4a",
        ".aac",
        ".bin",
    )

    @classmethod
    def configure_cache(
        cls,
        *,
        enabled: bool = True,
        ttl_seconds: int,
        gc_interval_seconds: int,
        gc_grace_seconds: int,
    ) -> None:
        """Configure media success-cache timing thresholds."""
        cls._CACHE_ENABLED = bool(enabled)
        cls._CACHE_TTL_SECONDS = max(1, int(ttl_seconds))
        cls._CACHE_GC_INTERVAL_SECONDS = max(1, int(gc_interval_seconds))
        cls._CACHE_GC_GRACE_SECONDS = max(0, int(gc_grace_seconds))

    def __init__(self, cache_dir: Path | None = None) -> None:
        if cache_dir is None:
            cache_dir = get_plugin_cache_dir("media")
        self._cache_dir = cache_dir
        self._cache_gc_lock = asyncio.Lock()
        self._cache_io_lock = asyncio.Lock()
        self._cache_gc_last_run = 0.0

    @staticmethod
    def _suffix_from_format_value(value: str) -> str:
        media_format = (
            unquote(str(value or "")).strip().lower().lstrip(".").split("&", 1)[0]
        )
        return _MEDIA_FORMAT_SUFFIXES.get(media_format, "")

    @staticmethod
    def _suffix_from_query(url: str) -> str:
        return suffix_from_query(url)

    @staticmethod
    def _suffix_from_content_type(content_type: str | None) -> str:
        return suffix_from_content_type(content_type)

    @staticmethod
    def _suffix_from_bytes(data: bytes) -> str:
        detection = detect_media_bytes(data)
        return "" if detection.suffix == ".bin" else detection.suffix

    @staticmethod
    def _suffix_from_file_header(path: Path) -> str:
        return suffix_from_file_header(path)

    @staticmethod
    def _guess_suffix(url: str) -> str:
        return guess_suffix_from_url(url)

    @staticmethod
    def _expand_download_candidates(url: str) -> list[str]:
        candidates = [url]
        try:
            parsed = urlparse(url)
            wrapped_values = parse_qs(parsed.query).get("url", [])
            for wrapped in wrapped_values:
                if wrapped.startswith("http://") or wrapped.startswith("https://"):
                    if wrapped not in candidates:
                        candidates.append(wrapped)
        except Exception:
            pass
        return candidates

    @staticmethod
    def _diagnostic_headers(resp: aiohttp.ClientResponse) -> str:
        parts = []
        for header in _DIAGNOSTIC_RESPONSE_HEADERS:
            value = resp.headers.get(header)
            if value:
                parts.append(f"{header}={value}")
        return ", ".join(parts)

    async def download_to_temp(
        self,
        *,
        url: str,
        timeout_seconds: int,
        proxy: str,
    ) -> Path:
        """下载媒体到临时文件

        Args:
            url: 媒体URL
            timeout_seconds: 下载超时
            proxy: 代理地址

        Returns:
            临时文件路径

        Raises:
            RuntimeError: 所有候选URL下载失败
        """
        timeout = aiohttp.ClientTimeout(total=max(1, int(timeout_seconds)))
        last_err: Exception | None = None

        async with aiohttp.ClientSession(
            timeout=timeout,
            trust_env=True,
            connector=build_tls_connector(),
        ) as session:
            for candidate_url in self._expand_download_candidates(url):
                try:
                    async with session.get(
                        candidate_url,
                        proxy=proxy or None,
                        headers=_MEDIA_REQUEST_HEADERS,
                        allow_redirects=True,
                        max_redirects=10,
                    ) as resp:
                        if resp.status >= 400:
                            diagnostics = self._diagnostic_headers(resp)
                            header_detail = (
                                f", headers=({diagnostics})" if diagnostics else ""
                            )
                            raise RuntimeError(
                                f"download failed: status={resp.status}, "
                                f"url={candidate_url}{header_detail}"
                            )
                        data = await resp.read()
                        if not data:
                            raise RuntimeError(
                                f"download failed: empty response, url={candidate_url}"
                            )
                        detection = detect_media_bytes(data)
                        if detection.suffix == ".bin":
                            detection = detect_media_hint(
                                url=candidate_url,
                                content_type=resp.headers.get("Content-Type"),
                            )
                        suffix = detection.suffix or ".bin"

                    fd, tmp_name = tempfile.mkstemp(
                        prefix="rsshub_media_",
                        suffix=suffix,
                    )
                    try:
                        with os.fdopen(fd, "wb") as fp:
                            fp.write(data)
                    except Exception:
                        Path(tmp_name).unlink(missing_ok=True)
                        raise
                    return Path(tmp_name)
                except Exception as ex:
                    last_err = ex
                    logger.warning(
                        "Media download attempt failed: origin=%s, "
                        "candidate=%s, err_type=%s, err=%r",
                        url,
                        candidate_url,
                        type(ex).__name__,
                        ex,
                    )

        if last_err is not None:
            raise RuntimeError(
                f"download failed for all candidates, url={url}, "
                f"last_error={last_err!r}"
            ) from last_err
        raise RuntimeError(f"download failed for all candidates, url={url}")

    @staticmethod
    def safe_unlink(path: Path | None) -> None:
        """安全删除文件"""
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except Exception as ex:
            logger.debug("remove temp media failed: path=%s, err=%s", path, ex)

    def _cache_file_prefix(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def _cache_file_path(self, url: str, suffix: str | None = None) -> Path:
        digest = self._cache_file_prefix(url)
        if suffix is None:
            suffix = self._guess_suffix(url)
        return self._cache_dir / f"{digest}{suffix}"

    def _cache_meta_path(self, url: str) -> Path:
        digest = self._cache_file_prefix(url)
        return self._cache_dir / f"{digest}.meta"

    def _renew_cache_expiry(self, url: str) -> float:
        """命中成功缓存时续期，避免活跃媒体被周期 GC 清掉。"""
        expire_ts = time.time() + self._CACHE_TTL_SECONDS
        self._cache_meta_path(url).write_text(str(expire_ts), encoding="utf-8")
        return expire_ts

    def _delete_cache_entry(self, url: str) -> None:
        digest = self._cache_file_prefix(url)
        self.safe_unlink(self._cache_meta_path(url))
        for suffix in self._CACHE_MEDIA_SUFFIXES:
            self.safe_unlink(self._cache_dir / f"{digest}{suffix}")

    def _stale_orphan_age_threshold(self) -> int:
        return self._CACHE_TTL_SECONDS + self._CACHE_GC_GRACE_SECONDS

    def _collect_expired_cache_paths(
        self, now_ts: float
    ) -> tuple[list[Path], list[tuple[Path, float]]]:
        meta_paths_to_check: list[Path] = []
        orphan_media_with_age: list[tuple[Path, float]] = []

        if not self._cache_dir.exists():
            return meta_paths_to_check, orphan_media_with_age

        for meta_path in self._cache_dir.glob("*.meta"):
            try:
                expire_ts = float(meta_path.read_text(encoding="utf-8").strip())
            except Exception:
                expire_ts = 0.0

            if expire_ts + self._CACHE_GC_GRACE_SECONDS >= now_ts:
                continue
            meta_paths_to_check.append(meta_path)

        stale_orphan_age = self._stale_orphan_age_threshold()
        for suffix in self._CACHE_MEDIA_SUFFIXES:
            for media_path in self._cache_dir.glob(f"*{suffix}"):
                meta_path = media_path.with_suffix(".meta")
                if meta_path.exists():
                    continue
                try:
                    age = now_ts - media_path.stat().st_mtime
                except OSError:
                    continue
                if age < stale_orphan_age:
                    continue
                orphan_media_with_age.append((media_path, age))

        return meta_paths_to_check, orphan_media_with_age

    def _apply_cache_gc_deletions(
        self,
        meta_paths_to_check: list[Path],
        orphan_media_with_age: list[tuple[Path, float]],
        now_ts: float,
    ) -> int:
        removed = 0

        for meta_path in meta_paths_to_check:
            if not meta_path.exists():
                continue

            try:
                raw_expire_ts = meta_path.read_text(encoding="utf-8").split("\n", 1)[0]
                expire_ts = float(raw_expire_ts)
            except Exception:
                expire_ts = 0.0
            if expire_ts + self._CACHE_GC_GRACE_SECONDS >= now_ts:
                continue

            stem = meta_path.stem
            self.safe_unlink(meta_path)
            removed += 1

            for suffix in self._CACHE_MEDIA_SUFFIXES:
                media_path = self._cache_dir / f"{stem}{suffix}"
                if media_path.exists():
                    self.safe_unlink(media_path)
                    removed += 1

        stale_orphan_age = self._stale_orphan_age_threshold()
        for media_path, age in orphan_media_with_age:
            if not media_path.exists():
                continue

            meta_path = media_path.with_suffix(".meta")
            if meta_path.exists():
                continue

            if age < stale_orphan_age:
                continue

            self.safe_unlink(media_path)
            removed += 1

        return removed

    async def _run_periodic_cache_gc(self) -> None:
        if not self._CACHE_ENABLED:
            return

        now_ts = time.time()
        if now_ts - self._cache_gc_last_run < self._CACHE_GC_INTERVAL_SECONDS:
            return

        async with self._cache_gc_lock:
            now_ts = time.time()
            if now_ts - self._cache_gc_last_run < self._CACHE_GC_INTERVAL_SECONDS:
                return

            meta_paths, orphan_media = self._collect_expired_cache_paths(now_ts)

            async with self._cache_io_lock:
                removed = self._apply_cache_gc_deletions(
                    meta_paths, orphan_media, now_ts
                )
                self._cache_gc_last_run = now_ts

        if removed > 0:
            logger.debug("Media cache GC removed %s files", removed)

    def _read_cache(self, url: str) -> Path | None:
        if not self._CACHE_ENABLED:
            return None

        meta_path = self._cache_meta_path(url)
        if not meta_path.exists():
            logger.debug(
                "Media cache miss: url=%s, meta_exists=False, meta=%s",
                url,
                meta_path,
            )
            return None

        digest = self._cache_file_prefix(url)
        file_path = None
        for suffix in self._CACHE_MEDIA_SUFFIXES:
            candidate = self._cache_dir / f"{digest}{suffix}"
            if candidate.exists():
                file_path = candidate
                break

        if file_path is None:
            logger.debug(
                "Media cache miss: url=%s, no matching file found for digest=%s",
                url,
                digest,
            )
            return None

        try:
            expire_ts = float(meta_path.read_text(encoding="utf-8").strip())
        except Exception:
            logger.debug("Media cache meta invalid: url=%s, meta=%s", url, meta_path)
            return None

        now_ts = time.time()
        if expire_ts < now_ts:
            logger.debug(
                "Media cache expired: url=%s, now=%s, expire=%s, file=%s",
                url,
                now_ts,
                expire_ts,
                file_path,
            )
            return None

        try:
            renewed_expire_ts = self._renew_cache_expiry(url)
            logger.debug(
                "Media cache hit: url=%s, file=%s, renewed_expire=%s",
                url,
                file_path,
                renewed_expire_ts,
            )
        except Exception as ex:
            logger.warning(
                "Media cache renew failed, keeping hit: url=%s, file=%s, err=%s",
                url,
                file_path,
                ex,
            )
        return file_path

    async def _read_valid_cache(
        self,
        url: str,
        *,
        media_type: str | None,
        warning_label: str = "Media cache validation failed",
    ) -> Path | None:
        async with self._cache_io_lock:
            cached = self._read_cache(url)
        if cached is None:
            return None

        validation_type = self._validation_type_for_path(cached, media_type)
        validation = await validate_media_file(
            cached,
            media_type=validation_type,
            timeout_seconds=10,
        )
        if validation.ok:
            return cached

        logger.warning(
            "%s, removing cache: url=%s, path=%s, detail=%s",
            warning_label,
            url,
            cached,
            validation.detail,
        )
        async with self._cache_io_lock:
            latest = self._read_cache(url)
            if latest == cached:
                self._delete_cache_entry(url)
        return None

    @staticmethod
    def _validation_type_for_path(path: Path, media_type: str | None) -> str | None:
        detected_type = detect_media_file(path).media_type
        if detected_type in {"image", "video", "audio"}:
            return detected_type
        return media_type

    def _write_cache(self, url: str, source: Path) -> Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        detection = detect_media_file(source)
        actual_suffix = detection.suffix or ".bin"
        cache_path = self._cache_file_path(url, suffix=actual_suffix)
        meta_path = self._cache_meta_path(url)
        cache_path.write_bytes(source.read_bytes())
        expire_ts = time.time() + self._CACHE_TTL_SECONDS
        meta_path.write_text(str(expire_ts), encoding="utf-8")
        logger.debug(
            "Media cache write: url=%s, source_suffix=%s, cache=%s, "
            "meta=%s, cache_exists=%s, meta_exists=%s, expire=%s",
            url,
            actual_suffix,
            cache_path,
            meta_path,
            cache_path.exists(),
            meta_path.exists(),
            expire_ts,
        )
        return cache_path

    def _normalize_detected_suffix(self, source: Path) -> Path:
        current_suffix = source.suffix.lower()
        detection = detect_media_file(source)
        detected_suffix = detection.suffix
        if current_suffix and current_suffix == detected_suffix:
            return source
        if not detected_suffix or detected_suffix == ".bin":
            return source

        fd, tmp_name = tempfile.mkstemp(
            prefix="rsshub_media_detected_",
            suffix=detected_suffix,
        )
        os.close(fd)
        normalized = Path(tmp_name)
        try:
            normalized.write_bytes(source.read_bytes())
        except Exception:
            normalized.unlink(missing_ok=True)
            raise
        return normalized

    async def _download_m3u8_to_cache(
        self,
        *,
        url: str,
        proxy: str,
        m3u8_timeout: int,
    ) -> Path:
        """使用 ffmpeg 下载 m3u8 流到缓存

        Args:
            url: m3u8 URL
            proxy: 代理地址
            m3u8_timeout: 下载超时

        Returns:
            缓存文件路径

        Raises:
            RuntimeError: 下载失败
        """
        cache_enabled = self._CACHE_ENABLED
        if cache_enabled:
            await self._run_periodic_cache_gc()

        cache_url = f"{url}#mp4"

        if cache_enabled:
            cached = await self._read_valid_cache(cache_url, media_type="video")
            if cached is not None:
                logger.debug(
                    "Media cache return existing m3u8: url=%s, path=%s",
                    cache_url,
                    cached,
                )
                return cached

            cache_digest = self._cache_file_prefix(cache_url)
            output_path = self._cache_dir / f"{cache_digest}.mp4"
            meta_path: Path | None = self._cache_dir / f"{cache_digest}.meta"
        else:
            fd, tmp_name = tempfile.mkstemp(prefix="rsshub_m3u8_", suffix=".mp4")
            os.close(fd)
            output_path = Path(tmp_name)
            meta_path = None

        logger.debug(
            "Media cache m3u8 download start: url=%s, timeout=%s, proxy=%s",
            url,
            m3u8_timeout,
            bool(proxy),
        )

        last_error: str | None = None
        success = False
        for candidate_url in self._expand_download_candidates(url):
            candidate_error: str | None = None
            try:
                if output_path.exists():
                    self.safe_unlink(output_path)
                success = await FFmpegTool.download_m3u8_to_mp4(
                    m3u8_url=candidate_url,
                    output_path=output_path,
                    timeout_seconds=m3u8_timeout,
                    proxy=proxy,
                )
            except Exception as ex:
                success = False
                candidate_error = repr(ex)
            if success:
                break
            if candidate_error is None:
                candidate_error = "ffmpeg returned unsuccessful result"
            last_error = candidate_error
            logger.warning(
                "Media cache m3u8 download attempt failed: origin=%s, candidate=%s, "
                "detail=%s",
                url,
                candidate_url,
                candidate_error,
            )

        if not success:
            self.safe_unlink(output_path)
            detail = f", last_error={last_error}" if last_error else ""
            raise RuntimeError(f"m3u8 download failed: {url}{detail}")

        validation = await validate_media_file(
            output_path,
            media_type="video",
            timeout_seconds=10,
        )
        if not validation.ok:
            self.safe_unlink(output_path)
            raise RuntimeError(
                f"m3u8 download produced invalid video: {url}, "
                f"detail={validation.detail}"
            )

        if cache_enabled and meta_path is not None:
            expire_ts = time.time() + self._CACHE_TTL_SECONDS
            meta_path.write_text(str(expire_ts), encoding="utf-8")

        logger.debug(
            "Media cache m3u8 download complete: url=%s, path=%s, bytes=%s",
            url,
            output_path,
            output_path.stat().st_size if output_path.exists() else 0,
        )
        return output_path

    async def get_or_download(
        self,
        *,
        url: str,
        timeout_seconds: int = 30,
        proxy: str = "",
        media_type: str | None = None,
        try_convert_gif: bool = False,
        gif_transcode_timeout: int = 60,
        m3u8_timeout: int = 120,
        image_relay_base_url: str | None = "",
        media_relay_base_url: str | None = "",
    ) -> Path:
        """下载媒体到缓存，支持 GIF 自动转换

        Args:
            url: 媒体URL
            timeout_seconds: 下载超时
            proxy: 代理地址
            media_type: 调用方已知媒体类型（image/video/audio/file）
            try_convert_gif: 是否尝试将无声视频转为GIF
            gif_transcode_timeout: GIF转码超时
            m3u8_timeout: m3u8下载超时
            image_relay_base_url: 图片反代 base URL，配置后图片走该反代抓取
            media_relay_base_url: 通用媒体反代 base URL，配置后非图片媒体走该反代抓取

        Returns:
            缓存文件路径
        """
        cache_enabled = self._CACHE_ENABLED
        if cache_enabled:
            await self._run_periodic_cache_gc()

        media_hint = detect_media_hint(url=url, declared_media_type=media_type)
        is_m3u8 = media_hint.suffix == ".m3u8"
        if is_m3u8:
            return await self._download_m3u8_to_cache(
                url=url, proxy=proxy, m3u8_timeout=m3u8_timeout
            )

        is_video = media_hint.media_type == "video"

        cache_url = url
        if try_convert_gif and is_video:
            cache_url = f"{url}#gif"

        if cache_enabled:
            cached = await self._read_valid_cache(cache_url, media_type=media_type)
            if cached is not None:
                logger.debug(
                    "Media cache return existing: url=%s, path=%s",
                    cache_url,
                    cached,
                )
                return cached

        logger.debug(
            "Media cache download start: url=%s, timeout_seconds=%s, "
            "proxy_enabled=%s, try_convert_gif=%s",
            url,
            timeout_seconds,
            bool(proxy),
            try_convert_gif,
        )
        relay_base = _select_relay_base(
            media_hint.media_type or media_type,
            image_relay_base_url,
            media_relay_base_url,
        )
        fetch_url = _build_relay_url(relay_base, url)
        if fetch_url != url:
            try:
                tmp_path = await self.download_to_temp(
                    url=fetch_url, timeout_seconds=timeout_seconds, proxy=proxy
                )
            except Exception as ex:
                logger.warning(
                    "媒体反代下载失败，回源直连: relay=%s, url=%s, err=%s",
                    fetch_url,
                    url,
                    ex,
                )
                tmp_path = await self.download_to_temp(
                    url=url, timeout_seconds=timeout_seconds, proxy=proxy
                )
        else:
            tmp_path = await self.download_to_temp(
                url=url, timeout_seconds=timeout_seconds, proxy=proxy
            )
        logger.debug(
            "Media cache download complete: url=%s, tmp=%s, tmp_exists=%s",
            url,
            tmp_path,
            tmp_path.exists(),
        )

        normalized_path = self._normalize_detected_suffix(tmp_path)
        converted_path = normalized_path
        if try_convert_gif and is_video and tmp_path.exists():
            try:
                has_audio = await FFmpegTool.has_audio_stream(
                    tmp_path,
                    timeout_seconds=10,
                    auto_install_ffmpeg=True,
                )
                if not has_audio:
                    logger.info(
                        "Converting silent video to GIF: url=%s, path=%s",
                        url,
                        tmp_path,
                    )
                    gif_path = await FFmpegTool.transcode_to_gif(
                        tmp_path,
                        timeout_seconds=gif_transcode_timeout,
                        auto_install_ffmpeg=True,
                        cache_enabled=cache_enabled,
                        cache_ttl_seconds=self._CACHE_TTL_SECONDS,
                    )
                    if gif_path and gif_path.exists():
                        converted_path = gif_path
                        logger.debug(
                            "GIF conversion successful: url=%s, gif_path=%s, size=%s",
                            url,
                            gif_path,
                            gif_path.stat().st_size,
                        )
                    else:
                        logger.warning(
                            "GIF conversion failed, using original video: url=%s",
                            url,
                        )
            except Exception as ex:
                logger.warning(
                    "GIF conversion error, using original video: url=%s, err=%s",
                    url,
                    ex,
                )

        preserve_path: Path | None = None
        try:
            if cache_enabled:
                cached = await self._read_valid_cache(
                    cache_url,
                    media_type=media_type,
                    warning_label="Media cache peer write validation failed",
                )
                if cached is not None:
                    logger.debug(
                        "Media cache filled by peer task: url=%s, path=%s",
                        cache_url,
                        cached,
                    )
                    return cached

            validation_type = (
                "image" if converted_path.suffix.lower() == ".gif" else media_type
            )
            validation = await validate_media_file(
                converted_path,
                media_type=validation_type,
                timeout_seconds=10,
            )
            if not validation.ok:
                raise RuntimeError(
                    f"media validation failed before cache: url={url}, "
                    f"detail={validation.detail}"
                )

            if not cache_enabled:
                logger.debug(
                    "Media cache disabled, return temp media: url=%s, path=%s",
                    url,
                    converted_path,
                )
                preserve_path = converted_path
                return converted_path

            async with self._cache_io_lock:
                written = self._write_cache(cache_url, converted_path)
            logger.debug(
                "Media cache return new write: url=%s, path=%s",
                cache_url,
                written,
            )
            return written
        finally:
            cleanup_paths: list[Path] = []
            for path in (converted_path, normalized_path, tmp_path):
                if path not in cleanup_paths:
                    cleanup_paths.append(path)
            for path in cleanup_paths:
                if path == preserve_path:
                    continue
                self.safe_unlink(path)

    async def get_or_download_prepared(
        self,
        *,
        url: str,
        timeout_seconds: int = 30,
        proxy: str = "",
        media_type: str | None = None,
        try_convert_gif: bool = False,
        gif_transcode_timeout: int = 60,
        m3u8_timeout: int = 120,
        image_relay_base_url: str | None = "",
        media_relay_base_url: str | None = "",
    ):
        """下载媒体并返回 PreparedMedia，保留原始视频与 GIF 变体。

        Args:
            image_relay_base_url: 图片反代 base URL，配置后图片走该反代抓取。
            media_relay_base_url: 通用媒体反代 base URL，配置后非图片媒体走该反代抓取。
        """
        from ..messaging.senders.types import MediaVariant, PreparedMedia

        download_media_type = None if try_convert_gif else media_type
        local_path = await self.get_or_download(
            url=url,
            timeout_seconds=timeout_seconds,
            proxy=proxy,
            media_type=download_media_type,
            try_convert_gif=False,
            gif_transcode_timeout=gif_transcode_timeout,
            m3u8_timeout=m3u8_timeout,
            image_relay_base_url=image_relay_base_url,
            media_relay_base_url=media_relay_base_url,
        )
        detection = detect_media_file(local_path)
        effective_type = (
            detection.media_type
            if detection.media_type in {"image", "video", "audio"}
            else (media_type or "file")
        )
        if download_media_type is None:
            validation_type = (
                effective_type
                if effective_type in {"image", "video", "audio"}
                else None
            )
            validation = await validate_media_file(
                local_path,
                media_type=validation_type,
                timeout_seconds=10,
            )
            if not validation.ok:
                raise RuntimeError(
                    f"media validation failed after detection: url={url}, "
                    f"detail={validation.detail}"
                )
        prepared = PreparedMedia(
            media_type=effective_type,
            original_url=url,
            local_path=local_path,
            detected_mime=detection.mime,
            detected_suffix=detection.suffix,
            detection_source=detection.source,
        )
        prepared.add_variant(
            MediaVariant(
                variant="original" if effective_type == "video" else "primary",
                media_type=effective_type,
                path=local_path,
                mime=detection.mime,
                suffix=detection.suffix,
                size_bytes=self._safe_size(local_path),
            )
        )
        if not self._CACHE_ENABLED:
            prepared.mark_owned_path(local_path)

        logger.debug(
            "Prepared media GIF decision: url=%s, declared_media_type=%s, "
            "download_media_type=%s, effective_type=%s, try_convert_gif=%s, "
            "detected_suffix=%s, detection_source=%s",
            url,
            media_type,
            download_media_type,
            effective_type,
            try_convert_gif,
            detection.suffix,
            detection.source,
        )
        if try_convert_gif and effective_type == "video" and local_path.exists():
            await self._append_gif_variants(
                prepared,
                local_path=local_path,
                timeout_seconds=gif_transcode_timeout,
            )
            gif_variant = next(
                (
                    variant
                    for variant in prepared.variants
                    if variant.variant in {"gif", "compressed_gif"}
                ),
                None,
            )
            if gif_variant is not None:
                prepared.local_path = gif_variant.path
                prepared.media_type = "image"
                prepared.detected_mime = gif_variant.mime
                prepared.detected_suffix = gif_variant.suffix
                prepared.detection_source = "gif_variant"
                logger.debug(
                    "Prepared media selected GIF variant: url=%s, variant=%s, "
                    "path=%s, size=%s",
                    url,
                    gif_variant.variant,
                    gif_variant.path,
                    gif_variant.size_bytes,
                )
            if not self._CACHE_ENABLED:
                for variant in prepared.variants:
                    prepared.mark_owned_path(variant.path)
        return prepared

    async def _append_gif_variants(
        self,
        prepared,
        *,
        local_path: Path,
        timeout_seconds: int,
    ) -> None:
        from ..messaging.senders.types import MediaVariant

        try:
            has_audio = await FFmpegTool.has_audio_stream(
                local_path,
                timeout_seconds=10,
                auto_install_ffmpeg=True,
            )
            if has_audio:
                logger.debug(
                    "GIF variant skipped because video has audio: url=%s, path=%s",
                    prepared.original_url,
                    local_path,
                )
                return
            gif_path = await FFmpegTool.transcode_to_gif(
                local_path,
                timeout_seconds=timeout_seconds,
                auto_install_ffmpeg=True,
                cache_enabled=self._CACHE_ENABLED,
                cache_ttl_seconds=self._CACHE_TTL_SECONDS,
            )
            gif_accepted = False
            if gif_path and gif_path.exists():
                if await self._is_valid_gif_variant(gif_path):
                    detection = detect_media_file(gif_path)
                    prepared.add_variant(
                        MediaVariant(
                            variant="gif",
                            media_type="image",
                            path=gif_path,
                            mime=detection.mime,
                            suffix=detection.suffix or ".gif",
                            size_bytes=self._safe_size(gif_path),
                        )
                    )
                    gif_accepted = True
                else:
                    self._discard_gif_variant_cache(gif_path)
            gif_size = self._safe_size(gif_path) if gif_accepted else 0
            if gif_size > GIF_COMPRESS_TARGET_MAX_BYTES:
                compressed_path = await FFmpegTool.transcode_to_gif_under_limit(
                    local_path,
                    max_bytes=GIF_COMPRESS_TARGET_MAX_BYTES,
                    timeout_seconds=timeout_seconds,
                    auto_install_ffmpeg=True,
                    cache_enabled=self._CACHE_ENABLED,
                    cache_ttl_seconds=self._CACHE_TTL_SECONDS,
                )
                if compressed_path and compressed_path.exists():
                    if await self._is_valid_gif_variant(compressed_path):
                        detection = detect_media_file(compressed_path)
                        prepared.add_variant(
                            MediaVariant(
                                variant="compressed_gif",
                                media_type="image",
                                path=compressed_path,
                                mime=detection.mime,
                                suffix=detection.suffix or ".gif",
                                size_bytes=self._safe_size(compressed_path),
                            )
                        )
                    else:
                        self._discard_gif_variant_cache(compressed_path)
        except Exception as ex:
            logger.warning(
                "GIF variant generation failed, keeping original video: url=%s, err=%s",
                prepared.original_url,
                ex,
            )

    @staticmethod
    async def _is_valid_gif_variant(path: Path) -> bool:
        validation = await validate_media_file(
            path,
            media_type="image",
            timeout_seconds=10,
        )
        if validation.ok:
            return True
        logger.warning(
            "GIF variant validation failed, skip variant: path=%s, detail=%s",
            path,
            validation.detail,
        )
        return False

    @staticmethod
    def _discard_gif_variant_cache(path: Path) -> None:
        # FFmpeg cache 命中会先续期 .meta，坏 GIF 必须连同元数据一起驱逐。
        MediaDownloader.safe_unlink(path)
        MediaDownloader.safe_unlink(path.with_suffix(".meta"))

    @staticmethod
    def _safe_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0
