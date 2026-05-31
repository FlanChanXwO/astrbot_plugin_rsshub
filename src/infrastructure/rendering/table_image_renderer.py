"""Lightweight HTML table to PNG renderer based on BeautifulSoup and Pillow."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from bs4 import BeautifulSoup
from bs4.element import Tag
from PIL import Image, ImageDraw, ImageFont

from ...domain.entities.content_types import (
    GENERATED_MEDIA_TABLE_KIND,
    build_generated_media_url,
    parse_generated_media_url,
)
from ..utils.logger import get_logger
from ..utils.paths import get_plugin_cache_dir
from .font_manager import get_runtime_font_dir

logger = get_logger()

TABLE_FONT_PATH_ENV = "RSSHUB_TABLE_FONT_PATH"
TABLE_FONT_DIR_ENV = "RSSHUB_TABLE_FONT_DIR"
TABLE_IMAGE_CACHE_PART = "table_images"
PLUGIN_FONT_DIR = Path(__file__).resolve().parents[3] / "assets" / "fonts"
FONT_FILE_SUFFIXES = (".ttf", ".otf", ".ttc")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def resolve_table_image_path(source_id: str) -> Path | None:
    """将表格生成媒体标识解析到插件 cache 内的 PNG 路径。"""
    parsed = parse_generated_media_url(source_id)
    if parsed is None:
        return None
    kind, digest = parsed
    if kind != GENERATED_MEDIA_TABLE_KIND or not _SHA256_RE.match(digest):
        return None
    return get_plugin_cache_dir(TABLE_IMAGE_CACHE_PART) / f"table_{digest}.png"


@dataclass(frozen=True)
class TableImageRenderResult:
    """Result for one rendered table image."""

    source_id: str
    path: Path
    digest: str
    reused: bool = False


@dataclass
class _TableCell:
    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    header: bool = False
    lines: list[str] = field(default_factory=list)


@dataclass
class _TableModel:
    caption: str
    cells: list[_TableCell]
    row_count: int
    col_count: int


class TableImageRenderer:
    """Render one semantic HTML table into a reusable PNG cache asset."""

    _BG = (249, 250, 251)
    _CARD_BG = (255, 255, 255)
    _HEADER_BG = (31, 41, 55)
    _HEADER_TEXT = (255, 255, 255)
    _BODY_TEXT = (31, 41, 55)
    _ZEBRA_BG = (243, 246, 250)
    _BORDER = (203, 213, 225)
    _CAPTION = (17, 24, 39)
    _warned_no_font = False

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir or get_plugin_cache_dir(TABLE_IMAGE_CACHE_PART)
        self._font_regular = self._load_font(size=24)
        self._font_header = self._load_font(size=24)
        self._font_caption = self._load_font(size=30)

    def render_table(self, table_html: str | Tag) -> TableImageRenderResult | None:
        """Render table HTML and return cache metadata.

        Empty or unparsable tables return None so the caller can preserve the
        existing plain-text fallback path.
        """
        if self._font_regular is None:
            logger.debug("表格图片渲染跳过：无可用 CJK 字体")
            return None
        model = self._parse_table(table_html)
        if model is None:
            return None

        digest = self._digest_model(model)
        source_id = build_generated_media_url(GENERATED_MEDIA_TABLE_KIND, digest)
        output_path = self._cache_dir / f"table_{digest}.png"
        if output_path.exists():
            return TableImageRenderResult(
                source_id=source_id,
                path=output_path,
                digest=digest,
                reused=True,
            )

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_name(
            f".{output_path.stem}.{os.getpid()}.{uuid4().hex}.tmp{output_path.suffix}"
        )
        try:
            image = self._draw_table(model)
            image.save(tmp_path, format="PNG", optimize=True)
            tmp_path.replace(output_path)
        except Exception as ex:
            logger.warning(
                "table_image_render_failed: digest=%s, rows=%s, cols=%s, "
                "err_type=%s, err=%s",
                digest,
                model.row_count,
                model.col_count,
                type(ex).__name__,
                ex,
            )
            raise
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError as ex:
                logger.debug(
                    "Table image temp cleanup failed: path=%s, err=%s",
                    tmp_path,
                    ex,
                )
        return TableImageRenderResult(
            source_id=source_id,
            path=output_path,
            digest=digest,
            reused=False,
        )

    def _parse_table(self, table_html: str | Tag) -> _TableModel | None:
        table = self._coerce_table(table_html)
        if table is None:
            return None

        caption_tag = table.find("caption", recursive=False)
        caption = (
            self._normalize_text(caption_tag.get_text(" ", strip=True))
            if caption_tag
            else ""
        )
        rows = self._table_rows(table)
        cells: list[_TableCell] = []
        occupied: dict[tuple[int, int], _TableCell] = {}
        max_row = 0
        max_col = 0

        for row_index, row in enumerate(rows):
            if not isinstance(row, Tag):
                continue
            col_index = 0
            row_cells = row.find_all(("th", "td"), recursive=False)
            for cell_tag in row_cells:
                if not isinstance(cell_tag, Tag):
                    continue
                while (row_index, col_index) in occupied:
                    col_index += 1
                rowspan = self._positive_span(cell_tag.get("rowspan"))
                colspan = self._positive_span(cell_tag.get("colspan"))
                text = self._cell_text(cell_tag, table)
                header = (
                    cell_tag.name == "th" or cell_tag.find_parent("thead") is not None
                )
                cell = _TableCell(
                    text=text,
                    row=row_index,
                    col=col_index,
                    rowspan=rowspan,
                    colspan=colspan,
                    header=header,
                )
                cells.append(cell)
                for dr in range(rowspan):
                    for dc in range(colspan):
                        occupied[(row_index + dr, col_index + dc)] = cell
                max_row = max(max_row, row_index + rowspan)
                max_col = max(max_col, col_index + colspan)
                col_index += colspan

        if not cells or max_row <= 0 or max_col <= 0:
            return None
        if not caption and not any(cell.text for cell in cells):
            return None
        return _TableModel(
            caption=caption,
            cells=cells,
            row_count=max_row,
            col_count=max_col,
        )

    @staticmethod
    def _coerce_table(table_html: str | Tag) -> Tag | None:
        if isinstance(table_html, Tag):
            return table_html
        soup = BeautifulSoup(str(table_html or ""), "lxml")
        table = soup.find("table")
        return table if isinstance(table, Tag) else None

    @staticmethod
    def _table_rows(table: Tag) -> list[Tag]:
        """只取当前 table 的行，避免嵌套 table 混入外层模型。"""
        return [
            row
            for row in table.find_all("tr")
            if isinstance(row, Tag) and row.find_parent("table") is table
        ]

    @classmethod
    def _cell_text(cls, cell_tag: Tag, table: Tag) -> str:
        texts: list[str] = []
        for text_node in cell_tag.find_all(string=True):
            if text_node.find_parent("table") is not table:
                continue
            text = str(text_node).strip()
            if text:
                texts.append(text)
        return cls._normalize_text(" ".join(texts))

    @staticmethod
    def _positive_span(value: Any) -> int:
        try:
            number = int(str(value or "1").strip())
        except (TypeError, ValueError):
            return 1
        return max(1, number)

    @staticmethod
    def _normalize_text(value: str) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return text.strip()

    @staticmethod
    def _digest_model(model: _TableModel) -> str:
        payload = {
            "caption": model.caption,
            "row_count": model.row_count,
            "col_count": model.col_count,
            "cells": [
                {
                    "text": cell.text,
                    "row": cell.row,
                    "col": cell.col,
                    "rowspan": cell.rowspan,
                    "colspan": cell.colspan,
                    "header": cell.header,
                }
                for cell in model.cells
            ],
        }
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def _draw_table(self, model: _TableModel) -> Image.Image:
        assert self._font_regular is not None
        assert self._font_header is not None
        assert self._font_caption is not None
        margin_x = 28
        margin_y = 24
        border = 1
        padding_x = 16
        padding_y = 12
        line_gap = 6

        col_widths = self._measure_column_widths(model, padding_x)
        row_heights = self._measure_row_heights(
            model,
            col_widths,
            padding_x=padding_x,
            padding_y=padding_y,
            line_gap=line_gap,
        )

        table_width = sum(col_widths) + border
        table_height = sum(row_heights) + border
        caption_height = 0
        caption_lines: list[str] = []
        if model.caption:
            caption_lines = self._wrap_text(
                model.caption,
                self._font_caption,
                max(table_width, 260),
            )
            caption_height = (
                self._line_block_height(
                    caption_lines,
                    self._font_caption,
                    line_gap,
                )
                + 14
            )

        image_width = table_width + margin_x * 2
        image_height = table_height + caption_height + margin_y * 2
        image = Image.new("RGB", (image_width, image_height), self._BG)
        draw = ImageDraw.Draw(image)

        card = [
            margin_x - 10,
            margin_y - 10,
            image_width - margin_x + 10,
            image_height - margin_y + 10,
        ]
        draw.rounded_rectangle(
            card,
            radius=18,
            fill=self._CARD_BG,
            outline=self._BORDER,
            width=1,
        )

        y = margin_y
        if caption_lines:
            for line in caption_lines:
                line_width = self._text_width(line, self._font_caption)
                draw.text(
                    ((image_width - line_width) / 2, y),
                    line,
                    font=self._font_caption,
                    fill=self._CAPTION,
                )
                y += getattr(self._font_caption, "size", 30) + line_gap
            y += 14

        table_x = margin_x
        table_y = y
        for cell in model.cells:
            x0 = table_x + sum(col_widths[: cell.col])
            y0 = table_y + sum(row_heights[: cell.row])
            width = sum(col_widths[cell.col : cell.col + cell.colspan])
            height = sum(row_heights[cell.row : cell.row + cell.rowspan])
            x1 = x0 + width
            y1 = y0 + height
            fill = self._cell_fill(cell)
            draw.rectangle(
                [x0, y0, x1, y1],
                fill=fill,
                outline=self._BORDER,
                width=border,
            )
            font = self._font_header if cell.header else self._font_regular
            text_fill = self._HEADER_TEXT if cell.header else self._BODY_TEXT
            text_y = y0 + padding_y
            for line in cell.lines or [""]:
                draw.text((x0 + padding_x, text_y), line, font=font, fill=text_fill)
                text_y += getattr(font, "size", 24) + line_gap

        return image

    def _cell_fill(self, cell: _TableCell) -> tuple[int, int, int]:
        if cell.header:
            return self._HEADER_BG
        return self._ZEBRA_BG if cell.row % 2 else self._CARD_BG

    def _measure_column_widths(
        self,
        model: _TableModel,
        padding_x: int,
    ) -> list[int]:
        assert self._font_regular is not None
        assert self._font_header is not None
        min_width = 96
        max_width = 340
        widths = [min_width for _ in range(model.col_count)]
        for cell in model.cells:
            font = self._font_header if cell.header else self._font_regular
            preferred = self._preferred_cell_width(cell.text, font, padding_x)
            preferred = max(min_width, min(max_width, preferred))
            share = max(min_width, int(preferred / cell.colspan))
            for index in range(cell.col, min(model.col_count, cell.col + cell.colspan)):
                widths[index] = max(widths[index], share)
        return widths

    def _measure_row_heights(
        self,
        model: _TableModel,
        col_widths: list[int],
        *,
        padding_x: int,
        padding_y: int,
        line_gap: int,
    ) -> list[int]:
        assert self._font_regular is not None
        assert self._font_header is not None
        min_height = 54
        row_heights = [min_height for _ in range(model.row_count)]
        spanned_cells: list[tuple[_TableCell, int]] = []

        for cell in model.cells:
            font = self._font_header if cell.header else self._font_regular
            available_width = (
                sum(col_widths[cell.col : cell.col + cell.colspan]) - padding_x * 2
            )
            cell.lines = self._wrap_text(cell.text, font, max(24, available_width))
            needed = (
                self._line_block_height(cell.lines or [""], font, line_gap)
                + padding_y * 2
            )
            if cell.rowspan == 1:
                row_heights[cell.row] = max(row_heights[cell.row], needed)
            else:
                spanned_cells.append((cell, needed))

        for cell, needed in spanned_cells:
            current = sum(row_heights[cell.row : cell.row + cell.rowspan])
            if current >= needed:
                continue
            extra = needed - current
            share, remainder = divmod(extra, cell.rowspan)
            for offset in range(cell.rowspan):
                row_heights[cell.row + offset] += share + (
                    1 if offset < remainder else 0
                )
        return row_heights

    def _preferred_cell_width(
        self,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        padding_x: int,
    ) -> int:
        if not text:
            return padding_x * 2 + 64
        samples = re.split(r"[\s\n]+", text)
        longest = max(
            (self._text_width(sample, font) for sample in samples if sample),
            default=0,
        )
        whole = self._text_width(text.replace("\n", " "), font)
        return min(max(longest + padding_x * 2, 120), max(whole + padding_x * 2, 180))

    def _wrap_text(
        self,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        value = str(text or "")
        if not value:
            return [""]

        lines: list[str] = []
        for paragraph in value.split("\n"):
            current = ""
            for char in paragraph:
                candidate = current + char
                if current and self._text_width(candidate, font) > max_width:
                    lines.append(current)
                    current = char
                else:
                    current = candidate
            lines.append(current)
        return lines or [""]

    @staticmethod
    def _line_block_height(
        lines: list[str],
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        line_gap: int,
    ) -> int:
        count = max(1, len(lines))
        font_size = getattr(font, "size", 24)
        return int(count * font_size + max(0, count - 1) * line_gap)

    @staticmethod
    def _text_width(
        text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    ) -> int:
        bbox = font.getbbox(text or "")
        return max(0, int(bbox[2] - bbox[0]))

    @staticmethod
    def _load_font(size: int) -> ImageFont.FreeTypeFont | None:
        for path in TableImageRenderer._iter_font_candidates():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception as ex:
                logger.debug("Table image font load failed: path=%s, err=%s", path, ex)
        TableImageRenderer._warn_no_font_once()
        return None

    @classmethod
    def _warn_no_font_once(cls) -> None:
        if cls._warned_no_font:
            return
        cls._warned_no_font = True
        logger.warning(
            "表格图片渲染未找到可用字体，表格将回退为纯文本展示；"
            "可通过 %s 指定字体文件，或把 .ttf/.otf/.ttc 放入 "
            "assets/fonts/ 或运行时字体目录。",
            TABLE_FONT_PATH_ENV,
        )

    @staticmethod
    def _iter_font_candidates() -> list[Path]:
        """按可控优先级查找字体，避免硬依赖维护者本机字体。"""
        candidates: list[Path] = []

        explicit_font = os.getenv(TABLE_FONT_PATH_ENV)
        if explicit_font:
            candidates.extend(TableImageRenderer._split_font_paths(explicit_font))

        explicit_dir = os.getenv(TABLE_FONT_DIR_ENV)
        if explicit_dir:
            candidates.extend(
                TableImageRenderer._font_files_in_dir(Path(explicit_dir).expanduser())
            )

        candidates.extend(TableImageRenderer._font_files_in_dir(get_runtime_font_dir()))

        candidates.extend(TableImageRenderer._font_files_in_dir(PLUGIN_FONT_DIR))

        existing: list[Path] = []
        seen: set[Path] = set()
        for path in candidates:
            try:
                resolved = path.expanduser().resolve()
            except OSError:
                continue
            if resolved in seen or not resolved.is_file():
                continue
            seen.add(resolved)
            existing.append(resolved)
        return existing

    @staticmethod
    def _split_font_paths(value: str) -> list[Path]:
        return [
            Path(item).expanduser() for item in value.split(os.pathsep) if item.strip()
        ]

    @staticmethod
    def _font_files_in_dir(font_dir: Path) -> list[Path]:
        try:
            if not font_dir.is_dir():
                return []
            return sorted(
                path
                for path in font_dir.iterdir()
                if path.is_file() and path.suffix.lower() in FONT_FILE_SUFFIXES
            )
        except OSError as ex:
            logger.debug(
                "Table image font dir scan failed: dir=%s, err=%s", font_dir, ex
            )
            return []
