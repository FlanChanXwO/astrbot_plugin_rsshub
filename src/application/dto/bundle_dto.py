"""Bundle 对外传输对象。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BundleMemberDTO(BaseModel):
    """Bundle 成员及其私有采集状态摘要。"""

    model_config = ConfigDict(frozen=True)

    id: int | None = None
    bundle_id: int
    feed_id: int
    position: int = Field(ge=0)
    last_check_status: str | None = None
    last_checked_at: datetime | None = None


class BundleDTO(BaseModel):
    """Bundle owner 的稳定 JSON 传输契约。"""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    id: int | None = None
    user_id: str
    name: str
    target_sessions: list[str]
    interval: int
    state: int = Field(ge=0, le=1)
    next_check_time: datetime | None = None
    notify: int
    send_mode: int
    length_limit: int
    display_author: int
    display_via: int
    display_title: int
    display_entry_tags: int
    style: int
    display_media: int
    handlers: list[dict[str, Any]] = Field(default_factory=list)
    send_card: bool = False
    template_id: str | None = None
    card_send_original_content: bool = False
    created_at: datetime
    updated_at: datetime
