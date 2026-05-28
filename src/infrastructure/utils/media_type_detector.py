"""Media type detection helpers.

The detector is intentionally cheap: file inspection reads only the header used by
the optional ``filetype`` package, then falls back to small local heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:  # pragma: no cover - import availability is environment dependent
    import filetype  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    filetype = None


MEDIA_TYPE_SUFFIXES: dict[str, str] = {
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "png": ".png",
    "gif": ".gif",
    "webp": ".webp",
    "mp4": ".mp4",
    "webm": ".webm",
    "mov": ".mov",
    "mkv": ".mkv",
    "avi": ".avi",
    "mp3": ".mp3",
    "ogg": ".ogg",
    "wav": ".wav",
    "m4a": ".m4a",
    "aac": ".aac",
    "m3u8": ".m3u8",
}

CONTENT_TYPE_SUFFIXES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "application/vnd.apple.mpegurl": ".m3u8",
    "application/x-mpegurl": ".m3u8",
}

SUFFIX_MEDIA_TYPES: dict[str, str] = {
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".gif": "image",
    ".webp": "image",
    ".mp4": "video",
    ".webm": "video",
    ".mov": "video",
    ".mkv": "video",
    ".avi": "video",
    ".m3u8": "video",
    ".mp3": "audio",
    ".ogg": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".aac": "audio",
}

MEDIA_MIME_PREFIXES = {
    "image/": "image",
    "video/": "video",
    "audio/": "audio",
}

FTYP_AUDIO_BRANDS = {
    b"M4A ",
    b"M4B ",
    b"M4P ",
    b"mp4a",
}
FTYP_QUICKTIME_BRANDS = {b"qt  "}
FTYP_MP4_BRANDS = {
    b"avc1",
    b"dash",
    b"iso2",
    b"isom",
    b"mp41",
    b"mp42",
    b"MSNV",
}


@dataclass(frozen=True)
class MediaTypeDetection:
    """Detected media type metadata."""

    media_type: str
    suffix: str
    mime: str = ""
    source: str = "fallback"


def suffix_from_format_value(value: str) -> str:
    media_format = (
        unquote(str(value or "")).strip().lower().lstrip(".").split("&", 1)[0]
    )
    return MEDIA_TYPE_SUFFIXES.get(media_format, "")


def suffix_from_query(url: str) -> str:
    try:
        query = parse_qs(urlparse(url).query)
    except Exception:
        return ""
    for key in ("format", "fm", "ext"):
        for value in query.get(key, []):
            suffix = suffix_from_format_value(value)
            if suffix:
                return suffix
    return ""


def suffix_from_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    normalized = content_type.split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_SUFFIXES.get(normalized, "")


def media_type_from_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    normalized = content_type.split(";", 1)[0].strip().lower()
    for prefix, media_type in MEDIA_MIME_PREFIXES.items():
        if normalized.startswith(prefix):
            return media_type
    suffix = CONTENT_TYPE_SUFFIXES.get(normalized, "")
    return SUFFIX_MEDIA_TYPES.get(suffix, "")


def suffix_from_bytes(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        major_brand = data[8:12]
        if major_brand in FTYP_AUDIO_BRANDS:
            return ".m4a"
        if major_brand in FTYP_QUICKTIME_BRANDS:
            return ".mov"
        if major_brand in FTYP_MP4_BRANDS:
            return ".mp4"
        return ".mp4"
    return ""


def suffix_from_file_header(path: Path) -> str:
    try:
        return suffix_from_bytes(path.read_bytes()[:261])
    except OSError:
        return ""


def guess_suffix_from_url(url: str) -> str:
    candidates = [url]
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        suffix = suffix_from_query(url)
        if suffix:
            return suffix
        candidates.append(unquote(parsed.path or ""))
        candidates.extend(query.get("url", []))
    except Exception:
        pass

    for candidate in candidates:
        suffix = suffix_from_query(candidate)
        if suffix:
            return suffix
        lowered = unquote(str(candidate or "")).lower()
        parsed_path = urlparse(lowered).path if "://" in lowered else lowered
        for marker, suffix in (
            (".m3u8", ".m3u8"),
            (".jpeg", ".jpg"),
            (".jpg", ".jpg"),
            (".png", ".png"),
            (".gif", ".gif"),
            (".webp", ".webp"),
            (".mp4", ".mp4"),
            (".webm", ".webm"),
            (".mov", ".mov"),
            (".mkv", ".mkv"),
            (".avi", ".avi"),
            (".mp3", ".mp3"),
            (".ogg", ".ogg"),
            (".wav", ".wav"),
            (".m4a", ".m4a"),
            (".aac", ".aac"),
        ):
            if marker in parsed_path:
                return suffix
    return ".bin"


def _detection_from_suffix(suffix: str, source: str) -> MediaTypeDetection:
    normalized_suffix = str(suffix or "").lower()
    media_type = SUFFIX_MEDIA_TYPES.get(normalized_suffix, "file")
    return MediaTypeDetection(
        media_type=media_type,
        suffix=normalized_suffix or ".bin",
        source=source,
    )


def detect_media_bytes(data: bytes) -> MediaTypeDetection:
    """Detect media type from an in-memory header/body sample."""
    if filetype is not None:
        try:
            kind = filetype.guess(data)
        except Exception:
            kind = None
        if kind is not None:
            suffix = MEDIA_TYPE_SUFFIXES.get(str(kind.extension).lower(), "")
            if suffix:
                return MediaTypeDetection(
                    media_type=media_type_from_content_type(kind.mime)
                    or SUFFIX_MEDIA_TYPES.get(suffix, "file"),
                    suffix=suffix,
                    mime=str(kind.mime or ""),
                    source="filetype",
                )

    suffix = suffix_from_bytes(data[:261])
    if suffix:
        return _detection_from_suffix(suffix, "header")
    return MediaTypeDetection(media_type="file", suffix=".bin", source="fallback")


def detect_media_file(path: Path) -> MediaTypeDetection:
    """Detect media type from a local file without running expensive probes."""
    if filetype is not None:
        try:
            kind = filetype.guess(str(path))
        except Exception:
            kind = None
        if kind is not None:
            suffix = MEDIA_TYPE_SUFFIXES.get(str(kind.extension).lower(), "")
            if suffix:
                media_type = media_type_from_content_type(kind.mime) or (
                    SUFFIX_MEDIA_TYPES.get(suffix, "file")
                )
                return MediaTypeDetection(
                    media_type=media_type,
                    suffix=suffix,
                    mime=str(kind.mime or ""),
                    source="filetype",
                )

    suffix = suffix_from_file_header(path)
    if suffix:
        return _detection_from_suffix(suffix, "header")

    suffix = path.suffix.lower()
    if suffix:
        return _detection_from_suffix(suffix, "path_suffix")

    return MediaTypeDetection(media_type="file", suffix=".bin", source="fallback")


def detect_media_hint(
    *,
    url: str = "",
    content_type: str | None = None,
    declared_media_type: str | None = None,
) -> MediaTypeDetection:
    """Detect media type from cheap HTTP/URL/declaration hints."""
    suffix = suffix_from_content_type(content_type)
    if suffix:
        return MediaTypeDetection(
            media_type=media_type_from_content_type(content_type)
            or SUFFIX_MEDIA_TYPES.get(suffix, "file"),
            suffix=suffix,
            mime=str(content_type or "").split(";", 1)[0].strip().lower(),
            source="content_type",
        )

    suffix = guess_suffix_from_url(url)
    if suffix and suffix != ".bin":
        return _detection_from_suffix(suffix, "url")

    declared = str(declared_media_type or "").strip().lower()
    if declared in {"image", "video", "audio"}:
        return MediaTypeDetection(media_type=declared, suffix=".bin", source="declared")

    return MediaTypeDetection(media_type="file", suffix=".bin", source="fallback")
