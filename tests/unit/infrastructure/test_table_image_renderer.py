from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import MagicMock

from PIL import Image

from astrbot_plugin_rsshub.src.infrastructure.rendering.table_image_renderer import (
    TABLE_FONT_PATH_ENV,
    TableImageRenderer,
)


def test_table_image_renderer_renders_basic_table(tmp_path: Path):
    renderer = TableImageRenderer(cache_dir=tmp_path)

    result = renderer.render_table(
        "<table><tr><th>名称</th><th>值</th></tr><tr><td>A</td><td>42</td></tr></table>"
    )

    assert result is not None
    assert result.path.exists()
    assert result.source_id.startswith("rsshub-generated://table/")
    with Image.open(result.path) as image:
        assert image.format == "PNG"
        assert image.width > 100
        assert image.height > 80


def test_table_image_renderer_supports_caption_thead_tbody_and_spans(tmp_path: Path):
    renderer = TableImageRenderer(cache_dir=tmp_path)

    result = renderer.render_table(
        """
        <table>
          <caption>今日状态</caption>
          <thead><tr><th rowspan="2">项目</th><th colspan="2">指标</th></tr></thead>
          <tbody>
            <tr><td>速度</td><td>很长很长的中文内容需要按像素宽度自动换行</td></tr>
          </tbody>
        </table>
        """
    )

    assert result is not None
    assert result.path.exists()
    with Image.open(result.path) as image:
        assert image.width > 200
        assert image.height > 120


def test_table_image_renderer_returns_none_for_empty_table(tmp_path: Path):
    renderer = TableImageRenderer(cache_dir=tmp_path)

    result = renderer.render_table("<table><tr><td> </td></tr></table>")

    assert result is None


def test_table_image_renderer_reuses_same_cache_for_same_content(tmp_path: Path):
    renderer = TableImageRenderer(cache_dir=tmp_path)
    html = "<table><tr><td>A</td><td>B</td></tr></table>"

    first = renderer.render_table(html)
    second = renderer.render_table(html)

    assert first is not None
    assert second is not None
    assert first.path == second.path
    assert first.digest == second.digest
    assert second.reused is True


def test_table_image_renderer_uses_unique_temp_files_for_concurrent_same_digest(
    tmp_path: Path,
):
    class FakeImage:
        def __init__(self, barrier: Barrier):
            self._barrier = barrier

        def save(self, path, *, format=None, optimize=None):
            Path(path).write_bytes(b"fake-png")
            self._barrier.wait(timeout=5)

    class RaceRenderer(TableImageRenderer):
        def __init__(self, cache_dir: Path, barrier: Barrier):
            super().__init__(cache_dir=cache_dir)
            self._barrier = barrier

        def _draw_table(self, model):
            return FakeImage(self._barrier)

    renderer = RaceRenderer(cache_dir=tmp_path, barrier=Barrier(2))
    html = "<table><tr><td>A</td><td>B</td></tr></table>"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(renderer.render_table, [html, html]))

    assert all(result is not None for result in results)
    assert all(result.path.exists() for result in results if result is not None)


def test_table_image_renderer_ignores_nested_table_rows(tmp_path: Path):
    renderer = TableImageRenderer(cache_dir=tmp_path)

    model = renderer._parse_table(
        """
        <table>
          <tr>
            <td>外层<table><tr><td>内层</td></tr></table></td>
          </tr>
        </table>
        """
    )

    assert model is not None
    assert [cell.text for cell in model.cells] == ["外层"]


def test_table_image_renderer_warns_when_using_default_font(
    monkeypatch,
):
    fake_logger = MagicMock()
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering.table_image_renderer.logger",
        fake_logger,
    )
    monkeypatch.setattr(TableImageRenderer, "_warned_default_font", False)
    monkeypatch.setattr(
        TableImageRenderer,
        "_iter_font_candidates",
        staticmethod(lambda: []),
    )

    font = TableImageRenderer._load_font(size=24)
    TableImageRenderer._load_font(size=30)

    assert getattr(font, "size", None) == 24
    fake_logger.warning.assert_called_once()


def test_table_image_renderer_prefers_configured_font(monkeypatch, tmp_path: Path):
    custom_font = tmp_path / "table-font.ttf"
    custom_font.write_bytes(b"font")
    calls: list[tuple[Path, int]] = []

    def fake_truetype(path: Path, *, size: int):
        calls.append((path, size))
        return MagicMock(size=size)

    monkeypatch.setenv(TABLE_FONT_PATH_ENV, str(custom_font))
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.ImageFont.truetype",
        fake_truetype,
    )

    font = TableImageRenderer._load_font(size=24)

    assert font.size == 24
    assert calls == [(custom_font.resolve(), 24)]
