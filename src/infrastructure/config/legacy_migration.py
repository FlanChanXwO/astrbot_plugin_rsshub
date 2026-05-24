"""Legacy AstrBot config shape migration helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import SenderStrategiesConfig


def record_config_heal(changes: list[str], path: str, reason: str) -> None:
    changes.append(f"{path}: {reason}")


def apply_legacy_config_aliases(
    raw_config: dict[str, Any],
    changes: list[str],
) -> dict[str, Any]:
    normalized = deepcopy(raw_config)

    def ensure_http_config() -> dict[str, Any]:
        http_config = normalized.setdefault("http_config", {})
        if not isinstance(http_config, dict):
            http_config = {}
            normalized["http_config"] = http_config
            record_config_heal(changes, "http_config", "reset invalid object")
        return http_config

    def migrate_http_value(source_path: str, value: Any, target_key: str) -> None:
        http_config = ensure_http_config()
        http_config.setdefault(target_key, value)
        record_config_heal(
            changes,
            source_path,
            f"migrated to http_config.{target_key}",
        )

    if "download_image_before_send" in normalized:
        normalized.pop("download_image_before_send", None)
        record_config_heal(changes, "download_image_before_send", "removed legacy key")

    if "m3u8_download_timeout" in normalized:
        migrate_http_value(
            "m3u8_download_timeout",
            normalized.pop("m3u8_download_timeout"),
            "media_timeout",
        )

    if "download_media_timeout" in normalized:
        migrate_http_value(
            "download_media_timeout",
            normalized.pop("download_media_timeout"),
            "media_timeout",
        )

    basic_config = normalized.get("basic_config")
    if isinstance(basic_config, dict):
        if "proxy" in basic_config:
            migrate_http_value("basic_config.proxy", basic_config.pop("proxy"), "proxy")
        if "timeout" in basic_config:
            migrate_http_value(
                "basic_config.timeout", basic_config.pop("timeout"), "timeout"
            )
        if "download_media_timeout" in basic_config:
            migrate_http_value(
                "basic_config.download_media_timeout",
                basic_config.pop("download_media_timeout"),
                "media_timeout",
            )

    media_config = normalized.get("media_config")
    if isinstance(media_config, dict) and "download_media_timeout" in media_config:
        migrate_http_value(
            "media_config.download_media_timeout",
            media_config.get("download_media_timeout"),
            "media_timeout",
        )

    sender_strategies = normalized.get("sender_strategies")
    if isinstance(sender_strategies, (str, list, tuple, set)) or (
        isinstance(sender_strategies, dict)
        and "enabled_platforms" not in sender_strategies
        and "platform_strategies" not in sender_strategies
    ):
        normalized["sender_strategies"] = SenderStrategiesConfig.from_config(
            sender_strategies
        ).to_config_dict()
        record_config_heal(
            changes,
            "sender_strategies",
            "normalized legacy sender strategy config",
        )

    return normalized
