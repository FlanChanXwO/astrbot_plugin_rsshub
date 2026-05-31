"""Pydantic config models for platform sender strategies."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ....shared.constants import (
    PLATFORM_QQ_OFFICIAL,
    PLATFORM_STRATEGY_TEMPLATE_KEYS,
    QQ_OFFICIAL_MARKDOWN_MODE_DEFAULT,
    QQ_OFFICIAL_MARKDOWN_MODE_OPTIONS,
    SENDER_STRATEGY_ENABLED_PLATFORMS,
)

_SENDER_STRATEGY_KEYS: tuple[str, ...] = SENDER_STRATEGY_ENABLED_PLATFORMS

_PLATFORM_STRATEGY_TEMPLATE_KEYS: dict[str, str] = PLATFORM_STRATEGY_TEMPLATE_KEYS


class PlatformSenderStrategyConfig(BaseModel):
    """平台专属 sender 策略。"""

    enable_telegraph: bool = Field(default=False, description="启用 Telegraph 自动分流")
    telegraph_token: str = Field(default="", description="Telegraph access token")
    telegraph_proxy: str = Field(default="", description="Telegraph API 独立代理")
    napcat_stream_mode: str | None = Field(
        default=None,
        description="NapCat 流式上传模式（disabled/fallback/always）；未配置时使用运行时默认值",
    )
    markdown_mode: str = Field(
        default=QQ_OFFICIAL_MARKDOWN_MODE_DEFAULT,
        description="QQ 官方 Markdown 发送模式",
    )

    @classmethod
    def from_dict(cls, data: Any) -> PlatformSenderStrategyConfig:
        if not data:
            return cls()
        if isinstance(data, list):
            data = next((item for item in data if isinstance(item, dict)), None)
        if not isinstance(data, dict):
            return cls()
        clean_data = {k: v for k, v in data.items() if k != "__template_key"}
        mode = str(clean_data.get("markdown_mode") or QQ_OFFICIAL_MARKDOWN_MODE_DEFAULT)
        if mode not in QQ_OFFICIAL_MARKDOWN_MODE_OPTIONS:
            clean_data["markdown_mode"] = QQ_OFFICIAL_MARKDOWN_MODE_DEFAULT
        return cls.model_validate({**cls().model_dump(), **clean_data})

    def to_template_item(
        self, template_key: str, include_fields: set[str] | None = None
    ) -> dict[str, Any] | None:
        data = self.model_dump()
        default_data = type(self)().model_dump()
        if include_fields is not None:
            data = {key: value for key, value in data.items() if key in include_fields}
            default_data = {
                key: value
                for key, value in default_data.items()
                if key in include_fields
            }
        if data == default_data:
            return None
        return {"__template_key": template_key, **data}


def _first_strategy_template(data: Any, template_key: str) -> dict[str, Any] | None:
    if not isinstance(data, list):
        return None
    return next(
        (
            item
            for item in data
            if isinstance(item, dict) and item.get("__template_key") == template_key
        ),
        None,
    )


class SenderStrategiesConfig(BaseModel):
    """发送策略配置"""

    telegram: bool = Field(default=True, description="Telegram策略")
    aiocqhttp: bool = Field(default=True, description="QQ策略")
    qq_official: bool = Field(default=True, description="QQ官方策略")
    telegram_settings: PlatformSenderStrategyConfig = Field(
        default_factory=PlatformSenderStrategyConfig, alias="telegram_config"
    )
    aiocqhttp_settings: PlatformSenderStrategyConfig = Field(
        default_factory=PlatformSenderStrategyConfig, alias="aiocqhttp_config"
    )
    qq_official_settings: PlatformSenderStrategyConfig = Field(
        default_factory=PlatformSenderStrategyConfig, alias="qq_official_config"
    )

    @classmethod
    def from_config(cls, data: Any) -> SenderStrategiesConfig:
        if data is None:
            return cls()
        if isinstance(data, dict):
            known_values = dict.fromkeys(_SENDER_STRATEGY_KEYS, True)
            if "enabled_platforms" in data:
                enabled = _enabled_from_sender_config(data) or set()
                known_values.update(
                    {key: key in enabled for key in _SENDER_STRATEGY_KEYS}
                )
            else:
                known_values.update(
                    {
                        key: bool(value)
                        for key, value in data.items()
                        if key in _SENDER_STRATEGY_KEYS and isinstance(value, bool)
                    }
                )
            platform_strategies = data.get("platform_strategies")
            telegram_source = _first_strategy_template(
                platform_strategies,
                _PLATFORM_STRATEGY_TEMPLATE_KEYS["telegram"],
            )
            if telegram_source is None:
                telegram_source = data.get("telegram") or data.get("telegram_config")
            aiocqhttp_source = _first_strategy_template(
                platform_strategies,
                _PLATFORM_STRATEGY_TEMPLATE_KEYS["aiocqhttp"],
            )
            if aiocqhttp_source is None:
                aiocqhttp_source = data.get("aiocqhttp") or data.get("aiocqhttp_config")
            qq_official_source = _first_strategy_template(
                platform_strategies,
                _PLATFORM_STRATEGY_TEMPLATE_KEYS["qq_official"],
            )
            if qq_official_source is None:
                qq_official_value = data.get("qq_official")
                qq_official_config = data.get("qq_official_config")
                if isinstance(qq_official_value, dict):
                    qq_official_source = qq_official_value
                elif isinstance(qq_official_config, dict):
                    qq_official_source = qq_official_config
                else:
                    qq_official_source = (
                        qq_official_value
                        if qq_official_value is not None
                        else qq_official_config
                    )
            return cls.model_validate(
                {
                    **known_values,
                    PLATFORM_QQ_OFFICIAL: known_values[PLATFORM_QQ_OFFICIAL],
                    "telegram_config": PlatformSenderStrategyConfig.from_dict(
                        telegram_source
                    ),
                    "aiocqhttp_config": PlatformSenderStrategyConfig.from_dict(
                        aiocqhttp_source
                    ),
                    "qq_official_config": PlatformSenderStrategyConfig.from_dict(
                        qq_official_source
                    ),
                }
            )
        if isinstance(data, str):
            parts = data.replace(",", "\n").splitlines()
            enabled = {part.strip() for part in parts if part.strip()}
            return cls.from_enabled_platforms(enabled)
        if isinstance(data, (list, tuple, set)):
            enabled = {str(item).strip() for item in data if str(item).strip()}
            return cls.from_enabled_platforms(enabled)
        return cls.model_validate({**cls().model_dump(), **(data or {})})

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SenderStrategiesConfig:
        return cls.from_config(data)

    @classmethod
    def from_enabled_platforms(cls, enabled: set[str]) -> SenderStrategiesConfig:
        enabled = {item for item in enabled if item in _SENDER_STRATEGY_KEYS}
        return cls(**{key: key in enabled for key in _SENDER_STRATEGY_KEYS})

    def to_enabled_platforms(self) -> list[str]:
        return [key for key in _SENDER_STRATEGY_KEYS if getattr(self, key)]

    def to_config_dict(self) -> dict[str, Any]:
        platform_strategies = [
            item
            for item in (
                self.telegram_settings.to_template_item(
                    _PLATFORM_STRATEGY_TEMPLATE_KEYS["telegram"],
                    include_fields={
                        "enable_telegraph",
                        "telegraph_token",
                        "telegraph_proxy",
                    },
                ),
                self.aiocqhttp_settings.to_template_item(
                    _PLATFORM_STRATEGY_TEMPLATE_KEYS["aiocqhttp"],
                    include_fields={"napcat_stream_mode"},
                ),
                self.qq_official_settings.to_template_item(
                    _PLATFORM_STRATEGY_TEMPLATE_KEYS["qq_official"],
                    include_fields={"markdown_mode"},
                ),
            )
            if item is not None
        ]
        return {
            "enabled_platforms": self.to_enabled_platforms(),
            "platform_strategies": platform_strategies,
        }


def _enabled_from_sender_config(data: dict[str, Any]) -> set[str] | None:
    if "enabled_platforms" in data:
        raw = data.get("enabled_platforms")
        if isinstance(raw, str):
            return {
                part.strip()
                for part in raw.replace(",", "\n").splitlines()
                if part.strip()
            }
        if isinstance(raw, (list, tuple, set)):
            return {str(item).strip() for item in raw if str(item).strip()}
        return set()

    bool_keys = {
        key for key in _SENDER_STRATEGY_KEYS if isinstance(data.get(key), bool)
    }
    if bool_keys:
        return {key for key in bool_keys if bool(data.get(key))}
    return None
