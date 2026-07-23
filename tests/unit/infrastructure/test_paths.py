from __future__ import annotations

from pathlib import Path

from astrbot_plugin_rsshub.src.infrastructure.utils import paths


def test_plugin_data_dir_avoids_plugin_local_astrbot_data(monkeypatch, tmp_path):
    """本地插件目录运行时，数据应回落到实际 AstrBot 根目录。"""
    astrbot_root = tmp_path / "astrbot"
    plugin_root = astrbot_root / "data" / "plugins" / paths.PLUGIN_NAME
    plugin_root.mkdir(parents=True)
    plugin_local_data = plugin_root / "data" / "plugin_data"

    monkeypatch.setattr(paths, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(
        paths, "_resolve_explicit_astrbot_data_dir", lambda: plugin_local_data
    )

    data_dir = paths.get_plugin_data_dir()

    assert data_dir == astrbot_root / "data" / "plugin_data" / paths.PLUGIN_NAME
    assert not _is_relative_to(data_dir, plugin_root / "data")


def test_plugin_data_dir_keeps_normal_astrbot_data(monkeypatch, tmp_path):
    astrbot_data = tmp_path / "astrbot" / "data" / "plugin_data"

    monkeypatch.setattr(
        paths, "_resolve_explicit_astrbot_data_dir", lambda: astrbot_data
    )

    assert paths.get_plugin_data_dir("cache") == (
        astrbot_data / paths.PLUGIN_NAME / "cache"
    )


def test_plugin_data_dir_falls_back_to_temp_when_no_runtime_path(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "_resolve_explicit_astrbot_data_dir", lambda: None)
    monkeypatch.setattr(paths, "_find_astrbot_project_root", lambda _start: None)
    monkeypatch.setattr(paths.tempfile, "gettempdir", lambda: str(tmp_path))

    assert paths.get_plugin_data_dir("exports") == (
        tmp_path / paths.PLUGIN_NAME / "exports"
    )


def test_plugin_data_dir_uses_temp_when_only_polluted_path_exists(
    monkeypatch, tmp_path
):
    plugin_local_data = paths.PLUGIN_ROOT / "data" / "plugin_data"

    monkeypatch.setattr(
        paths, "_resolve_explicit_astrbot_data_dir", lambda: plugin_local_data
    )
    monkeypatch.setattr(paths, "_find_astrbot_project_root", lambda _start: None)
    monkeypatch.setattr(paths.tempfile, "gettempdir", lambda: str(tmp_path))

    assert paths.get_plugin_data_dir() == tmp_path / paths.PLUGIN_NAME


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
