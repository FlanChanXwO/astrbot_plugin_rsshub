"""卡片 HTML/PNG 分阶段渲染服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ...domain.entities.push_history import PushHistory
from ...domain.repositories.push_history_repository import PushHistoryRepository
from ...infrastructure.rendering.card_artifacts import CardArtifactStore
from ...infrastructure.templates.rendering import (
    CardTemplateService,
    CardTemplateSnapshot,
)


class HtmlImageRenderer(Protocol):
    """将已经完成 Jinja 渲染的 HTML 转成 PNG。"""

    async def render(self, html: str) -> bytes:
        """返回 PNG 字节。"""
        ...


@dataclass(frozen=True, slots=True)
class CardRenderResult:
    """一个可供发送端复用的完整卡片产物。"""

    html_ref: str
    png_ref: str
    png_path: Path


class CardRenderer:
    """逐阶段固化 HTML/PNG，并从历史引用恢复重试。"""

    def __init__(
        self,
        *,
        template_service: CardTemplateService,
        artifact_store: CardArtifactStore,
        image_renderer: HtmlImageRenderer,
        history_repository: PushHistoryRepository,
    ) -> None:
        self._template_service = template_service
        self._artifact_store = artifact_store
        self._image_renderer = image_renderer
        self._history_repository = history_repository

    async def render(
        self,
        history: PushHistory,
        snapshot: CardTemplateSnapshot,
        context: dict[str, Any],
    ) -> CardRenderResult:
        """补齐缺失阶段；已有受控引用绝不重复生成。"""
        if history.id is None:
            raise ValueError("卡片渲染要求已持久化的历史记录")
        if history.output_kind != "card":
            raise ValueError("CardRenderer 只能处理 card 输出")

        source_context = dict(history.source_context or {})
        raw_references = source_context.get("card_artifacts")
        references = dict(raw_references) if isinstance(raw_references, dict) else {}

        html_ref = references.get("html")
        if isinstance(html_ref, str):
            html = self._artifact_store.read_html(html_ref)
        else:
            html = self._template_service.render(snapshot, context)
            html_ref = self._artifact_store.write_html(history.id, html)
            references["html"] = html_ref
            await self._checkpoint(history, source_context, references)

        png_ref = references.get("png")
        if not isinstance(png_ref, str):
            image = await self._image_renderer.render(html)
            png_ref = self._artifact_store.write_png(history.id, image)
            references["png"] = png_ref
            await self._checkpoint(history, source_context, references)

        return CardRenderResult(
            html_ref=html_ref,
            png_ref=png_ref,
            png_path=self._artifact_store.path(png_ref),
        )

    async def _checkpoint(
        self,
        history: PushHistory,
        source_context: dict[str, Any],
        references: dict[str, Any],
    ) -> None:
        source_context["card_artifacts"] = dict(references)
        history.source_context = source_context
        await self._history_repository.save(history)
