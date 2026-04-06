"""Common helper functions for RSS monitor normalization and dedupe tuning."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlencode


def normalize_text(value: str, max_length: int = 1024) -> str:
    text = unescape(value or "")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text[:max_length]


def normalize_identifier(value: str, max_length: int = 1024) -> str:
    """Treat identifiers as opaque tokens: keep case and inner whitespace."""
    return (value or "").strip()[:max_length]


def tracking_query_params_cache_key(raw) -> tuple[str, ...] | None:
    """Build a deterministic cache key for tracking_query_params config."""
    items = None
    if isinstance(raw, str):
        tokens = re.split(r"[,\s]+", raw)
        items = [token for token in tokens if token]
    elif isinstance(raw, (list, tuple, set)):
        items = raw

    if not items:
        return None

    normalized = sorted(
        {str(item).strip().lower() for item in items if str(item).strip()}
    )
    return tuple(normalized) if normalized else None


def normalize_path(path: str) -> str:
    normalized = path or ""
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized


def normalize_query(query: str, tracking_query_params: set[str]) -> str:
    query_pairs = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key in tracking_query_params:
            continue
        query_pairs.append((normalized_key, value))
    query_pairs.sort()
    return urlencode(query_pairs, doseq=True)


def looks_like_bare_domain_scheme(parsed, trimmed_link: str) -> bool:
    """Detect urlsplit misclassification: example.com/post -> scheme=example.com."""
    if not (parsed.scheme and not parsed.netloc):
        return False
    if trimmed_link.startswith("//"):
        return False
    scheme = parsed.scheme.lower()
    return "." in scheme and not trimmed_link.startswith(f"{scheme}:")


def normalize_config_positive_int(raw, key: str, default: int, logger) -> int:
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw if raw > 0 else default
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return default
        if re.fullmatch(r"\d+", stripped):
            parsed = int(stripped)
            return parsed if parsed > 0 else default
        logger.warning("Invalid %s=%r; expected positive integer", key, raw)
        return default
    return default


def resolve_hash_history_limit(
    *,
    entry_count: int,
    min_limit: int,
    multiplier: int,
    hard_limit: int,
    absolute_max: int,
    logger,
) -> int:
    if min_limit > absolute_max:
        logger.warning(
            "hash_history_min=%s is too large; capped to %s",
            min_limit,
            absolute_max,
        )
        min_limit = absolute_max

    if multiplier > absolute_max:
        logger.warning(
            "hash_history_multiplier=%s is too large; capped to %s",
            multiplier,
            absolute_max,
        )
        multiplier = absolute_max

    if hard_limit > absolute_max:
        logger.warning(
            "hash_history_hard_limit=%s is too large; capped to %s",
            hard_limit,
            absolute_max,
        )
        hard_limit = absolute_max

    if hard_limit < min_limit:
        logger.warning(
            "hash_history_hard_limit=%s is smaller than hash_history_min=%s; "
            "using min as effective hard limit",
            hard_limit,
            min_limit,
        )
        hard_limit = min_limit

    growth_limit = max(entry_count, 1) * multiplier
    return min(max(min_limit, growth_limit), hard_limit)
