from __future__ import annotations

from pathlib import Path

from astrbot_plugin_rsshub.src.infrastructure.messaging.media_send_planner import (
    SEND_ACTION_FILE,
    SEND_ACTION_LINK,
    SEND_ACTION_MEDIA,
    MediaSendPlanner,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    MediaVariant,
    PreparedMedia,
)
from astrbot_plugin_rsshub.src.shared.constants import (
    QQ_OFFICIAL_GIF_MAX_BYTES,
    QQ_OFFICIAL_VIDEO_MAX_BYTES,
    WEIXIN_GIF_MAX_BYTES,
)


def _touch(path: Path, size: int) -> Path:
    path.write_bytes(b"x" * size)
    return path


def test_qq_official_gif_uses_compressed_then_original_video(tmp_path: Path):
    original = _touch(tmp_path / "video.mp4", 1024)
    big_gif = _touch(tmp_path / "big.gif", QQ_OFFICIAL_GIF_MAX_BYTES + 1)
    compressed = _touch(tmp_path / "compressed.gif", QQ_OFFICIAL_GIF_MAX_BYTES)
    item = PreparedMedia(
        media_type="image",
        original_url="https://example.com/video.mp4",
        local_path=big_gif,
        detected_suffix=".gif",
    )
    item.variants = [
        MediaVariant("original", "video", original, suffix=".mp4", size_bytes=1024),
        MediaVariant(
            "gif",
            "image",
            big_gif,
            suffix=".gif",
            size_bytes=QQ_OFFICIAL_GIF_MAX_BYTES + 1,
        ),
        MediaVariant(
            "compressed_gif",
            "image",
            compressed,
            suffix=".gif",
            size_bytes=QQ_OFFICIAL_GIF_MAX_BYTES,
        ),
    ]

    candidates = MediaSendPlanner.candidates_for(item, platform="qq_official")

    assert [
        (candidate.action, candidate.media_type, candidate.variant)
        for candidate in candidates
    ][:3] == [
        (SEND_ACTION_MEDIA, "image", "compressed_gif"),
        (SEND_ACTION_MEDIA, "video", "original"),
        (SEND_ACTION_FILE, "file", "compressed_gif"),
    ]
    assert candidates[-1].action == SEND_ACTION_LINK


def test_qq_official_oversize_video_skips_native_video(tmp_path: Path):
    video = _touch(tmp_path / "huge.mp4", 10)
    item = PreparedMedia(
        media_type="video",
        original_url="https://example.com/huge.mp4",
        local_path=video,
    )
    item.variants = [
        MediaVariant(
            "original",
            "video",
            video,
            suffix=".mp4",
            size_bytes=QQ_OFFICIAL_VIDEO_MAX_BYTES + 1,
        )
    ]

    candidates = MediaSendPlanner.candidates_for(item, platform="qq_official")

    assert candidates[0].action == SEND_ACTION_FILE
    assert not any(
        candidate.action == SEND_ACTION_MEDIA and candidate.media_type == "video"
        for candidate in candidates
    )


def test_qq_official_file_candidate_prefers_compressed_gif(tmp_path: Path):
    original = _touch(tmp_path / "video.mp4", 1024)
    big_gif = _touch(tmp_path / "big.gif", QQ_OFFICIAL_GIF_MAX_BYTES + 1)
    compressed = _touch(tmp_path / "compressed.gif", WEIXIN_GIF_MAX_BYTES)
    item = PreparedMedia(
        media_type="image",
        original_url="https://example.com/video.mp4",
        local_path=big_gif,
        detected_suffix=".gif",
    )
    item.variants = [
        MediaVariant("original", "video", original, suffix=".mp4", size_bytes=1024),
        MediaVariant(
            "gif",
            "image",
            big_gif,
            suffix=".gif",
            size_bytes=QQ_OFFICIAL_GIF_MAX_BYTES + 1,
        ),
        MediaVariant(
            "compressed_gif",
            "image",
            compressed,
            suffix=".gif",
            size_bytes=WEIXIN_GIF_MAX_BYTES,
        ),
    ]

    candidates = MediaSendPlanner.candidates_for(item, platform="qq_official")
    file_candidate = next(
        item for item in candidates if item.action == SEND_ACTION_FILE
    )

    assert file_candidate.file == str(compressed)
    assert file_candidate.variant == "compressed_gif"
