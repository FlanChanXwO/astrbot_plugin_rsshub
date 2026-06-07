from __future__ import annotations

from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper import FFmpegTool


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        return None

    async def wait(self) -> None:
        return None


@pytest.mark.asyncio
async def test_has_valid_video_stream_accepts_positive_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"mp4")

    monkeypatch.setattr(FFmpegTool, "ensure_ffprobe_ready", lambda **kwargs: "ffprobe")

    async def fake_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=b"video\n12.345\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    assert await FFmpegTool.has_valid_video_stream(media) is True


@pytest.mark.asyncio
async def test_has_valid_video_stream_rejects_zero_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"mp4")

    monkeypatch.setattr(FFmpegTool, "ensure_ffprobe_ready", lambda **kwargs: "ffprobe")

    async def fake_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=b"video\n0.000000\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    assert await FFmpegTool.has_valid_video_stream(media) is False


@pytest.mark.asyncio
async def test_m3u8_download_rejects_invalid_ffmpeg_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.mp4"

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")

    async def fake_exec(*args, **kwargs):
        output.write_bytes(b"broken mp4")
        return _FakeProcess(returncode=0, stdout=b"", stderr=b"")

    async def fake_validate(*args, **kwargs):
        return False

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(FFmpegTool, "has_valid_video_stream", fake_validate)

    assert (
        await FFmpegTool.download_m3u8_to_mp4(
            "https://example.com/video.m3u8",
            output,
        )
        is False
    )
    assert not output.exists()


@pytest.mark.asyncio
async def test_m3u8_download_passes_proxy_to_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.mp4"
    captured: dict[str, object] = {}

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env")
        output.write_bytes(b"valid mp4")
        return _FakeProcess(returncode=0, stdout=b"", stderr=b"")

    async def fake_validate(*args, **kwargs):
        return True

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(FFmpegTool, "has_valid_video_stream", fake_validate)

    assert (
        await FFmpegTool.download_m3u8_to_mp4(
            "https://example.com/video.m3u8",
            output,
            proxy="localhost:7890",
        )
        is True
    )

    args = list(captured["args"])
    assert args[args.index("-http_proxy") + 1] == "http://localhost:7890"
    assert args.index("-http_proxy") < args.index("-i")
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["HTTP_PROXY"] == "http://localhost:7890"
    assert env["HTTPS_PROXY"] == "http://localhost:7890"
    assert env["http_proxy"] == "http://localhost:7890"
    assert env["https_proxy"] == "http://localhost:7890"


def test_configure_bundler_clears_bundled_cache_when_switching_to_system() -> None:
    FFmpegTool._ffmpeg_source = "auto"
    FFmpegTool._ffmpeg_exe_cache = "/tmp/bundled-ffmpeg"
    FFmpegTool._ffmpeg_exe_cache_source = "bundled"
    FFmpegTool._ffprobe_exe_cache = "/tmp/bundled-ffprobe"
    FFmpegTool._ffprobe_exe_cache_source = "bundled"

    FFmpegTool.configure_bundler(ffmpeg_source="system")

    assert FFmpegTool._ffmpeg_source == "system"
    assert FFmpegTool._ffmpeg_exe_cache is None
    assert FFmpegTool._ffmpeg_exe_cache_source is None
    assert FFmpegTool._ffprobe_exe_cache is None
    assert FFmpegTool._ffprobe_exe_cache_source is None

    FFmpegTool.configure_bundler(ffmpeg_source="auto")
