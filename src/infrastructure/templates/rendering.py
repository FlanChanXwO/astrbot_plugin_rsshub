"""卡片模板快照与安全 Jinja 渲染。"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

from jinja2 import DictLoader, StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...domain.entities.card_rendering import CardRenderContext
from ...domain.entities.card_template import CardTemplateMetadata
from .repository import CardTemplatePackage


class CardTemplateRenderError(ValueError):
    """模板快照或渲染内容无效。"""


class CardTemplateSnapshot(BaseModel):
    """一次投递批次固化的完整模板包。"""

    model_config = ConfigDict(frozen=True)

    metadata: CardTemplateMetadata
    templates: dict[str, str] = Field(min_length=1)
    assets: dict[str, str] = Field(default_factory=dict)


class CardTemplateService:
    """固化模板包，并以受限 Jinja 环境渲染 HTML。"""

    _FILTER_NAMES = frozenset(
        {
            "abs",
            "capitalize",
            "default",
            "e",
            "escape",
            "first",
            "float",
            "forceescape",
            "format",
            "int",
            "join",
            "last",
            "length",
            "list",
            "lower",
            "replace",
            "reverse",
            "round",
            "safe",
            "slice",
            "sort",
            "string",
            "striptags",
            "title",
            "trim",
            "truncate",
            "upper",
            "urlencode",
            "wordcount",
        }
    )

    def snapshot(self, package: CardTemplatePackage) -> CardTemplateSnapshot:
        """读取模板包，创建不再依赖原目录的不可变快照。"""
        templates = {
            "template.html": (package.root / "template.html").read_text(
                encoding="utf-8"
            )
        }
        partials_dir = package.root / "partials"
        if partials_dir.is_dir():
            for path in self._package_files(partials_dir):
                templates[path.relative_to(package.root).as_posix()] = path.read_text(
                    encoding="utf-8"
                )
        assets: dict[str, str] = {}
        assets_dir = package.root / "assets"
        if assets_dir.is_dir():
            for path in self._package_files(assets_dir):
                assets[path.relative_to(assets_dir).as_posix()] = base64.b64encode(
                    path.read_bytes()
                ).decode("ascii")
        return CardTemplateSnapshot(
            metadata=package.metadata,
            templates=templates,
            assets=assets,
        )

    @staticmethod
    def _package_files(root: Path) -> list[Path]:
        files: list[Path] = []
        for path in root.rglob("*"):
            if path.is_symlink():
                raise CardTemplateRenderError(
                    f"模板包不允许符号链接: {path.relative_to(root).as_posix()}"
                )
            if path.is_file():
                files.append(path)
        return sorted(files)

    def render(
        self,
        snapshot: CardTemplateSnapshot,
        context: dict[str, Any],
    ) -> str:
        """使用默认转义和严格未定义变量策略渲染批次快照。"""
        environment = SandboxedEnvironment(
            loader=DictLoader(snapshot.templates),
            autoescape=True,
            undefined=StrictUndefined,
        )
        environment.globals.clear()
        environment.filters = {
            name: filter_function
            for name, filter_function in environment.filters.items()
            if name in self._FILTER_NAMES
        }

        def asset(name: str) -> str:
            normalized_name = str(name).replace("\\", "/")
            if (
                not normalized_name
                or normalized_name.startswith("/")
                or ".." in normalized_name.split("/")
                or normalized_name not in snapshot.assets
            ):
                raise CardTemplateRenderError(f"模板资源不存在: {name!r}")
            media_type = mimetypes.guess_type(normalized_name)[0]
            if media_type is None:
                media_type = "application/octet-stream"
            return f"data:{media_type};base64,{snapshot.assets[normalized_name]}"

        environment.globals["asset"] = asset
        try:
            render_context = json.loads(
                json.dumps(context, allow_nan=False, ensure_ascii=False)
            )
        except (TypeError, ValueError) as exc:
            raise CardTemplateRenderError(
                f"模板上下文必须是 JSON-safe 数据: {exc}"
            ) from exc
        if not isinstance(render_context, dict):
            raise CardTemplateRenderError("模板上下文必须是 JSON-safe 对象")
        try:
            render_context = CardRenderContext.model_validate(
                render_context
            ).model_dump(mode="json")
        except ValidationError as exc:
            raise CardTemplateRenderError(f"模板上下文无效: {exc}") from exc
        render_context["template"] = snapshot.metadata.model_dump(
            include={"id", "name", "version", "author"}, mode="json"
        )
        try:
            return environment.get_template("template.html").render(**render_context)
        except TemplateError as exc:
            raise CardTemplateRenderError(f"模板渲染失败: {exc}") from exc
