from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest
from astrbot_plugin_rsshub.src.application.ports.route_knowledge import (
    RouteKnowledgeDocument,
    RouteKnowledgeDocumentRecord,
    RouteKnowledgeFile,
    RouteKnowledgeManifest,
)
from astrbot_plugin_rsshub.src.application.services.route_knowledge_service import (
    RouteKnowledgeSyncAlreadyRunning,
    RouteKnowledgeSyncService,
    build_sync_plan,
    managed_doc_name,
)
from astrbot_plugin_rsshub.src.infrastructure.config import RouteKnowledgeSettings


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class _StoredDoc:
    doc_id: str
    doc_name: str
    content: str


class _FakeSource:
    def __init__(self, files: dict[str, str]):
        self.files = files
        self.closed = False

    async def fetch_manifest(self):
        return RouteKnowledgeManifest(
            files=tuple(
                RouteKnowledgeFile(path=path, sha256=_sha(content))
                for path, content in self.files.items()
            ),
            version="v1",
            generated_at="2026-05-19T00:00:00Z",
        )

    async def fetch_document(self, file):
        return RouteKnowledgeDocument(
            path=file.path,
            content=self.files[file.path],
            sha256=file.sha256,
        )

    async def close(self):
        self.closed = True


class _BadHashSource(_FakeSource):
    async def fetch_document(self, file):
        return RouteKnowledgeDocument(
            path=file.path,
            content="tampered",
            sha256=file.sha256,
        )


class _FakeRepository:
    def __init__(self):
        self.docs: dict[str, _StoredDoc] = {}
        self.deleted: list[str] = []
        self.uploaded: list[str] = []

    async def ensure_kb(self):
        return "kb-1"

    async def list_documents(self):
        return [
            RouteKnowledgeDocumentRecord(doc_id=doc.doc_id, doc_name=doc.doc_name)
            for doc in self.docs.values()
        ]

    async def delete_document(self, doc_id: str):
        self.deleted.append(doc_id)
        self.docs.pop(doc_id, None)

    async def upload_document(self, document):
        doc_id = f"doc-{len(self.docs) + len(self.uploaded) + 1}"
        doc_name = managed_doc_name(document.path)
        self.docs[doc_id] = _StoredDoc(doc_id, doc_name, document.content)
        self.uploaded.append(doc_name)
        return doc_id


class _FlakyUploadRepository(_FakeRepository):
    def __init__(self, fail_path: str):
        super().__init__()
        self.fail_path = fail_path

    async def upload_document(self, document):
        if document.path == self.fail_path:
            raise RuntimeError("boom")
        return await super().upload_document(document)


def test_build_sync_plan_detects_add_update_delete_unchanged():
    source = RouteKnowledgeManifest(
        files=(
            RouteKnowledgeFile(path="index/namespaces.md", sha256="a"),
            RouteKnowledgeFile(path="docs/routes/foo.md", sha256="b2"),
            RouteKnowledgeFile(path="docs/routes/bar.md", sha256="c"),
        )
    )
    local = {
        "files": [
            {"path": "index/namespaces.md", "sha256": "a"},
            {"path": "docs/routes/foo.md", "sha256": "b1"},
            {"path": "docs/routes/deleted.md", "sha256": "d"},
        ]
    }

    plan = build_sync_plan(source, local, kb_doc_names=None)

    assert [item.path for item in plan.added] == ["docs/routes/bar.md"]
    assert [item.path for item in plan.updated] == ["docs/routes/foo.md"]
    assert plan.deleted == ("docs/routes/deleted.md",)
    assert [item.path for item in plan.unchanged] == ["index/namespaces.md"]
    assert plan.reconciled == ()


def test_build_sync_plan_reconciles_kb_existing_docs_without_local_manifest():
    """KB 中已有文档但 local manifest 丢失——插件重载后典型场景。"""
    source = RouteKnowledgeManifest(
        files=(
            RouteKnowledgeFile(path="index/namespaces.md", sha256="a"),
            RouteKnowledgeFile(path="docs/routes/foo.md", sha256="b2"),
            RouteKnowledgeFile(path="docs/routes/new.md", sha256="e"),
        )
    )
    # local manifest 为空（重载后丢失）
    local: dict = {}
    # KB 中已有这两个文档
    kb_doc_names = {
        managed_doc_name("index/namespaces.md"),
        managed_doc_name("docs/routes/foo.md"),
    }

    plan = build_sync_plan(source, local, kb_doc_names=kb_doc_names)

    # KB 已有但 local 缺记录 → reconciled（无需重新下载上传）
    assert [item.path for item in plan.reconciled] == [
        "docs/routes/foo.md",
        "index/namespaces.md",
    ]
    # KB 中没有且 local 也没有 → added
    assert [item.path for item in plan.added] == ["docs/routes/new.md"]
    assert plan.updated == ()
    assert plan.deleted == ()
    assert plan.unchanged == ()


def test_build_sync_plan_reconciles_kb_docs_with_stale_local_sha():
    """KB 有文档但 local sha 与 source 不一致——对账修复，不强制重新下载。"""
    source = RouteKnowledgeManifest(
        files=(RouteKnowledgeFile(path="docs/routes/foo.md", sha256="b2"),)
    )
    local = {
        "files": [
            {"path": "docs/routes/foo.md", "sha256": "old"},
        ]
    }
    kb_doc_names = {managed_doc_name("docs/routes/foo.md")}

    plan = build_sync_plan(source, local, kb_doc_names=kb_doc_names)

    # KB 有文档，local sha 过期但 KB 中实际已有→对账修复
    assert [item.path for item in plan.reconciled] == ["docs/routes/foo.md"]
    assert plan.updated == ()
    assert plan.added == ()


@pytest.mark.asyncio
async def test_sync_deletes_then_uploads_changed_documents(tmp_path):
    source = _FakeSource(
        {
            "index/namespaces.md": "# Namespaces",
            "docs/routes/foo.md": "# Foo v2",
        }
    )
    repo = _FakeRepository()
    old_doc_id = "old-doc"
    repo.docs[old_doc_id] = _StoredDoc(
        old_doc_id,
        managed_doc_name("docs/routes/foo.md"),
        "# Foo v1",
    )
    # deleted 也在 KB 中，确保可以物理删除
    deleted_doc_id = "deleted-doc"
    repo.docs[deleted_doc_id] = _StoredDoc(
        deleted_doc_id,
        managed_doc_name("docs/routes/deleted.md"),
        "# deleted",
    )
    (tmp_path / "manifest.json").write_text(
        '{"files":[{"path":"docs/routes/foo.md","sha256":"old"},'
        '{"path":"docs/routes/deleted.md","sha256":"gone"}]}',
        encoding="utf-8",
    )
    service = RouteKnowledgeSyncService(
        settings=RouteKnowledgeSettings(),
        source=source,
        repository=repo,
        state_dir=tmp_path,
    )

    result = await service.sync(task_id="task-1")

    assert result.success is True
    # foo.md 已在 KB 中但 local sha 过期 → reconciled（对账修复），不重新上传
    assert result.reconciled == 1
    assert managed_doc_name("docs/routes/foo.md") not in repo.uploaded
    assert managed_doc_name("index/namespaces.md") in repo.uploaded
    # deleted.md 被 source 移除，从 KB 物理删除
    assert deleted_doc_id in repo.deleted
    status = service.get_task_status()
    assert status.status == "completed"
    assert status.added == 1
    assert status.reconciled == 1
    assert status.deleted == 1


@pytest.mark.asyncio
async def test_sync_skips_failed_document_and_continues(tmp_path):
    source = _FakeSource(
        {
            "docs/routes/a.md": "# A",
            "docs/routes/b.md": "# B",
        }
    )
    repo = _FlakyUploadRepository("docs/routes/a.md")
    service = RouteKnowledgeSyncService(
        settings=RouteKnowledgeSettings(),
        source=source,
        repository=repo,
        state_dir=tmp_path,
    )

    result = await service.sync(task_id="task-1")

    assert result.success is True
    assert result.skipped == 1
    assert managed_doc_name("docs/routes/b.md") in repo.uploaded
    assert managed_doc_name("docs/routes/a.md") not in repo.uploaded
    assert service.get_task_status().skipped == 1


@pytest.mark.asyncio
async def test_sync_rejects_sha256_mismatch(tmp_path):
    source = _BadHashSource({"docs/routes/foo.md": "# Foo"})
    repo = _FakeRepository()
    service = RouteKnowledgeSyncService(
        settings=RouteKnowledgeSettings(),
        source=source,
        repository=repo,
        state_dir=tmp_path,
    )

    result = await service.sync(task_id="task-1")

    assert result.success is False
    assert "sha256 校验失败" in result.message
    assert service.get_task_status().status == "failed"
    assert repo.uploaded == []


@pytest.mark.asyncio
async def test_sync_lock_rejects_parallel_runs(tmp_path):
    source = _FakeSource({"docs/routes/foo.md": "# Foo"})
    repo = _FakeRepository()
    service = RouteKnowledgeSyncService(
        settings=RouteKnowledgeSettings(),
        source=source,
        repository=repo,
        state_dir=tmp_path,
    )

    await service._lock.acquire()
    try:
        with pytest.raises(RouteKnowledgeSyncAlreadyRunning):
            await service.sync(task_id="task-2")
    finally:
        service._lock.release()


@pytest.mark.asyncio
async def test_sync_reconciles_kb_existing_docs_on_reload(tmp_path):
    """插件重载后 local manifest 丢失，但 KB 中已有文档——对账修复，不重复下载。"""
    source_files = {
        "index/namespaces.md": "# Namespaces",
        "docs/routes/foo.md": "# Foo",
        "docs/routes/new.md": "# New",
    }
    source = _FakeSource(source_files)
    repo = _FakeRepository()
    # 模拟 KB 中已有这两个文档（重载前上传的）
    for path in ("index/namespaces.md", "docs/routes/foo.md"):
        doc_id = f"existing-{path}"
        repo.docs[doc_id] = _StoredDoc(
            doc_id,
            managed_doc_name(path),
            source_files[path],
        )
    # 不写 manifest.json——模拟重载后丢失
    service = RouteKnowledgeSyncService(
        settings=RouteKnowledgeSettings(),
        source=source,
        repository=repo,
        state_dir=tmp_path,
    )

    result = await service.sync(task_id="task-reload")

    assert result.success is True
    # 已在 KB 的文档不重新上传（对账修复）
    assert result.reconciled == 2
    # 只有新文档需要上传
    assert result.uploaded == 1
    assert managed_doc_name("docs/routes/new.md") in repo.uploaded
    # reconciled 的文档不应被下载/上传
    assert managed_doc_name("index/namespaces.md") not in repo.uploaded
    assert managed_doc_name("docs/routes/foo.md") not in repo.uploaded
    # 同步完成后 local manifest 应包含所有文件的记录
    import json

    local_data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    local_files = {item["path"]: item["sha256"] for item in local_data.get("files", [])}
    assert "docs/routes/new.md" in local_files
    assert "index/namespaces.md" in local_files
    assert "docs/routes/foo.md" in local_files
