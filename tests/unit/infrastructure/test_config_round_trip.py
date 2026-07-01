"""Round-trip tests: JSON -> RsshubPluginConfig -> ApplicationSettings.

These tests lock down the wiring so that config field mismatches like the
v2.1.0 ``media.*`` freeze-at-default bug are caught immediately.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ── helpers ────────────────────────────────────────────────────────────


def _find_runtime_config() -> Path | None:
    """尝试定位 runtime config，从插件根向上查找 data/config/ 目录。

    优先在开发环境（../../../data/config/）查找；找不到时返回 None，
    由调用方决定是否 skip 测试。
    """
    plugin_root = Path(__file__).resolve().parents[3]
    # 尝试相对路径：从插件根目录向上 3 层找 data/config/
    candidates = [
        plugin_root.parents[2]
        / "data"
        / "config"
        / "astrbot_plugin_rsshub_config.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_live_config() -> dict:
    """Load the running plugin config from the AstrBot runtime data dir."""
    config_path = _find_runtime_config()
    if config_path is None:
        pytest.skip("Runtime config not found (not in dev environment)")
    return json.loads(config_path.read_text(encoding="utf-8-sig"))


def _load_schema() -> dict:
    schema_path = Path(__file__).resolve().parents[3] / "_conf_schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8-sig"))


# ── round-trip from live config ───────────────────────────────────────


def test_real_config_round_trip_media_settings_match_json():
    """Build ApplicationSettings from the actual runtime JSON and verify key
    ``media.*`` fields propagate through."""
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        RsshubPluginConfig,
        build_application_settings,
    )

    raw = _load_live_config()
    config = RsshubPluginConfig.from_astrbot_config(raw)
    settings = build_application_settings(config)

    media_json = raw.get("media", {})
    m = settings.media

    assert m.gif_transcode == bool(media_json.get("gif_transcode", False))
    assert m.video_transcode == bool(media_json.get("video_transcode", False))
    assert m.table_to_image == bool(media_json.get("table_to_image", True))
    assert m.image_relay_base_url == str(
        media_json.get("image_relay_base_url", "") or ""
    )
    assert m.media_relay_base_url == str(
        media_json.get("media_relay_base_url", "") or ""
    )
    assert m.media_download_concurrency >= 1
    assert m.ffmpeg_source == str(media_json.get("ffmpeg_source", "auto") or "auto")
    assert m.ffmpeg_mirror == str(media_json.get("ffmpeg_mirror", "auto") or "auto")
    assert (
        m.ffmpeg_mirror_custom_url
        == str(media_json.get("ffmpeg_mirror_custom_url", "") or "").strip()
    )

    # Pydantic model should mirror JSON -> confirms from_astrbot_config reads the
    # right key.
    assert config.media.gif_transcode == bool(media_json.get("gif_transcode", False))
    assert config.media.video_transcode == bool(
        media_json.get("video_transcode", False)
    )
    assert config.media.media_download_concurrency == int(
        media_json.get("media_download_concurrency", 1) or 1
    )
    assert settings.media_platform_limits.cache_enabled == bool(
        media_json.get("cache_enabled", True)
    )
    assert settings.media_platform_limits.cache_ttl_seconds == max(
        60, int(media_json.get("cache_ttl_seconds", 900) or 900)
    )


# ── schema default propagation ─────────────────────────────────────────


def test_schema_healer_fills_media_defaults():
    """Schema healer should add ``media.gif_transcode`` (and siblings) from
    schema defaults when the field is absent in user JSON."""
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        heal_astrbot_plugin_config,
        build_application_settings,
    )

    schema = _load_schema()
    # minimal config with no media block at all
    healed, changes = heal_astrbot_plugin_config({}, schema)

    assert isinstance(healed, dict)
    media = healed.get("media", {})
    assert media.get("gif_transcode") is False  # schema default
    assert media.get("video_transcode") is False
    assert media.get("video_transcode_timeout") == 120
    assert media.get("gif_transcode_timeout") == 60
    assert media.get("ffmpeg_source") == "auto"
    assert media.get("media_download_concurrency") == 1
    assert media.get("cache_enabled") is True
    assert media.get("cache_ttl_seconds") == 900

    # settings_builder must also receive these defaults
    from astrbot_plugin_rsshub.src.infrastructure.config.models.plugin_config_models import (
        RsshubPluginConfig,
    )

    config = RsshubPluginConfig.from_astrbot_config(healed)
    settings = build_application_settings(config)
    assert settings.media.gif_transcode is False
    assert settings.media.video_transcode is False
    assert settings.media.ffmpeg_source == "auto"
    assert settings.media_platform_limits.cache_enabled is True
    assert settings.media_platform_limits.cache_ttl_seconds == 900
