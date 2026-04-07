from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.core.utils.http_ssl import build_tls_connector

_CACHE_DIR = Path(tempfile.gettempdir()) / "astrbot_rsshub_media_cache"
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


async def download_media_to_temp(
    *,
    url: str,
    timeout_seconds: int,
    proxy: str,
) -> Path:
    timeout = aiohttp.ClientTimeout(total=max(1, int(timeout_seconds)))

    async with aiohttp.ClientSession(
        timeout=timeout,
        trust_env=True,
        connector=build_tls_connector(),
    ) as session:
        async with session.get(
            url,
            proxy=proxy or None,
            allow_redirects=True,
            max_redirects=10,
        ) as resp:
            if resp.history:
                logger.debug(
                    "Media redirect followed: origin=%s, final=%s, hops=%s",
                    url,
                    str(resp.url),
                    len(resp.history),
                )
            if resp.status >= 400:
                raise RuntimeError(f"download failed: status={resp.status}, url={url}")
            data = await resp.read()
            if not data:
                raise RuntimeError(f"download failed: empty response, url={url}")

    fd, tmp_name = tempfile.mkstemp(prefix="rsshub_media_", suffix=_guess_suffix(url))
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return Path(tmp_name)


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


def _cleanup_expired_cache_files(now_ts: float) -> int:
    if not _CACHE_DIR.exists():
        return 0

    removed = 0

    for meta_path in _CACHE_DIR.glob("*.meta"):
        try:
            expire_ts = float(meta_path.read_text(encoding="utf-8").strip())
        except Exception:
            expire_ts = 0.0

        # Keep a grace window to avoid deleting files that may still be in-flight.
        if expire_ts + _CACHE_GC_GRACE_SECONDS >= now_ts:
            continue

        stem = meta_path.stem
        safe_unlink(meta_path)
        removed += 1

        for suffix in _CACHE_MEDIA_SUFFIXES:
            candidate = _CACHE_DIR / f"{stem}{suffix}"
            if candidate.exists():
                safe_unlink(candidate)
                removed += 1

    stale_orphan_age = _CACHE_TTL_SECONDS + _CACHE_GC_GRACE_SECONDS
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

        async with _cache_io_lock:
            removed = _cleanup_expired_cache_files(now_ts)
            _cache_gc_last_run = now_ts

    if removed > 0:
        logger.debug("Media cache GC removed %s files", removed)


def _read_cache(url: str) -> Path | None:
    file_path = _cache_file_path(url)
    meta_path = _cache_meta_path(url)
    if not file_path.exists() or not meta_path.exists():
        return None

    try:
        expire_ts = float(meta_path.read_text(encoding="utf-8").strip())
    except Exception:
        return None

    if expire_ts < time.time():
        return None
    return file_path


def _write_cache(url: str, source: Path) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_file_path(url)
    meta_path = _cache_meta_path(url)
    cache_path.write_bytes(source.read_bytes())
    expire_ts = time.time() + _CACHE_TTL_SECONDS
    meta_path.write_text(str(expire_ts), encoding="utf-8")
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
            return cached

    tmp_path = await download_media_to_temp(
        url=url,
        timeout_seconds=timeout_seconds,
        proxy=proxy,
    )
    try:
        async with _cache_io_lock:
            # Another task may have filled cache while we were downloading.
            cached = _read_cache(url)
            if cached is not None:
                return cached
            return _write_cache(url, tmp_path)
    finally:
        safe_unlink(tmp_path)
