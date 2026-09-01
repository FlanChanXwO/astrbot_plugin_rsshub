"""Handler chain entities and normalization helpers."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...shared.constants import (
    AiFilterInputScope,
    AiTransformScope,
    HandlerFieldType,
    HandlerStatus,
    HandlerType,
)

HANDLER_STATUS_INHERIT = int(HandlerStatus.INHERIT)
HANDLER_STATUS_DISABLED = int(HandlerStatus.DISABLED)
HANDLER_STATUS_ENABLED = int(HandlerStatus.ENABLED)
SUPPORTED_HANDLER_TYPES = {item.value for item in HandlerType}
SUPPORTED_HANDLER_FIELD_TYPES = {item.value for item in HandlerFieldType}


class HandlerConfigField(BaseModel):
    """Handler config field metadata."""

    key: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., description="字段类型")
    label: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=512)
    required: bool = False
    default: Any = None
    options: list[str] | None = None

    @property
    def name(self) -> str:
        """Frontend-friendly alias for key."""
        return self.key

    def normalized(self) -> HandlerConfigField:
        field_type = str(self.type or "").strip().lower()
        if field_type not in SUPPORTED_HANDLER_FIELD_TYPES:
            field_type = HandlerFieldType.JSON.value
        options = None
        if field_type == HandlerFieldType.SELECT.value:
            options = [
                str(item).strip() for item in (self.options or []) if str(item).strip()
            ]
        return HandlerConfigField(
            key=str(self.key or "").strip(),
            type=field_type,
            label=str(self.label or "").strip(),
            description=str(self.description or "").strip(),
            required=bool(self.required),
            default=self.default,
            options=options,
        )


class HandlerMetadata(BaseModel):
    """Runtime-visible handler registry metadata."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=64)
    type: str = Field(default="builtin")
    title: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=512)
    default_enabled: bool = False
    config_schema: list[HandlerConfigField] = Field(
        default_factory=list, alias="schema"
    )

    @property
    def display_name(self) -> str:
        """Public alias matching the handler spec wording."""
        return self.title

    @property
    def fields(self) -> list[HandlerConfigField]:
        """Frontend-friendly alias for schema."""
        return self.config_schema

    def normalized(self) -> HandlerMetadata:
        return HandlerMetadata(
            name=str(self.name or "").strip(),
            type=(
                str(self.type or HandlerType.BUILTIN.value).strip().lower()
                or HandlerType.BUILTIN.value
            ),
            title=str(self.title or "").strip(),
            description=str(self.description or "").strip(),
            default_enabled=bool(self.default_enabled),
            config_schema=[
                field.normalized() for field in self.config_schema if field.key
            ],
        )


BUILTIN_HANDLER_REGISTRY: dict[str, HandlerMetadata] = {
    "ai_filter": HandlerMetadata(
        name="ai_filter",
        title="AI 过滤",
        description="使用 AstrBot 当前 Provider 判断条目是否应该推送；返回 allow=false 时记录 skipped 且不发送。",
        default_enabled=True,
        config_schema=[
            HandlerConfigField(
                key="prompt",
                type="text",
                label="过滤要求",
                description="告诉 AI 应该保留或跳过什么内容。",
                required=True,
                default="",
            ),
            HandlerConfigField(
                key="input_scope",
                type="select",
                label="输入范围",
                description="text 使用清洗文本，raw_xml 使用原始 XML，both 同时使用。",
                default=AiFilterInputScope.TEXT.value,
                options=[item.value for item in AiFilterInputScope],
            ),
            HandlerConfigField(
                key="reason_max_length",
                type="int",
                label="原因最大长度",
                description="记录 AI 过滤原因时保留的最大字符数。",
                default=120,
            ),
        ],
    ),
    "ai_transform": HandlerMetadata(
        name="ai_transform",
        title="AI 改写",
        description="使用 AstrBot Agent 按提示改写文本，或在 xml scope 下改写完整 RSS item/entry XML。",
        default_enabled=True,
        config_schema=[
            HandlerConfigField(
                key="prompt",
                type="text",
                label="改写要求",
                description="例如总结为三条要点、清理广告、改写成中文摘要。",
                required=True,
                default="",
            ),
            HandlerConfigField(
                key="scope",
                type="select",
                label="改写范围",
                description="plaintext 改写 title/summary/content；xml 改写完整 raw_xml 并重新解析。",
                required=True,
                default=AiTransformScope.PLAINTEXT.value,
                options=[item.value for item in AiTransformScope],
            ),
        ],
    ),
    "ai_comment": HandlerMetadata(
        name="ai_comment",
        title="AI 评论",
        description="推送合并转发成功发送后，作为独立普通消息输出一段 AI 吐槽/观点/评论；绝不合并进转发记录。",
        default_enabled=False,
        config_schema=[
            HandlerConfigField(
                key="prompt",
                type="text",
                label="评论要求",
                description="告诉 AI 以什么口吻/角度评论这条推送。",
                required=True,
                default="",
            ),
            HandlerConfigField(
                key="with_media",
                type="bool",
                label="阅读图片",
                description="开启后使用图片描述模型读取条目图片，让评论能结合图片内容。",
                required=False,
                default=True,
            ),
        ],
    ),
}


class HandlerSpec(BaseModel):
    """Declarative content handler item."""

    id: str = Field(..., min_length=1, max_length=255, description="Handler 唯一标识")
    type: str = Field(default=HandlerType.BUILTIN.value, description="Handler 类型")
    name: str = Field(..., min_length=1, max_length=64, description="Handler 名称")
    status: int = Field(
        default=HANDLER_STATUS_INHERIT,
        description="状态: 1=启用, 0=禁用, -100=跟随默认值",
    )
    config: dict[str, Any] = Field(default_factory=dict, description="Handler 私有配置")

    def normalized(self) -> HandlerSpec:
        """Return a normalized copy."""
        handler_type = str(self.type or "").strip().lower() or HandlerType.BUILTIN.value
        if handler_type not in SUPPORTED_HANDLER_TYPES:
            handler_type = HandlerType.EXTERNAL.value

        status = self.status
        if status not in {
            HANDLER_STATUS_ENABLED,
            HANDLER_STATUS_DISABLED,
            HANDLER_STATUS_INHERIT,
        }:
            status = HANDLER_STATUS_INHERIT

        return HandlerSpec(
            id=str(self.id or "").strip(),
            type=handler_type,
            name=str(self.name or "").strip(),
            status=status,
            config=normalize_handler_config(self.name, self.config),
        )


def _normalize_handler_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, raw in value.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        normalized[normalized_key] = raw
    return normalized


def list_handler_registry() -> list[dict[str, Any]]:
    """Return builtin handler metadata for API/LLM clients."""
    return [
        _dump_handler_metadata(metadata.normalized())
        for metadata in BUILTIN_HANDLER_REGISTRY.values()
    ]


def get_handler_metadata(name: str) -> dict[str, Any] | None:
    """Return metadata for one builtin handler."""
    metadata = BUILTIN_HANDLER_REGISTRY.get(str(name or "").strip())
    return _dump_handler_metadata(metadata.normalized()) if metadata else None


def _dump_handler_metadata(metadata: HandlerMetadata) -> dict[str, Any]:
    """Dump metadata with both backend and frontend field aliases."""
    data = metadata.model_dump(by_alias=True)
    fields = []
    for field in metadata.config_schema:
        field_data = field.model_dump()
        field_data["name"] = field.key
        fields.append(field_data)
    data["display_name"] = metadata.title
    data["fields"] = fields
    data["schema"] = fields
    return data


def normalize_handler_config(name: str, value: Any) -> dict[str, Any]:
    """Normalize known builtin handler config against registry schema."""
    raw = _normalize_handler_config(value)
    metadata = BUILTIN_HANDLER_REGISTRY.get(str(name or "").strip())
    if metadata is None:
        return raw

    normalized: dict[str, Any] = {}
    for field in metadata.normalized().config_schema:
        raw_value = raw.get(field.key, field.default)
        if raw_value is None and not field.required:
            continue
        normalized[field.key] = _coerce_handler_config_value(field, raw_value)
    if str(name or "").strip() == "ai_transform":
        normalized.setdefault("scope", AiTransformScope.PLAINTEXT.value)
    if str(name or "").strip() == "ai_filter":
        normalized.setdefault("input_scope", AiFilterInputScope.TEXT.value)
    if str(name or "").strip() == "ai_comment":
        normalized.setdefault("with_media", True)
    return normalized


def _coerce_handler_config_value(
    field: HandlerConfigField,
    value: Any,
) -> Any:
    field_type = field.type
    if field_type in {HandlerFieldType.STRING.value, HandlerFieldType.TEXT.value}:
        normalized = str(value or "").strip()
        if field.required and not normalized:
            raise ValueError(f"{field.key} 不能为空")
        return normalized
    if field_type == HandlerFieldType.BOOL.value:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "on", "启用", "是"}:
            return True
        if text in {"0", "false", "no", "off", "禁用", "否", ""}:
            return False
        raise ValueError(f"{field.key} 必须是布尔值")
    if field_type == HandlerFieldType.INT.value:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field.key} 必须是整数") from exc
    if field_type == HandlerFieldType.FLOAT.value:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field.key} 必须是数字") from exc
    if field_type == HandlerFieldType.SELECT.value:
        normalized = str(value or field.default or "").strip()
        options = field.options or []
        if options and normalized not in options:
            raise ValueError(f"{field.key} 必须是以下之一: {', '.join(options)}")
        return normalized
    if field_type == HandlerFieldType.LIST_STRING.value:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                parsed = [part.strip() for part in value.split(",")]
            value = parsed
        if not isinstance(value, list):
            raise ValueError(f"{field.key} 必须是字符串数组")
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception as exc:
            raise ValueError(f"{field.key} 必须是合法 JSON") from exc
    return value


def _generate_handler_id(name: str, handler_type: str, seen_ids: set[str]) -> str:
    """为缺少 id 的 handler 生成稳定 id（前端 helpers.js 与之保持一致）。"""
    base = f"builtin.{name}" if handler_type == "builtin" else name
    candidate = base
    suffix = 2
    while candidate in seen_ids:
        candidate = f"{base}.{suffix}"
        suffix += 1
    return candidate


def normalize_handlers(value: Any) -> list[HandlerSpec]:
    """Normalize stored handler payload to validated list."""
    if value is None or value == "":
        return []

    payload = value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            payload = json.loads(stripped)
        except Exception:
            return []

    if not isinstance(payload, list):
        return []

    normalized: list[HandlerSpec] = []
    seen_ids: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw = dict(item)
        name = str(raw.get("name", "") or "").strip()
        if not name:
            continue
        # id 缺失时由 name 生成，避免粘贴的 handler 被静默丢弃
        if not str(raw.get("id", "") or "").strip():
            handler_type = (
                str(raw.get("type", "") or "").strip().lower() or HandlerType.BUILTIN.value
            )
            raw["id"] = _generate_handler_id(name, handler_type, seen_ids)
        try:
            spec = HandlerSpec.model_validate(raw).normalized()
        except Exception:
            continue
        if not spec.id or not spec.name or spec.id in seen_ids:
            continue
        if spec.type == HandlerType.BUILTIN.value and spec.name == "xml_parse":
            continue
        seen_ids.add(spec.id)
        normalized.append(spec)
    return normalized


def validate_handlers(value: Any) -> list[HandlerSpec]:
    """Normalize and validate user-provided handler payload strictly."""
    if value is None or value == "":
        return []
    payload = value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        payload = json.loads(stripped)
    if not isinstance(payload, list):
        raise ValueError("handlers 必须是 JSON 数组")

    normalized: list[HandlerSpec] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"handlers[{index}] 必须是 JSON 对象")
        spec = HandlerSpec.model_validate(item).normalized()
        if not spec.id or not spec.name:
            raise ValueError(f"handlers[{index}] 缺少 id/name")
        if spec.type == HandlerType.BUILTIN.value and spec.name == "xml_parse":
            continue
        if spec.id in seen_ids:
            raise ValueError(f"重复 handler id: {spec.id}")
        seen_ids.add(spec.id)
        normalized.append(spec)
    return normalized


def dump_handlers(value: Any) -> list[dict[str, Any]]:
    """Dump handler payload to stable JSON-serializable list."""
    return [spec.model_dump() for spec in normalize_handlers(value)]


def handlers_json(value: Any) -> str:
    """Serialize handlers to compact stable JSON for persistence."""
    return json.dumps(dump_handlers(value), ensure_ascii=False, separators=(",", ":"))


def parse_handlers_input(value: Any) -> list[dict[str, Any]]:
    """Parse user-provided handler payload and raise on invalid non-empty input."""
    if value is None:
        return []
    if isinstance(value, list):
        return dump_handlers(value)

    normalized = str(value or "").strip()
    if not normalized:
        return []

    try:
        payload = json.loads(normalized)
    except Exception as exc:
        raise ValueError("handlers 必须是合法 JSON 数组") from exc

    return [spec.model_dump() for spec in validate_handlers(payload)]


def handler_default_enabled(name: str) -> bool:
    """Return the default enabled state for a builtin handler."""
    metadata = BUILTIN_HANDLER_REGISTRY.get(str(name or "").strip())
    return bool(metadata.default_enabled) if metadata is not None else False


def is_handler_enabled(spec: HandlerSpec | dict[str, Any]) -> bool:
    """Resolve the runtime enabled state for a handler spec."""
    normalized = (
        spec
        if isinstance(spec, HandlerSpec)
        else HandlerSpec.model_validate(spec).normalized()
    )
    if normalized.status == HANDLER_STATUS_ENABLED:
        return True
    if normalized.status == HANDLER_STATUS_DISABLED:
        return False
    return handler_default_enabled(normalized.name)


def build_ai_transform_handler(prompt: str) -> list[dict[str, Any]]:
    """Build migrated default AI transform handler from legacy ai_prompt."""
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        return []
    return [
        {
            "id": "builtin.ai_transform.default",
            "type": HandlerType.BUILTIN.value,
            "name": "ai_transform",
            "status": HANDLER_STATUS_ENABLED,
            "config": {
                "prompt": normalized_prompt,
                "scope": AiTransformScope.PLAINTEXT.value,
            },
        }
    ]


DEFAULT_AI_COMMENT_PROMPT = (
    "以 bot 自己的口吻，像群里的朋友一样，对这条推送发表一句简短自然的吐槽或看法。"
)


def build_ai_comment_handler(
    prompt: str = DEFAULT_AI_COMMENT_PROMPT,
) -> list[dict[str, Any]]:
    """Build a default-enabled ai_comment handler.

    Used by the LLM ``rss_subscribe`` tool when the user did not explicitly
    decline comments: the subscription gets its own snapshot of the user's
    global handlers plus this enabled ai_comment handler.
    """
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        return []
    return [
        {
            "id": "builtin.ai_comment.default",
            "type": HandlerType.BUILTIN.value,
            "name": "ai_comment",
            "status": HANDLER_STATUS_ENABLED,
            "config": {
                "prompt": normalized_prompt,
                "with_media": True,
            },
        }
    ]
