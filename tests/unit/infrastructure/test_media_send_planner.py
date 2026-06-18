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
    QQ_OFFICIAL_FILE_MAX_BYTES,
    QQ_OFFICIAL_GIF_MAX_BYTES,
    QQ_OFFICIAL_IMAGE_MAX_BYTES,
    QQ_OFFICIAL_VIDEO_MAX_BYTES,
    WEIXIN_GIF_MAX_BYTES,
)


def _touch(path: Path, size: int) -> Path:
    path.write_bytes(b"x" * size)
    return path


def _prepared_media(
    tmp_path: Path,
    *,
    media_type: str,
    filename: str,
    suffix: str,
    size_bytes: int,
) -> PreparedMedia:
    path = tmp_path / filename
    item = PreparedMedia(
        media_type=media_type,
        original_url=f"https://example.com/{filename}",
        local_path=path,
        detected_suffix=suffix,
    )
    item.variants = [
        MediaVariant(
            "primary",
            media_type,
            path,
            suffix=suffix,
            size_bytes=size_bytes,
        )
    ]
    return item


def test_qq_official_small_image_uses_native_file_then_link(tmp_path: Path):
    item = _prepared_media(
        tmp_path,
        media_type="image",
        filename="small.jpg",
        suffix=".jpg",
        size_bytes=9 * 1024 * 1024,
    )

    candidates = MediaSendPlanner.candidates_for(item, platform="qq_official")

    assert [candidate.action for candidate in candidates] == [
        SEND_ACTION_MEDIA,
        SEND_ACTION_FILE,
        SEND_ACTION_LINK,
    ]
    assert candidates[0].media_type == "image"
    assert candidates[1].media_type == "file"


def test_qq_official_mid_image_skips_native_and_uses_file_then_link(tmp_path: Path):
    item = _prepared_media(
        tmp_path,
        media_type="image",
        filename="mid.jpg",
        suffix=".jpg",
        size_bytes=QQ_OFFICIAL_IMAGE_MAX_BYTES + 1,
    )

    candidates = MediaSendPlanner.candidates_for(item, platform="qq_official")

    assert [candidate.action for candidate in candidates] == [
        SEND_ACTION_FILE,
        SEND_ACTION_LINK,
    ]


def test_qq_official_large_image_uses_link_only(tmp_path: Path):
    item = _prepared_media(
        tmp_path,
        media_type="image",
        filename="large.jpg",
        suffix=".jpg",
        size_bytes=QQ_OFFICIAL_FILE_MAX_BYTES + 1,
    )

    candidates = MediaSendPlanner.candidates_for(item, platform="qq_official")

    assert [candidate.action for candidate in candidates] == [SEND_ACTION_LINK]


def test_qq_official_large_video_uses_link_only(tmp_path: Path):
    item = _prepared_media(
        tmp_path,
        media_type="video",
        filename="large.mp4",
        suffix=".mp4",
        size_bytes=39 * 1024 * 1024,
    )

    candidates = MediaSendPlanner.candidates_for(item, platform="qq_official")

    assert [candidate.action for candidate in candidates] == [SEND_ACTION_LINK]


def test_qq_official_download_failed_still_uses_link_only():
    item = PreparedMedia(
        media_type="image",
        original_url="https://example.com/missing.jpg",
        download_failed=True,
    )

    candidates = MediaSendPlanner.candidates_for(item, platform="qq_official")

    assert [candidate.action for candidate in candidates] == [SEND_ACTION_LINK]
    assert candidates[0].reason == "download_failed"


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


def test_qq_official_oversize_video_skips_upload_and_uses_link(tmp_path: Path):
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

    assert [candidate.action for candidate in candidates] == [SEND_ACTION_LINK]
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
