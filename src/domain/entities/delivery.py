"""可靠投递 inbox 与批次的领域数据契约。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .push_history import PushHistory

DeliveryOwnerType = Literal["subscription", "bundle"]


class DeliveryOwner(BaseModel):
    """可靠投递数据的多态 owner 引用。"""

    model_config = ConfigDict(frozen=True)

    owner_type: DeliveryOwnerType
    owner_id: int = Field(gt=0)


class DeliveryInboxItemDraft(BaseModel):
    """尚未持久化的 inbox 条目快照。"""

    feed_id: int = Field(gt=0)
    bundle_feed_id: int | None = Field(default=None, gt=0)
    member_position: int | None = Field(default=None, ge=0)
    item_key: str
    hash_group: list[str] = Field(default_factory=list)
    discovery_key: str
    entry_payload: dict[str, Any] = Field(default_factory=dict)
    raw_xml: str | None = None
    media_items: list[dict[str, Any]] = Field(default_factory=list)
    published_at: datetime | None = None
    entry_updated_at: datetime | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("item_key", "discovery_key")
    @classmethod
    def _require_non_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("投递条目标识不能为空")
        return value


class DeliveryInboxItem(DeliveryInboxItemDraft):
    """已持久化的 inbox 条目。"""

    id: int = Field(gt=0)
    owner: DeliveryOwner
    batch_id: int | None = Field(default=None, gt=0)


class SubscriptionInboxDiscovery(BaseModel):
    """一个卡片 Subscription 在单次 Feed 发现中的完整 inbox fan-out。"""

    owner: DeliveryOwner
    items: list[DeliveryInboxItemDraft] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_single_subscription_discovery(self) -> SubscriptionInboxDiscovery:
        if self.owner.owner_type != "subscription":
            raise ValueError("Subscription discovery owner 必须是 subscription")
        discovery_keys = {item.discovery_key for item in self.items}
        if len(discovery_keys) != 1:
            raise ValueError("Subscription discovery items 必须共享 discovery_key")
        return self


class InboxStoreResult(BaseModel):
    """一次幂等入箱的可观测结果。"""

    inserted_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)


class DeliveryBatchDraft(BaseModel):
    """创建批次时固化的配置快照。"""

    target_sessions: list[str] = Field(min_length=1)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    template_snapshot: dict[str, Any] | None = None
    document_snapshot: dict[str, Any] | None = None

    @field_validator("target_sessions")
    @classmethod
    def _require_non_blank_unique_targets(cls, value: list[str]) -> list[str]:
        if any(not target.strip() for target in value):
            raise ValueError("目标会话不能为空")
        if len(set(value)) != len(value):
            raise ValueError("目标会话不能重复")
        return value


class DeliveryOutputIdentity(BaseModel):
    """用于检测输出历史缺失的不可变身份。"""

    model_config = ConfigDict(frozen=True)

    target_session: str
    output_kind: Literal["card", "standard"]
    output_order: int = Field(ge=0)


class DeliveryBatch(DeliveryBatchDraft):
    """包含已认领输入与输出历史的可靠投递批次。"""

    id: int = Field(gt=0)
    owner: DeliveryOwner
    status: Literal["pending", "confirmed", "discarded"]
    created_at: datetime
    confirmed_at: datetime | None = None
    output_manifest: list[DeliveryOutputIdentity]
    inbox_items: list[DeliveryInboxItem] = Field(default_factory=list)
    outputs: list[PushHistory] = Field(default_factory=list)
