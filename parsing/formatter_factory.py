from __future__ import annotations

from .post_formatter import PostFormatter, SimplePostFormatter


def get_formatter_for_platform(platform_name: str | None) -> type[PostFormatter]:
    normalized = (platform_name or "").strip().lower()

    # if normalized in {"qq_official", "qqofficial", "qq"}:
    #     return MarkdownPostFormatter
    # if "qq_official" in normalized or "qqofficial" in normalized:
    #     return MarkdownPostFormatter

    _ = normalized
    return SimplePostFormatter
