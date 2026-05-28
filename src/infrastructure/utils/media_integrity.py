"""Reusable media file integrity checks."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg_helper import FFmpegTool
from .logger import get_logger

logger = get_logger()
_MIN_VALID_BYTES = 1

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
AUDIO_SUFFIXES = {".mp3", ".ogg", ".wav", ".m4a", ".aac"}

_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"RIFF", "webp"),
)

_IMAGE_SUFFIX_FORMATS = {
    ".jpg": {"jpeg"},
    ".jpeg": {"jpeg"},
    ".png": {"png"},
    ".gif": {"gif"},
    ".webp": {"webp"},
}


@dataclass(frozen=True)
class MediaValidationResult:
    """Result of a local media integrity check."""

    ok: bool
    detail: str = ""


def configure_media_integrity(*, min_valid_bytes: int = 1) -> None:
    """Configure runtime media integrity thresholds."""
    global _MIN_VALID_BYTES
    _MIN_VALID_BYTES = max(1, int(min_valid_bytes))


def _basic_file_check(path: Path) -> MediaValidationResult:
    if not path.exists():
        return MediaValidationResult(False, "missing_file")
    if not path.is_file():
        return MediaValidationResult(False, "not_file")
    try:
        file_size = path.stat().st_size
        if file_size < _MIN_VALID_BYTES:
            return MediaValidationResult(False, f"too_small:{file_size}")
    except OSError as ex:
        return MediaValidationResult(False, f"stat_failed:{ex}")
    return MediaValidationResult(True)


def _detect_image_format(path: Path) -> str:
    try:
        header = path.read_bytes()[:16]
    except OSError:
        return ""

    for magic, image_format in _IMAGE_MAGIC:
        if not header.startswith(magic):
            continue
        if image_format == "webp":
            return "webp" if header[8:12] == b"WEBP" else ""
        return image_format
    return ""


def _validate_with_pillow(path: Path) -> MediaValidationResult:
    try:
        from PIL import Image as PillowImage  # type: ignore[import-not-found]
    except Exception:
        return MediaValidationResult(True)

    try:
        with PillowImage.open(path) as image:
            image.verify()
        with PillowImage.open(path) as image:
            image.load()
    except Exception as ex:
        return MediaValidationResult(False, f"pillow_rejected:{ex}")
    return MediaValidationResult(True)


def validate_image_file(path: Path) -> MediaValidationResult:
    """Validate a local image without requiring optional dependencies."""
    basic = _basic_file_check(path)
    if not basic.ok:
        return basic

    suffix = path.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        return MediaValidationResult(False, f"unsupported_image_suffix:{suffix}")

    mime_type, _encoding = mimetypes.guess_type(str(path))
    if not mime_type or not mime_type.startswith("image/"):
        return MediaValidationResult(False, f"unsupported_image_mime:{mime_type}")

    image_format = _detect_image_format(path)
    if not image_format:
        return MediaValidationResult(False, "unknown_image_header")
    if image_format not in _IMAGE_SUFFIX_FORMATS.get(suffix, set()):
        return MediaValidationResult(
            False,
            f"image_suffix_header_mismatch:{suffix}:{image_format}",
        )

    return _validate_with_pillow(path)


async def validate_video_file(
    path: Path,
    *,
    timeout_seconds: int = 10,
) -> MediaValidationResult:
    """Validate that a local video has a playable video stream."""
    basic = _basic_file_check(path)
    if not basic.ok:
        return basic
    valid = await FFmpegTool.has_valid_video_stream(
        path,
        timeout_seconds=timeout_seconds,
        auto_install_ffmpeg=True,
    )
    if not valid:
        return MediaValidationResult(False, "invalid_video_stream")
    return MediaValidationResult(True)


async def validate_media_file(
    path: Path,
    *,
    media_type: str | None,
    timeout_seconds: int = 10,
) -> MediaValidationResult:
    """Validate a media file according to its dispatch type."""
    normalized_type = str(media_type or "").strip().lower()
    suffix = path.suffix.lower()

    if normalized_type == "image" or (not normalized_type and suffix in IMAGE_SUFFIXES):
        return validate_image_file(path)
    if normalized_type == "video" or (not normalized_type and suffix in VIDEO_SUFFIXES):
        return await validate_video_file(path, timeout_seconds=timeout_seconds)
    return _basic_file_check(path)
