"""Source adapters for RSSHub Routes knowledge metadata and documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ...application.ports.route_knowledge import (
    RouteKnowledgeDocument,
    RouteKnowledgeFile,
    RouteKnowledgeManifest,
    RouteKnowledgeSource,
)
from ...infrastructure.config import RouteKnowledgeSettings
from ..fetcher.http import HttpFetcher

GITHUB_RAW_BASE_URL = (
    "https://raw.githubusercontent.com/FlanChanXwO/rsshub-routes-knowledgebase/main"
)


def build_route_knowledge_source(
    settings: RouteKnowledgeSettings,
    *,
    proxy: str = "",
) -> RouteKnowledgeSource:
    mode = (settings.source_mode or "mirror").strip().lower()
    if mode == "local":
        return LocalRouteKnowledgeSource(settings.local_source_dir)
    if mode == "github":
        return HttpRouteKnowledgeSource(
            GITHUB_RAW_BASE_URL,
            timeout=settings.timeout,
            proxy=proxy,
        )
    primary = HttpRouteKnowledgeSource(
        settings.source_base_url,
        timeout=settings.timeout,
        proxy=proxy,
    )
    if mode == "auto":
        fallback_base = settings.fallback_base_url or GITHUB_RAW_BASE_URL
        fallback = HttpRouteKnowledgeSource(
            fallback_base,
            timeout=settings.timeout,
            proxy=proxy,
        )
        return FallbackRouteKnowledgeSource(primary, fallback)
    return primary


class HttpRouteKnowledgeSource:
    """Read routes knowledge files from a raw HTTP base URL."""

    def __init__(self, base_url: str, *, timeout: int = 30, proxy: str = "") -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._fetcher = HttpFetcher(timeout=timeout, proxy=proxy)
        self._manifest: RouteKnowledgeManifest | None = None

    async def fetch_manifest(self) -> RouteKnowledgeManifest:
        content = await self._fetch_text("metadata.json")
        raw = json.loads(content)
        if not isinstance(raw, dict):
            raise ValueError("metadata.json 格式无效")
        manifest = normalize_route_manifest(raw, source=self._base_url)
        self._manifest = manifest
        return manifest

    async def fetch_document(self, file: RouteKnowledgeFile) -> RouteKnowledgeDocument:
        content = await self._fetch_text(file.path)
        return RouteKnowledgeDocument(
            path=file.path,
            content=content,
            sha256=file.sha256,
        )

    async def close(self) -> None:
        await self._fetcher.close()

    async def _fetch_text(self, relative_path: str) -> str:
        url = _join_raw_url(self._base_url, relative_path)
        result = await self._fetcher.fetch(url, verbose=False)
        if result.error or result.status != 200 or result.content is None:
            reason = str(result.error) if result.error else result.reason
            raise OSError(f"获取 Routes KB 文件失败: {relative_path} ({reason})")
        return result.content.decode("utf-8")


class LocalRouteKnowledgeSource:
    """Read routes knowledge files from a local directory."""

    def __init__(self, source_dir: str) -> None:
        if not source_dir:
            raise ValueError("route_knowledge.local_source_dir 不能为空")
        self._source_dir = Path(source_dir).expanduser().resolve()

    async def fetch_manifest(self) -> RouteKnowledgeManifest:
        metadata_path = self._source_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"metadata.json 不存在: {metadata_path}")
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("metadata.json 格式无效")
        return normalize_route_manifest(raw, source=str(self._source_dir))

    async def fetch_document(self, file: RouteKnowledgeFile) -> RouteKnowledgeDocument:
        path = _safe_join(self._source_dir, file.path)
        content = path.read_text(encoding="utf-8")
        return RouteKnowledgeDocument(
            path=file.path,
            content=content,
            sha256=file.sha256,
        )

    async def close(self) -> None:
        return None


class FallbackRouteKnowledgeSource:
    """Try a primary source first, then fallback to a secondary source."""

    def __init__(
        self,
        primary: RouteKnowledgeSource,
        fallback: RouteKnowledgeSource,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._active: RouteKnowledgeSource | None = None

    async def fetch_manifest(self) -> RouteKnowledgeManifest:
        try:
            manifest = await self._primary.fetch_manifest()
            self._active = self._primary
            return manifest
        except Exception:
            manifest = await self._fallback.fetch_manifest()
            self._active = self._fallback
            return manifest

    async def fetch_document(self, file: RouteKnowledgeFile) -> RouteKnowledgeDocument:
        source = self._active or self._primary
        try:
            return await source.fetch_document(file)
        except Exception:
            if source is self._fallback:
                raise
            self._active = self._fallback
            return await self._fallback.fetch_document(file)

    async def close(self) -> None:
        await self._primary.close()
        await self._fallback.close()


def normalize_route_manifest(
    raw: dict[str, Any],
    *,
    source: str = "",
) -> RouteKnowledgeManifest:
    """Normalize supported metadata.json shapes into a stable manifest."""
    files = tuple(
        sorted(
            (
                file
                for file in (_normalize_file(item) for item in _iter_file_items(raw))
                if file is not None and _is_importable_route_doc(file.path)
            ),
            key=lambda item: item.path,
        )
    )
    if not files:
        raise ValueError("metadata.json 未包含可导入的 routes markdown 文件")
    return RouteKnowledgeManifest(
        files=files,
        version=str(raw.get("version") or raw.get("commit") or ""),
        generated_at=str(
            raw.get("generated_at")
            or raw.get("generatedAt")
            or raw.get("updated_at")
            or ""
        ),
        source=source,
        raw=raw,
    )


def _iter_file_items(raw: dict[str, Any]):
    for key in ("files", "documents", "docs", "items"):
        value = raw.get(key)
        if isinstance(value, list):
            yield from value
            return
        if isinstance(value, dict):
            for path, item in value.items():
                if isinstance(item, dict):
                    yield {"path": path, **item}
                else:
                    yield {"path": path, "sha256": item}
            return
    for path, item in raw.items():
        if isinstance(item, dict) and ("sha256" in item or "sha" in item):
            yield {"path": path, **item}


def _normalize_file(item: Any) -> RouteKnowledgeFile | None:
    if not isinstance(item, dict):
        return None
    path = str(item.get("path") or item.get("name") or item.get("file") or "").strip()
    sha = str(item.get("sha256") or item.get("sha") or "").strip().lower()
    if sha.startswith("sha256:"):
        sha = sha.split(":", 1)[1]
    if not path or not sha:
        return None
    size = item.get("size")
    try:
        normalized_size = int(size) if size is not None else None
    except (TypeError, ValueError):
        normalized_size = None
    return RouteKnowledgeFile(
        path=path.lstrip("/"),
        sha256=sha,
        size=normalized_size,
        title=str(item.get("title") or ""),
        kind=str(item.get("kind") or item.get("type") or ""),
    )


def _is_importable_route_doc(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    if not normalized.endswith(".md"):
        return False
    if normalized == "index/namespaces.md":
        return True
    if normalized.startswith("index/") and "/" not in normalized[len("index/") :]:
        return True
    return normalized.startswith("docs/routes/")


def _join_raw_url(base_url: str, relative_path: str) -> str:
    encoded = "/".join(quote(part) for part in relative_path.strip("/").split("/"))
    return f"{base_url.rstrip('/')}/{encoded}"


def _safe_join(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"非法本地路径: {relative_path}") from exc
    return target
