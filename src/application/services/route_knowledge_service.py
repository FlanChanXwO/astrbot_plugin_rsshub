"""RSSHub Routes knowledge-base synchronization service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...infrastructure.config import RouteKnowledgeSettings
from ...infrastructure.utils import get_logger
from ..ports.route_knowledge import (
    RouteKnowledgeDocument,
    RouteKnowledgeFile,
    RouteKnowledgeManifest,
    RouteKnowledgeRepository,
    RouteKnowledgeSource,
)

MANAGED_DOC_PREFIX = "rsshub-routes/"
logger = get_logger()


@dataclass(frozen=True)
class RouteKnowledgeSyncPlan:
    """Diff between source manifest, local managed manifest and KB actual state."""

    added: tuple[RouteKnowledgeFile, ...] = field(default_factory=tuple)
    updated: tuple[RouteKnowledgeFile, ...] = field(default_factory=tuple)
    deleted: tuple[str, ...] = field(default_factory=tuple)
    unchanged: tuple[RouteKnowledgeFile, ...] = field(default_factory=tuple)
    reconciled: tuple[RouteKnowledgeFile, ...] = field(default_factory=tuple)

    @property
    def changed_count(self) -> int:
        return len(self.added) + len(self.updated) + len(self.deleted)


@dataclass(frozen=True)
class RouteKnowledgeTaskStatus:
    """Current or last background sync task status."""

    task_id: str = ""
    status: str = "idle"
    kb_name: str = ""
    started_at: str = ""
    finished_at: str = ""
    message: str = ""
    error: str = ""
    added: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    reconciled: int = 0
    skipped: int = 0
    processed: int = 0
    total: int = 0
    current_path: str = ""


@dataclass(frozen=True)
class RouteKnowledgeStatus:
    """Routes KB sync status snapshot."""

    kb_name: str
    kb_id: str = ""
    source_version: str = ""
    source_generated_at: str = ""
    last_sync_at: str = ""
    managed_files: int = 0
    kb_docs: int = 0
    last_error: str = ""
    task: RouteKnowledgeTaskStatus = field(default_factory=RouteKnowledgeTaskStatus)


@dataclass(frozen=True)
class RouteKnowledgeSyncResult:
    """Completed sync result."""

    success: bool
    message: str
    task_id: str
    plan: RouteKnowledgeSyncPlan
    uploaded: int = 0
    deleted: int = 0
    skipped: int = 0
    reconciled: int = 0
    kb_id: str = ""


class RouteKnowledgeSyncAlreadyRunning(RuntimeError):
    """Raised when a sync is requested while another sync is running."""


class RouteKnowledgeSyncService:
    """Synchronize RSSHub route markdown files into an AstrBot knowledge base."""

    def __init__(
        self,
        *,
        settings: RouteKnowledgeSettings,
        source: RouteKnowledgeSource,
        repository: RouteKnowledgeRepository,
        state_dir: Path,
    ) -> None:
        self._settings = settings
        self._source = source
        self._repository = repository
        self._state_dir = state_dir
        self._manifest_path = state_dir / "manifest.json"
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[RouteKnowledgeSyncResult] | None = None
        self._task_status = RouteKnowledgeTaskStatus(kb_name=settings.kb_name)

    async def close(self) -> None:
        await self._source.close()

    async def ensure_kb(self) -> str:
        return await self._repository.ensure_kb()

    def get_task_status(self) -> RouteKnowledgeTaskStatus:
        return self._task_status

    async def get_status(self) -> RouteKnowledgeStatus:
        local = self._load_local_manifest()
        kb_id = ""
        kb_docs = 0
        last_error = ""
        try:
            kb_id = await self._repository.ensure_kb()
            kb_docs = len(await self._repository.list_documents())
        except Exception as exc:
            last_error = str(exc)
        if self._task_status.error:
            last_error = self._task_status.error
        return RouteKnowledgeStatus(
            kb_name=self._settings.kb_name,
            kb_id=kb_id,
            source_version=str(local.get("version", "") or ""),
            source_generated_at=str(local.get("generated_at", "") or ""),
            last_sync_at=str(local.get("last_sync_at", "") or ""),
            managed_files=len(_local_files_map(local)),
            kb_docs=kb_docs,
            last_error=last_error,
            task=self._task_status,
        )

    async def start_sync(self) -> RouteKnowledgeTaskStatus:
        if self._task is not None and not self._task.done():
            raise RouteKnowledgeSyncAlreadyRunning("Routes KB 同步任务正在运行")
        task_id = uuid.uuid4().hex[:12]
        self._task_status = RouteKnowledgeTaskStatus(
            task_id=task_id,
            status="queued",
            kb_name=self._settings.kb_name,
            started_at=_now_iso(),
            message="等待同步",
        )
        self._task = asyncio.create_task(self.sync(task_id=task_id))
        return self._task_status

    async def sync(self, *, task_id: str | None = None) -> RouteKnowledgeSyncResult:
        if self._lock.locked():
            raise RouteKnowledgeSyncAlreadyRunning("Routes KB 同步任务正在运行")
        async with self._lock:
            effective_task_id = task_id or uuid.uuid4().hex[:12]
            started_at = _now_iso()
            logger.info(
                "Routes KB 同步开始: task_id=%s kb_name=%s",
                effective_task_id,
                self._settings.kb_name,
            )
            self._task_status = RouteKnowledgeTaskStatus(
                task_id=effective_task_id,
                status="running",
                kb_name=self._settings.kb_name,
                started_at=started_at,
                message="读取 metadata.json",
            )
            try:
                kb_id = await self._repository.ensure_kb()
                logger.info(
                    "Routes KB 已确认知识库: task_id=%s kb_id=%s",
                    effective_task_id,
                    kb_id or "-",
                )
                source_manifest = await self._source.fetch_manifest()
                logger.info(
                    "Routes KB 已读取源 manifest: task_id=%s version=%s files=%d",
                    effective_task_id,
                    source_manifest.version,
                    len(source_manifest.files),
                )
                local_manifest = self._load_local_manifest()
                # 对账 KB 已有文档，避免重载后从 0 重新下载
                kb_docs = await self._repository.list_documents()
                kb_doc_names = {doc.doc_name for doc in kb_docs}
                plan = build_sync_plan(
                    source_manifest,
                    local_manifest,
                    kb_doc_names,
                )
                # reconciled 文档无需下载/上传，但仍需修复 local manifest
                total = len(plan.added) + len(plan.updated) + len(plan.deleted)
                logger.info(
                    "Routes KB 同步计划: task_id=%s added=%d updated=%d deleted=%d unchanged=%d reconciled=%d total=%d",
                    effective_task_id,
                    len(plan.added),
                    len(plan.updated),
                    len(plan.deleted),
                    len(plan.unchanged),
                    len(plan.reconciled),
                    total,
                )
                self._task_status = _replace_task(
                    self._task_status,
                    message="同步文档",
                    added=len(plan.added),
                    updated=len(plan.updated),
                    deleted=len(plan.deleted),
                    unchanged=len(plan.unchanged),
                    reconciled=len(plan.reconciled),
                    skipped=0,
                    total=total,
                )

                # 复用对账阶段已获取的 KB 文档列表
                docs_by_name = {doc.doc_name: doc.doc_id for doc in kb_docs}
                uploaded_count = 0
                deleted_count = 0
                skipped_count = 0
                reconciled_count = 0
                processed = 0

                # 在内存中维护 files_map，sync 结束后一次性落盘
                files_map = _local_files_map(local_manifest)

                for path in plan.deleted:
                    doc_name = managed_doc_name(path)
                    doc_id = docs_by_name.get(doc_name)
                    self._task_status = _replace_task(
                        self._task_status,
                        current_path=path,
                        processed=processed,
                        message=f"删除文档: {path}",
                    )
                    logger.debug(
                        "Routes KB 同步进度: task_id=%s %d/%d 删除 %s",
                        effective_task_id,
                        processed + 1,
                        total or 1,
                        path,
                    )
                    if doc_id:
                        await self._repository.delete_document(doc_id)
                        deleted_count += 1
                        files_map.pop(path, None)
                    processed += 1
                    self._task_status = _replace_task(
                        self._task_status, processed=processed
                    )

                for file in (*plan.added, *plan.updated):
                    doc_name = managed_doc_name(file.path)
                    old_doc_id = docs_by_name.get(doc_name)
                    self._task_status = _replace_task(
                        self._task_status,
                        current_path=file.path,
                        processed=processed,
                        message=f"下载文档: {file.path}",
                    )
                    logger.debug(
                        "Routes KB 同步进度: task_id=%s %d/%d 上传 %s",
                        effective_task_id,
                        processed + 1,
                        total or 1,
                        file.path,
                    )
                    document = await self._source.fetch_document(file)
                    _validate_document_hash(file, document)
                    try:
                        self._task_status = _replace_task(
                            self._task_status,
                            current_path=file.path,
                            processed=processed,
                            message=f"上传文档: {file.path}",
                        )
                        if old_doc_id:
                            await self._repository.delete_document(old_doc_id)
                        await self._repository.upload_document(document)
                        uploaded_count += 1
                        # 仅在上传成功后更新 manifest 快照，避免失败文档被误记为已同步。
                        files_map[file.path] = file.sha256
                    except Exception as exc:
                        skipped_count += 1
                        logger.exception(
                            "Routes KB 文档上传失败，已跳过: task_id=%s path=%s error=%s",
                            effective_task_id,
                            file.path,
                            exc,
                        )
                        self._task_status = _replace_task(
                            self._task_status,
                            current_path=file.path,
                            skipped=skipped_count,
                            message=f"跳过文档: {file.path}",
                        )
                    processed += 1
                    self._task_status = _replace_task(
                        self._task_status, processed=processed
                    )

                # reconciled 文档已在 KB 但 local manifest 丢失了它们的记录，补回
                for file in plan.reconciled:
                    files_map[file.path] = file.sha256
                    reconciled_count += 1

                # 一次性将内存中的 files_map 与元数据写入 local manifest
                self._flush_local_manifest(files_map, source_manifest)
                message = (
                    "Routes KB 同步完成: "
                    f"新增 {len(plan.added)}, 更新 {len(plan.updated)}, "
                    f"删除 {deleted_count}, 跳过 {skipped_count}, "
                    f"对账修复 {reconciled_count}, 未变更 {len(plan.unchanged)}"
                )
                finished_at = _now_iso()
                logger.info(
                    "Routes KB 同步完成: task_id=%s kb_id=%s 新增=%d 更新=%d 删除=%d 跳过=%d 对账=%d 未变更=%d",
                    effective_task_id,
                    kb_id or "-",
                    len(plan.added),
                    len(plan.updated),
                    deleted_count,
                    skipped_count,
                    reconciled_count,
                    len(plan.unchanged),
                )
                self._task_status = _replace_task(
                    self._task_status,
                    status="completed",
                    finished_at=finished_at,
                    message=message,
                    current_path="",
                    processed=total,
                    skipped=skipped_count,
                    reconciled=reconciled_count,
                )
                return RouteKnowledgeSyncResult(
                    success=True,
                    message=message,
                    task_id=effective_task_id,
                    plan=plan,
                    uploaded=uploaded_count,
                    deleted=deleted_count,
                    skipped=skipped_count,
                    reconciled=reconciled_count,
                    kb_id=kb_id,
                )
            except Exception as exc:
                logger.exception(
                    "Routes KB 同步失败: task_id=%s kb_name=%s error=%s",
                    effective_task_id,
                    self._settings.kb_name,
                    exc,
                )
                self._task_status = _replace_task(
                    self._task_status,
                    status="failed",
                    finished_at=_now_iso(),
                    error=str(exc),
                    message="Routes KB 同步失败",
                )
                empty_plan = RouteKnowledgeSyncPlan()
                return RouteKnowledgeSyncResult(
                    success=False,
                    message=f"Routes KB 同步失败: {exc}",
                    task_id=effective_task_id,
                    plan=empty_plan,
                )

    def _load_local_manifest(self) -> dict[str, Any]:
        if not self._manifest_path.exists():
            return {}
        try:
            raw = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _flush_local_manifest(
        self,
        files_map: dict[str, str],
        manifest: RouteKnowledgeManifest,
    ) -> None:
        """一次性将内存中的 files_map 与元数据写入 local manifest。"""
        files_list = [
            {"path": p, "sha256": sha} for p, sha in sorted(files_map.items())
        ]
        self._state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": manifest.version,
            "generated_at": manifest.generated_at,
            "source": manifest.source,
            "last_sync_at": _now_iso(),
            "files": files_list,
        }
        self._manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def build_sync_plan(
    source_manifest: RouteKnowledgeManifest,
    local_manifest: dict[str, Any],
    kb_doc_names: set[str] | None = None,
) -> RouteKnowledgeSyncPlan:
    """Build an incremental sync plan by comparing path + sha256.

    三路归并：source manifest（远端真值）、local manifest（上次同步快照）、
    kb_doc_names（KB 中实际存在的文档名集合）。
    当 local manifest 缺失或过期时，KB 对账能把已上传的文档从 added 降级为
    reconciled，避免重载插件后从 0 重新下载。
    """
    source_files = {file.path: file for file in source_manifest.files}
    local_files = _local_files_map(local_manifest)
    # KB 中已有文档的相对路径集合（去掉 MANAGED_DOC_PREFIX）
    kb_paths: set[str] = set()
    if kb_doc_names:
        prefix = MANAGED_DOC_PREFIX
        for name in kb_doc_names:
            if name.startswith(prefix):
                kb_paths.add(name[len(prefix) :].lstrip("/"))

    added: list[RouteKnowledgeFile] = []
    updated: list[RouteKnowledgeFile] = []
    unchanged: list[RouteKnowledgeFile] = []
    reconciled: list[RouteKnowledgeFile] = []

    for path, file in source_files.items():
        local_sha = local_files.get(path)
        in_kb = path in kb_paths
        if local_sha is not None and local_sha == file.sha256:
            # local manifest 与 source 一致：无需任何操作
            unchanged.append(file)
        elif in_kb and local_sha is None:
            # KB 有文档、local manifest 缺记录——重载后典型场景，对账修复
            reconciled.append(file)
        elif in_kb and local_sha != file.sha256:
            # KB 有文档，但 local manifest 记录的 sha 与当前 source 不一致。
            logger.info(
                "Routes KB 对账: %s local manifest 记录的 sha=%s "
                "与当前 source sha=%s 不一致（KB 中已存在文档），"
                "标记 reconciled 但未重新下载",
                path,
                local_sha or "(local manifest 无记录)",
                file.sha256,
            )
            reconciled.append(file)
        elif not in_kb and local_sha is not None and local_sha != file.sha256:
            # 不在 KB 但 local sha 过期——需要更新
            updated.append(file)
        elif not in_kb and local_sha is None:
            # 不在 KB 且 local 无记录——全新文档
            added.append(file)
        else:
            # 不在 KB，local sha 与 source 一致（但 KB 实际缺失）
            # local 说已同步但 KB 实际没有，需要补传
            added.append(file)

    deleted = sorted(path for path in local_files if path not in source_files)
    return RouteKnowledgeSyncPlan(
        added=tuple(sorted(added, key=lambda item: item.path)),
        updated=tuple(sorted(updated, key=lambda item: item.path)),
        deleted=tuple(deleted),
        unchanged=tuple(sorted(unchanged, key=lambda item: item.path)),
        reconciled=tuple(sorted(reconciled, key=lambda item: item.path)),
    )


def managed_doc_name(path: str) -> str:
    return f"{MANAGED_DOC_PREFIX}{path.strip().lstrip('/')}"


def _validate_document_hash(
    file: RouteKnowledgeFile, document: RouteKnowledgeDocument
) -> None:
    digest = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    if digest != file.sha256:
        raise ValueError(
            f"sha256 校验失败: {file.path} expected={file.sha256} actual={digest}"
        )


def _local_files_map(local_manifest: dict[str, Any]) -> dict[str, str]:
    raw_files = local_manifest.get("files", [])
    files: dict[str, str] = {}
    if isinstance(raw_files, dict):
        iterable = raw_files.items()
        for path, item in iterable:
            if isinstance(item, dict):
                sha = item.get("sha256") or item.get("sha")
            else:
                sha = item
            if path and sha:
                files[str(path)] = str(sha)
        return files
    if isinstance(raw_files, list):
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            path = item.get("path") or item.get("name")
            sha = item.get("sha256") or item.get("sha")
            if path and sha:
                files[str(path)] = str(sha)
    return files


def _replace_task(
    current: RouteKnowledgeTaskStatus, **updates: Any
) -> RouteKnowledgeTaskStatus:
    data = asdict(current)
    data.update(updates)
    return RouteKnowledgeTaskStatus(**data)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
