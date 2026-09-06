"""卡片 HTML/PNG 分阶段持久化测试。"""

import asyncio
import threading
from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.application.services.card_renderer import CardRenderer
from astrbot_plugin_rsshub.src.domain.entities.card_template import CardTemplateMetadata
from astrbot_plugin_rsshub.src.domain.entities.push_history import PushHistory
from astrbot_plugin_rsshub.src.infrastructure.rendering.card_artifacts import (
    CardArtifactError,
    CardArtifactStore,
)
from astrbot_plugin_rsshub.src.infrastructure.templates.rendering import (
    CardTemplateService,
)
from astrbot_plugin_rsshub.src.infrastructure.templates.repository import (
    CardTemplatePackage,
)


class RecordingHistoryRepository:
    def __init__(self) -> None:
        self.saved: list[PushHistory] = []

    async def save(self, history: PushHistory) -> PushHistory:
        self.saved.append(history.model_copy(deep=True))
        return history


class FailingOnceImageRenderer:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.should_fail = True

    async def render(self, html: str) -> bytes:
        self.calls.append(html)
        if self.should_fail:
            raise RuntimeError("t2i offline")
        return b"png-result"


class EventBlockingTemplateService(CardTemplateService):
    def __init__(self, release: threading.Event) -> None:
        self.release = release
        self.event_loop_progressed_during_render = False

    def render(self, snapshot, context) -> str:
        # 仅防止回归实现永久挂住测试；生产渲染链路没有固定超时。
        self.event_loop_progressed_during_render = self.release.wait(timeout=0.2)
        return "<h1>rendered</h1>"


def _snapshot(tmp_path: Path):
    tmp_path.mkdir()
    (tmp_path / "template.html").write_text(
        "<h1>{{ document.text }}</h1>", encoding="utf-8"
    )
    package = CardTemplatePackage(
        metadata=CardTemplateMetadata(
            id="astrbot_plugin_rsshub_card_test",
            name="Test",
            version="1.0.0",
            author="Tester",
            description="Test template",
            repository="https://example.com/template",
            targets=["feed"],
        ),
        root=tmp_path,
        origin="installed",
    )
    return CardTemplateService().snapshot(package)


def _render_context(text: str) -> dict[str, object]:
    return {
        "source": {"type": "feed", "owner_id": 7},
        "feed": {"id": 1, "title": "News", "link": "https://example.com/feed"},
        "bundle": None,
        "feeds": [],
        "entries": [],
        "document": {"text": text, "rss_xml": ""},
        "meta": {"batch_id": 1, "rendered_at": "2026-08-24T00:00:00+00:00"},
    }


@pytest.mark.asyncio
async def test_card_renderer_reuses_completed_artifact_stages_after_failure(
    tmp_path: Path,
) -> None:
    history = PushHistory(
        id=42,
        user_id="user",
        output_kind="card",
        source_context={"source": {"type": "feed", "owner_id": 7}},
    )
    repository = RecordingHistoryRepository()
    image_renderer = FailingOnceImageRenderer()
    renderer = CardRenderer(
        template_service=CardTemplateService(),
        artifact_store=CardArtifactStore(tmp_path / "artifacts"),
        image_renderer=image_renderer,
        history_repository=repository,
    )
    snapshot = _snapshot(tmp_path / "package")

    with pytest.raises(RuntimeError, match="t2i offline"):
        await renderer.render(history, snapshot, _render_context("hello"))

    assert history.source_context is not None
    assert history.source_context["card_artifacts"] == {"html": "42/card.html"}
    assert repository.saved[-1].source_context == history.source_context

    image_renderer.should_fail = False
    result = await renderer.render(history, snapshot, {})

    assert image_renderer.calls == ["<h1>hello</h1>", "<h1>hello</h1>"]
    assert result.html_ref == "42/card.html"
    assert result.png_ref == "42/card.png"
    assert result.png_path.read_bytes() == b"png-result"

    image_renderer.should_fail = True
    repeated = await renderer.render(history, snapshot, {})
    assert repeated == result
    assert len(image_renderer.calls) == 2


@pytest.mark.asyncio
async def test_card_renderer_keeps_event_loop_responsive_during_template_render(
    tmp_path: Path,
) -> None:
    release = threading.Event()
    template_service = EventBlockingTemplateService(release)
    image_renderer = FailingOnceImageRenderer()
    image_renderer.should_fail = False
    renderer = CardRenderer(
        template_service=template_service,
        artifact_store=CardArtifactStore(tmp_path / "artifacts"),
        image_renderer=image_renderer,
        history_repository=RecordingHistoryRepository(),
    )
    history = PushHistory(id=43, user_id="user", output_kind="card")

    async def advance_event_loop() -> None:
        await asyncio.sleep(0)
        release.set()

    heartbeat = asyncio.create_task(advance_event_loop())
    result = await renderer.render(history, _snapshot(tmp_path / "package"), {})
    await heartbeat

    assert template_service.event_loop_progressed_during_render
    assert result.png_path.read_bytes() == b"png-result"


def test_card_artifact_store_rejects_symlink_escape(tmp_path: Path) -> None:
    storage = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    storage.mkdir()
    outside.mkdir()
    (storage / "42").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CardArtifactError, match="产物目录"):
        CardArtifactStore(storage).write_html(42, "secret")

    assert not (outside / "card.html").exists()


def test_card_artifact_store_rejects_symlinked_storage_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    storage = tmp_path / "artifacts"
    storage.symlink_to(outside, target_is_directory=True)

    with pytest.raises(CardArtifactError, match="产物根目录"):
        CardArtifactStore(storage).write_html(42, "secret")

    assert not (outside / "42" / "card.html").exists()
