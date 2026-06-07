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
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.qq_official_sender import (
    QQOfficialMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    MessageContext,
    PreparedMedia,
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
