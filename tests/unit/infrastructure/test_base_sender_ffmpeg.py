from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import pytest
from astrbot_plugin_rsshub.src.domain.entities.content_types import (
    LayoutFragment,
    build_generated_media_url,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.base_sender import (
    DefaultMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.media.media_downloader import (
    MediaDownloader,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender import (
    OneBotMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.qq_official_sender import (
    QQOfficialMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegram_sender import (
    TelegramMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.weixin_oc_sender import (
    WeixinOCMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    MessageContext,
    PreparedMedia,
    SendResult,
    SendRequest,
)


class _FakeDownloader:
    calls: list[dict] = []
    path: Path = Path("/tmp/source.webm")

    async def get_or_download(self, **kwargs):
        self.calls.append(kwargs)
        return self.path

    async def get_or_download_prepared(self, **kwargs):
        self.calls.append(kwargs)
        from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.base_sender import (
            detect_media_file,
        )
        from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
            PreparedMedia,
        )

        detection = detect_media_file(self.path)
        item = PreparedMedia(
            media_type=detection.media_type or kwargs.get("media_type") or "file",
            original_url=kwargs.get("url") or "",
            local_path=self.path,
            detected_mime=detection.mime,
            detected_suffix=detection.suffix or self.path.suffix,
            detection_source=detection.source,
        )
        item.ensure_primary_variant()
        return item


@pytest.fixture(autouse=True)
def _reset_sender_behavior():
    MediaDownloader.configure_cache(
        enabled=True,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
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
    MediaDownloader.configure_cache(
        enabled=True,
        ttl_seconds=900,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )
    DefaultMessageSender.configure_runtime(timeout_seconds=30, proxy="")
    DefaultMessageSender.configure_behavior(
        video_transcode=False,
        video_transcode_timeout=120,
        gif_transcode=False,
        gif_transcode_timeout=60,
    )


@pytest.fixture
def fake_detector(monkeypatch):
    def configure(*, media_type: str = "video", suffix: str = ".webm"):
        from astrbot_plugin_rsshub.src.infrastructure.utils.media_type_detector import (
            MediaTypeDetection,
        )

        monkeypatch.setattr(
            "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.base_sender.detect_media_file",
            lambda _path: MediaTypeDetection(
                media_type=media_type,
                suffix=suffix,
                mime=f"{media_type}/{suffix.lstrip('.')}",
                source="test",
            ),
        )

    configure()
    return configure


@pytest.mark.asyncio
async def test_prepare_media_passes_gif_transcode_config(monkeypatch, fake_detector):
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
            "media_type": "video",
            "try_convert_gif": True,
            "gif_transcode_timeout": 77,
            "image_relay_base_url": "",
            "media_relay_base_url": "",
        }
    ]


@pytest.mark.asyncio
async def test_prepare_media_enables_gif_for_wrapped_video_url(
    monkeypatch,
    fake_detector,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )
    DefaultMessageSender.configure_behavior(gif_transcode=True)
    wrapped_url = "https://rss.example/?url=" + quote(
        "https://video.twimg.com/tweet_video/source.mp4",
        safe="",
    )

    prepared = await DefaultMessageSender().prepare_media([("image", wrapped_url)])

    assert prepared[0].local_path == Path("/tmp/source.webm")
    assert _FakeDownloader.calls[0]["media_type"] == "video"
    assert _FakeDownloader.calls[0]["try_convert_gif"] is True


@pytest.mark.asyncio
async def test_prepare_media_lets_download_detection_decide_for_opaque_media(
    monkeypatch,
    fake_detector,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )
    DefaultMessageSender.configure_behavior(gif_transcode=True)

    await DefaultMessageSender().prepare_media(
        [("file", "https://example.com/media/opaque")]
    )

    assert _FakeDownloader.calls[0]["media_type"] == "file"
    assert _FakeDownloader.calls[0]["try_convert_gif"] is True


@pytest.mark.asyncio
async def test_prepare_media_does_not_enable_gif_for_known_image_url(
    monkeypatch,
    fake_detector,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )
    DefaultMessageSender.configure_behavior(gif_transcode=True)

    await DefaultMessageSender().prepare_media(
        [("image", "https://example.com/photo.jpg")]
    )

    assert _FakeDownloader.calls[0]["media_type"] == "image"
    assert _FakeDownloader.calls[0]["try_convert_gif"] is False


@pytest.mark.asyncio
async def test_prepare_media_applies_video_transcode_config(monkeypatch, fake_detector):
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
        cache_enabled: bool,
        cache_ttl_seconds: int,
    ):
        calls.append(
            (
                source_path,
                timeout_seconds,
                auto_install_ffmpeg,
                cache_enabled,
                cache_ttl_seconds,
            )
        )
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
    assert calls == [(Path("/tmp/source.webm"), 222, True, True, 900)]
    assert _FakeDownloader.calls[0]["try_convert_gif"] is True
    assert _FakeDownloader.calls[0]["gif_transcode_timeout"] == 66


@pytest.mark.asyncio
async def test_prepare_media_marks_uncached_transcoded_video_owned(
    monkeypatch,
    tmp_path: Path,
    fake_detector,
):
    source = tmp_path / "source.webm"
    source.write_bytes(b"webm")
    transcoded = tmp_path / "rsshub_video_transcoded_result.mp4"
    transcoded.write_bytes(b"mp4")
    _FakeDownloader.path = source
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=120,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )

    async def fake_transcode_to_mp4(
        source_path: Path,
        *,
        timeout_seconds: int,
        auto_install_ffmpeg: bool,
        cache_enabled: bool,
        cache_ttl_seconds: int,
    ):
        assert source_path == source
        assert cache_enabled is False
        assert cache_ttl_seconds == 120
        return transcoded

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.FFmpegTool.transcode_to_mp4",
        fake_transcode_to_mp4,
    )
    DefaultMessageSender.configure_behavior(video_transcode=True)

    prepared = await DefaultMessageSender().prepare_media(
        [("video", "https://example.com/video.webm")]
    )

    assert prepared[0].local_path == transcoded
    assert transcoded in prepared[0].owned_paths


@pytest.mark.asyncio
async def test_default_sender_cleans_uncached_transcoded_video_after_send(
    monkeypatch,
    tmp_path: Path,
    fake_detector,
):
    source = tmp_path / "source.webm"
    source.write_bytes(b"webm")
    transcoded = tmp_path / "rsshub_video_transcoded_cleanup.mp4"
    _FakeDownloader.path = source
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )
    MediaDownloader.configure_cache(
        enabled=False,
        ttl_seconds=120,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )

    async def fake_transcode_to_mp4(*_args, **_kwargs):
        transcoded.write_bytes(b"mp4")
        return transcoded

    async def fake_send_chain(session_id, chain, use_markdown=None):
        assert transcoded.exists()
        return SendResult(ok=True)

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.FFmpegTool.transcode_to_mp4",
        fake_transcode_to_mp4,
    )
    DefaultMessageSender.configure_behavior(video_transcode=True)
    sender = DefaultMessageSender()
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="session",
            message="正文",
            media=[("video", "https://example.com/video.webm")],
        )
    )

    assert result.ok is True
    assert not transcoded.exists()


@pytest.mark.asyncio
async def test_prepare_media_keeps_cached_transcoded_video_unowned(
    monkeypatch,
    tmp_path: Path,
    fake_detector,
):
    source = tmp_path / "source.webm"
    source.write_bytes(b"webm")
    transcoded = tmp_path / "cache" / "cached.mp4"
    transcoded.parent.mkdir()
    transcoded.write_bytes(b"mp4")
    _FakeDownloader.path = source
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )
    MediaDownloader.configure_cache(
        enabled=True,
        ttl_seconds=240,
        gc_interval_seconds=300,
        gc_grace_seconds=600,
    )

    async def fake_transcode_to_mp4(
        source_path: Path,
        *,
        timeout_seconds: int,
        auto_install_ffmpeg: bool,
        cache_enabled: bool,
        cache_ttl_seconds: int,
    ):
        assert source_path == source
        assert cache_enabled is True
        assert cache_ttl_seconds == 240
        return transcoded

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.FFmpegTool.transcode_to_mp4",
        fake_transcode_to_mp4,
    )
    DefaultMessageSender.configure_behavior(video_transcode=True)

    prepared = await DefaultMessageSender().prepare_media(
        [("video", "https://example.com/video.webm")]
    )

    assert prepared[0].local_path == transcoded
    assert transcoded not in prepared[0].owned_paths


@pytest.mark.asyncio
async def test_qq_official_prepare_media_keeps_gif_transcode(
    monkeypatch,
    fake_detector,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )

    DefaultMessageSender.configure_behavior(
        gif_transcode=True,
        gif_transcode_timeout=77,
    )

    prepared = await QQOfficialMessageSender().prepare_media(
        [("video", "https://example.com/small-twitter-video.mp4")],
        timeout=9,
        proxy="",
    )

    assert prepared[0].local_path == Path("/tmp/source.webm")
    assert _FakeDownloader.calls[0]["try_convert_gif"] is True
    assert _FakeDownloader.calls[0]["media_type"] == "video"


@pytest.mark.asyncio
async def test_prepare_media_always_downloads_media(monkeypatch, fake_detector):
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
async def test_prepare_media_corrects_type_from_downloaded_file(
    monkeypatch,
    fake_detector,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )
    _FakeDownloader.path = Path("/tmp/actual.mp4")
    fake_detector(media_type="video", suffix=".mp4")

    prepared = await DefaultMessageSender().prepare_media(
        [("image", "https://example.com/opaque")]
    )

    assert prepared[0].media_type == "video"
    assert prepared[0].detected_suffix == ".mp4"
    assert prepared[0].detection_source == "test"


@pytest.mark.asyncio
async def test_prepare_effective_media_falls_back_to_runtime_proxy(
    monkeypatch,
    fake_detector,
):
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


@pytest.mark.asyncio
async def test_prepare_media_uses_generated_png_without_downloading(
    monkeypatch,
    tmp_path: Path,
    fake_detector,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.media.MediaDownloader",
        _FakeDownloader,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.get_plugin_cache_dir",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    digest = "a" * 64
    source_id = build_generated_media_url("table", digest)
    path = tmp_path / "table_images" / f"table_{digest}.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)
    fake_detector(media_type="image", suffix=".png")

    prepared = await DefaultMessageSender().prepare_media([("image", source_id)])

    assert prepared[0].local_path == path
    assert prepared[0].generated is True
    assert prepared[0].download_failed is False
    assert _FakeDownloader.calls == []


@pytest.mark.asyncio
async def test_prepare_media_generated_missing_does_not_expose_failed_url(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.get_plugin_cache_dir",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    source_id = build_generated_media_url("table", "b" * 64)

    prepared = await DefaultMessageSender().prepare_media([("image", source_id)])

    assert prepared[0].download_failed is True
    assert prepared[0].generated is True
    assert DefaultMessageSender._collect_failed_urls(prepared) == []


def test_build_components_uses_table_text_when_generated_cache_missing():
    sender = DefaultMessageSender()
    source_id = build_generated_media_url("table", "c" * 64)
    request = SendRequest(
        session_id="session",
        message="正文",
        media=[("image", source_id)],
        layout=[
            LayoutFragment(
                kind="image",
                media_type="image",
                url=source_id,
                fallback_text="A | B",
            )
        ],
    )
    prepared = [
        PreparedMedia(
            media_type="image",
            original_url=source_id,
            download_failed=True,
            generated=True,
        )
    ]

    components = sender._build_components(request, prepared)

    assert [component.kind for component in components] == ["text"]
    assert components[0].text == "正文\n\nA | B"
    assert source_id not in components[0].text


def test_layout_components_use_table_text_when_generated_preparation_failed():
    sender = DefaultMessageSender()
    source_id = build_generated_media_url("table", "d" * 64)
    request = SendRequest(
        session_id="session",
        message="正文",
        layout=[
            LayoutFragment(
                kind="image",
                media_type="image",
                url=source_id,
                local_path="/tmp/missing.png",
                fallback_text="A | B",
            )
        ],
    )

    components = sender._layout_to_components(
        request,
        prepared_media_by_url={
            source_id: PreparedMedia(
                media_type="image",
                original_url=source_id,
                download_failed=True,
                generated=True,
            )
        },
    )

    assert [component.kind for component in components] == ["text"]
    assert components[0].text == "A | B"


@pytest.mark.asyncio
async def test_prepare_effective_media_uses_generated_layout_local_path(
    monkeypatch,
    tmp_path: Path,
    fake_detector,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.get_plugin_cache_dir",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    fake_detector(media_type="image", suffix=".png")
    digest = "e" * 64
    source_id = build_generated_media_url("table", digest)
    temp_png = tmp_path / "rsshub_table_temp.png"
    temp_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

    prepared = await DefaultMessageSender()._prepare_effective_media(
        SendRequest(
            session_id="session",
            media=[("image", source_id)],
            layout=[
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url=source_id,
                    local_path=str(temp_png),
                )
            ],
        )
    )

    assert prepared is not None
    assert prepared[0].local_path != temp_png
    assert prepared[0].local_path is not None
    assert prepared[0].local_path.exists()
    assert prepared[0].generated is True
    assert prepared[0].download_failed is False
    assert prepared[0].owned_paths == [prepared[0].local_path]
    assert temp_png.exists()


@pytest.mark.asyncio
async def test_prepare_effective_media_keeps_external_generated_local_path_unowned(
    monkeypatch,
    tmp_path: Path,
    fake_detector,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.get_plugin_cache_dir",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    fake_detector(media_type="image", suffix=".png")
    source_id = build_generated_media_url("table", "9" * 64)
    external_png = tmp_path / "external-table.png"
    external_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

    prepared = await DefaultMessageSender()._prepare_effective_media(
        SendRequest(
            session_id="session",
            media=[("image", source_id)],
            layout=[
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url=source_id,
                    local_path=str(external_png),
                )
            ],
        )
    )

    assert prepared is not None
    assert prepared[0].local_path == external_png
    assert prepared[0].owned_paths == []
    assert external_png.exists()


@pytest.mark.asyncio
async def test_generated_layout_temp_path_is_copied_per_send(
    monkeypatch,
    tmp_path: Path,
    fake_detector,
):
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.get_plugin_cache_dir",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    fake_detector(media_type="image", suffix=".png")
    digest = "f" * 64
    source_id = build_generated_media_url("table", digest)
    source_png = tmp_path / "rsshub_table_shared.png"
    source_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)
    cleaned_paths: list[Path] = []

    async def fake_send_chain(session_id, chain, use_markdown=None):
        return SendResult(ok=True)

    sender = DefaultMessageSender()
    original_cleanup = sender._cleanup_owned_paths

    def capture_cleanup(prepared_media):
        for item in prepared_media or []:
            cleaned_paths.extend(item.owned_paths)
        original_cleanup(prepared_media)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(sender, "_cleanup_owned_paths", capture_cleanup)
    request = SendRequest(
        session_id="session",
        message="正文",
        media=[("image", source_id)],
        layout=[
            LayoutFragment(
                kind="image",
                media_type="image",
                url=source_id,
                local_path=str(source_png),
            )
        ],
    )

    first = await sender.send_to_user(request)
    second = await sender.send_to_user(request)

    assert first.ok is True
    assert second.ok is True
    assert source_png.exists()
    assert len(cleaned_paths) == 2
    assert cleaned_paths[0] != cleaned_paths[1]
    assert not cleaned_paths[0].exists()
    assert not cleaned_paths[1].exists()


@pytest.mark.asyncio
async def test_default_sender_cleans_self_prepared_owned_paths_on_failure(
    monkeypatch,
    tmp_path: Path,
):
    owned = tmp_path / "owned.png"
    owned.write_bytes(b"temp")
    prepared = PreparedMedia(
        media_type="image",
        original_url="https://example.com/a.png",
        local_path=owned,
    )
    prepared.mark_owned_path(owned)

    async def fake_prepare_media(media, timeout=30, proxy=""):
        return [prepared]

    async def fake_send_chain(session_id, chain, use_markdown=None):
        return SendResult(ok=False, detail="platform_failed")

    sender = DefaultMessageSender()
    monkeypatch.setattr(sender, "prepare_media", fake_prepare_media)
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="session",
            message="正文",
            media=[("image", "https://example.com/a.png")],
        )
    )

    assert result.ok is False
    assert not owned.exists()


@pytest.mark.asyncio
async def test_default_sender_cleans_self_prepared_owned_paths_on_success(
    monkeypatch,
    tmp_path: Path,
):
    owned = tmp_path / "owned-success.png"
    owned.write_bytes(b"temp")
    prepared = PreparedMedia(
        media_type="image",
        original_url="https://example.com/success.png",
        local_path=owned,
    )
    prepared.mark_owned_path(owned)

    async def fake_prepare_media(media, timeout=30, proxy=""):
        return [prepared]

    async def fake_send_chain(session_id, chain, use_markdown=None):
        return SendResult(ok=True)

    sender = DefaultMessageSender()
    monkeypatch.setattr(sender, "prepare_media", fake_prepare_media)
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="session",
            message="正文",
            media=[("image", "https://example.com/success.png")],
        )
    )

    assert result.ok is True
    assert not owned.exists()


@pytest.mark.asyncio
async def test_default_sender_keeps_external_prepared_owned_paths(
    monkeypatch,
    tmp_path: Path,
):
    owned = tmp_path / "external.png"
    owned.write_bytes(b"external")
    prepared = PreparedMedia(
        media_type="image",
        original_url="https://example.com/external.png",
        local_path=owned,
    )
    prepared.mark_owned_path(owned)

    async def fake_send_chain(session_id, chain, use_markdown=None):
        return SendResult(ok=True)

    sender = DefaultMessageSender()
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="session",
            message="正文",
            prepared_media=[prepared],
        )
    )

    assert result.ok is True
    assert owned.exists()


def test_telegram_normalize_planned_media_preserves_owned_paths(tmp_path: Path):
    large_image = tmp_path / "large.png"
    large_image.write_bytes(b"x" * (11 * 1024 * 1024))
    prepared = PreparedMedia(
        media_type="image",
        original_url="https://example.com/large.png",
        local_path=large_image,
        detected_suffix=".png",
        owned_paths=[large_image],
    )
    prepared.ensure_primary_variant()

    normalized = TelegramMessageSender._normalize_planned_media([prepared])

    assert normalized[0].media_type == "file"
    assert normalized[0].owned_paths == [large_image]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sender_cls,platform",
    [
        (OneBotMessageSender, "aiocqhttp"),
        (TelegramMessageSender, "telegram"),
        (QQOfficialMessageSender, "qq_official"),
        (WeixinOCMessageSender, "weixin_official_account"),
    ],
)
async def test_platform_senders_clean_self_prepared_owned_paths(
    monkeypatch,
    tmp_path: Path,
    sender_cls,
    platform: str,
):
    owned = tmp_path / f"{platform}.png"
    owned.write_bytes(b"temp")
    prepared = PreparedMedia(
        media_type="image",
        original_url=f"https://example.com/{platform}.png",
        local_path=owned,
        detected_suffix=".png",
    )
    prepared.mark_owned_path(owned)
    prepared.ensure_primary_variant()

    async def fake_prepare_media(media, timeout=30, proxy=""):
        return [prepared]

    async def fake_send_chain(session_id, chain, use_markdown=None):
        return SendResult(ok=True)

    sender = sender_cls()
    monkeypatch.setattr(sender, "prepare_media", fake_prepare_media)
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="session",
            message="正文",
            media=[("image", prepared.original_url)],
        ),
        MessageContext(platform_name=platform),
    )

    if sender_cls is not OneBotMessageSender:
        assert result.ok is True
    assert not owned.exists()
