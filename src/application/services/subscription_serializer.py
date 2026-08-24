"""订阅导入/导出工具模块

处理订阅配置的序列化和反序列化，支持 TOML 和 JSON 格式。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..dto.subscription_export_record import (
    SUBSCRIPTION_EXPORT_BOOL_FIELDS,
    SUBSCRIPTION_EXPORT_INT_FIELDS,
    SUBSCRIPTION_EXPORT_STRING_FIELDS,
    SubscriptionExportRecord,
)

EXPORT_FORMAT = "astrbot-rsshub-subscriptions"
EXPORT_VERSION = 2

# 导出时排除的字段（这些是运行时计算的）
EXPORT_EXCLUDED_FIELDS = {"id", "sid", "sub_id"}

STRING_FIELDS = SUBSCRIPTION_EXPORT_STRING_FIELDS
INT_FIELDS = SUBSCRIPTION_EXPORT_INT_FIELDS
BOOL_FIELDS = SUBSCRIPTION_EXPORT_BOOL_FIELDS


@dataclass
class ImportSubscriptionRecord:
    """导入订阅记录"""

    link: str
    feed_title: str | None = None
    options: dict[str, bool | int | str] = field(default_factory=dict)


@dataclass
class SubscriptionImportPayload:
    """订阅导入载荷"""

    records: list[ImportSubscriptionRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _toml_string(value: str) -> str:
    """将字符串序列化为 TOML 字符串"""
    return json.dumps(value, ensure_ascii=False)


def serialize_subscriptions_to_toml(
    *,
    user_id: str,
    records: list[SubscriptionExportRecord],
) -> str:
    """将用户订阅序列化为 TOML 文本

    Args:
        user_id: 用户 ID
        records: 导出读模型列表

    Returns:
        TOML 格式的订阅配置文本
    """
    lines = [
        f"format = {_toml_string(EXPORT_FORMAT)}",
        f"version = {EXPORT_VERSION}",
        f"exported_at = {_toml_string(datetime.now(timezone.utc).isoformat())}",
        f"user_id = {_toml_string(str(user_id))}",
        "",
    ]

    for record in records:
        if not record.link:
            continue
        lines.append("[[subscriptions]]")
        lines.append(f"link = {_toml_string(str(record.link))}")
        if record.feed_title:
            lines.append(f"feed_title = {_toml_string(str(record.feed_title))}")

        for key in sorted(STRING_FIELDS - {"feed_title"}):
            if key in EXPORT_EXCLUDED_FIELDS:
                continue
            value = record.options.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"{key} = {_toml_string(value)}")

        for key in sorted(INT_FIELDS):
            if key in EXPORT_EXCLUDED_FIELDS:
                continue
            value = record.options.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                lines.append(f"{key} = {value}")

        for key in sorted(BOOL_FIELDS):
            value = record.options.get(key)
            if isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _parse_int_value(
    raw: object,
    *,
    key: str,
    index: int,
    legacy_send_mode: bool = False,
) -> tuple[int | None, str | None]:
    """解析整数值

    Args:
        raw: 原始值
        key: 字段名
        index: 订阅索引

    Returns:
        (值, 错误信息) 元组
    """
    if isinstance(raw, bool):
        return None, f"subscriptions[{index}].{key} must be an integer"

    if isinstance(raw, int):
        if key == "send_mode" and legacy_send_mode:
            if raw == 2:
                return 1, None
            if raw == 1:
                return 0, None
        return raw, None

    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None, f"subscriptions[{index}].{key} cannot be empty"
        if not re.fullmatch(r"[+-]?\d+", stripped):
            return None, f"subscriptions[{index}].{key} must be an integer"
        parsed = int(stripped)
        if key == "send_mode" and legacy_send_mode:
            if parsed == 2:
                return 1, None
            if parsed == 1:
                return 0, None
        return parsed, None

    return None, f"subscriptions[{index}].{key} must be an integer"


def parse_subscriptions_toml(content: str) -> SubscriptionImportPayload:
    """解析和验证订阅导入 TOML 内容

    Args:
        content: TOML 文本内容

    Returns:
        SubscriptionImportPayload: 解析结果
    """
    payload = SubscriptionImportPayload()

    try:
        import tomllib

        data = tomllib.loads(content)
    except ImportError:
        # Python < 3.11
        try:
            import tomli as tomllib

            data = tomllib.loads(content)
        except ImportError:
            payload.errors.append("TOML parser not available. Install 'tomli' package.")
            return payload
    except Exception as ex:
        payload.errors.append(f"TOML parse failed: {ex}")
        return payload

    if not isinstance(data, dict):
        payload.errors.append("TOML root must be a table")
        return payload

    format_name = data.get("format")
    if format_name and format_name != EXPORT_FORMAT:
        payload.warnings.append(
            f"Unexpected format={format_name!r}; parser will try best-effort import"
        )

    version = data.get("version")
    if version is not None and version not in {1, EXPORT_VERSION}:
        payload.warnings.append(
            f"Unexpected version={version!r}; parser will try best-effort import"
        )
    legacy_send_mode = version in {None, 1}

    subs = data.get("subscriptions")
    if not isinstance(subs, list):
        payload.errors.append("Missing or invalid subscriptions array")
        return payload

    for i, raw in enumerate(subs, start=1):
        if not isinstance(raw, dict):
            payload.errors.append(f"subscriptions[{i}] must be a table")
            continue

        link = str(raw.get("link") or "").strip()
        if not link:
            payload.errors.append(f"subscriptions[{i}].link is required")
            continue
        if not re.match(r"^https?://", link, re.IGNORECASE):
            payload.errors.append(
                f"subscriptions[{i}].link must start with http:// or https://"
            )
            continue

        record = ImportSubscriptionRecord(link=link)

        # 警告 ID 字段会被忽略
        ID_FIELDS = {"id", "sid", "sub_id"}
        for id_field in ID_FIELDS:
            if id_field in raw:
                payload.warnings.append(
                    f"subscriptions[{i}].{id_field} is present but will be ignored; "
                    f"new ID will be generated by the current bot instance"
                )

        feed_title = raw.get("feed_title")
        if feed_title is not None:
            if not isinstance(feed_title, str):
                payload.errors.append(f"subscriptions[{i}].feed_title must be a string")
                continue
            title = feed_title.strip()
            if title:
                record.feed_title = title

        has_error = False
        for key in STRING_FIELDS - {"feed_title"}:
            if key not in raw:
                continue
            value = raw.get(key)
            if value is None:
                continue
            if key == "handlers":
                if isinstance(value, str):
                    normalized = value.strip()
                    if normalized:
                        record.options[key] = normalized
                        continue
                if isinstance(value, list):
                    record.options[key] = json.dumps(value, ensure_ascii=False)
                    continue
                payload.errors.append(
                    f"subscriptions[{i}].{key} must be a string or array"
                )
                has_error = True
                continue
            if key == "handlers_mode":
                if not isinstance(value, str):
                    payload.errors.append(f"subscriptions[{i}].{key} must be a string")
                    has_error = True
                    continue
                normalized = value.strip().lower()
                if normalized not in {"inherit", "override", "disabled"}:
                    payload.errors.append(
                        f"subscriptions[{i}].{key} must be one of: inherit, override, disabled"
                    )
                    has_error = True
                    continue
                record.options[key] = normalized
                continue
            if not isinstance(value, str):
                payload.errors.append(f"subscriptions[{i}].{key} must be a string")
                has_error = True
                continue
            normalized = value.strip()
            if normalized:
                record.options[key] = normalized

        for key in INT_FIELDS:
            if key not in raw:
                continue
            parsed, error = _parse_int_value(
                raw.get(key),
                key=key,
                index=i,
                legacy_send_mode=legacy_send_mode,
            )
            if error:
                payload.errors.append(error)
                has_error = True
                continue
            if parsed is not None:
                record.options[key] = parsed

        for key in BOOL_FIELDS:
            if key not in raw:
                continue
            value = raw.get(key)
            if not isinstance(value, bool):
                payload.errors.append(f"subscriptions[{i}].{key} must be a boolean")
                has_error = True
                continue
            record.options[key] = value

        if has_error:
            continue

        payload.records.append(record)

    return payload
