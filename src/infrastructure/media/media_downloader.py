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
from urllib.parse import parse_qs, urlparse

import aiohttp

from astrbot.core.utils.http_ssl import build_tls_connector

from ..utils import get_plugin_cache_dir
from ..utils.ffmpeg_helper import FFmpegTool
from ..utils.logger import get_logger

logger = get_logger()


class MediaDownloader:
    """媒体下载器，支持缓存管理和格式转换。"""

    _CACHE_TTL_SECONDS: int = 15 * 60
    _CACHE_GC_INTERVAL_SECONDS: int = 5 * 60
    _CACHE_GC_GRACE_SECONDS: int = 10 * 60
    _CACHE_MEDIA_SUFFIXES: tuple[str, ...] = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".mp4",
        ".mp3",
        ".ogg",
        ".bin",
    )

    def __init__(self, cache_dir: Path | None = None) -> None:
        if cache_dir is None:
            cache_dir = get_plugin_cache_dir("media")
        self._cache_dir = cache_dir
        self._cache_gc_lock = asyncio.Lock()
        self._cache_io_lock = asyncio.Lock()
        self._cache_gc_last_run = 0.0

    @staticmethod
    def _guess_suffix(url: str) -> str:
        lowered = url.lower()
        if ".m3u8" in lowered:
            return ".m3u8"
        if ".jpg" in lowered or ".jpeg" in lowered:
            return ".jpg"
        if ".png" in lowered:
            return ".png"
        if ".gif" in lowered:
            return ".gif"
        if ".webp" in lowered:
            return ".webp"
        if ".mp4" in lowered:
            return ".mp4"
        if ".mp3" in lowered:
            return ".mp3"
        if ".ogg" in lowered:
            return ".ogg"
        return ".bin"

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
                        allow_redirects=True,
                        max_redirects=10,
                    ) as resp:
                        if resp.status >= 400:
                            raise RuntimeError(
                                f"download failed: status={resp.status}, "
                                f"url={candidate_url}"
                            )
                        data = await resp.read()
                        if not data:
                            raise RuntimeError(
                                f"download failed: empty response, url={candidate_url}"
                            )

                    fd, tmp_name = tempfile.mkstemp(
                        prefix="rsshub_media_",
                        suffix=self._guess_suffix(candidate_url),
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

        logger.debug("Media cache hit: url=%s, file=%s", url, file_path)
        return file_path

    def _write_cache(self, url: str, source: Path) -> Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        actual_suffix = (
            source.suffix.lower() if source.suffix else self._guess_suffix(url)
        )
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
        await self._run_periodic_cache_gc()

        cache_url = f"{url}#mp4"

        async with self._cache_io_lock:
            cached = self._read_cache(cache_url)
            if cached is not None:
                logger.debug(
                    "Media cache return existing m3u8: url=%s, path=%s",
                    cache_url,
                    cached,
                )
                return cached

        cache_digest = self._cache_file_prefix(cache_url)
        cache_path = self._cache_dir / f"{cache_digest}.mp4"
        meta_path = self._cache_dir / f"{cache_digest}.meta"

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
                if cache_path.exists():
                    self.safe_unlink(cache_path)
                success = await FFmpegTool.download_m3u8_to_mp4(
                    m3u8_url=candidate_url,
                    output_path=cache_path,
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
            self.safe_unlink(cache_path)
            detail = f", last_error={last_error}" if last_error else ""
            raise RuntimeError(f"m3u8 download failed: {url}{detail}")

        expire_ts = time.time() + self._CACHE_TTL_SECONDS
        meta_path.write_text(str(expire_ts), encoding="utf-8")

        logger.debug(
            "Media cache m3u8 download complete: url=%s, path=%s, bytes=%s",
            url,
            cache_path,
            cache_path.stat().st_size if cache_path.exists() else 0,
        )
        return cache_path

    async def get_or_download(
        self,
        *,
        url: str,
        timeout_seconds: int = 30,
        proxy: str = "",
        try_convert_gif: bool = False,
        gif_transcode_timeout: int = 60,
        m3u8_timeout: int = 120,
    ) -> Path:
        """下载媒体到缓存，支持 GIF 自动转换

        Args:
            url: 媒体URL
            timeout_seconds: 下载超时
            proxy: 代理地址
            try_convert_gif: 是否尝试将无声视频转为GIF
            gif_transcode_timeout: GIF转码超时
            m3u8_timeout: m3u8下载超时

        Returns:
            缓存文件路径
        """
        await self._run_periodic_cache_gc()

        is_m3u8 = self._guess_suffix(url) == ".m3u8"
        if is_m3u8:
            return await self._download_m3u8_to_cache(
                url=url, proxy=proxy, m3u8_timeout=m3u8_timeout
            )

        is_video = self._guess_suffix(url) in {
            ".mp4",
            ".webm",
            ".mov",
            ".mkv",
            ".avi",
        }

        cache_url = url
        if try_convert_gif and is_video:
            cache_url = f"{url}#gif"

        async with self._cache_io_lock:
            cached = self._read_cache(cache_url)
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
        tmp_path = await self.download_to_temp(
            url=url,
            timeout_seconds=timeout_seconds,
            proxy=proxy,
        )
        logger.debug(
            "Media cache download complete: url=%s, tmp=%s, tmp_exists=%s",
            url,
            tmp_path,
            tmp_path.exists(),
        )

        converted_path = tmp_path
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

        try:
            async with self._cache_io_lock:
                cached = self._read_cache(cache_url)
                if cached is not None:
                    logger.debug(
                        "Media cache filled by peer task: url=%s, path=%s",
                        cache_url,
                        cached,
                    )
                    return cached
                written = self._write_cache(cache_url, converted_path)
                logger.debug(
                    "Media cache return new write: url=%s, path=%s",
                    cache_url,
                    written,
                )
                return written
        finally:
            if converted_path != tmp_path:
                self.safe_unlink(tmp_path)
            if converted_path == tmp_path:
                self.safe_unlink(converted_path)
