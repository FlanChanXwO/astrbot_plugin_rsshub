from __future__ import annotations

from pathlib import Path

from astrbot_plugin_rsshub.src.infrastructure.utils.media_type_detector import (
    detect_media_file,
    detect_media_hint,
)


def test_detect_media_file_uses_header_for_opaque_jpeg(tmp_path: Path):
    path = tmp_path / "opaque"
    path.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + (b"\x00" * 300))

    detection = detect_media_file(path)

    assert detection.media_type == "image"
    assert detection.suffix == ".jpg"
    assert detection.source in {"filetype", "header"}


def test_detect_media_file_uses_header_for_mp4_without_suffix(tmp_path: Path):
    path = tmp_path / "opaque"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 300))

    detection = detect_media_file(path)

    assert detection.media_type == "video"
    assert detection.suffix == ".mp4"
    assert detection.source in {"filetype", "header"}


def test_detect_media_file_distinguishes_m4a_ftyp_brand(tmp_path: Path):
    path = tmp_path / "opaque"
    path.write_bytes(b"\x00\x00\x00\x18ftypM4A " + (b"\x00" * 300))

    detection = detect_media_file(path)

    assert detection.media_type == "audio"
    assert detection.suffix == ".m4a"
    assert detection.source in {"filetype", "header"}


def test_detect_media_file_distinguishes_quicktime_ftyp_brand(tmp_path: Path):
    path = tmp_path / "opaque"
    path.write_bytes(b"\x00\x00\x00\x18ftypqt  " + (b"\x00" * 300))

    detection = detect_media_file(path)

    assert detection.media_type == "video"
    assert detection.suffix == ".mov"
    assert detection.source in {"filetype", "header"}


def test_detect_media_hint_prefers_content_type_over_url():
    detection = detect_media_hint(
        url="https://example.com/not-real.jpg",
        content_type="video/mp4; charset=binary",
        declared_media_type="image",
    )

    assert detection.media_type == "video"
    assert detection.suffix == ".mp4"
    assert detection.source == "content_type"


def test_detect_media_hint_reads_wrapped_query_format():
    detection = detect_media_hint(
        url=(
            "https://proxy.atri.rodeo?url="
            "https://pbs.twimg.com/media/HJGT9y_aMAEIFmt?format=jpg&name=orig"
        )
    )

    assert detection.media_type == "image"
    assert detection.suffix == ".jpg"
    assert detection.source == "url"
