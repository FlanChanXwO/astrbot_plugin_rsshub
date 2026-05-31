"""Legacy AstrBot config shape migration helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...shared.constants import PLATFORM_STRATEGY_TEMPLATE_KEYS
from .models import SenderStrategiesConfig

_LEGACY_FFMPEG_KEYS: tuple[str, ...] = (
    "video_transcode",
    "video_transcode_timeout",
    "gif_transcode",
    "gif_transcode_timeout",
)


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

    def ensure_media_config() -> dict[str, Any]:
        media = normalized.setdefault("media", {})
        if not isinstance(media, dict):
            media = {}
            normalized["media"] = media
            record_config_heal(changes, "media", "reset invalid object")
        return media

    ffmpeg_config = normalized.get("ffmpeg")
    if isinstance(ffmpeg_config, dict):
        media = ensure_media_config()
        migrated = False
        for key in _LEGACY_FFMPEG_KEYS:
            if key not in ffmpeg_config or key in media:
                continue
            media[key] = ffmpeg_config[key]
            migrated = True
        normalized.pop("ffmpeg", None)
        record_config_heal(
            changes,
            "ffmpeg",
            "migrated to media" if migrated else "removed legacy key",
        )
    elif "ffmpeg" in normalized:
        normalized.pop("ffmpeg", None)
        record_config_heal(changes, "ffmpeg", "removed invalid legacy key")

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
    if isinstance(media_config, dict):
        if "download_media_timeout" in media_config:
            migrate_http_value(
                "media_config.download_media_timeout",
                media_config.get("download_media_timeout"),
                "media_timeout",
            )

        # 迁移 onebot_prefer_local_video 到 onebot_napcat_stream_mode
        if "onebot_prefer_local_video" in media_config:
            old_value = media_config.pop("onebot_prefer_local_video")
            # true -> "fallback" (默认行为，失败后重试)
            # false -> "disabled" (不使用流式上传)
            new_value = "fallback" if old_value else "disabled"
            media_config["onebot_napcat_stream_mode"] = new_value
            record_config_heal(
                changes,
                "media_config.onebot_prefer_local_video",
                f"migrated to onebot_napcat_stream_mode={new_value}",
            )

    # 将 media.telegraph_proxy 迁移到 telegram_strategy 模板（归属修正 + 接通）。
    # 必须在下方 sender_strategies 归一化之前执行，使新建/补齐的模板项能随后被
    # SenderStrategiesConfig 正确收口。
    media = normalized.get("media")
    if isinstance(media, dict) and "telegraph_proxy" in media:
        proxy_value = media.pop("telegraph_proxy")
        telegram_key = PLATFORM_STRATEGY_TEMPLATE_KEYS["telegram"]
        sender = normalized.get("sender_strategies")
        if not isinstance(sender, dict):
            sender = {}
            normalized["sender_strategies"] = sender
        strategies = sender.get("platform_strategies")
        if not isinstance(strategies, list):
            strategies = []
            sender["platform_strategies"] = strategies
        telegram_item = next(
            (
                item
                for item in strategies
                if isinstance(item, dict) and item.get("__template_key") == telegram_key
            ),
            None,
        )
        if telegram_item is None:
            telegram_item = {"__template_key": telegram_key}
            strategies.append(telegram_item)
        telegram_item.setdefault("telegraph_proxy", proxy_value)
        record_config_heal(
            changes,
            "media.telegraph_proxy",
            f"migrated to sender_strategies.platform_strategies[{telegram_key}]",
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
