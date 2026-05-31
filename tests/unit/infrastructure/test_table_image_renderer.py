from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import MagicMock

from PIL import Image

from astrbot_plugin_rsshub.src.infrastructure.rendering.table_image_renderer import (
    TABLE_FONT_DIR_ENV,
    TABLE_FONT_PATH_ENV,
    TableImageRenderer,
)

# 需要真实字体的渲染测试使用 macOS / Linux 上可用的 CJK 字体
_CJK_FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def _find_cjk_font() -> str | None:
    """返回本机可用的 CJK 字体路径，无可用字体时返回 None。"""
    for p in _CJK_FONT_CANDIDATES:
        if Path(p).is_file():
            return p
    return None


CJK_FONT_PATH = _find_cjk_font()


def test_table_image_renderer_renders_basic_table(tmp_path: Path, monkeypatch):
    if CJK_FONT_PATH:
        monkeypatch.setenv(TABLE_FONT_PATH_ENV, CJK_FONT_PATH)
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


def test_table_image_renderer_supports_caption_thead_tbody_and_spans(
    tmp_path: Path, monkeypatch
):
    if CJK_FONT_PATH:
        monkeypatch.setenv(TABLE_FONT_PATH_ENV, CJK_FONT_PATH)
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


def test_table_image_renderer_reuses_same_cache_for_same_content(
    tmp_path: Path, monkeypatch
):
    if CJK_FONT_PATH:
        monkeypatch.setenv(TABLE_FONT_PATH_ENV, CJK_FONT_PATH)
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
    monkeypatch,
):
    if CJK_FONT_PATH:
        monkeypatch.setenv(TABLE_FONT_PATH_ENV, CJK_FONT_PATH)

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


def test_table_image_renderer_warns_when_no_font_available(
    monkeypatch,
):
    fake_logger = MagicMock()
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering.table_image_renderer.logger",
        fake_logger,
    )
    monkeypatch.setattr(TableImageRenderer, "_warned_no_font", False)
    monkeypatch.setattr(
        TableImageRenderer,
        "_iter_font_candidates",
        staticmethod(lambda: []),
    )

    font = TableImageRenderer._load_font(size=24)

    assert font is None
    fake_logger.warning.assert_called_once()


def test_table_image_renderer_render_returns_none_when_no_font(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(TableImageRenderer, "_warned_no_font", False)
    monkeypatch.setattr(
        TableImageRenderer,
        "_iter_font_candidates",
        staticmethod(lambda: []),
    )

    renderer = TableImageRenderer(cache_dir=tmp_path)
    result = renderer.render_table("<table><tr><th>名称</th><th>值</th></tr></table>")

    assert result is None


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


def test_table_image_renderer_discovers_runtime_font_dir(monkeypatch, tmp_path: Path):
    """_iter_font_candidates finds fonts in the runtime download directory."""
    runtime_font_dir = tmp_path / "data" / "fonts"
    runtime_font_dir.mkdir(parents=True)
    (runtime_font_dir / "NotoSansSC-subset.otf").write_bytes(b"fake-otf")

    monkeypatch.delenv(TABLE_FONT_PATH_ENV, raising=False)
    monkeypatch.delenv(TABLE_FONT_DIR_ENV, raising=False)
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.get_runtime_font_dir",
        lambda: runtime_font_dir,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.PLUGIN_FONT_DIR",
        tmp_path / "empty_fonts",
    )

    candidates = TableImageRenderer._iter_font_candidates()

    assert len(candidates) >= 1
    assert candidates[0].name == "NotoSansSC-subset.otf"


def test_table_image_renderer_no_system_font_paths(monkeypatch, tmp_path: Path):
    """_iter_font_candidates must never return hard-coded system font paths."""
    monkeypatch.delenv(TABLE_FONT_PATH_ENV, raising=False)
    monkeypatch.delenv(TABLE_FONT_DIR_ENV, raising=False)
    empty_dir = tmp_path / "empty_fonts"
    empty_dir.mkdir()
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.PLUGIN_FONT_DIR",
        empty_dir,
    )

    candidates = TableImageRenderer._iter_font_candidates()
    system_prefixes = ("/System/", "/usr/share/fonts/")
    for c in candidates:
        for prefix in system_prefixes:
            assert not str(c).startswith(prefix), f"System path leaked: {c}"
