"""m3u8 流下载集成测试。

需要设置 RSSHUB_RUN_NETWORK_TESTS=1、系统 ffmpeg 可用且能访问外网。
标记为 @pytest.mark.integration，CI 默认跳过。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper import FFmpegTool

# Big Buck Bunny 240p VOD — Mux/hls.js 官方维护，长期稳定
M3U8_BBB_240P = (
    "https://test-streams.mux.dev/x36xhzz/url_2/193039199_mp4_h264_aac_ld_7.m3u8"
)

# 自适应码率主 playlist
M3U8_BBB_MASTER = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"


skip_no_network_opt_in = pytest.mark.skipif(
    os.getenv("RSSHUB_RUN_NETWORK_TESTS") != "1",
    reason="set RSSHUB_RUN_NETWORK_TESTS=1 to run public network m3u8 tests",
)


def _ffmpeg_available() -> bool:
    """检查系统 ffmpeg 是否可用。"""
    return FFmpegTool.ensure_ffmpeg_ready(auto_install=False) is not None


def _ffprobe_available() -> bool:
    """检查系统 ffprobe 是否可用。"""
    return FFmpegTool.ensure_ffprobe_ready(auto_install=False) is not None


skip_no_ffmpeg = pytest.mark.skipif(
    not _ffmpeg_available(),
    reason="ffmpeg not available on system PATH",
)

skip_no_ffprobe = pytest.mark.skipif(
    not _ffprobe_available(),
    reason="ffprobe not available on system PATH",
)


@pytest.mark.integration
@pytest.mark.asyncio
@skip_no_network_opt_in
@skip_no_ffmpeg
async def test_m3u8_download_real_240p(tmp_path: Path) -> None:
    """真实下载 240p m3u8 VOD，验证输出为有效 mp4。"""
    output = tmp_path / "bbb_240p.mp4"
    result = await FFmpegTool.download_m3u8_to_mp4(
        M3U8_BBB_240P,
        output,
        timeout_seconds=120,
        auto_install_ffmpeg=False,
    )
    assert result is True, "m3u8 download should succeed"
    assert output.exists(), "output mp4 file should exist"
    assert output.stat().st_size > 10_000, "output mp4 should be > 10 KB"


@pytest.mark.integration
@pytest.mark.asyncio
@skip_no_network_opt_in
@skip_no_ffmpeg
@skip_no_ffprobe
async def test_m3u8_download_has_audio_and_video(tmp_path: Path) -> None:
    """验证下载的 mp4 包含音频和视频流。"""
    output = tmp_path / "bbb_240p_av.mp4"
    result = await FFmpegTool.download_m3u8_to_mp4(
        M3U8_BBB_240P,
        output,
        timeout_seconds=120,
        auto_install_ffmpeg=False,
    )
    assert result is True

    has_video = await FFmpegTool.has_valid_video_stream(
        output, timeout_seconds=10, auto_install_ffmpeg=False
    )
    assert has_video is True, "downloaded mp4 should have valid video stream"

    has_audio = await FFmpegTool.has_audio_stream(
        output, timeout_seconds=10, auto_install_ffmpeg=False
    )
    assert has_audio is True, "Big Buck Bunny m3u8 should contain audio"


@pytest.mark.integration
@pytest.mark.asyncio
@skip_no_network_opt_in
@skip_no_ffmpeg
async def test_m3u8_download_master_playlist(tmp_path: Path) -> None:
    """下载自适应码率主 playlist，验证 ffmpeg 能处理 multi-variant m3u8。

    自适应码率会选择更高分辨率，下载量大，给充足超时。
    """
    output = tmp_path / "bbb_master.mp4"
    result = await FFmpegTool.download_m3u8_to_mp4(
        M3U8_BBB_MASTER,
        output,
        timeout_seconds=600,
        auto_install_ffmpeg=False,
    )
    assert result is True, "master playlist m3u8 download should succeed"
    assert output.exists()
    assert output.stat().st_size > 100_000, (
        "master playlist output should be substantial"
    )


@pytest.mark.integration
@pytest.mark.asyncio
@skip_no_network_opt_in
@skip_no_ffmpeg
async def test_m3u8_download_invalid_url(tmp_path: Path) -> None:
    """验证无效 m3u8 URL 的错误处理。"""
    output = tmp_path / "invalid.mp4"
    result = await FFmpegTool.download_m3u8_to_mp4(
        "https://test-streams.mux.dev/nonexistent/missing.m3u8",
        output,
        timeout_seconds=30,
        auto_install_ffmpeg=False,
    )
    assert result is False, "invalid m3u8 URL should return False"
