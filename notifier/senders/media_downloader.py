from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp

from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
from astrbot.core.utils.http_ssl import build_tls_connector

from ...utils.log_utils import logger

_CACHE_DIR = (
    Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_rsshub" / "cache" / "media"
)
_CACHE_TTL_SECONDS = 15 * 60
_CACHE_GC_INTERVAL_SECONDS = 5 * 60
_CACHE_GC_GRACE_SECONDS = 10 * 60
_CACHE_MEDIA_SUFFIXES = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".mp4",
    ".mp3",
    ".ogg",
    ".bin",
)

_cache_gc_lock = asyncio.Lock()
_cache_io_lock = asyncio.Lock()
_cache_gc_last_run = 0.0


def _stale_orphan_age_threshold() -> int:
    return _CACHE_TTL_SECONDS + _CACHE_GC_GRACE_SECONDS


def _guess_suffix(url: str) -> str:
    lowered = url.lower()
    if ".jpg" in lowered or ".jpeg" in lowered:
        return ".jpg"
    if ".png" in lowered:
        return ".png"
    if ".gif" in lowered:
        return ".gif"
    if ".webp" in lowered:
        return ".webp"
    if ".mp4" in lowered:
        return ".mp4"
    if ".mp3" in lowered:
        return ".mp3"
    if ".ogg" in lowered:
        return ".ogg"
    return ".bin"


def _expand_download_candidates(url: str) -> list[str]:
    candidates = [url]
    try:
        parsed = urlparse(url)
        wrapped_values = parse_qs(parsed.query).get("url", [])
        for wrapped in wrapped_values:
            if wrapped.startswith("http://") or wrapped.startswith("https://"):
                if wrapped not in candidates:
                    candidates.append(wrapped)
    except Exception:
        pass
    return candidates


async def download_media_to_temp(
    *,
    url: str,
    timeout_seconds: int,
    proxy: str,
) -> Path:
    timeout = aiohttp.ClientTimeout(total=max(1, int(timeout_seconds)))

    last_err: Exception | None = None
    async with aiohttp.ClientSession(
        timeout=timeout,
        trust_env=True,
        connector=build_tls_connector(),
    ) as session:
        for candidate_url in _expand_download_candidates(url):
            logger.debug(
                "Media download attempt: origin=%s, candidate=%s, timeout_seconds=%s, proxy_enabled=%s",
                url,
                candidate_url,
                timeout_seconds,
                bool(proxy),
            )
            try:
                async with session.get(
                    candidate_url,
                    proxy=proxy or None,
                    allow_redirects=True,
                    max_redirects=10,
                ) as resp:
                    if resp.history:
                        logger.debug(
                            "Media redirect followed: origin=%s, candidate=%s, final=%s, hops=%s",
                            url,
                            candidate_url,
                            str(resp.url),
                            len(resp.history),
                        )
                    if resp.status >= 400:
                        raise RuntimeError(
                            f"download failed: status={resp.status}, url={candidate_url}"
                        )
                    data = await resp.read()
                    if not data:
                        raise RuntimeError(
                            f"download failed: empty response, url={candidate_url}"
                        )

                fd, tmp_name = tempfile.mkstemp(
                    prefix="rsshub_media_",
                    suffix=_guess_suffix(candidate_url),
                )
                try:
                    with os.fdopen(fd, "wb") as fp:
                        fp.write(data)
                except Exception:
                    Path(tmp_name).unlink(missing_ok=True)
                    raise
                logger.debug(
                    "Media download success: origin=%s, candidate=%s, bytes=%s, tmp=%s",
                    url,
                    candidate_url,
                    len(data),
                    tmp_name,
                )
                return Path(tmp_name)
            except Exception as ex:
                last_err = ex
                logger.warning(
                    "Media download attempt failed: origin=%s, candidate=%s, err_type=%s, err=%r",
                    url,
                    candidate_url,
                    type(ex).__name__,
                    ex,
                )

    if last_err is not None:
        raise RuntimeError(
            f"download failed for all candidates, url={url}, last_error={last_err!r}"
        ) from last_err
    raise RuntimeError(f"download failed for all candidates, url={url}")


def safe_unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception as ex:
        logger.debug("remove temp media failed: path=%s, err=%s", path, ex)


def _cache_file_prefix(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _cache_file_path(url: str) -> Path:
    digest = _cache_file_prefix(url)
    return _CACHE_DIR / f"{digest}{_guess_suffix(url)}"


def _cache_meta_path(url: str) -> Path:
    digest = _cache_file_prefix(url)
    return _CACHE_DIR / f"{digest}.meta"


def _collect_expired_cache_paths(
    now_ts: float,
) -> tuple[list[Path], list[tuple[Path, float]]]:
    """Collect candidate stale meta/media paths; deletion is re-validated under lock."""
    meta_paths_to_check: list[Path] = []
    orphan_media_with_age_to_check: list[tuple[Path, float]] = []

    if not _CACHE_DIR.exists():
        return meta_paths_to_check, orphan_media_with_age_to_check

    for meta_path in _CACHE_DIR.glob("*.meta"):
        try:
            expire_ts = float(meta_path.read_text(encoding="utf-8").strip())
        except Exception:
            expire_ts = 0.0

        if expire_ts + _CACHE_GC_GRACE_SECONDS >= now_ts:
            continue
        meta_paths_to_check.append(meta_path)

    stale_orphan_age = _stale_orphan_age_threshold()
    for suffix in _CACHE_MEDIA_SUFFIXES:
        for media_path in _CACHE_DIR.glob(f"*{suffix}"):
            meta_path = media_path.with_suffix(".meta")
            if meta_path.exists():
                continue
            try:
                age = now_ts - media_path.stat().st_mtime
            except OSError:
                continue
            if age < stale_orphan_age:
                continue
            orphan_media_with_age_to_check.append((media_path, age))

    return meta_paths_to_check, orphan_media_with_age_to_check


def _apply_cache_gc_deletions(
    meta_paths_to_check: list[Path],
    orphan_media_with_age_to_check: list[tuple[Path, float]],
    now_ts: float,
) -> int:
    removed = 0

    for meta_path in meta_paths_to_check:
        if not meta_path.exists():
            continue

        # Re-check expiry under lock to avoid deleting freshly refreshed entries.
        try:
            expire_ts = float(meta_path.read_text(encoding="utf-8").strip())
        except Exception:
            expire_ts = 0.0
        if expire_ts + _CACHE_GC_GRACE_SECONDS >= now_ts:
            continue

        stem = meta_path.stem
        safe_unlink(meta_path)
        removed += 1

        for suffix in _CACHE_MEDIA_SUFFIXES:
            media_path = _CACHE_DIR / f"{stem}{suffix}"
            if media_path.exists():
                safe_unlink(media_path)
                removed += 1

    stale_orphan_age = _stale_orphan_age_threshold()
    for media_path, age in orphan_media_with_age_to_check:
        if not media_path.exists():
            continue

        meta_path = media_path.with_suffix(".meta")
        if meta_path.exists():
            continue

        # Age was computed during scan phase to avoid duplicate stat() under lock.
        if age < stale_orphan_age:
            continue

        safe_unlink(media_path)
        removed += 1

    return removed


async def _run_periodic_cache_gc() -> None:
    global _cache_gc_last_run

    now_ts = time.time()
    if now_ts - _cache_gc_last_run < _CACHE_GC_INTERVAL_SECONDS:
        return

    async with _cache_gc_lock:
        now_ts = time.time()
        if now_ts - _cache_gc_last_run < _CACHE_GC_INTERVAL_SECONDS:
            return

        # Scan without I/O lock to reduce blocking of normal cache read/write flow.
        meta_paths_to_check, orphan_media_with_age_to_check = (
            _collect_expired_cache_paths(now_ts)
        )

        async with _cache_io_lock:
            removed = _apply_cache_gc_deletions(
                meta_paths_to_check,
                orphan_media_with_age_to_check,
                now_ts,
            )
            _cache_gc_last_run = now_ts

    if removed > 0:
        logger.debug("Media cache GC removed %s files", removed)


def _read_cache(url: str) -> Path | None:
    file_path = _cache_file_path(url)
    meta_path = _cache_meta_path(url)
    if not file_path.exists() or not meta_path.exists():
        logger.debug(
            "Media cache miss: url=%s, file_exists=%s, meta_exists=%s, file=%s, meta=%s",
            url,
            file_path.exists(),
            meta_path.exists(),
            file_path,
            meta_path,
        )
        return None

    try:
        expire_ts = float(meta_path.read_text(encoding="utf-8").strip())
    except Exception:
        logger.debug(
            "Media cache meta invalid: url=%s, meta=%s",
            url,
            meta_path,
        )
        return None

    now_ts = time.time()
    if expire_ts < now_ts:
        logger.debug(
            "Media cache expired: url=%s, now=%s, expire=%s, file=%s",
            url,
            now_ts,
            expire_ts,
            file_path,
        )
        return None

    logger.debug("Media cache hit: url=%s, file=%s", url, file_path)
    return file_path


def _write_cache(url: str, source: Path) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_file_path(url)
    meta_path = _cache_meta_path(url)
    cache_path.write_bytes(source.read_bytes())
    expire_ts = time.time() + _CACHE_TTL_SECONDS
    meta_path.write_text(str(expire_ts), encoding="utf-8")
    logger.debug(
        "Media cache write: url=%s, cache=%s, meta=%s, cache_exists=%s, meta_exists=%s, expire=%s",
        url,
        cache_path,
        meta_path,
        cache_path.exists(),
        meta_path.exists(),
        expire_ts,
    )
    return cache_path


async def get_or_download_media_to_cache(
    *,
    url: str,
    timeout_seconds: int,
    proxy: str,
) -> Path:
    await _run_periodic_cache_gc()

    async with _cache_io_lock:
        cached = _read_cache(url)
        if cached is not None:
            logger.debug("Media cache return existing: url=%s, path=%s", url, cached)
            return cached

    logger.debug(
        "Media cache download start: url=%s, timeout_seconds=%s, proxy_enabled=%s",
        url,
        timeout_seconds,
        bool(proxy),
    )
    tmp_path = await download_media_to_temp(
        url=url,
        timeout_seconds=timeout_seconds,
        proxy=proxy,
    )
    logger.debug(
        "Media cache download complete: url=%s, tmp=%s, tmp_exists=%s",
        url,
        tmp_path,
        tmp_path.exists(),
    )
    try:
        async with _cache_io_lock:
            # Another task may have filled cache while we were downloading.
            cached = _read_cache(url)
            if cached is not None:
                logger.debug(
                    "Media cache filled by peer task: url=%s, path=%s",
                    url,
                    cached,
                )
                return cached
            written = _write_cache(url, tmp_path)
            logger.debug("Media cache return new write: url=%s, path=%s", url, written)
            return written
    finally:
        safe_unlink(tmp_path)
