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


def ensure_ffmpeg_ready(*, auto_install: bool = True) -> str | None:
    """Resolve an FFmpeg executable path for plugin runtime use."""
    del auto_install  # imageio-ffmpeg wheel already bundles executable.

    global _ffmpeg_exe_cache
    if _ffmpeg_exe_cache and Path(_ffmpeg_exe_cache).exists():
        return _ffmpeg_exe_cache

    if imageio_ffmpeg is not None:
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


async def transcode_video_to_mp4_for_qq(
    source_path: Path,
    *,
    timeout_seconds: int = 120,
) -> Path | None:
    """Transcode source video to QQ-friendly H264/AAC MP4."""
    ffmpeg_exe = ensure_ffmpeg_ready(auto_install=True)
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
