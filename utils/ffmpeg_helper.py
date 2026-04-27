"""FFmpeg Tool Module

提供视频处理相关的 FFmpeg 工具函数。

使用示例:
    >>> from .ffmpeg_helper import FFmpegTool
    >>> ffmpeg_path = FFmpegTool.ensure_ffmpeg_ready()
    >>> has_audio = await FFmpegTool.has_audio_stream(video_path)
    >>> output = await FFmpegTool.transcode_to_mp4(source_path)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from pathlib import Path

# 直接导入，依赖缺失会在插件加载时由 AstrBot 处理
import imageio_ffmpeg

from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .log_utils import logger


class FFmpegTool:
    """FFmpeg 工具类，提供视频处理静态方法"""

    # 类级别缓存
    _ffmpeg_exe_cache: str | None = None
    _ffprobe_exe_cache: str | None = None

    # GIF 转码配置
    _GIF_TRANSCODE_FPS = 30
    _GIF_TRANSCODE_SCALE = "iw:-1"
    _GIF_TRANSCODE_MAX_COLORS = 256
    _GIF_TRANSCODE_DITHER = "sierra2_4a"
    _GIF_TRANSCODE_PROFILE = (
        f"fps={_GIF_TRANSCODE_FPS};"
        f"scale={_GIF_TRANSCODE_SCALE};"
        f"colors={_GIF_TRANSCODE_MAX_COLORS};"
        f"dither={_GIF_TRANSCODE_DITHER}"
    )

    @staticmethod
    def ensure_ffmpeg_ready(*, auto_install: bool = True) -> str | None:
        """Resolve an FFmpeg executable path for plugin runtime use.

        Priority:
        1. Cached path if still valid
        2. System PATH ffmpeg (most stable for HLS/m3u8)
        3. imageio-ffmpeg bundled binary (fallback)

        Args:
            auto_install: Whether to auto-install ffmpeg if not found

        Returns:
            Path to ffmpeg executable, or None if not found
        """
        if FFmpegTool._ffmpeg_exe_cache and Path(FFmpegTool._ffmpeg_exe_cache).exists():
            return FFmpegTool._ffmpeg_exe_cache

        # 使用字符串而非 PathLike（兼容 Python < 3.12 on Windows）
        # 优先使用系统 ffmpeg，因为对 HLS/m3u8 兼容性更好
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            FFmpegTool._ffmpeg_exe_cache = str(Path(system_ffmpeg).resolve())
            logger.debug("Using system ffmpeg: %s", FFmpegTool._ffmpeg_exe_cache)
            return FFmpegTool._ffmpeg_exe_cache

        # 回退到 imageio-ffmpeg 内置版本
        if auto_install and imageio_ffmpeg is not None:
            try:
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                if ffmpeg_exe and Path(ffmpeg_exe).exists():
                    FFmpegTool._ffmpeg_exe_cache = str(Path(ffmpeg_exe).resolve())
                    logger.debug(
                        "Using imageio-ffmpeg bundled: %s", FFmpegTool._ffmpeg_exe_cache
                    )
                    return FFmpegTool._ffmpeg_exe_cache
            except Exception as ex:
                logger.warning("FFmpeg resolve via imageio-ffmpeg failed: %s", ex)

        return None

    @staticmethod
    def ensure_ffprobe_ready(*, auto_install: bool = True) -> str | None:
        """Resolve an FFprobe executable path for plugin runtime use.

        Priority:
        1. Cached path if still valid
        2. Same directory as ffmpeg
        3. System PATH
        4. imageio-ffmpeg (if auto_install)

        Args:
            auto_install: Whether to auto-install ffmpeg if not found

        Returns:
            Path to ffprobe executable, or None if not found
        """
        if (
            FFmpegTool._ffprobe_exe_cache
            and Path(FFmpegTool._ffprobe_exe_cache).exists()
        ):
            return FFmpegTool._ffprobe_exe_cache

        # Try to find ffprobe alongside ffmpeg
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
                    return FFmpegTool._ffprobe_exe_cache

        # Try system PATH
        system_ffprobe = shutil.which("ffprobe")
        if system_ffprobe:
            FFmpegTool._ffprobe_exe_cache = str(Path(system_ffprobe).resolve())
            return FFmpegTool._ffprobe_exe_cache

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
                            FFmpegTool._ffprobe_exe_cache = str(candidate.resolve())
                            return FFmpegTool._ffprobe_exe_cache
            except Exception as ex:
                logger.warning("FFprobe resolve via imageio-ffmpeg failed: %s", ex)

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
                "FFprobe not available, assuming audio exists: path=%s", video_path
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
                "FFprobe audio detection failed: path=%s, err=%s", video_path, ex
            )
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

    @staticmethod
    async def transcode_to_mp4(
        source_path: Path,
        *,
        timeout_seconds: int = 120,
        auto_install_ffmpeg: bool = True,
    ) -> Path | None:
        """Transcode source video to QQ-friendly H264/AAC MP4.

        Args:
            source_path: Path to the source video file
            timeout_seconds: Maximum time allowed for transcoding
            auto_install_ffmpeg: Whether to auto-install ffmpeg if not found

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
            logger.warning("FFmpeg transcode timeout: src=%s", source_path)
            if process is not None:
                process.kill()
                await process.wait()
            output_path.unlink(missing_ok=True)
            return None
        except (OSError, ValueError) as ex:
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

        return None

    @staticmethod
    async def transcode_to_gif(
        source_path: Path,
        *,
        timeout_seconds: int = 60,
        auto_install_ffmpeg: bool = True,
    ) -> Path | None:
        """Transcode a silent video to high-quality GIF.

        Uses ffmpeg with palette generation tuned for quality-first output.
        Caches output to avoid repeated transcoding.

        Args:
            source_path: Path to the source video file
            timeout_seconds: Maximum time allowed for transcoding (default 60s)
            auto_install_ffmpeg: Whether to auto-install ffmpeg if not found

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

        # Cache directory for GIF files
        cache_root = (
            Path(get_astrbot_plugin_data_path())
            / "astrbot_plugin_rsshub"
            / "cache"
            / "gif"
        )
        cache_root.mkdir(parents=True, exist_ok=True)

        # Cache key includes source identity and transcode profile
        digest = hashlib.sha256(
            (
                f"{source_path.resolve()}::{int(stat.st_mtime)}::{stat.st_size}"
                f"::{FFmpegTool._GIF_TRANSCODE_PROFILE}"
            ).encode("utf-8", errors="ignore")
        ).hexdigest()
        output_path = cache_root / f"{digest}.gif"

        # Return cached file if exists
        if output_path.exists() and output_path.stat().st_size > 0:
            logger.debug(
                "GIF cache hit: src=%s, out=%s, bytes=%s, profile=%s",
                source_path,
                output_path,
                output_path.stat().st_size,
                FFmpegTool._GIF_TRANSCODE_PROFILE,
            )
            return output_path

        # Build ffmpeg command for quality-first GIF
        vf_expr = (
            f"fps={FFmpegTool._GIF_TRANSCODE_FPS},"
            f"scale={FFmpegTool._GIF_TRANSCODE_SCALE}:flags=lanczos,"
            "split[s0][s1];"
            f"[s0]palettegen=max_colors={FFmpegTool._GIF_TRANSCODE_MAX_COLORS}:stats_mode=full[p];"
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
                "FFmpeg GIF transcode success: src=%s, out=%s, bytes=%s, profile=%s",
                source_path,
                output_path,
                output_path.stat().st_size,
                FFmpegTool._GIF_TRANSCODE_PROFILE,
            )
            return output_path

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

        # 构建 ffmpeg 命令
        args = [
            ffmpeg_exe,
            "-y",
            "-protocol_whitelist",
            "file,http,https,tcp,tls,crypto,httpproxy",
            "-i",
            m3u8_url,
            "-c",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            str(output_path),
        ]

        # 设置环境变量（代理）
        env = None
        if proxy:
            env = os.environ.copy()
            env["HTTP_PROXY"] = proxy
            env["HTTPS_PROXY"] = proxy

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
                "FFmpeg m3u8 download process failed: url=%s, err=%s", m3u8_url, e
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
            logger.debug(
                "FFmpeg m3u8 download success: url=%s, out=%s, bytes=%s",
                m3u8_url,
                output_path,
                output_path.stat().st_size,
            )
            return True

        return False


# 向后兼容别名（已弃用，请直接使用 FFmpegTool）
ensure_ffmpeg_ready = FFmpegTool.ensure_ffmpeg_ready
ensure_ffprobe_ready = FFmpegTool.ensure_ffprobe_ready
has_audio_stream = FFmpegTool.has_audio_stream
transcode_video_to_mp4_for_qq = FFmpegTool.transcode_to_mp4
transcode_video_to_gif = FFmpegTool.transcode_to_gif
