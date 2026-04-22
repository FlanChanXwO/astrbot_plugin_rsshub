from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path

from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .log_utils import logger

try:
    import imageio_ffmpeg
except Exception:  # pragma: no cover
    imageio_ffmpeg = None

_ffmpeg_exe_cache: str | None = None
_ffprobe_exe_cache: str | None = None


def ensure_ffmpeg_ready(*, auto_install: bool = True) -> str | None:
    """Resolve an FFmpeg executable path for plugin runtime use."""
    global _ffmpeg_exe_cache
    if _ffmpeg_exe_cache and Path(_ffmpeg_exe_cache).exists():
        return _ffmpeg_exe_cache

    if auto_install and imageio_ffmpeg is not None:
        try:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            if ffmpeg_exe and Path(ffmpeg_exe).exists():
                _ffmpeg_exe_cache = str(Path(ffmpeg_exe).resolve())
                return _ffmpeg_exe_cache
        except Exception as ex:
            logger.warning("FFmpeg resolve via imageio-ffmpeg failed: %s", ex)

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        _ffmpeg_exe_cache = str(Path(system_ffmpeg).resolve())
        return _ffmpeg_exe_cache

    return None


def ensure_ffprobe_ready(*, auto_install: bool = True) -> str | None:
    """Resolve an FFprobe executable path for plugin runtime use.

    Priority:
    1. Cached path if still valid
    2. Same directory as ffmpeg
    3. System PATH
    4. imageio-ffmpeg (if auto_install)
    """
    global _ffprobe_exe_cache
    if _ffprobe_exe_cache and Path(_ffprobe_exe_cache).exists():
        return _ffprobe_exe_cache

    # Try to find ffprobe alongside ffmpeg
    ffmpeg_path = ensure_ffmpeg_ready(auto_install=auto_install)
    if ffmpeg_path:
        ffmpeg_dir = Path(ffmpeg_path).parent
        ffprobe_candidates = [
            ffmpeg_dir / "ffprobe",
            ffmpeg_dir / "ffprobe.exe",
        ]
        for candidate in ffprobe_candidates:
            if candidate.exists():
                _ffprobe_exe_cache = str(candidate.resolve())
                return _ffprobe_exe_cache

    # Try system PATH
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        _ffprobe_exe_cache = str(Path(system_ffprobe).resolve())
        return _ffprobe_exe_cache

    # Try imageio-ffmpeg
    if auto_install and imageio_ffmpeg is not None:
        try:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            if ffmpeg_exe:
                ffmpeg_dir = Path(ffmpeg_exe).parent
                ffprobe_candidates = [
                    ffmpeg_dir / "ffprobe",
                    ffmpeg_dir / "ffprobe.exe",
                ]
                for candidate in ffprobe_candidates:
                    if candidate.exists():
                        _ffprobe_exe_cache = str(candidate.resolve())
                        return _ffprobe_exe_cache
        except Exception as ex:
            logger.warning("FFprobe resolve via imageio-ffmpeg failed: %s", ex)

    return None


async def has_audio_stream(
    video_path: Path,
    *,
    timeout_seconds: int = 10,
    auto_install_ffmpeg: bool = True,
) -> bool:
    """Detect if video file contains audio stream using ffprobe.

    Returns True if video has audio stream, False if not (silent video).
    Returns True on any error (conservative fallback).
    """
    ffprobe_exe = ensure_ffprobe_ready(auto_install=auto_install_ffmpeg)
    if not ffprobe_exe:
        logger.debug("FFprobe not available, assuming audio exists: path=%s", video_path)
        return True

    if not video_path.exists():
        return True

    args = [
        ffprobe_exe,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "csv=s=x:p=0",
        str(video_path),
    ]

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
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
        return True
    except Exception as ex:
        logger.warning("FFprobe audio detection failed: path=%s, err=%s", video_path, ex)
        return True

    # If stdout has content, audio stream exists
    has_audio = bool(stdout and stdout.strip())
    logger.debug(
        "Audio stream detection: path=%s, has_audio=%s, stdout=%r",
        video_path,
        has_audio,
        stdout.decode("utf-8", errors="ignore") if stdout else "",
    )
    return has_audio


async def transcode_video_to_mp4_for_qq(
    source_path: Path,
    *,
    timeout_seconds: int = 120,
    auto_install_ffmpeg: bool = True,
) -> Path | None:
    """Transcode source video to QQ-friendly H264/AAC MP4."""
    ffmpeg_exe = ensure_ffmpeg_ready(auto_install=auto_install_ffmpeg)
    if not ffmpeg_exe:
        return None

    if not source_path.exists() or not source_path.is_file():
        return None

    try:
        stat = source_path.stat()
    except OSError:
        return None

    cache_root = (
        Path(get_astrbot_plugin_data_path())
        / "astrbot_plugin_rsshub"
        / "cache"
        / "qq_video"
    )
    cache_root.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256(
        f"{source_path.resolve()}::{int(stat.st_mtime)}::{stat.st_size}".encode(
            "utf-8", errors="ignore"
        )
    ).hexdigest()
    output_path = cache_root / f"{digest}.mp4"

    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

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

    process = None
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
        logger.warning("FFmpeg transcode timeout: src=%s", source_path)
        if process is not None:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
        output_path.unlink(missing_ok=True)
        return None
    except Exception as ex:
        logger.warning(
            "FFmpeg transcode process failed: src=%s, err=%s", source_path, ex
        )
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
        logger.debug(
            "FFmpeg transcode success: src=%s, out=%s, bytes=%s",
            source_path,
            output_path,
            output_path.stat().st_size,
        )
        return output_path

    _ = stdout
    return None


async def transcode_video_to_gif(
    source_path: Path,
    *,
    timeout_seconds: int = 60,
    auto_install_ffmpeg: bool = True,
) -> Path | None:
    """Transcode a silent video to high-quality GIF.

    Uses ffmpeg with optimized palette generation for best quality.
    Caches output to avoid repeated transcoding.

    Args:
        source_path: Path to the source video file
        timeout_seconds: Maximum time allowed for transcoding (default 60s)
        auto_install_ffmpeg: Whether to auto-install ffmpeg if not found

    Returns:
        Path to the generated GIF file, or None if transcoding failed
    """
    ffmpeg_exe = ensure_ffmpeg_ready(auto_install=auto_install_ffmpeg)
    if not ffmpeg_exe:
        logger.warning("FFmpeg not available for GIF transcode: src=%s", source_path)
        return None

    if not source_path.exists() or not source_path.is_file():
        return None

    try:
        stat = source_path.stat()
    except OSError:
        return None

    # Cache directory for GIF files
    cache_root = (
        Path(get_astrbot_plugin_data_path())
        / "astrbot_plugin_rsshub"
        / "cache"
        / "gif"
    )
    cache_root.mkdir(parents=True, exist_ok=True)

    # Cache key based on file path, mtime, and size
    digest = hashlib.sha256(
        f"{source_path.resolve()}::{int(stat.st_mtime)}::{stat.st_size}".encode(
            "utf-8", errors="ignore"
        )
    ).hexdigest()
    output_path = cache_root / f"{digest}.gif"

    # Return cached file if exists
    if output_path.exists() and output_path.stat().st_size > 0:
        logger.debug(
            "GIF cache hit: src=%s, out=%s, bytes=%s",
            source_path,
            output_path,
            output_path.stat().st_size,
        )
        return output_path

    # Build ffmpeg command for optimized GIF
    # - fps=15: balance between smoothness and file size (was 30)
    # - 320px width: smaller file size, suitable for IM platforms (was 480)
    # - 64 colors: reduced palette for smaller size (was 128)
    # - lanczos: high-quality scaling
    # - palettegen/paletteuse: optimized color palette
    args = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(source_path),
        "-vf",
        "fps=15,scale=320:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=64[p];[s1][p]paletteuse=dither=bayer",
        "-loop",
        "0",
        str(output_path),
    ]

    process = None
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
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
        output_path.unlink(missing_ok=True)
        return None
    except Exception as ex:
        logger.warning(
            "FFmpeg GIF transcode process failed: src=%s, err=%s", source_path, ex
        )
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
        logger.debug(
            "FFmpeg GIF transcode success: src=%s, out=%s, bytes=%s",
            source_path,
            output_path,
            output_path.stat().st_size,
        )
        return output_path

    _ = stdout
    return None
