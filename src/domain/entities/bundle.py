"""多源聚合订阅领域实体。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...shared.constants import INHERIT_VALUE
from .handlers import dump_handlers


class Bundle(BaseModel):
    """保存多源聚合 owner 的基础配置。"""

    model_config = ConfigDict(populate_by_name=True)

    id: int | None = Field(default=None, description="数据库 ID")
    user_id: str = Field(..., description="用户 ID")
    name: str = Field(..., min_length=1, description="聚合订阅名称")
    target_sessions: list[str] = Field(
        ...,
        min_length=1,
        description="有序推送目标会话",
    )
    interval: int = Field(..., gt=0, description="固定滚动周期（分钟）")
    state: int = Field(default=0, ge=0, le=1, description="状态: 0=停用, 1=启用")
    next_check_time: datetime | None = Field(default=None, description="下次检查时间")
    notify: int = Field(default=INHERIT_VALUE, description="是否通知")
    send_mode: int = Field(default=INHERIT_VALUE, description="发送模式")
    length_limit: int = Field(default=INHERIT_VALUE, description="长度限制")
    display_author: int = Field(default=INHERIT_VALUE, description="显示作者")
    display_via: int = Field(default=INHERIT_VALUE, description="显示来源")
    display_title: int = Field(default=INHERIT_VALUE, description="显示标题")
    display_entry_tags: int = Field(default=INHERIT_VALUE, description="显示标签")
    style: int = Field(default=INHERIT_VALUE, description="推送排版策略")
    display_media: int = Field(default=INHERIT_VALUE, description="显示媒体")
    handler_specs: Any = Field(
        default_factory=list,
        alias="handlers",
        description="Bundle 文档级 handlers",
    )
    send_card: bool = Field(default=False, description="是否发送模板卡片")
    template_id: str | None = Field(default=None, description="卡片模板 ID")
    card_send_original_content: bool = Field(
        default=False,
        description="卡片发送成功后是否继续发送聚合内容",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="更新时间",
    )

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Bundle name must not be blank")
        return normalized

    @field_validator("target_sessions", mode="before")
    @classmethod
    def _normalize_target_sessions(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_target in value:
            target = str(raw_target or "").strip()
            if target and target not in seen:
                normalized.append(target)
                seen.add(target)
        return normalized

    @model_validator(mode="before")
    @classmethod
    def _normalize_handlers_field(cls, value: Any) -> Any:
        if isinstance(value, dict):
            payload = dict(value)
            raw_handlers = payload.get("handlers", payload.get("handler_specs"))
            normalized_handlers = dump_handlers(raw_handlers)
            # Pydantic 同时收到 alias 与字段名时优先 alias，因此统一写回 alias。
            payload.pop("handler_specs", None)
            payload["handlers"] = normalized_handlers
            return payload
        return value

    @property
    def handlers(self) -> list[dict[str, Any]]:
        """返回规范化的文档级 handlers。"""
        return dump_handlers(self.handler_specs)
