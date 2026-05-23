from __future__ import annotations

from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.base_sender import (
    DefaultMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    MessageContext,
    SendRequest,
)


class _FakeDownloader:
    calls: list[dict] = []
    path: Path = Path("/tmp/source.webm")

    async def get_or_download(self, **kwargs):
        self.calls.append(kwargs)
        return self.path


@pytest.fixture(autouse=True)
def _reset_sender_behavior():
    DefaultMessageSender.configure_runtime(timeout_seconds=30, proxy="")
    DefaultMessageSender.configure_behavior(
        video_transcode=False,
        video_transcode_timeout=120,
        gif_transcode=False,
        gif_transcode_timeout=60,
    )
    _FakeDownloader.calls = []
    _FakeDownloader.path = Path("/tmp/source.webm")
    yield
    DefaultMessageSender.configure_runtime(timeout_seconds=30, proxy="")
    DefaultMessageSender.configure_behavior(
        video_transcode=False,
        video_transcode_timeout=120,
        gif_transcode=False,
        gif_transcode_timeout=60,
    )


@pytest.mark.asyncio
async def test_prepare_media_passes_gif_transcode_config(monkeypatch):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )

    DefaultMessageSender.configure_behavior(
        gif_transcode=True,
        gif_transcode_timeout=77,
    )

    prepared = await DefaultMessageSender().prepare_media(
        [("video", "https://example.com/gif-video.webm")],
        timeout=9,
        proxy="http://proxy.local",
    )

    assert prepared[0].local_path == Path("/tmp/source.webm")
    assert _FakeDownloader.calls == [
        {
            "url": "https://example.com/gif-video.webm",
            "timeout_seconds": 9,
            "proxy": "http://proxy.local",
            "try_convert_gif": True,
            "gif_transcode_timeout": 77,
        }
    ]


@pytest.mark.asyncio
async def test_prepare_media_applies_video_transcode_config(monkeypatch):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )
    calls: list[tuple[Path, int, bool]] = []

    async def fake_transcode_to_mp4(
        source_path: Path,
        *,
        timeout_seconds: int,
        auto_install_ffmpeg: bool,
    ):
        calls.append((source_path, timeout_seconds, auto_install_ffmpeg))
        return Path("/tmp/transcoded.mp4")

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.FFmpegTool.transcode_to_mp4",
        fake_transcode_to_mp4,
    )
    monkeypatch.setattr(Path, "exists", lambda self: True)

    DefaultMessageSender.configure_behavior(
        video_transcode=True,
        video_transcode_timeout=222,
        gif_transcode=True,
        gif_transcode_timeout=66,
    )

    prepared = await DefaultMessageSender().prepare_media(
        [("video", "https://example.com/video.webm")],
        timeout=10,
        proxy="",
    )

    assert prepared[0].local_path == Path("/tmp/transcoded.mp4")
    assert calls == [(Path("/tmp/source.webm"), 222, True)]
    assert _FakeDownloader.calls[0]["try_convert_gif"] is True
    assert _FakeDownloader.calls[0]["gif_transcode_timeout"] == 66


@pytest.mark.asyncio
async def test_prepare_media_always_downloads_media(monkeypatch):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )

    prepared = await DefaultMessageSender().prepare_media(
        [("video", "https://example.com/remote-only-video.webm")]
    )

    assert prepared[0].local_path == Path("/tmp/source.webm")
    assert prepared[0].original_url == "https://example.com/remote-only-video.webm"
    assert _FakeDownloader.calls[0]["url"] == (
        "https://example.com/remote-only-video.webm"
    )


@pytest.mark.asyncio
async def test_prepare_effective_media_falls_back_to_runtime_proxy(monkeypatch):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )

    DefaultMessageSender.configure_runtime(
        timeout_seconds=120,
        proxy="http://localhost:7890",
    )

    prepared = await DefaultMessageSender()._prepare_effective_media(
        SendRequest(
            session_id="default:GroupMessage:1",
            media=[("video", "https://example.com/video.m3u8#mp4")],
        ),
        MessageContext(platform_name="qq_official"),
    )

    assert prepared is not None
    assert prepared[0].local_path == Path("/tmp/source.webm")
    assert _FakeDownloader.calls[0]["timeout_seconds"] == 120
    assert _FakeDownloader.calls[0]["proxy"] == "http://localhost:7890"
