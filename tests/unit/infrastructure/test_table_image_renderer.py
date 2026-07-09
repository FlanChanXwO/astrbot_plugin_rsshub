from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import MagicMock

import pytest
from PIL import Image

from astrbot_plugin_rsshub.src.infrastructure.rendering.table_image_renderer import (
    TABLE_FONT_DIR_ENV,
    TABLE_FONT_PATH_ENV,
    TableImageRenderer,
    cleanup_ephemeral_generated_media_paths,
)
from astrbot_plugin_rsshub.src.domain.entities.content_types import (
    LayoutFragment,
    build_generated_media_url,
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


@pytest.fixture(autouse=True)
def _reset_table_cache_policy():
    TableImageRenderer.configure_cache(enabled=True, ttl_seconds=3600)
    yield
    TableImageRenderer.configure_cache(enabled=True, ttl_seconds=3600)


class _FakeRenderedImage:
    """测试用图片对象，只负责把可观察字节写到目标路径。"""

    def __init__(self, payload: bytes):
        self._payload = payload

    def save(self, path, *, format=None, optimize=None):
        Path(path).write_bytes(self._payload)


def _renderer_without_real_font(monkeypatch, tmp_path: Path) -> TableImageRenderer:
    # 缓存策略测试只关心落盘语义，不依赖真实字体和 Pillow 绘制。
    monkeypatch.setattr(
        TableImageRenderer,
        "_load_font",
        staticmethod(lambda size: MagicMock(size=size)),
    )
    return TableImageRenderer(cache_dir=tmp_path)


def _write_table_meta(meta_path: Path, expire_ts: float) -> None:
    meta_path.write_text(
        json.dumps({"expire_ts": expire_ts}, separators=(",", ":")),
        encoding="utf-8",
    )


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


def test_table_image_renderer_refreshes_meta_on_cache_hit(tmp_path: Path, monkeypatch):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    TableImageRenderer.configure_cache(enabled=True, ttl_seconds=10)
    now_values = iter([100.0, 105.0])
    monkeypatch.setattr(
        TableImageRenderer,
        "_now_ts",
        staticmethod(lambda: next(now_values)),
    )
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(b"first"),
    )
    html = "<table><tr><td>A</td><td>B</td></tr></table>"

    first = renderer.render_table(html)
    second = renderer.render_table(html)

    assert first is not None
    assert second is not None
    assert second.path == first.path
    assert second.reused is True
    assert second.path.read_bytes() == b"first"
    meta = second.path.with_suffix(".meta").read_text(encoding="utf-8")
    assert '"expire_ts":115.0' in meta


def test_table_image_renderer_reuses_legacy_png_and_writes_missing_meta(
    tmp_path: Path, monkeypatch
):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    TableImageRenderer.configure_cache(enabled=True, ttl_seconds=30)
    monkeypatch.setattr(TableImageRenderer, "_now_ts", staticmethod(lambda: 200.0))
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(b"legacy"),
    )
    html = "<table><tr><td>旧缓存</td></tr></table>"
    first = renderer.render_table(html)
    assert first is not None
    first.path.with_suffix(".meta").unlink()

    second = renderer.render_table(html)

    assert second is not None
    assert second.reused is True
    assert second.path.read_bytes() == b"legacy"
    assert second.path.with_suffix(".meta").exists()


def test_table_image_renderer_rerenders_when_meta_expired(tmp_path: Path, monkeypatch):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    TableImageRenderer.configure_cache(enabled=True, ttl_seconds=10)
    now_values = iter([100.0, 200.0])
    monkeypatch.setattr(
        TableImageRenderer,
        "_now_ts",
        staticmethod(lambda: next(now_values)),
    )
    payloads = iter([b"first", b"second"])
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(next(payloads)),
    )
    html = "<table><tr><td>过期</td></tr></table>"

    first = renderer.render_table(html)
    second = renderer.render_table(html)

    assert first is not None
    assert second is not None
    assert second.path == first.path
    assert second.reused is False
    assert second.path.read_bytes() == b"second"


def test_table_image_renderer_gc_deletes_expired_unvisited_table(
    tmp_path: Path, monkeypatch
):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    TableImageRenderer.configure_cache(enabled=True, ttl_seconds=10)
    monkeypatch.setattr(TableImageRenderer, "_now_ts", staticmethod(lambda: 1000.0))
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(b"new"),
    )
    old_png = tmp_path / "table_old.png"
    old_meta = tmp_path / "table_old.meta"
    old_png.write_bytes(b"old")
    _write_table_meta(old_meta, 1.0)

    result = renderer.render_table("<table><tr><td>新表格</td></tr></table>")

    assert result is not None
    assert result.path.exists()
    assert not old_png.exists()
    assert not old_meta.exists()


def test_table_image_renderer_gc_keeps_current_legacy_digest(
    tmp_path: Path, monkeypatch
):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    TableImageRenderer.configure_cache(enabled=True, ttl_seconds=10)
    monkeypatch.setattr(TableImageRenderer, "_now_ts", staticmethod(lambda: 1000.0))
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(b"legacy"),
    )
    html = "<table><tr><td>当前旧缓存</td></tr></table>"
    first = renderer.render_table(html)
    assert first is not None
    first.path.with_suffix(".meta").unlink()
    os.utime(first.path, (1, 1))

    second = renderer.render_table(html)

    assert second is not None
    assert second.reused is True
    assert second.path.read_bytes() == b"legacy"
    assert second.path.with_suffix(".meta").exists()


def test_table_image_renderer_clamps_cache_ttl_to_one_second(
    tmp_path: Path, monkeypatch
):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    TableImageRenderer.configure_cache(enabled=True, ttl_seconds=0)
    monkeypatch.setattr(TableImageRenderer, "_now_ts", staticmethod(lambda: 100.0))
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(b"ttl"),
    )

    result = renderer.render_table("<table><tr><td>TTL</td></tr></table>")

    assert result is not None
    meta = json.loads(result.path.with_suffix(".meta").read_text(encoding="utf-8"))
    assert meta["expire_ts"] == 101.0


def test_table_image_renderer_throttles_cache_gc(tmp_path: Path, monkeypatch):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    TableImageRenderer.configure_cache(
        enabled=True,
        ttl_seconds=10,
        gc_interval_seconds=300,
    )
    now_values = iter([1000.0, 1001.0])
    monkeypatch.setattr(
        TableImageRenderer,
        "_now_ts",
        staticmethod(lambda: next(now_values)),
    )
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(b"new"),
    )

    first_old_png = tmp_path / "table_first_old.png"
    first_old_meta = tmp_path / "table_first_old.meta"
    first_old_png.write_bytes(b"old")
    _write_table_meta(first_old_meta, 1.0)

    first = renderer.render_table("<table><tr><td>首个</td></tr></table>")
    assert first is not None
    assert not first_old_png.exists()
    assert not first_old_meta.exists()

    second_old_png = tmp_path / "table_second_old.png"
    second_old_meta = tmp_path / "table_second_old.meta"
    second_old_png.write_bytes(b"old")
    _write_table_meta(second_old_meta, 1.0)

    second = renderer.render_table("<table><tr><td>第二个</td></tr></table>")

    assert second is not None
    assert second_old_png.exists()
    assert second_old_meta.exists()


def test_table_image_renderer_reuses_png_when_meta_refresh_fails(
    tmp_path: Path, monkeypatch
):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(b"cache"),
    )
    html = "<table><tr><td>meta refresh</td></tr></table>"
    first = renderer.render_table(html)
    assert first is not None
    first.path.with_suffix(".meta").unlink(missing_ok=True)

    monkeypatch.setattr(
        renderer,
        "_write_cache_meta",
        lambda output_path, *, now_ts=None: (_ for _ in ()).throw(
            OSError("meta denied")
        ),
    )

    second = renderer.render_table(html)

    assert second is not None
    assert second.reused is True
    assert second.path == first.path
    assert second.path.read_bytes() == b"cache"


def test_table_image_renderer_returns_png_when_meta_write_after_render_fails(
    tmp_path: Path, monkeypatch
):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(b"rendered"),
    )
    monkeypatch.setattr(
        renderer,
        "_write_cache_meta",
        lambda output_path, *, now_ts=None: (_ for _ in ()).throw(
            OSError("meta denied")
        ),
    )

    result = renderer.render_table("<table><tr><td>meta write</td></tr></table>")

    assert result is not None
    assert result.reused is False
    assert result.path.exists()
    assert result.path.read_bytes() == b"rendered"


def test_cleanup_generated_table_keeps_external_non_renderer_path(tmp_path: Path):
    external_png = tmp_path / "external-table.png"
    external_png.write_bytes(b"external")
    source_id = build_generated_media_url("table", "8" * 64)

    cleanup_ephemeral_generated_media_paths(
        [
            LayoutFragment(
                kind="image",
                media_type="image",
                url=source_id,
                local_path=str(external_png),
            )
        ]
    )

    assert external_png.exists()


def test_table_image_renderer_cleans_meta_tmp_when_replace_fails(
    tmp_path: Path, monkeypatch
):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    meta_target = tmp_path / "table_deadbeef.meta"
    original_replace = Path.replace

    def fail_meta_replace(self, target):
        if Path(target) == meta_target:
            raise OSError("replace denied")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_meta_replace)

    with pytest.raises(OSError, match="replace denied"):
        renderer._write_cache_meta(meta_target.with_suffix(".png"), now_ts=100.0)

    assert list(tmp_path.glob("*.tmp")) == []


def test_table_image_renderer_disabled_cache_uses_unique_temp_png(
    tmp_path: Path, monkeypatch
):
    renderer = _renderer_without_real_font(monkeypatch, tmp_path)
    TableImageRenderer.configure_cache(enabled=False, ttl_seconds=10)
    monkeypatch.setattr(
        renderer,
        "_draw_table",
        lambda _model: _FakeRenderedImage(b"temp"),
    )
    html = "<table><tr><td>临时</td></tr></table>"

    first = None
    second = None
    try:
        first = renderer.render_table(html)
        second = renderer.render_table(html)

        assert first is not None
        assert second is not None
        assert first.reused is False
        assert second.reused is False
        assert first.path != second.path
        assert first.path.exists()
        assert second.path.exists()
        assert list(tmp_path.glob("table_*.png")) == []
        assert list(tmp_path.glob("table_*.meta")) == []
    finally:
        if first is not None:
            first.path.unlink(missing_ok=True)
        if second is not None:
            second.path.unlink(missing_ok=True)


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
