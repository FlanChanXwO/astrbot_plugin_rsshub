from __future__ import annotations

from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.infrastructure.media.media_downloader import (
    MediaDownloader,
)
from astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper import FFmpegTool

_VALID_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
    b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
    b"D\x01\x00;"
)


@pytest.mark.asyncio
async def test_media_downloader_retries_after_download_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls = 0

    async def fail_download(self, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("origin status=523")

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fail_download)

    first = MediaDownloader(cache_dir=tmp_path)
    with pytest.raises(RuntimeError, match="origin status=523"):
        await first.get_or_download(url="https://example.com/a.png")

    second = MediaDownloader(cache_dir=tmp_path)
    with pytest.raises(RuntimeError, match="origin status=523"):
        await second.get_or_download(url="https://example.com/a.png")

    assert calls == 2
    assert not list(tmp_path.glob("*.fail"))


@pytest.mark.asyncio
async def test_media_downloader_does_not_persist_download_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls = 0

    async def fail_download(self, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("origin status=522")

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fail_download)

    first = MediaDownloader(cache_dir=tmp_path)
    with pytest.raises(RuntimeError, match="origin status=522"):
        await first.get_or_download(url="https://example.com/p1.jpg")

    second = MediaDownloader(cache_dir=tmp_path)
    with pytest.raises(RuntimeError, match="origin status=522"):
        await second.get_or_download(url="https://example.com/p1.jpg")

    assert calls == 2
    assert not list(tmp_path.glob("*.fail"))


@pytest.mark.asyncio
async def test_media_downloader_keeps_success_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls = 0

    async def fake_download(self, **kwargs):
        nonlocal calls
        calls += 1
        path = tmp_path / f"source-{calls}.gif"
        path.write_bytes(_VALID_GIF)
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    first = MediaDownloader(cache_dir=tmp_path)
    first_path = await first.get_or_download(url="https://example.com/a.gif")

    second = MediaDownloader(cache_dir=tmp_path)
    second_path = await second.get_or_download(url="https://example.com/a.gif")

    assert calls == 1
    assert first_path == second_path
    assert second_path.read_bytes() == _VALID_GIF
    assert not list(tmp_path.glob("*.fail"))


@pytest.mark.asyncio
async def test_media_downloader_discards_invalid_success_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls = 0

    async def fake_download(self, **kwargs):
        nonlocal calls
        calls += 1
        path = tmp_path / f"source-{calls}.gif"
        path.write_bytes(b"not an image" if calls == 1 else _VALID_GIF)
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    first = MediaDownloader(cache_dir=tmp_path)
    with pytest.raises(RuntimeError, match="media validation failed"):
        await first.get_or_download(url="https://example.com/a.gif", media_type="image")

    second = MediaDownloader(cache_dir=tmp_path)
    path = await second.get_or_download(
        url="https://example.com/a.gif", media_type="image"
    )

    assert calls == 2
    assert path.read_bytes() == _VALID_GIF


@pytest.mark.asyncio
async def test_media_downloader_m3u8_tries_wrapped_and_inner_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []
    wrapped_url = (
        "https://proxy.atri.rodeo?url="
        "https://video.bsky.app/watch/example/playlist.m3u8"
    )
    inner_url = "https://video.bsky.app/watch/example/playlist.m3u8"

    async def fake_download_m3u8_to_mp4(
        m3u8_url: str,
        output_path: Path,
        **_kwargs,
    ) -> bool:
        calls.append(m3u8_url)
        if m3u8_url == inner_url:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"mp4")
            return True
        return False

    monkeypatch.setattr(
        FFmpegTool,
        "download_m3u8_to_mp4",
        fake_download_m3u8_to_mp4,
    )

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(FFmpegTool, "has_valid_video_stream", fake_has_valid_video_stream)

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(url=wrapped_url)

    assert calls == [wrapped_url, inner_url]
    assert path.exists()
    assert path.read_bytes() == b"mp4"
    assert downloader._read_cache(f"{wrapped_url}#mp4") == path
    assert downloader._read_cache(f"{inner_url}#mp4") is None


@pytest.mark.asyncio
async def test_media_downloader_m3u8_reports_original_url_when_all_candidates_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []
    wrapped_url = (
        "https://proxy.atri.rodeo?url="
        "https://video.bsky.app/watch/example/playlist.m3u8"
    )
    inner_url = "https://video.bsky.app/watch/example/playlist.m3u8"

    async def fake_download_m3u8_to_mp4(
        m3u8_url: str,
        output_path: Path,
        **_kwargs,
    ) -> bool:
        calls.append(m3u8_url)
        output_path.write_bytes(b"broken")
        return False

    monkeypatch.setattr(
        FFmpegTool,
        "download_m3u8_to_mp4",
        fake_download_m3u8_to_mp4,
    )

    downloader = MediaDownloader(cache_dir=tmp_path)
    with pytest.raises(RuntimeError) as exc_info:
        await downloader.get_or_download(url=wrapped_url)

    assert calls == [wrapped_url, inner_url]
    assert f"m3u8 download failed: {wrapped_url}" in str(exc_info.value)
    assert "ffmpeg returned unsuccessful result" in str(exc_info.value)
    assert not list(tmp_path.glob("*.mp4"))
