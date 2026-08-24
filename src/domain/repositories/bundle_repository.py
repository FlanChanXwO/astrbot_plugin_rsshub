"""Bundle 仓储协议。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from ..entities.bundle import Bundle
from ..entities.bundle_feed import BundleFeed


class BundleRepository(Protocol):
    """Bundle owner 与有序成员的持久化边界。"""

    async def get_by_id(self, bundle_id: int) -> Bundle | None: ...

    async def get_by_user(self, user_id: str) -> list[Bundle]: ...

    async def get_all_active(self) -> list[Bundle]: ...

    async def list_due(self, now: datetime) -> list[Bundle]: ...

    async def update_next_check_time(
        self,
        bundle_id: int,
        next_check_time: datetime,
    ) -> Bundle | None: ...

    async def save(self, bundle: Bundle) -> Bundle: ...

    async def delete(self, bundle_id: int) -> bool: ...

    async def list_members(self, bundle_id: int) -> list[BundleFeed]: ...

    async def add_member(
        self,
        bundle_id: int,
        feed_id: int,
        *,
        position: int | None = None,
    ) -> BundleFeed: ...

    async def replace_members(
        self,
        bundle_id: int,
        feed_ids: Sequence[int],
    ) -> list[BundleFeed]: ...

    async def remove_member(self, bundle_feed_id: int) -> bool: ...

    async def move_member(
        self, bundle_feed_id: int, position: int
    ) -> list[BundleFeed]: ...
