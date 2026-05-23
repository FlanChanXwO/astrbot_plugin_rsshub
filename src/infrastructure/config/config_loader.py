"""Config loading and runtime settings adaptation."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from ...shared.constants import (
    INHERIT_VALUE,
    PLATFORM_ONEBOT,
    PLATFORM_QQ_OFFICIAL,
    PLATFORM_STRATEGY_TEMPLATE_KEYS,
    PLATFORM_TELEGRAM,
    SENDER_STRATEGY_ENABLED_PLATFORMS,
)
from .datamodels import (
    ApplicationSettings,
    BasicSettings,
    ContentHandlerSettings,
    FeedFetchSettings,
    FFmpegSettings,
    PlatformStrategySettings,
    RouteKnowledgeSettings,
    RsshubPluginConfig,
    RSSSettings,
    SchedulerSettings,
    SenderStrategiesConfig,
    SenderStrategySettings,
    SubscriptionDefaults,
)

if TYPE_CHECKING:
    from astrbot.api import AstrBotConfig

MAX_INTERVAL_MINUTES = 1440


_SCHEMA_DEFAULTS: dict[str, Any] = {
    "bool": False,
    "int": 0,
    "float": 0.0,
    "list": [],
    "object": {},
    "string": "",
    "template_list": [],
    "text": "",
}


def _get_value(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _normalize_proxy_url(value: Any) -> str:
    proxy = str(value or "").strip()
    if not proxy:
        return ""
    if "://" not in proxy:
        return f"http://{proxy}"
    return proxy


def _schema_default(meta: dict[str, Any]) -> Any:
    if "default" in meta:
        return deepcopy(meta["default"])
    meta_type = meta.get("type")
    if meta_type == "object":
        return {
            key: _schema_default(item)
            for key, item in (meta.get("items") or {}).items()
            if isinstance(item, dict)
        }
    return deepcopy(_SCHEMA_DEFAULTS.get(str(meta_type), None))


def _record_config_heal(changes: list[str], path: str, reason: str) -> None:
    changes.append(f"{path}: {reason}")


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _clamp_slider_value(
    value: int | float,
    meta: dict[str, Any],
    path: str,
    changes: list[str],
) -> int | float:
    slider = meta.get("slider")
    if not isinstance(slider, dict):
        return value
    minimum = slider.get("min")
    maximum = slider.get("max")
    if isinstance(minimum, (int, float)) and value < minimum:
        _record_config_heal(changes, path, "clamped to slider minimum")
        return minimum
    if isinstance(maximum, (int, float)) and value > maximum:
        _record_config_heal(changes, path, "clamped to slider maximum")
        return maximum
    return value


def _normalize_list_value(
    value: Any,
    meta: dict[str, Any],
    path: str,
    changes: list[str],
) -> list[Any]:
    if not isinstance(value, list):
        _record_config_heal(changes, path, "reset invalid list")
        return _schema_default(meta)

    options = meta.get("options")
    item_meta = meta.get("items")
    normalized: list[Any] = []
    item_changed = False
    for item in value:
        normalized_item = item
        if not isinstance(item_meta, dict):
            if not isinstance(item, str):
                item_changed = True
                continue
        else:
            item_type = item_meta.get("type")
            if item_type in {"string", "text"} and not isinstance(item, str):
                item_changed = True
                continue
            if item_type == "int":
                coerced = _coerce_int(item)
                if coerced is None:
                    item_changed = True
                    continue
                normalized_item = coerced
                item_changed = item_changed or coerced != item
            elif item_type == "float":
                coerced = _coerce_float(item)
                if coerced is None:
                    item_changed = True
                    continue
                normalized_item = coerced
                item_changed = item_changed or coerced != item
            elif item_type == "bool" and not isinstance(item, bool):
                item_changed = True
                continue

        if isinstance(options, list) and normalized_item not in options:
            item_changed = True
            continue
        normalized.append(normalized_item)

    if item_changed or len(normalized) != len(value):
        _record_config_heal(changes, path, "removed invalid list items")
    return normalized


def _normalize_template_list_value(
    value: Any,
    meta: dict[str, Any],
    path: str,
    changes: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _record_config_heal(changes, path, "reset invalid template_list")
        return _schema_default(meta)

    templates = meta.get("templates")
    if not isinstance(templates, dict):
        return [item for item in value if isinstance(item, dict)]

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            _record_config_heal(changes, item_path, "removed invalid template item")
            continue
        template_key = item.get("__template_key")
        template_meta = templates.get(template_key)
        if not isinstance(template_key, str) or not isinstance(template_meta, dict):
            _record_config_heal(changes, item_path, "removed unknown template item")
            continue
        template_items = template_meta.get("items")
        if not isinstance(template_items, dict):
            normalized.append({"__template_key": template_key})
            continue

        normalized_item = {"__template_key": template_key}
        for key, child_meta in template_items.items():
            child_path = f"{item_path}.{key}"
            if key in item:
                normalized_item[key] = _normalize_schema_value(
                    item[key],
                    child_meta,
                    child_path,
                    changes,
                )
            else:
                normalized_item[key] = _schema_default(child_meta)
                _record_config_heal(changes, child_path, "added missing default")
        for key in item:
            if key != "__template_key" and key not in template_items:
                _record_config_heal(
                    changes, f"{item_path}.{key}", "removed unknown key"
                )
        normalized.append(normalized_item)
    return normalized


def _normalize_schema_value(
    value: Any,
    meta: dict[str, Any],
    path: str,
    changes: list[str],
) -> Any:
    meta_type = meta.get("type")

    if value is None:
        _record_config_heal(changes, path, "reset null value")
        return _schema_default(meta)

    if meta_type == "object":
        if not isinstance(value, dict):
            _record_config_heal(changes, path, "reset invalid object")
            return _schema_default(meta)
        items = meta.get("items")
        if not isinstance(items, dict):
            return {}
        normalized: dict[str, Any] = {}
        for key, child_meta in items.items():
            child_path = f"{path}.{key}" if path else key
            if key in value:
                normalized[key] = _normalize_schema_value(
                    value[key],
                    child_meta,
                    child_path,
                    changes,
                )
            else:
                normalized[key] = _schema_default(child_meta)
                _record_config_heal(changes, child_path, "added missing default")
        for key in value:
            if key not in items:
                extra_path = f"{path}.{key}" if path else key
                _record_config_heal(changes, extra_path, "removed unknown key")
        return normalized

    if meta_type == "template_list":
        return _normalize_template_list_value(value, meta, path, changes)

    if meta_type == "list":
        return _normalize_list_value(value, meta, path, changes)

    if meta_type == "int":
        coerced = _coerce_int(value)
        if coerced is None:
            _record_config_heal(changes, path, "reset invalid int")
            return _schema_default(meta)
        if coerced != value:
            _record_config_heal(changes, path, "coerced int")
        return _clamp_slider_value(coerced, meta, path, changes)

    if meta_type == "float":
        coerced = _coerce_float(value)
        if coerced is None:
            _record_config_heal(changes, path, "reset invalid float")
            return _schema_default(meta)
        if coerced != value:
            _record_config_heal(changes, path, "coerced float")
        return _clamp_slider_value(coerced, meta, path, changes)

    if meta_type == "bool":
        if not isinstance(value, bool):
            _record_config_heal(changes, path, "reset invalid bool")
            return _schema_default(meta)
        return value

    if meta_type in {"string", "text"}:
        if not isinstance(value, str):
            _record_config_heal(changes, path, "reset invalid string")
            return _schema_default(meta)
        options = meta.get("options")
        if isinstance(options, list) and value not in options:
            _record_config_heal(changes, path, "reset invalid option")
            return _schema_default(meta)
        return value

    return value


def _apply_legacy_config_aliases(
    raw_config: dict[str, Any],
    changes: list[str],
) -> dict[str, Any]:
    normalized = deepcopy(raw_config)

    if "download_image_before_send" in normalized:
        normalized.pop("download_image_before_send", None)
        _record_config_heal(changes, "download_image_before_send", "removed legacy key")

    if "m3u8_download_timeout" in normalized:
        basic_config = normalized.setdefault("basic_config", {})
        if not isinstance(basic_config, dict):
            basic_config = {}
            normalized["basic_config"] = basic_config
            _record_config_heal(changes, "basic_config", "reset invalid object")
        basic_config["download_media_timeout"] = normalized.pop("m3u8_download_timeout")
        _record_config_heal(
            changes,
            "m3u8_download_timeout",
            "migrated to basic_config.download_media_timeout",
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
        _record_config_heal(
            changes,
            "sender_strategies",
            "normalized legacy sender strategy config",
        )

    return normalized


def heal_astrbot_plugin_config(
    raw_config: dict[str, Any] | None,
    schema: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Project raw AstrBot config onto the current plugin schema."""
    if raw_config is None:
        return {}, []
    if not isinstance(raw_config, dict) or not isinstance(schema, dict):
        return dict(raw_config or {}), []

    changes: list[str] = []
    aliased = _apply_legacy_config_aliases(raw_config, changes)
    normalized = _normalize_schema_value(
        aliased, {"type": "object", "items": schema}, "", changes
    )
    if normalized == raw_config:
        changes.clear()
    return normalized, changes


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = value.replace(",", "\n").splitlines()
        return tuple(part.strip() for part in parts if part.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _normalize_route_knowledge_base_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    old = "FlanChanXwO/astrbot_plugin_rsshub/rsshub-routes-knowledgebase"
    new = "FlanChanXwO/rsshub-routes-knowledgebase/main"
    return raw.replace(old, new)


_SENDER_STRATEGY_KEYS: tuple[str, ...] = SENDER_STRATEGY_ENABLED_PLATFORMS

_PLATFORM_STRATEGY_TEMPLATE_KEYS: dict[str, str] = PLATFORM_STRATEGY_TEMPLATE_KEYS


def _enabled_sender_strategy_names(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, dict) and "enabled_platforms" in value:
        return _enabled_sender_strategy_names(value.get("enabled_platforms"))
    if isinstance(value, str):
        return set(_as_tuple(value))
    if isinstance(value, (list, tuple, set)):
        return set(_as_tuple(value))
    return None


def _first_template_item(value: Any) -> Any:
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), None)
    return value


def _first_strategy_template(value: Any, template_key: str) -> Any:
    if not isinstance(value, list):
        return None
    return next(
        (
            item
            for item in value
            if isinstance(item, dict) and item.get("__template_key") == template_key
        ),
        None,
    )


def _build_sender_strategy_settings(value: Any) -> SenderStrategySettings:
    enabled = _enabled_sender_strategy_names(value)
    platform_strategies = _get_value(value, "platform_strategies", None)
    telegram_source = _first_strategy_template(
        platform_strategies,
        _PLATFORM_STRATEGY_TEMPLATE_KEYS["telegram"],
    )
    if not isinstance(telegram_source, dict):
        telegram_source = _first_template_item(_get_value(value, "telegram", None))
    if not isinstance(telegram_source, dict):
        telegram_source = _first_template_item(
            _get_value(value, "telegram_settings", None)
            or _get_value(value, "telegram_config", None)
        )
    aiocqhttp_source = _first_strategy_template(
        platform_strategies,
        _PLATFORM_STRATEGY_TEMPLATE_KEYS["aiocqhttp"],
    )
    if not isinstance(aiocqhttp_source, dict):
        aiocqhttp_source = _first_template_item(_get_value(value, "aiocqhttp", None))
    if not isinstance(aiocqhttp_source, dict):
        aiocqhttp_source = _first_template_item(
            _get_value(value, "aiocqhttp_settings", None)
            or _get_value(value, "aiocqhttp_config", None)
        )
    telegram_config = PlatformStrategySettings(
        enable_telegraph=bool(_get_value(telegram_source, "enable_telegraph", False)),
        telegraph_token=str(_get_value(telegram_source, "telegraph_token", "") or ""),
    )
    aiocqhttp_config = PlatformStrategySettings(
        prefer_local_video=bool(
            _get_value(aiocqhttp_source, "prefer_local_video", False)
        ),
    )
    if enabled is not None:
        enabled = {item for item in enabled if item in _SENDER_STRATEGY_KEYS}
        return SenderStrategySettings(
            **{key: key in enabled for key in _SENDER_STRATEGY_KEYS},
            telegram_settings=telegram_config,
            aiocqhttp_settings=aiocqhttp_config,
        )
    return SenderStrategySettings(
        telegram=bool(_get_value(value, PLATFORM_TELEGRAM, True)),
        aiocqhttp=bool(_get_value(value, PLATFORM_ONEBOT, True)),
        qq_official=bool(_get_value(value, PLATFORM_QQ_OFFICIAL, True)),
        telegram_settings=telegram_config,
        aiocqhttp_settings=aiocqhttp_config,
    )


def _build_content_handler_settings(value: Any) -> ContentHandlerSettings:
    return ContentHandlerSettings(
        ai_provider_id=str(_get_value(value, "ai_provider_id", "") or ""),
        ai_persona_id=str(_get_value(value, "ai_persona_id", "") or ""),
    )


def load_astrbot_plugin_config(raw: dict[str, Any] | None) -> RsshubPluginConfig:
    return RsshubPluginConfig.from_astrbot_config(raw)


def save_astrbot_plugin_config(
    config: RsshubPluginConfig,
    astrbot_config: AstrBotConfig,
) -> None:
    config.save(astrbot_config)


def build_application_settings(config: Any) -> ApplicationSettings:
    basic_cfg = _get_value(config, "basic_config")
    global_cfg = _get_value(config, "global_config")
    ffmpeg_cfg = _get_value(config, "ffmpeg")
    content_handlers_cfg = _get_value(config, "content_handlers")
    sender_cfg = _get_value(config, "sender_strategies")
    route_knowledge_cfg = _get_value(config, "route_knowledge")

    basic = BasicSettings(
        proxy=_normalize_proxy_url(
            _get_value(basic_cfg, "proxy", _get_value(config, "proxy", "")) or ""
        ),
        timeout=int(
            _get_value(basic_cfg, "timeout", _get_value(config, "timeout", 30)) or 30
        ),
        rsshub_base_url=str(
            _get_value(
                basic_cfg,
                "rsshub_base_url",
                _get_value(config, "rsshub_base_url", "https://rsshub.app"),
            )
            or "https://rsshub.app"
        ),
        minimal_interval=int(
            _get_value(
                basic_cfg,
                "minimal_interval",
                _get_value(config, "minimal_interval", 1),
            )
            or 1
        ),
        failed_queue_capacity=max(
            0,
            int(
                _get_value(
                    basic_cfg,
                    "failed_queue_capacity",
                    _get_value(config, "failed_queue_capacity", 50),
                )
                or 0
            ),
        ),
        failed_queue_max_retries=max(
            0,
            int(
                _get_value(
                    basic_cfg,
                    "failed_queue_max_retries",
                    _get_value(config, "failed_queue_max_retries", 3),
                )
                or 0
            ),
        ),
        deduplicate_multi_bot=bool(
            _get_value(
                basic_cfg,
                "deduplicate_multi_bot",
                _get_value(config, "deduplicate_multi_bot", True),
            )
        ),
        history_entry_limit=int(
            _get_value(
                basic_cfg,
                "history_entry_limit",
                _get_value(config, "history_entry_limit", 0),
            )
            or 0
        ),
        download_media_before_send=True,
        download_media_timeout=int(
            _get_value(
                basic_cfg,
                "download_media_timeout",
                _get_value(config, "download_media_timeout", 30),
            )
            or 30
        ),
    )

    return ApplicationSettings(
        basic=basic,
        fetch=FeedFetchSettings(
            timeout=basic.timeout,
            proxy=basic.proxy,
            rsshub_base_url=basic.rsshub_base_url,
        ),
        rss=RSSSettings(
            hash_history_min=int(_get_value(basic_cfg, "hash_history_min", 200) or 200),
            hash_history_multiplier=int(
                _get_value(basic_cfg, "hash_history_multiplier", 2) or 2
            ),
            hash_history_hard_limit=int(
                _get_value(basic_cfg, "hash_history_hard_limit", 5000) or 5000
            ),
            tracking_query_params=tuple(
                _get_value(basic_cfg, "tracking_query_params", []) or []
            ),
            bootstrap_skip_history=bool(
                _get_value(basic_cfg, "bootstrap_skip_history", True)
            ),
        ),
        scheduler=SchedulerSettings(
            default_interval=int(_get_value(global_cfg, "interval", 10) or 10),
            history_retention_days=max(
                1,
                int(
                    _get_value(
                        basic_cfg,
                        "history_retention_days",
                        _get_value(config, "history_retention_days", 30),
                    )
                    or 30
                ),
            ),
            history_entry_limit=basic.history_entry_limit,
        ),
        subscription_defaults=SubscriptionDefaults(
            interval=int(_get_value(global_cfg, "interval", 10) or 10),
            notify=bool(_get_value(global_cfg, "notify", True)),
            send_mode=str(_get_value(global_cfg, "send_mode", "自动") or "自动"),
            length_limit=int(_get_value(global_cfg, "length_limit", 0) or 0),
            display_author=str(
                _get_value(global_cfg, "display_author", "自动") or "自动"
            ),
            display_via=str(_get_value(global_cfg, "display_via", "自动") or "自动"),
            display_title=str(
                _get_value(global_cfg, "display_title", "自动") or "自动"
            ),
            display_entry_tags=bool(
                _get_value(global_cfg, "display_entry_tags", False)
            ),
            style=str(_get_value(global_cfg, "style", "auto") or "auto"),
            display_media=bool(_get_value(global_cfg, "display_media", True)),
        ),
        content_handlers=_build_content_handler_settings(content_handlers_cfg),
        sender_strategies=_build_sender_strategy_settings(sender_cfg),
        ffmpeg=FFmpegSettings(
            video_transcode=bool(_get_value(ffmpeg_cfg, "video_transcode", False)),
            video_transcode_timeout=max(
                1, int(_get_value(ffmpeg_cfg, "video_transcode_timeout", 120) or 120)
            ),
            gif_transcode=bool(_get_value(ffmpeg_cfg, "gif_transcode", False)),
            gif_transcode_timeout=max(
                1, int(_get_value(ffmpeg_cfg, "gif_transcode_timeout", 60) or 60)
            ),
        ),
        route_knowledge=RouteKnowledgeSettings(
            kb_name=str(
                _get_value(route_knowledge_cfg, "kb_name", "RSSHub Routes")
                or "RSSHub Routes"
            ),
            embedding_provider_id=str(
                _get_value(route_knowledge_cfg, "embedding_provider_id", "") or ""
            ),
            rerank_provider_id=str(
                _get_value(route_knowledge_cfg, "rerank_provider_id", "") or ""
            ),
            source_mode=str(
                _get_value(route_knowledge_cfg, "source_mode", "mirror") or "mirror"
            ),
            source_base_url=str(
                _normalize_route_knowledge_base_url(
                    _get_value(
                        route_knowledge_cfg,
                        "source_base_url",
                        RouteKnowledgeSettings.source_base_url,
                    )
                    or RouteKnowledgeSettings.source_base_url
                )
            ),
            fallback_base_url=str(
                _normalize_route_knowledge_base_url(
                    _get_value(
                        route_knowledge_cfg,
                        "fallback_base_url",
                        RouteKnowledgeSettings.fallback_base_url,
                    )
                    or RouteKnowledgeSettings.fallback_base_url
                )
            ),
            local_source_dir=str(
                _get_value(route_knowledge_cfg, "local_source_dir", "") or ""
            ),
            timeout=max(
                1, int(_get_value(route_knowledge_cfg, "timeout", basic.timeout) or 30)
            ),
            batch_size=max(
                1, int(_get_value(route_knowledge_cfg, "batch_size", 32) or 32)
            ),
            tasks_limit=max(
                1, int(_get_value(route_knowledge_cfg, "tasks_limit", 3) or 3)
            ),
            max_retries=max(
                0, int(_get_value(route_knowledge_cfg, "max_retries", 3) or 3)
            ),
        ),
    )


_config: RsshubPluginConfig | None = None


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
