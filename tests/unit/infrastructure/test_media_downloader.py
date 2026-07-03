from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from astrbot_plugin_rsshub.src.infrastructure.media.media_downloader import (
    MediaDownloader,
)
from astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper import FFmpegTool
from astrbot_plugin_rsshub.src.shared.constants import GIF_COMPRESS_TARGET_MAX_BYTES

_VALID_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
    b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
    b"D\x01\x00;"
)

_VALID_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00"
    b"\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09\x08\x0a\x0c\x14"
    b"\x0d\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a"
    b"\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x07"
    b"\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\xff\xd9"
)


class _FakeProcess:
    def __init__(self, *, returncode: int = 0) -> None:
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""

    def kill(self) -> None:
        return None

    async def wait(self) -> None:
        return None


@pytest.fixture(autouse=True)
def restore_media_downloader_cache_config():
    original_values = {
        "_CACHE_ENABLED": MediaDownloader._CACHE_ENABLED,
        "_CACHE_TTL_SECONDS": MediaDownloader._CACHE_TTL_SECONDS,
        "_CACHE_GC_INTERVAL_SECONDS": MediaDownloader._CACHE_GC_INTERVAL_SECONDS,
        "_CACHE_GC_GRACE_SECONDS": MediaDownloader._CACHE_GC_GRACE_SECONDS,
    }
    try:
        yield
    finally:
        for name, value in original_values.items():
            setattr(MediaDownloader, name, value)


def test_media_downloader_guesses_suffix_from_wrapped_format_query():
    url = (
        "https://proxy.atri.rodeo?url="
        "https://pbs.twimg.com/media/HJGT9y_aMAEIFmt?format=jpg&name=orig"
    )

    assert MediaDownloader._guess_suffix(url) == ".jpg"


def test_media_downloader_guesses_suffix_from_content_type():
    assert (
        MediaDownloader._suffix_from_content_type("image/jpeg; charset=binary")
        == ".jpg"
    )


def test_media_downloader_configure_cache_sets_enabled_flag():
    original_values = {
        "_CACHE_ENABLED": MediaDownloader._CACHE_ENABLED,
        "_CACHE_TTL_SECONDS": MediaDownloader._CACHE_TTL_SECONDS,
        "_CACHE_GC_INTERVAL_SECONDS": MediaDownloader._CACHE_GC_INTERVAL_SECONDS,
        "_CACHE_GC_GRACE_SECONDS": MediaDownloader._CACHE_GC_GRACE_SECONDS,
    }
    try:
        MediaDownloader.configure_cache(
            enabled=False,
            ttl_seconds=120,
            gc_interval_seconds=60,
            gc_grace_seconds=30,
        )

        assert MediaDownloader._CACHE_ENABLED is False
        assert MediaDownloader._CACHE_TTL_SECONDS == 120
    finally:
        for name, value in original_values.items():
            setattr(MediaDownloader, name, value)


@pytest.mark.asyncio
async def test_media_downloader_passes_browser_like_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    seen_headers: dict[str, str] = {}

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "image/png"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def read(self):
            return b"\x89PNG\r\n\x1a\n" + (b"\x00" * 300)

    class FakeSession:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, _url, **kwargs):
            seen_headers.update(kwargs.get("headers") or {})
            return FakeResponse()

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.media_downloader.aiohttp.ClientSession",
        FakeSession,
    )

    path = await MediaDownloader(cache_dir=tmp_path).download_to_temp(
        url="https://example.com/image.png",
        timeout_seconds=5,
        proxy="",
    )

    assert path.suffix == ".png"
    assert seen_headers["User-Agent"].startswith("Mozilla/5.0")
    assert "image/" in seen_headers["Accept"]
    path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_media_downloader_includes_diagnostic_headers_on_http_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeResponse:
        status = 403
        headers = {
            "server": "cloudflare",
            "cf-ray": "abc-LAX",
            "content-type": "text/html",
        }

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeSession:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.media_downloader.aiohttp.ClientSession",
        FakeSession,
    )

    with pytest.raises(RuntimeError) as exc_info:
        await MediaDownloader(cache_dir=tmp_path).download_to_temp(
            url="https://example.com/blocked.png",
            timeout_seconds=5,
            proxy="",
        )

    error = str(exc_info.value)
    assert "status=403" in error
    assert "server=cloudflare" in error
    assert "cf-ray=abc-LAX" in error


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
async def test_media_downloader_renews_meta_on_success_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    url = "https://example.com/a.gif"
    source = tmp_path / "source.gif"
    source.write_bytes(_VALID_GIF)
    downloader = MediaDownloader(cache_dir=tmp_path)

    now_values = [1000.0, 1010.0]

    def fake_time() -> float:
        if now_values:
            return now_values.pop(0)
        return 1010.0

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.media_downloader.time.time",
        fake_time,
    )
    cached = downloader._write_cache(url, source)
    first_expire = float(downloader._cache_meta_path(url).read_text(encoding="utf-8"))

    async def fail_download(self, **_kwargs):
        raise AssertionError("cache hit should not download")

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fail_download)

    path = await downloader.get_or_download(url=url)
    second_expire = float(downloader._cache_meta_path(url).read_text(encoding="utf-8"))

    assert path == cached
    assert second_expire > first_expire


@pytest.mark.asyncio
async def test_media_downloader_returns_cache_hit_when_renew_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    url = "https://example.com/a.gif"
    source = tmp_path / "source.gif"
    source.write_bytes(_VALID_GIF)
    downloader = MediaDownloader(cache_dir=tmp_path)
    cached = downloader._write_cache(url, source)

    def fail_renew(self, renew_url: str) -> float:
        assert renew_url == url
        raise OSError("meta is read-only")

    async def fail_download(self, **_kwargs):
        raise AssertionError("cache hit should not download")

    monkeypatch.setattr(MediaDownloader, "_renew_cache_expiry", fail_renew)
    monkeypatch.setattr(MediaDownloader, "download_to_temp", fail_download)

    path = await downloader.get_or_download(url=url)

    assert path == cached


@pytest.mark.asyncio
async def test_media_downloader_cache_disabled_downloads_every_time_without_cache_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    calls = 0

    async def fake_download(self, **_kwargs):
        nonlocal calls
        calls += 1
        path = tmp_path / f"source-{calls}.gif"
        path.write_bytes(_VALID_GIF + str(calls).encode("ascii"))
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    downloader = MediaDownloader(cache_dir=tmp_path)
    first_path = await downloader.get_or_download(url="https://example.com/a.gif")
    second_path = await downloader.get_or_download(url="https://example.com/a.gif")

    assert calls == 2
    assert first_path != second_path
    assert first_path.read_bytes() != second_path.read_bytes()
    assert not list(tmp_path.glob("*.meta"))
    assert not list(tmp_path.glob("*.fail"))


@pytest.mark.asyncio
async def test_media_downloader_cache_disabled_ignores_existing_success_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    url = "https://example.com/a.gif"
    cached_source = tmp_path / "cached-source.gif"
    cached_source.write_bytes(_VALID_GIF)
    downloader = MediaDownloader(cache_dir=tmp_path)
    cached = downloader._write_cache(url, cached_source)

    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )

    async def fake_download(self, **_kwargs):
        path = tmp_path / "fresh-source.gif"
        path.write_bytes(_VALID_GIF + b"fresh")
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    fresh = await downloader.get_or_download(url=url)

    assert fresh != cached
    assert fresh.read_bytes().endswith(b"fresh")
    assert cached.exists()


@pytest.mark.asyncio
async def test_media_downloader_validates_cache_hits_outside_io_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    url = "https://example.com/a.gif"
    source = tmp_path / "source.gif"
    source.write_bytes(_VALID_GIF)
    downloader = MediaDownloader(cache_dir=tmp_path)
    cached = downloader._write_cache(url, source)
    validation_paths: list[Path] = []

    async def fake_validate(path: Path, **_kwargs):
        assert downloader._cache_io_lock.locked() is False
        validation_paths.append(path)
        return SimpleNamespace(ok=True, detail="")

    async def fail_download(self, **_kwargs):
        raise AssertionError("cache hit should not download")

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.media_downloader.validate_media_file",
        fake_validate,
    )
    monkeypatch.setattr(MediaDownloader, "download_to_temp", fail_download)

    path = await downloader.get_or_download(url=url, media_type="image")

    assert path == cached
    assert validation_paths == [cached]


@pytest.mark.asyncio
async def test_media_downloader_caches_wrapped_twitter_image_with_query_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    url = (
        "https://proxy.atri.rodeo?url="
        "https://pbs.twimg.com/media/HJGT9y_aMAEIFmt?format=jpg&name=orig"
    )

    async def fake_download(self, **kwargs):
        assert kwargs["url"] == url
        path = tmp_path / "source.jpg"
        path.write_bytes(_VALID_JPEG)
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(url=url, media_type="image")

    assert path.suffix == ".jpg"
    assert path.read_bytes() == _VALID_JPEG
    assert downloader._read_cache(url) == path


@pytest.mark.asyncio
async def test_media_downloader_detects_real_suffix_from_file_header(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_download(self, **kwargs):
        path = tmp_path / "source.bin"
        path.write_bytes(_VALID_JPEG)
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(
        url="https://example.com/media/opaque",
        media_type="image",
    )

    assert path.suffix == ".jpg"
    assert path.read_bytes() == _VALID_JPEG
    assert downloader._read_cache("https://example.com/media/opaque") == path


@pytest.mark.asyncio
async def test_media_downloader_uses_declared_video_type_for_gif_cache_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_download(self, **kwargs):
        path = tmp_path / "source.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
        return path

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(
        url="https://example.com/media/opaque",
        media_type="video",
        try_convert_gif=True,
    )

    assert path.suffix == ".mp4"
    assert downloader._read_cache("https://example.com/media/opaque#gif") == path


@pytest.mark.asyncio
async def test_media_downloader_cleans_normalized_temp_when_gif_replaces_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_download(self, **kwargs):
        path = tmp_path / "source"
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
        return path

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_transcode_to_gif(*_args, **_kwargs):
        gif_path = tmp_path / "converted.gif"
        gif_path.write_bytes(_VALID_GIF)
        return gif_path

    unlinked: list[Path] = []
    original_safe_unlink = MediaDownloader.safe_unlink

    def record_unlink(path: Path | None) -> None:
        if path is not None:
            unlinked.append(path)
        original_safe_unlink(path)

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "transcode_to_gif", fake_transcode_to_gif)
    monkeypatch.setattr(
        MediaDownloader,
        "safe_unlink",
        staticmethod(record_unlink),
    )

    path = await MediaDownloader(cache_dir=tmp_path).get_or_download(
        url="https://example.com/media/opaque",
        media_type="video",
        try_convert_gif=True,
    )

    normalized_paths = [
        item for item in unlinked if item.name.startswith("rsshub_media_detected_")
    ]
    assert path.suffix == ".gif"
    assert normalized_paths
    assert all(not item.exists() for item in normalized_paths)


@pytest.mark.asyncio
async def test_media_downloader_cache_disabled_gif_transcode_uses_temp_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    cache_dir_calls: list[str] = []

    async def fake_download(self, **_kwargs):
        path = tmp_path / "source.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
        return path

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    def fail_cache_dir(part: str):
        cache_dir_calls.append(part)
        raise AssertionError(f"cache disabled should not use cache/{part}")

    async def fake_exec(*args, **_kwargs):
        output_path = Path(args[-1])
        output_path.write_bytes(_VALID_GIF)
        return _FakeProcess()

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **_kwargs: "ffmpeg")
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        fail_cache_dir,
    )
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    path = await MediaDownloader(cache_dir=tmp_path).get_or_download(
        url="https://example.com/video.mp4",
        media_type="video",
        try_convert_gif=True,
    )

    try:
        assert path.exists()
        assert path.suffix == ".gif"
        assert "rsshub_gif_" in path.name
        assert cache_dir_calls == []
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_get_or_download_prepared_builds_valid_gif_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=True,
        ttl_seconds=123,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    gif_path = tmp_path / "source.gif"
    gif_path.write_bytes(_VALID_GIF + (b"0" * GIF_COMPRESS_TARGET_MAX_BYTES))
    compressed_path = tmp_path / "source-small.gif"
    compressed_path.write_bytes(_VALID_GIF)

    async def fake_get_or_download(self, **_kwargs):
        return source

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_transcode_to_gif(*_args, **kwargs):
        assert kwargs["cache_ttl_seconds"] == 123
        return gif_path

    async def fake_transcode_to_gif_under_limit(*_args, **kwargs):
        assert kwargs["max_bytes"] == GIF_COMPRESS_TARGET_MAX_BYTES
        assert kwargs["cache_ttl_seconds"] == 123
        return compressed_path

    monkeypatch.setattr(MediaDownloader, "get_or_download", fake_get_or_download)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "transcode_to_gif", fake_transcode_to_gif)
    monkeypatch.setattr(
        FFmpegTool,
        "transcode_to_gif_under_limit",
        fake_transcode_to_gif_under_limit,
    )

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/video.mp4",
        media_type="video",
        try_convert_gif=True,
    )

    assert prepared.media_type == "image"
    assert prepared.local_path == gif_path
    assert [variant.variant for variant in prepared.variants] == [
        "original",
        "gif",
        "compressed_gif",
    ]


@pytest.mark.asyncio
async def test_get_or_download_prepared_cache_disabled_marks_owned_primary_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )

    async def fake_download(self, **_kwargs):
        path = tmp_path / "source.gif"
        path.write_bytes(_VALID_GIF)
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/a.gif",
        media_type="image",
    )

    assert prepared.local_path in prepared.owned_paths
    assert prepared.variants[0].path in prepared.owned_paths


@pytest.mark.asyncio
async def test_get_or_download_prepared_cache_disabled_marks_owned_variant_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    gif_path = tmp_path / "source.gif"
    gif_path.write_bytes(_VALID_GIF)

    async def fake_get_or_download(self, **_kwargs):
        return source

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_transcode_to_gif(*_args, **_kwargs):
        return gif_path

    monkeypatch.setattr(MediaDownloader, "get_or_download", fake_get_or_download)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "transcode_to_gif", fake_transcode_to_gif)

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/video.mp4",
        media_type="video",
        try_convert_gif=True,
    )

    assert source in prepared.owned_paths
    assert gif_path in prepared.owned_paths


@pytest.mark.asyncio
async def test_get_or_download_prepared_cache_disabled_gif_variants_use_temp_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    cache_dir_calls: list[str] = []
    exec_outputs: list[Path] = []

    async def fake_get_or_download(self, **_kwargs):
        return source

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    def fail_cache_dir(part: str):
        cache_dir_calls.append(part)
        raise AssertionError(f"cache disabled should not use cache/{part}")

    async def fake_exec(*args, **_kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        if len(exec_outputs) == 1:
            output_path.write_bytes(_VALID_GIF + (b"0" * GIF_COMPRESS_TARGET_MAX_BYTES))
        else:
            output_path.write_bytes(_VALID_GIF)
        return _FakeProcess()

    monkeypatch.setattr(MediaDownloader, "get_or_download", fake_get_or_download)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **_kwargs: "ffmpeg")
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        fail_cache_dir,
    )
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/video.mp4",
        media_type="video",
        try_convert_gif=True,
    )

    assert cache_dir_calls == []
    assert len(exec_outputs) == 2
    assert all(path.name.startswith("rsshub_gif") for path in exec_outputs)
    assert all(path in prepared.owned_paths for path in [source, *exec_outputs])
    assert [variant.variant for variant in prepared.variants] == [
        "original",
        "gif",
        "compressed_gif",
    ]


@pytest.mark.asyncio
async def test_get_or_download_prepared_cache_disabled_removes_invalid_gif_variant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    exec_outputs: list[Path] = []

    async def fake_get_or_download(self, **_kwargs):
        return source

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_exec(*args, **_kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        output_path.write_bytes(b"not a gif")
        return _FakeProcess()

    monkeypatch.setattr(MediaDownloader, "get_or_download", fake_get_or_download)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **_kwargs: "ffmpeg")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/video.mp4",
        media_type="video",
        try_convert_gif=True,
    )

    assert exec_outputs
    assert all(not path.exists() for path in exec_outputs)
    assert all(path not in prepared.owned_paths for path in exec_outputs)
    assert [variant.variant for variant in prepared.variants] == ["original"]


@pytest.mark.asyncio
async def test_get_or_download_prepared_cache_disabled_removes_invalid_compressed_gif(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    exec_outputs: list[Path] = []

    async def fake_get_or_download(self, **_kwargs):
        return source

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_exec(*args, **_kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        if len(exec_outputs) == 1:
            output_path.write_bytes(_VALID_GIF + (b"0" * GIF_COMPRESS_TARGET_MAX_BYTES))
        else:
            output_path.write_bytes(b"not a gif")
        return _FakeProcess()

    monkeypatch.setattr(MediaDownloader, "get_or_download", fake_get_or_download)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **_kwargs: "ffmpeg")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/video.mp4",
        media_type="video",
        try_convert_gif=True,
    )

    assert len(exec_outputs) == 2
    assert exec_outputs[0].exists()
    assert not exec_outputs[1].exists()
    assert exec_outputs[0] in prepared.owned_paths
    assert exec_outputs[1] not in prepared.owned_paths
    assert [variant.variant for variant in prepared.variants] == ["original", "gif"]


@pytest.mark.asyncio
async def test_get_or_download_prepared_cache_enabled_does_not_mark_cache_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_download(self, **_kwargs):
        path = tmp_path / "source.gif"
        path.write_bytes(_VALID_GIF)
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/a.gif",
        media_type="image",
    )

    assert prepared.local_path is not None
    assert prepared.local_path.name.startswith(
        MediaDownloader(cache_dir=tmp_path)._cache_file_prefix(
            "https://example.com/a.gif"
        )
    )
    assert prepared.owned_paths == []


@pytest.mark.asyncio
async def test_get_or_download_prepared_converts_download_detected_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    gif_path = tmp_path / "source.gif"
    gif_path.write_bytes(_VALID_GIF)
    calls: list[dict] = []

    async def fake_get_or_download(self, **kwargs):
        calls.append(kwargs)
        return source

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_transcode_to_gif(*_args, **_kwargs):
        return gif_path

    monkeypatch.setattr(MediaDownloader, "get_or_download", fake_get_or_download)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "transcode_to_gif", fake_transcode_to_gif)

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/media/opaque",
        media_type="image",
        try_convert_gif=True,
    )

    assert calls[0]["media_type"] is None
    assert prepared.media_type == "image"
    assert prepared.local_path == gif_path
    assert prepared.detected_suffix == ".gif"
    assert [variant.variant for variant in prepared.variants] == ["original", "gif"]


@pytest.mark.asyncio
async def test_get_or_download_prepared_skips_invalid_gif_variant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    gif_path = tmp_path / "broken.gif"
    gif_path.write_bytes(b"not a gif")

    async def fake_get_or_download(self, **_kwargs):
        return source

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_transcode_to_gif(*_args, **_kwargs):
        return gif_path

    async def fake_transcode_to_gif_under_limit(*_args, **_kwargs):
        raise AssertionError("invalid high quality GIF should not be compressed")

    monkeypatch.setattr(MediaDownloader, "get_or_download", fake_get_or_download)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "transcode_to_gif", fake_transcode_to_gif)
    monkeypatch.setattr(
        FFmpegTool,
        "transcode_to_gif_under_limit",
        fake_transcode_to_gif_under_limit,
    )

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/video.mp4",
        media_type="video",
        try_convert_gif=True,
    )

    assert prepared.media_type == "video"
    assert [variant.variant for variant in prepared.variants] == ["original"]


@pytest.mark.asyncio
async def test_get_or_download_prepared_cache_enabled_removes_invalid_gif_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=True,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    gif_path = tmp_path / "broken-cache.gif"
    gif_path.write_bytes(b"not a gif")
    gif_meta = gif_path.with_suffix(".meta")
    gif_meta.write_text("1234", encoding="utf-8")

    async def fake_get_or_download(self, **_kwargs):
        return source

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_transcode_to_gif(*_args, **_kwargs):
        return gif_path

    async def fake_transcode_to_gif_under_limit(*_args, **_kwargs):
        raise AssertionError("invalid GIF cache should not be compressed")

    monkeypatch.setattr(MediaDownloader, "get_or_download", fake_get_or_download)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "transcode_to_gif", fake_transcode_to_gif)
    monkeypatch.setattr(
        FFmpegTool,
        "transcode_to_gif_under_limit",
        fake_transcode_to_gif_under_limit,
    )

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/video.mp4",
        media_type="video",
        try_convert_gif=True,
    )

    assert [variant.variant for variant in prepared.variants] == ["original"]
    assert not gif_path.exists()
    assert not gif_meta.exists()


@pytest.mark.asyncio
async def test_get_or_download_prepared_cache_enabled_removes_invalid_compressed_gif_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=True,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    gif_path = tmp_path / "source.gif"
    gif_path.write_bytes(_VALID_GIF + (b"0" * GIF_COMPRESS_TARGET_MAX_BYTES))
    compressed_path = tmp_path / "broken-compressed-cache.gif"
    compressed_path.write_bytes(b"not a gif")
    compressed_meta = compressed_path.with_suffix(".meta")
    compressed_meta.write_text("1234", encoding="utf-8")

    async def fake_get_or_download(self, **_kwargs):
        return source

    async def fake_has_audio_stream(*_args, **_kwargs) -> bool:
        return False

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    async def fake_transcode_to_gif(*_args, **_kwargs):
        return gif_path

    async def fake_transcode_to_gif_under_limit(*_args, **_kwargs):
        return compressed_path

    monkeypatch.setattr(MediaDownloader, "get_or_download", fake_get_or_download)
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )
    monkeypatch.setattr(FFmpegTool, "has_audio_stream", fake_has_audio_stream)
    monkeypatch.setattr(FFmpegTool, "transcode_to_gif", fake_transcode_to_gif)
    monkeypatch.setattr(
        FFmpegTool,
        "transcode_to_gif_under_limit",
        fake_transcode_to_gif_under_limit,
    )

    prepared = await MediaDownloader(cache_dir=tmp_path).get_or_download_prepared(
        url="https://example.com/video.mp4",
        media_type="video",
        try_convert_gif=True,
    )

    assert [variant.variant for variant in prepared.variants] == ["original", "gif"]
    assert not compressed_path.exists()
    assert not compressed_meta.exists()


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

    monkeypatch.setattr(
        FFmpegTool, "has_valid_video_stream", fake_has_valid_video_stream
    )

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(url=wrapped_url)

    assert calls == [wrapped_url, inner_url]
    assert path.exists()
    assert path.read_bytes() == b"mp4"
    assert downloader._read_cache(f"{wrapped_url}#mp4") == path
    assert downloader._read_cache(f"{inner_url}#mp4") is None


@pytest.mark.asyncio
async def test_media_downloader_validates_m3u8_cache_hits_outside_io_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    url = "https://video.example.com/playlist.m3u8"
    cache_url = f"{url}#mp4"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
    downloader = MediaDownloader(cache_dir=tmp_path)
    cached = downloader._write_cache(cache_url, source)
    validation_paths: list[Path] = []

    async def fake_validate(path: Path, **_kwargs):
        assert downloader._cache_io_lock.locked() is False
        validation_paths.append(path)
        return SimpleNamespace(ok=True, detail="")

    async def fail_download_m3u8_to_mp4(*_args, **_kwargs) -> bool:
        raise AssertionError("m3u8 cache hit should not run ffmpeg")

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.media_downloader.validate_media_file",
        fake_validate,
    )
    monkeypatch.setattr(
        FFmpegTool,
        "download_m3u8_to_mp4",
        fail_download_m3u8_to_mp4,
    )

    path = await downloader.get_or_download(url=url)

    assert path == cached
    assert validation_paths == [cached]


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


@pytest.mark.asyncio
async def test_media_downloader_m3u8_cache_disabled_returns_temp_without_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    calls: list[Path] = []

    async def fake_download_m3u8_to_mp4(
        m3u8_url: str,
        output_path: Path,
        **_kwargs,
    ) -> bool:
        assert m3u8_url == "https://video.example.com/playlist.m3u8"
        calls.append(output_path)
        output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))
        return True

    async def fake_has_valid_video_stream(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(
        FFmpegTool,
        "download_m3u8_to_mp4",
        fake_download_m3u8_to_mp4,
    )
    monkeypatch.setattr(
        FFmpegTool,
        "has_valid_video_stream",
        fake_has_valid_video_stream,
    )

    path = await MediaDownloader(cache_dir=tmp_path).get_or_download(
        url="https://video.example.com/playlist.m3u8"
    )

    try:
        assert calls == [path]
        assert path.exists()
        assert path.suffix == ".mp4"
        assert not list(tmp_path.glob("*.meta"))
        assert not list(tmp_path.glob("*.mp4"))
    finally:
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# 反代 (reverse-proxy / relay) 行为测试                                         #
# --------------------------------------------------------------------------- #
# 约定：网络抓取走 self.download_to_temp(url=<FETCH_URL>)，其中 FETCH_URL 是反代
# 包装后的 URL；缓存键与 PreparedMedia.original_url 始终保持原始 url 不变。


def _capture_download(captured: list[str], tmp_path: Path, payload: bytes):
    """复用既有 download_to_temp seam：捕获 url 并落地一个临时文件。"""

    async def fake_download(self, **kwargs):
        captured.append(kwargs["url"])
        path = tmp_path / f"source-{len(captured)}.gif"
        path.write_bytes(payload)
        return path

    return fake_download


@pytest.mark.asyncio
async def test_relay_image_with_base_ending_in_equals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # base 以 "=" 结尾 → base + quote(original)
    captured: list[str] = []
    original = "https://example.com/a.gif"
    base = "https://wsrv.nl/?url="
    expected_fetch = base + quote(original, safe="")

    monkeypatch.setattr(
        MediaDownloader,
        "download_to_temp",
        _capture_download(captured, tmp_path, _VALID_GIF),
    )

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(
        url=original,
        media_type="image",
        image_relay_base_url=base,
    )

    assert captured == [expected_fetch]
    # 缓存键 / 原始 url 仍是原始地址
    assert downloader._read_cache(original) == path
    assert path.read_bytes() == _VALID_GIF


@pytest.mark.asyncio
async def test_relay_image_with_bare_base_appends_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # base 既不以 "=" 结尾，也不含 "?" → base.rstrip("/") + "/?url=" + quote(original)
    captured: list[str] = []
    original = "https://example.com/a.gif"
    base = "https://wsrv.nl/"
    expected_fetch = "https://wsrv.nl/?url=" + quote(original, safe="")

    monkeypatch.setattr(
        MediaDownloader,
        "download_to_temp",
        _capture_download(captured, tmp_path, _VALID_GIF),
    )

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(
        url=original,
        media_type="image",
        image_relay_base_url=base,
    )

    assert captured == [expected_fetch]
    assert downloader._read_cache(original) == path


@pytest.mark.asyncio
async def test_relay_non_image_uses_media_relay_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # 非图片 (file) 只设置 media_relay_base_url → 走 media 反代。
    # bare base → base.rstrip("/") + "/?url=" + quote(original)
    captured: list[str] = []
    original = "https://example.com/doc.bin"
    base = "https://relay.example/"
    expected_fetch = "https://relay.example/?url=" + quote(original, safe="")

    monkeypatch.setattr(
        MediaDownloader,
        "download_to_temp",
        _capture_download(captured, tmp_path, _VALID_GIF),
    )

    downloader = MediaDownloader(cache_dir=tmp_path)
    await downloader.get_or_download(
        url=original,
        media_type="file",
        media_relay_base_url=base,
    )

    assert captured == [expected_fetch]


@pytest.mark.asyncio
async def test_relay_image_falls_back_to_media_relay_when_image_relay_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # 图片：image_relay 未设置但 media_relay 已设置 → 回退使用 media 反代。
    captured: list[str] = []
    original = "https://example.com/a.gif"
    base = "https://relay.example/"
    expected_fetch = "https://relay.example/?url=" + quote(original, safe="")

    monkeypatch.setattr(
        MediaDownloader,
        "download_to_temp",
        _capture_download(captured, tmp_path, _VALID_GIF),
    )

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(
        url=original,
        media_type="image",
        image_relay_base_url="",
        media_relay_base_url=base,
    )

    assert captured == [expected_fetch]
    assert downloader._read_cache(original) == path


@pytest.mark.asyncio
async def test_relay_both_empty_fetches_original_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # 两个反代 base 都为空 → 行为与之前完全一致，抓取原始 url。
    captured: list[str] = []
    original = "https://example.com/a.gif"

    monkeypatch.setattr(
        MediaDownloader,
        "download_to_temp",
        _capture_download(captured, tmp_path, _VALID_GIF),
    )

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(
        url=original,
        media_type="image",
        image_relay_base_url="",
        media_relay_base_url="",
    )

    assert captured == [original]
    assert downloader._read_cache(original) == path


@pytest.mark.asyncio
async def test_relay_falls_back_to_origin_when_relay_fetch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # "先反代再回源"：第一次（反代 url）抓取抛错 → 第二次用原始 url 重试并成功。
    captured: list[str] = []
    original = "https://example.com/a.gif"
    base = "https://wsrv.nl/?url="
    relay_fetch = base + quote(original, safe="")

    async def fake_download(self, **kwargs):
        captured.append(kwargs["url"])
        if kwargs["url"] == relay_fetch:
            raise RuntimeError("relay status=502")
        path = tmp_path / f"source-{len(captured)}.gif"
        path.write_bytes(_VALID_GIF)
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    downloader = MediaDownloader(cache_dir=tmp_path)
    path = await downloader.get_or_download(
        url=original,
        media_type="image",
        image_relay_base_url=base,
    )

    assert captured == [relay_fetch, original]
    assert path.read_bytes() == _VALID_GIF
    # 回源时缓存键 / 原始 url 仍保持原始地址
    assert downloader._read_cache(original) == path


@pytest.mark.asyncio
async def test_get_or_download_prepared_passes_relay_kwargs_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # get_or_download_prepared 透传反代 kwargs：抓取 url 是反代 url，
    # 而 PreparedMedia.original_url 仍是原始地址。
    captured: list[str] = []
    original = "https://example.com/a.jpg"
    base = "https://wsrv.nl/?url="
    expected_fetch = base + quote(original, safe="")

    async def fake_download(self, **kwargs):
        captured.append(kwargs["url"])
        path = tmp_path / f"source-{len(captured)}.jpg"
        path.write_bytes(_VALID_JPEG)
        return path

    monkeypatch.setattr(MediaDownloader, "download_to_temp", fake_download)

    downloader = MediaDownloader(cache_dir=tmp_path)
    prepared = await downloader.get_or_download_prepared(
        url=original,
        media_type="image",
        image_relay_base_url=base,
    )

    assert captured == [expected_fetch]
    assert prepared.original_url == original
