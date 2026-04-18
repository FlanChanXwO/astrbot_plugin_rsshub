from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse


def resolve_local_file_path(file_value: str) -> str | None:
    if not file_value or not isinstance(file_value, str):
        return None
    if not file_value.startswith("file:///"):
        return None
    parsed = urlparse(file_value)
    if parsed.scheme != "file":
        return None
    local_path = unquote(parsed.path or "")
    if local_path.startswith("/") and len(local_path) >= 3 and local_path[2] == ":":
        local_path = local_path[1:]
    return local_path or None


def normalize_local_media_file_value(file_value: str) -> str:
    local_path = resolve_local_file_path(file_value) or file_value
    return str(Path(local_path).resolve())
