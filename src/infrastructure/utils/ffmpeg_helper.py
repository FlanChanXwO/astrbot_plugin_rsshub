"""FFmpeg 工具模块

提供视频处理相关的 FFmpeg 工具函数。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Final

from ...shared.constants import MEDIA_CACHE_TTL_SECONDS_DEFAULT
from .logger import get_logger
from .paths import get_plugin_cache_dir

logger = get_logger()


class FFmpegTool:
    """FFmpeg 工具类，提供视频处理静态方法"""

    _ffmpeg_exe_cache: str | None = None
    _ffprobe_exe_cache: str | None = None
    _ffmpeg_exe_cache_source: str | None = None
    _ffprobe_exe_cache_source: str | None = None
    _ffmpeg_source: str = "auto"  # "auto" | "system"

    _GIF_TRANSCODE_FPS: Final = 30
    _GIF_TRANSCODE_SCALE: Final = "iw:-1"
    _GIF_TRANSCODE_MAX_COLORS: Final = 256
    _GIF_TRANSCODE_DITHER: Final = "sierra2_4a"
    _GIF_TRANSCODE_PROFILE: Final = (
        f"fps={_GIF_TRANSCODE_FPS};"
        f"scale={_GIF_TRANSCODE_SCALE};"
        f"colors={_GIF_TRANSCODE_MAX_COLORS};"
        f"dither={_GIF_TRANSCODE_DITHER}"
    )

    @staticmethod
    def _normalize_proxy_url(proxy: str | None) -> str:
        proxy_url = (proxy or "").strip()
        if not proxy_url:
            return ""
        if "://" not in proxy_url:
            return f"http://{proxy_url}"
        return proxy_url

    @staticmethod
    def ensure_ffmpeg_ready(*, auto_install: bool = True) -> str | None:
        """Resolve an FFmpeg executable path for plugin runtime use.

        Priority:
        1. Cached path if still valid
        2. System PATH ffmpeg (most stable for HLS/m3u8)
        3. Bundled ffmpeg (auto-downloaded from GitHub)

        Args:
            auto_install: Whether to use bundled ffmpeg if not found on system

        Returns:
            Path to ffmpeg executable, or None if not found
        """
        if FFmpegTool._ffmpeg_exe_cache and Path(FFmpegTool._ffmpeg_exe_cache).exists():
            if (
                FFmpegTool._ffmpeg_source == "system"
                and FFmpegTool._ffmpeg_exe_cache_source != "system"
            ):
                FFmpegTool._clear_ffmpeg_cache()
            else:
                return FFmpegTool._ffmpeg_exe_cache

        if FFmpegTool._ffmpeg_exe_cache and Path(FFmpegTool._ffmpeg_exe_cache).exists():
            return FFmpegTool._ffmpeg_exe_cache

        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            FFmpegTool._ffmpeg_exe_cache = str(Path(system_ffmpeg).resolve())
            FFmpegTool._ffmpeg_exe_cache_source = "system"
            logger.debug("Using system ffmpeg: %s", FFmpegTool._ffmpeg_exe_cache)
            return FFmpegTool._ffmpeg_exe_cache

        if auto_install and FFmpegTool._ffmpeg_source != "system":
            from .ffmpeg_bundler import get_bundled_ffmpeg_path

            bundled = get_bundled_ffmpeg_path()
            if bundled and bundled.exists():
                FFmpegTool._ffmpeg_exe_cache = str(bundled.resolve())
                FFmpegTool._ffmpeg_exe_cache_source = "bundled"
                logger.debug("Using bundled ffmpeg: %s", FFmpegTool._ffmpeg_exe_cache)
                return FFmpegTool._ffmpeg_exe_cache

        return None

    @staticmethod
    def ensure_ffprobe_ready(*, auto_install: bool = True) -> str | None:
        """Resolve an FFprobe executable path for plugin runtime use.

        Priority:
        1. Cached path if still valid
        2. Same directory as ffmpeg
        3. System PATH
        4. Bundled ffprobe (auto-downloaded from GitHub)

        Args:
            auto_install: Whether to use bundled ffprobe if not found on system

        Returns:
            Path to ffprobe executable, or None if not found
        """
        if (
            FFmpegTool._ffprobe_exe_cache
            and Path(FFmpegTool._ffprobe_exe_cache).exists()
        ):
            if (
                FFmpegTool._ffmpeg_source == "system"
                and FFmpegTool._ffprobe_exe_cache_source != "system"
            ):
                FFmpegTool._clear_ffprobe_cache()
            else:
                return FFmpegTool._ffprobe_exe_cache

        ffmpeg_path = FFmpegTool.ensure_ffmpeg_ready(auto_install=auto_install)
        if ffmpeg_path:
            ffmpeg_dir = Path(ffmpeg_path).parent
            ffprobe_candidates = [
                ffmpeg_dir / "ffprobe",
                ffmpeg_dir / "ffprobe.exe",
            ]
            for candidate in ffprobe_candidates:
                if candidate.exists():
                    FFmpegTool._ffprobe_exe_cache = str(candidate.resolve())
                    FFmpegTool._ffprobe_exe_cache_source = (
                        FFmpegTool._ffmpeg_exe_cache_source
                    )
                    return FFmpegTool._ffprobe_exe_cache

        system_ffprobe = shutil.which("ffprobe")
        if system_ffprobe:
            FFmpegTool._ffprobe_exe_cache = str(Path(system_ffprobe).resolve())
            FFmpegTool._ffprobe_exe_cache_source = "system"
            return FFmpegTool._ffprobe_exe_cache

        if auto_install and FFmpegTool._ffmpeg_source != "system":
            from .ffmpeg_bundler import get_bundled_ffprobe_path

            bundled = get_bundled_ffprobe_path()
            if bundled and bundled.exists():
                FFmpegTool._ffprobe_exe_cache = str(bundled.resolve())
                FFmpegTool._ffprobe_exe_cache_source = "bundled"
                logger.debug("Using bundled ffprobe: %s", FFmpegTool._ffprobe_exe_cache)
                return FFmpegTool._ffprobe_exe_cache

        return None

    @staticmethod
    async def has_audio_stream(
        video_path: Path,
        *,
        timeout_seconds: int = 10,
        auto_install_ffmpeg: bool = True,
    ) -> bool:
        """Detect if video file contains audio stream using ffprobe.

        Returns True if video has audio stream, False if not (silent video).
        Returns True on any error (conservative fallback).

        Args:
            video_path: Path to the video file
            timeout_seconds: Maximum time allowed for detection
            auto_install_ffmpeg: Whether to auto-install ffmpeg if not found

        Returns:
            True if audio stream exists, False otherwise
        """
        ffprobe_exe = FFmpegTool.ensure_ffprobe_ready(auto_install=auto_install_ffmpeg)
        if not ffprobe_exe:
            logger.debug(
                "FFprobe not available, assuming audio exists: path=%s",
                video_path,
            )
            return True

        if not video_path.exists():
            return True

        args = [
            ffprobe_exe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=s=x:p=0",
            str(video_path),
        ]

        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(1, int(timeout_seconds)),
            )
        except asyncio.TimeoutError:
            logger.warning("FFprobe audio detection timeout: path=%s", video_path)
            if process is not None:
                process.kill()
                await process.wait()
            return True
        except (OSError, ValueError) as ex:
            logger.warning(
                "FFprobe audio detection failed: path=%s, err=%s",
                video_path,
                ex,
            )
            return True

        has_audio = bool(stdout and stdout.strip())
        logger.debug(
            "Audio stream detection: path=%s, has_audio=%s, stdout=%r",
            video_path,
            has_audio,
            stdout.decode("utf-8", errors="ignore") if stdout else "",
        )
        return has_audio

    @staticmethod
    async def has_valid_video_stream(
        video_path: Path,
        *,
        timeout_seconds: int = 10,
        auto_install_ffmpeg: bool = True,
    ) -> bool:
        """Detect whether a media file has a playable video stream."""
        ffprobe_exe = FFmpegTool.ensure_ffprobe_ready(auto_install=auto_install_ffmpeg)
        if not ffprobe_exe:
            logger.debug(
                "FFprobe not available, accepting video without validation: path=%s",
                video_path,
            )
            return video_path.exists() and video_path.is_file()

        if not video_path.exists() or not video_path.is_file():
            return False

        args = [
            ffprobe_exe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type:format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]

        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(1, int(timeout_seconds)),
            )
        except asyncio.TimeoutError:
            logger.warning("FFprobe video validation timeout: path=%s", video_path)
            if process is not None:
                process.kill()
                await process.wait()
            return False
        except (OSError, ValueError) as ex:
            logger.warning(
                "FFprobe video validation failed: path=%s, err=%s",
                video_path,
                ex,
            )
            return False

        output = stdout.decode("utf-8", errors="ignore") if stdout else ""
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        has_video = "video" in lines
        duration = 0.0
        for line in reversed(lines):
            try:
                duration = float(line)
                break
            except ValueError:
                continue

        valid = process.returncode == 0 and has_video and duration > 0
        if not valid:
            err_tail = (stderr or b"").decode("utf-8", errors="ignore")[-300:]
            logger.warning(
                "FFprobe video validation rejected file: path=%s, "
                "returncode=%s, has_video=%s, duration=%s, stderr_tail=%s",
                video_path,
                process.returncode,
                has_video,
                duration,
                err_tail,
            )
        return valid

    @staticmethod
    def _meta_path(output_path: Path) -> Path:
        return output_path.with_suffix(".meta")

    @staticmethod
    def _read_expire_ts(meta_path: Path) -> float | None:
        try:
            text = meta_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not text:
            return None
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return float(payload.get("expire_ts", 0))
            return float(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            try:
                return float(text.split("\n", 1)[0])
            except ValueError:
                return None

    @staticmethod
    def _write_cache_meta(
        output_path: Path,
        *,
        now_ts: float,
        cache_ttl_seconds: int,
    ) -> None:
        meta_path = FFmpegTool._meta_path(output_path)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "expire_ts": now_ts + max(1, int(cache_ttl_seconds)),
        }
        tmp_file = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=meta_path.parent,
            prefix=f".{meta_path.name}.",
            suffix=".tmp",
        )
        tmp_path = Path(tmp_file.name)
        try:
            with tmp_file:
                json.dump(payload, tmp_file, ensure_ascii=False, separators=(",", ":"))
            tmp_path.replace(meta_path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as cleanup_ex:
                logger.debug(
                    "FFmpeg cache meta temp cleanup failed: path=%s, err=%s",
                    tmp_path,
                    cleanup_ex,
                )
            raise

    @staticmethod
    def _write_cache_meta_best_effort(
        output_path: Path,
        *,
        now_ts: float,
        cache_ttl_seconds: int,
        stage: str,
    ) -> None:
        try:
            FFmpegTool._write_cache_meta(
                output_path,
                now_ts=now_ts,
                cache_ttl_seconds=cache_ttl_seconds,
            )
        except Exception as ex:
            logger.warning(
                "FFmpeg cache meta write failed: stage=%s, path=%s, "
                "err_type=%s, err=%s",
                stage,
                output_path,
                type(ex).__name__,
                ex,
            )

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as ex:
            logger.debug("FFmpeg cache cleanup failed: path=%s, err=%s", path, ex)

    @staticmethod
    def _cache_entry_reusable(
        output_path: Path,
        *,
        now_ts: float,
        cache_ttl_seconds: int,
    ) -> bool:
        try:
            stat = output_path.stat()
            if not output_path.exists() or stat.st_size <= 0:
                return False
        except OSError:
            return False

        meta_path = FFmpegTool._meta_path(output_path)
        if not meta_path.exists():
            # 旧版本或 meta 写入失败会留下无 meta 输出；按文件 mtime 兜底执行 TTL。
            return now_ts - stat.st_mtime < max(1, int(cache_ttl_seconds))
        expire_ts = FFmpegTool._read_expire_ts(meta_path)
        return expire_ts is not None and expire_ts > now_ts

    @staticmethod
    def _gc_transcode_cache(
        cache_root: Path,
        *,
        suffixes: tuple[str, ...],
        now_ts: float,
        cache_ttl_seconds: int,
        skip_paths: set[Path] | None = None,
    ) -> int:
        """按 TTL 清理专用转码 cache，跳过当前 digest 的 legacy 文件。"""
        if not cache_root.exists():
            return 0

        removed = 0
        skip_resolved: set[Path] = set()
        for path in skip_paths or set():
            try:
                skip_resolved.add(path.resolve())
            except OSError:
                skip_resolved.add(path)

        def should_skip(path: Path) -> bool:
            try:
                return path.resolve() in skip_resolved
            except OSError:
                return path in (skip_paths or set())

        for meta_path in cache_root.glob("*.meta"):
            output_paths = tuple(
                cache_root / f"{meta_path.stem}{suffix}" for suffix in suffixes
            )
            if any(should_skip(path) for path in output_paths):
                continue
            expire_ts = FFmpegTool._read_expire_ts(meta_path)
            if expire_ts is not None and expire_ts > now_ts:
                continue
            FFmpegTool._safe_unlink(meta_path)
            removed += 1
            for output_path in output_paths:
                if output_path.exists():
                    FFmpegTool._safe_unlink(output_path)
                    removed += 1

        stale_orphan_age = max(1, int(cache_ttl_seconds))
        for suffix in suffixes:
            for output_path in cache_root.glob(f"*{suffix}"):
                if FFmpegTool._meta_path(output_path).exists():
                    if should_skip(output_path):
                        continue
                    continue
                try:
                    age = now_ts - output_path.stat().st_mtime
                except OSError:
                    continue
                if age < stale_orphan_age:
                    continue
                FFmpegTool._safe_unlink(output_path)
                removed += 1

        if removed > 0:
            logger.debug("FFmpeg transcode cache GC removed %s files", removed)
        return removed

    @staticmethod
    def _transcode_cache_hit(
        output_path: Path,
        *,
        now_ts: float,
        cache_ttl_seconds: int,
        stage: str,
    ) -> Path | None:
        if not FFmpegTool._cache_entry_reusable(
            output_path,
            now_ts=now_ts,
            cache_ttl_seconds=cache_ttl_seconds,
        ):
            return None
        FFmpegTool._write_cache_meta_best_effort(
            output_path,
            now_ts=now_ts,
            cache_ttl_seconds=cache_ttl_seconds,
            stage=stage,
        )
        return output_path

    @staticmethod
    async def transcode_to_mp4(
        source_path: Path,
        *,
        timeout_seconds: int = 120,
        auto_install_ffmpeg: bool = True,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = MEDIA_CACHE_TTL_SECONDS_DEFAULT,
    ) -> Path | None:
        """Transcode source video to QQ-friendly H264/AAC MP4.

        Args:
            source_path: Path to the source video file
            timeout_seconds: Maximum time allowed for transcoding
            auto_install_ffmpeg: Whether to auto-install ffmpeg if not found
            cache_enabled: 是否复用插件 MP4 转码 cache；False 时输出唯一临时文件
            cache_ttl_seconds: 转码 cache 命中后的续期秒数

        Returns:
            Path to the transcoded MP4 file, or None if failed
        """
        ffmpeg_exe = FFmpegTool.ensure_ffmpeg_ready(auto_install=auto_install_ffmpeg)
        if not ffmpeg_exe:
            return None

        if not source_path.exists() or not source_path.is_file():
            return None

        try:
            stat = source_path.stat()
        except OSError:
            return None

        if cache_enabled:
            cache_root = get_plugin_cache_dir("qq_video")
            cache_root.mkdir(parents=True, exist_ok=True)

            digest = hashlib.sha256(
                (
                    f"{source_path.resolve()}::{int(stat.st_mtime)}::{stat.st_size}"
                ).encode("utf-8", errors="ignore")
            ).hexdigest()
            output_path = cache_root / f"{digest}.mp4"
            now_ts = time.time()
            FFmpegTool._gc_transcode_cache(
                cache_root,
                suffixes=(".mp4",),
                now_ts=now_ts,
                cache_ttl_seconds=cache_ttl_seconds,
                skip_paths={output_path},
            )
            cached = FFmpegTool._transcode_cache_hit(
                output_path,
                now_ts=now_ts,
                cache_ttl_seconds=cache_ttl_seconds,
                stage="mp4_cache_hit",
            )
            if cached is not None:
                return cached
        else:
            output_path = FFmpegTool._new_temp_mp4_path()

        args = [
            ffmpeg_exe,
            "-y",
            "-i",
            str(source_path),
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "main",
            "-level",
            "4.0",
            "-movflags",
            "+faststart",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(output_path),
        ]

        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(10, int(timeout_seconds)),
            )
        except asyncio.TimeoutError:
            logger.warning("FFmpeg transcode timeout: src=%s", source_path)
            if process is not None:
                process.kill()
                await process.wait()
            output_path.unlink(missing_ok=True)
            return None
        except (OSError, ValueError) as ex:
            logger.warning(
                "FFmpeg transcode process failed: src=%s, err=%s",
                source_path,
                ex,
            )
            output_path.unlink(missing_ok=True)
            return None

        if process.returncode != 0:
            output_path.unlink(missing_ok=True)
            err_tail = (stderr or b"").decode("utf-8", errors="ignore")[-500:]
            logger.warning(
                "FFmpeg transcode failed: src=%s, code=%s, stderr_tail=%s",
                source_path,
                process.returncode,
                err_tail,
            )
            return None

        if output_path.exists() and output_path.stat().st_size > 0:
            if cache_enabled:
                FFmpegTool._write_cache_meta_best_effort(
                    output_path,
                    now_ts=time.time(),
                    cache_ttl_seconds=cache_ttl_seconds,
                    stage="mp4_success",
                )
            logger.debug(
                "FFmpeg transcode success: src=%s, out=%s, bytes=%s",
                source_path,
                output_path,
                output_path.stat().st_size,
            )
            return output_path

        return None

    @staticmethod
    def _new_temp_gif_path(prefix: str) -> Path:
        """生成调用方拥有的临时 GIF 路径；用于禁用缓存时避开插件 cache。"""
        fd, tmp_name = tempfile.mkstemp(prefix=prefix, suffix=".gif")
        os.close(fd)
        return Path(tmp_name)

    @staticmethod
    def _new_temp_mp4_path() -> Path:
        """生成调用方拥有的临时 MP4 路径；用于禁用缓存时避开插件 cache。"""
        fd, tmp_name = tempfile.mkstemp(
            prefix="rsshub_video_transcoded_",
            suffix=".mp4",
        )
        os.close(fd)
        return Path(tmp_name)

    @staticmethod
    async def transcode_to_gif(
        source_path: Path,
        *,
        timeout_seconds: int = 60,
        auto_install_ffmpeg: bool = True,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = MEDIA_CACHE_TTL_SECONDS_DEFAULT,
    ) -> Path | None:
        """Transcode a silent video to high-quality GIF.

        Uses ffmpeg with palette generation tuned for quality-first output.
        Caches output to avoid repeated transcoding.

        Args:
            source_path: Path to the source video file
            timeout_seconds: Maximum time allowed for transcoding (default 60s)
            auto_install_ffmpeg: Whether to auto-install ffmpeg if not found
            cache_enabled: 是否复用插件 GIF cache；False 时输出唯一临时文件
            cache_ttl_seconds: 转码 cache 命中后的续期秒数

        Returns:
            Path to the generated GIF file, or None if transcoding failed
        """
        ffmpeg_exe = FFmpegTool.ensure_ffmpeg_ready(auto_install=auto_install_ffmpeg)
        if not ffmpeg_exe:
            logger.warning(
                "FFmpeg not available for GIF transcode: src=%s", source_path
            )
            return None

        if not source_path.exists() or not source_path.is_file():
            return None

        try:
            stat = source_path.stat()
        except OSError:
            return None

        if cache_enabled:
            cache_root = get_plugin_cache_dir("gif")
            cache_root.mkdir(parents=True, exist_ok=True)

            digest = hashlib.sha256(
                (
                    f"{source_path.resolve()}::"
                    f"{int(stat.st_mtime)}::"
                    f"{stat.st_size}::"
                    f"{FFmpegTool._GIF_TRANSCODE_PROFILE}"
                ).encode("utf-8", errors="ignore")
            ).hexdigest()
            output_path = cache_root / f"{digest}.gif"

            now_ts = time.time()
            FFmpegTool._gc_transcode_cache(
                cache_root,
                suffixes=(".gif",),
                now_ts=now_ts,
                cache_ttl_seconds=cache_ttl_seconds,
                skip_paths={output_path},
            )
            cached = FFmpegTool._transcode_cache_hit(
                output_path,
                now_ts=now_ts,
                cache_ttl_seconds=cache_ttl_seconds,
                stage="gif_cache_hit",
            )
            if cached is not None:
                logger.debug(
                    "GIF cache hit: src=%s, out=%s, bytes=%s, profile=%s",
                    source_path,
                    cached,
                    cached.stat().st_size,
                    FFmpegTool._GIF_TRANSCODE_PROFILE,
                )
                return cached
        else:
            output_path = FFmpegTool._new_temp_gif_path("rsshub_gif_")

        vf_expr = (
            f"fps={FFmpegTool._GIF_TRANSCODE_FPS},"
            f"scale={FFmpegTool._GIF_TRANSCODE_SCALE}:flags=lanczos,"
            "split[s0][s1];"
            f"[s0]palettegen=max_colors={FFmpegTool._GIF_TRANSCODE_MAX_COLORS}"
            ":stats_mode=full[p];"
            f"[s1][p]paletteuse=dither={FFmpegTool._GIF_TRANSCODE_DITHER}"
        )
        args = [
            ffmpeg_exe,
            "-y",
            "-i",
            str(source_path),
            "-vf",
            vf_expr,
            "-loop",
            "0",
            str(output_path),
        ]

        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(10, int(timeout_seconds)),
            )
        except asyncio.TimeoutError:
            logger.warning("FFmpeg GIF transcode timeout: src=%s", source_path)
            if process is not None:
                process.kill()
                await process.wait()
            output_path.unlink(missing_ok=True)
            return None
        except (OSError, ValueError) as ex:
            logger.warning(
                "FFmpeg GIF transcode process failed: src=%s, err=%s",
                source_path,
                ex,
            )
            output_path.unlink(missing_ok=True)
            return None

        if process.returncode != 0:
            output_path.unlink(missing_ok=True)
            err_tail = (stderr or b"").decode("utf-8", errors="ignore")[-500:]
            logger.warning(
                "FFmpeg GIF transcode failed: src=%s, code=%s, stderr_tail=%s",
                source_path,
                process.returncode,
                err_tail,
            )
            return None

        if output_path.exists() and output_path.stat().st_size > 0:
            if cache_enabled:
                FFmpegTool._write_cache_meta_best_effort(
                    output_path,
                    now_ts=time.time(),
                    cache_ttl_seconds=cache_ttl_seconds,
                    stage="gif_success",
                )
            logger.debug(
                "FFmpeg GIF transcode success: src=%s, out=%s, bytes=%s, profile=%s",
                source_path,
                output_path,
                output_path.stat().st_size,
                FFmpegTool._GIF_TRANSCODE_PROFILE,
            )
            return output_path

        if not cache_enabled:
            output_path.unlink(missing_ok=True)
        return None

    _GIF_COMPRESS_SCALE_FACTORS: Final = [0.75, 0.5, 0.35, 0.25]
    _GIF_COMPRESS_MIN_FPS: Final = 15

    @staticmethod
    async def transcode_to_gif_under_limit(
        source_path: Path,
        *,
        max_bytes: int,
        timeout_seconds: int = 60,
        auto_install_ffmpeg: bool = True,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = MEDIA_CACHE_TTL_SECONDS_DEFAULT,
    ) -> Path | None:
        """将视频转码为不超过 max_bytes 的 GIF。

        逐步降低分辨率和帧率来压缩，直到满足大小限制。

        Args:
            source_path: 源视频文件路径
            max_bytes: GIF 最大字节数
            timeout_seconds: 单次转码超时（秒）
            auto_install_ffmpeg: 是否自动安装 ffmpeg
            cache_enabled: 是否复用插件压缩 GIF cache；False 时输出唯一临时文件
            cache_ttl_seconds: 转码 cache 命中后的续期秒数

        Returns:
            生成的 GIF 路径，或 None（失败时）
        """
        ffmpeg_exe = FFmpegTool.ensure_ffmpeg_ready(auto_install=auto_install_ffmpeg)
        if not ffmpeg_exe:
            return None

        if not source_path.exists() or not source_path.is_file():
            return None

        try:
            stat = source_path.stat()
        except OSError:
            return None

        cache_root: Path | None = None
        cache_attempts: list[tuple[int, float, Path | None]] = []
        attempts = [
            (FFmpegTool._GIF_TRANSCODE_FPS, factor)
            for factor in FFmpegTool._GIF_COMPRESS_SCALE_FACTORS
        ] + [
            (FFmpegTool._GIF_COMPRESS_MIN_FPS, factor)
            for factor in FFmpegTool._GIF_COMPRESS_SCALE_FACTORS
        ]
        if cache_enabled:
            cache_root = get_plugin_cache_dir("gif_compressed")
            cache_root.mkdir(parents=True, exist_ok=True)
            for fps, scale_factor in attempts:
                cache_key = (
                    f"{source_path.resolve()}::"
                    f"{int(stat.st_mtime)}::{stat.st_size}::"
                    f"compressed:{max_bytes}:{fps}:{scale_factor}"
                )
                digest = hashlib.sha256(
                    cache_key.encode("utf-8", errors="ignore")
                ).hexdigest()
                cache_attempts.append((fps, scale_factor, cache_root / f"{digest}.gif"))
            now_ts = time.time()
            FFmpegTool._gc_transcode_cache(
                cache_root,
                suffixes=(".gif",),
                now_ts=now_ts,
                cache_ttl_seconds=cache_ttl_seconds,
                skip_paths={path for _fps, _scale, path in cache_attempts if path},
            )
        else:
            cache_attempts = [
                (fps, scale_factor, None) for fps, scale_factor in attempts
            ]

        for fps, scale_factor, cached_output_path in cache_attempts:
            if cache_enabled and cached_output_path is not None:
                output_path = cached_output_path
                cached = FFmpegTool._transcode_cache_hit(
                    output_path,
                    now_ts=time.time(),
                    cache_ttl_seconds=cache_ttl_seconds,
                    stage="gif_compressed_cache_hit",
                )
                if cached is not None:
                    cached_size = cached.stat().st_size
                    if cached_size <= max_bytes:
                        return cached
                    continue
            else:
                output_path = FFmpegTool._new_temp_gif_path("rsshub_gif_compressed_")

            scale_w = f"iw*{scale_factor}"
            vf_expr = (
                f"fps={fps},"
                f"scale={scale_w}:-1:flags=lanczos,"
                "split[s0][s1];"
                f"[s0]palettegen=max_colors={FFmpegTool._GIF_TRANSCODE_MAX_COLORS}"
                ":stats_mode=full[p];"
                f"[s1][p]paletteuse=dither={FFmpegTool._GIF_TRANSCODE_DITHER}"
            )
            args = [
                ffmpeg_exe,
                "-y",
                "-i",
                str(source_path),
                "-vf",
                vf_expr,
                "-loop",
                "0",
                str(output_path),
            ]

            process: asyncio.subprocess.Process | None = None
            try:
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=max(10, int(timeout_seconds)),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "FFmpeg compressed GIF timeout: src=%s, scale=%s",
                    source_path,
                    scale_factor,
                )
                if process is not None:
                    process.kill()
                    await process.wait()
                output_path.unlink(missing_ok=True)
                continue
            except (OSError, ValueError) as ex:
                logger.warning(
                    "FFmpeg compressed GIF failed: src=%s, err=%s",
                    source_path,
                    ex,
                )
                output_path.unlink(missing_ok=True)
                continue

            if process.returncode != 0:
                output_path.unlink(missing_ok=True)
                continue

            if not output_path.exists():
                output_path.unlink(missing_ok=True)
                continue
            output_size = output_path.stat().st_size
            if output_size == 0:
                output_path.unlink(missing_ok=True)
                continue

            if output_size <= max_bytes:
                if cache_enabled:
                    FFmpegTool._write_cache_meta_best_effort(
                        output_path,
                        now_ts=time.time(),
                        cache_ttl_seconds=cache_ttl_seconds,
                        stage="gif_compressed_success",
                    )
                logger.debug(
                    "Compressed GIF success: src=%s, bytes=%s, scale=%s, fps=%s",
                    source_path,
                    output_size,
                    scale_factor,
                    fps,
                )
                return output_path

            if not cache_enabled:
                output_path.unlink(missing_ok=True)
            logger.debug(
                "Compressed GIF still too large: src=%s, bytes=%s > %s, scale=%s",
                source_path,
                output_size,
                max_bytes,
                scale_factor,
            )

        logger.warning(
            "Failed to compress GIF under limit: src=%s, max_bytes=%s",
            source_path,
            max_bytes,
        )
        return None

    @staticmethod
    async def download_m3u8_to_mp4(
        m3u8_url: str,
        output_path: Path,
        *,
        timeout_seconds: int = 120,
        proxy: str | None = None,
        auto_install_ffmpeg: bool = True,
    ) -> bool:
        """下载 m3u8 流媒体并转换为 mp4。

        使用 ffmpeg 直接下载 HLS 流并合并为 mp4 文件。

        Args:
            m3u8_url: m3u8 播放列表 URL
            output_path: 输出 mp4 文件路径
            timeout_seconds: 下载超时时间（默认120秒）
            proxy: HTTP 代理地址
            auto_install_ffmpeg: 是否自动安装 ffmpeg

        Returns:
            是否成功
        """
        ffmpeg_exe = FFmpegTool.ensure_ffmpeg_ready(auto_install=auto_install_ffmpeg)
        if not ffmpeg_exe:
            logger.warning("FFmpeg not available for m3u8 download: %s", m3u8_url)
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        proxy_url = FFmpegTool._normalize_proxy_url(proxy)

        args = [
            ffmpeg_exe,
            "-y",
            "-protocol_whitelist",
            "file,http,https,tcp,tls,crypto,httpproxy",
        ]
        if proxy_url:
            args.extend(["-http_proxy", proxy_url])
        args.extend(
            [
                "-i",
                m3u8_url,
                "-c",
                "copy",
                "-bsf:a",
                "aac_adtstoasc",
                str(output_path),
            ]
        )

        env = None
        if proxy_url:
            env = os.environ.copy()
            env["HTTP_PROXY"] = proxy_url
            env["HTTPS_PROXY"] = proxy_url
            env["http_proxy"] = proxy_url
            env["https_proxy"] = proxy_url

        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(10, int(timeout_seconds)),
            )
        except asyncio.TimeoutError:
            logger.warning("FFmpeg m3u8 download timeout: url=%s", m3u8_url)
            if process is not None:
                process.kill()
                await process.wait()
            output_path.unlink(missing_ok=True)
            return False
        except Exception as e:
            logger.warning(
                "FFmpeg m3u8 download process failed: url=%s, err=%s",
                m3u8_url,
                e,
            )
            if process is not None:
                process.kill()
                await process.wait()
            output_path.unlink(missing_ok=True)
            return False

        if process.returncode != 0:
            stderr_tail = (
                stderr.decode("utf-8", errors="ignore")[-500:] if stderr else ""
            )
            logger.warning(
                "FFmpeg m3u8 download failed: url=%s, code=%s, stderr_tail=%s",
                m3u8_url,
                process.returncode,
                stderr_tail,
            )
            output_path.unlink(missing_ok=True)
            return False

        if output_path.exists() and output_path.stat().st_size > 0:
            if not await FFmpegTool.has_valid_video_stream(
                output_path,
                timeout_seconds=10,
                auto_install_ffmpeg=auto_install_ffmpeg,
            ):
                output_path.unlink(missing_ok=True)
                return False
            logger.debug(
                "FFmpeg m3u8 download success: url=%s, out=%s, bytes=%s",
                m3u8_url,
                output_path,
                output_path.stat().st_size,
            )
            return True

        return False

    @staticmethod
    def configure_bundler(
        *,
        http_proxy: str = "",
        timeout: int = 300,
        ffmpeg_source: str = "auto",
        ffmpeg_mirror: str = "default",
        ffmpeg_mirror_custom_url: str = "",
    ) -> None:
        """配置 ffmpeg bundler 的代理、超时、来源模式和镜像（启动时调用）。"""
        new_source = str(ffmpeg_source or "auto")
        if new_source == "bundled":
            logger.warning("ffmpeg_source 'bundled' 已合并为 'auto'，请更新配置")
            new_source = "auto"
        if new_source not in ("auto", "system"):
            new_source = "auto"
        if new_source != FFmpegTool._ffmpeg_source:
            FFmpegTool._clear_ffmpeg_cache()
            FFmpegTool._clear_ffprobe_cache()
        FFmpegTool._ffmpeg_source = new_source

        from .ffmpeg_bundler import configure_ffmpeg_bundler

        configure_ffmpeg_bundler(
            http_proxy=http_proxy,
            timeout=timeout,
            mirror=ffmpeg_mirror,
            mirror_custom_url=ffmpeg_mirror_custom_url,
        )

    @staticmethod
    def prefetch_bundled_ffmpeg() -> None:
        """后台异步预取 ffmpeg 捆绑包，不阻塞插件启动。"""
        if FFmpegTool._ffmpeg_source == "system":
            return
        from .ffmpeg_bundler import prefetch_bundled_ffmpeg

        prefetch_bundled_ffmpeg()

    @staticmethod
    def allows_bundled_download() -> bool:
        """返回当前配置是否允许联网下载捆绑 FFmpeg。"""
        return FFmpegTool._ffmpeg_source != "system"

    @staticmethod
    def _clear_ffmpeg_cache() -> None:
        """清理 ffmpeg 路径缓存，避免配置切换后复用旧来源。"""
        FFmpegTool._ffmpeg_exe_cache = None
        FFmpegTool._ffmpeg_exe_cache_source = None

    @staticmethod
    def _clear_ffprobe_cache() -> None:
        """清理 ffprobe 路径缓存，避免配置切换后复用旧来源。"""
        FFmpegTool._ffprobe_exe_cache = None
        FFmpegTool._ffprobe_exe_cache_source = None
