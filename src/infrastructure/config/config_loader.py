"""Config loading facade and runtime config accessors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...shared.constants import INHERIT_VALUE
from .models import ApplicationSettings, BasicSettings, RsshubPluginConfig
from .schema_healer import heal_astrbot_plugin_config as _heal_astrbot_plugin_config
from .settings_builder import build_application_settings

if TYPE_CHECKING:
    from astrbot.api import AstrBotConfig

MAX_INTERVAL_MINUTES = 1440

_config: RsshubPluginConfig | None = None


def load_astrbot_plugin_config(raw: dict[str, Any] | None) -> RsshubPluginConfig:
    return RsshubPluginConfig.from_astrbot_config(raw)


def save_astrbot_plugin_config(
    config: RsshubPluginConfig,
    astrbot_config: AstrBotConfig,
) -> None:
    config.save(astrbot_config)


def heal_astrbot_plugin_config(
    raw_config: dict[str, Any] | None,
    schema: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    return _heal_astrbot_plugin_config(raw_config, schema)


def get_config() -> RsshubPluginConfig | None:
    return _config


def get_config_manager() -> RsshubPluginConfig | None:
    return _config


def set_config(config: RsshubPluginConfig) -> None:
    global _config
    _config = config


def get_application_settings(config: Any | None = None) -> ApplicationSettings:
    return build_application_settings(config if config is not None else _config)


def get_basic_settings(config: Any | None = None) -> BasicSettings:
    return get_application_settings(config).basic


def get_minimal_interval(config: Any | None = None) -> int:
    return max(1, int(get_basic_settings(config).minimal_interval or 1))


def get_failed_queue_capacity(config: Any | None = None) -> int:
    return max(0, int(get_basic_settings(config).failed_queue_capacity or 0))


def get_failed_queue_max_retries(config: Any | None = None) -> int:
    return max(0, int(get_basic_settings(config).failed_queue_max_retries or 0))


def get_deduplicate_multi_bot(config: Any | None = None) -> bool:
    return bool(get_basic_settings(config).deduplicate_multi_bot)


def validate_interval_value(
    value: Any,
    *,
    allow_inherit: bool,
    field_name: str = "interval",
    config: Any | None = None,
) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 需要数字值") from exc

    if allow_inherit and normalized == INHERIT_VALUE:
        return normalized

    minimal_interval = get_minimal_interval(config)
    if normalized < minimal_interval:
        raise ValueError(f"{field_name} 不能小于最小监控间隔 {minimal_interval} 分钟")
    if normalized > MAX_INTERVAL_MINUTES:
        raise ValueError(f"{field_name} 不能大于 {MAX_INTERVAL_MINUTES} 分钟")
    return normalized
