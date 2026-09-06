"""Bundle 成员及其私有采集水位领域实体。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .feed import normalize_entry_hashes


class BundleFeed(BaseModel):
    """Bundle 中一个有序 Feed 成员的持久化状态。"""

    id: int | None = Field(default=None, description="BundleFeed ID")
    bundle_id: int = Field(gt=0, description="Bundle ID")
    feed_id: int = Field(gt=0, description="Feed ID")
    position: int = Field(ge=0, description="成员顺序，从 0 开始")
    entry_hashes: list[list[str]] | None = Field(
        default=None,
        description="成员私有条目哈希水位",
    )
    etag: str | None = Field(default=None, description="成员私有 ETag")
    last_modified: datetime | None = Field(
        default=None,
        description="成员私有 Last-Modified",
    )
    last_check_status: str | None = Field(default=None, description="最近检查状态")
    last_checked_at: datetime | None = Field(default=None, description="最近检查时间")

    @field_validator("entry_hashes", mode="before")
    @classmethod
    def _normalize_entry_hashes(cls, value: Any) -> list[list[str]] | None:
        return normalize_entry_hashes(value)
