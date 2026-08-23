"""可靠投递仓储协议。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..entities.delivery import (
    DeliveryBatch,
    DeliveryBatchDraft,
    DeliveryInboxItem,
    DeliveryInboxItemDraft,
    DeliveryOwner,
    InboxStoreResult,
)
from ..entities.push_history import PushHistory


class DeliveryOwnerNotFoundError(LookupError):
    """指定的可靠投递 owner 不存在。"""


class DeliverySourceMismatchError(ValueError):
    """inbox 来源不属于给定 owner。"""


class DeliveryBatchConflictError(RuntimeError):
    """owner 已有未解决批次。"""


class DeliveryInboxEmptyError(RuntimeError):
    """没有可供批次认领的 inbox 条目。"""


class DeliveryOutputMismatchError(ValueError):
    """输出历史与批次 owner 或目标不一致。"""


class DeliveryBatchNotFoundError(LookupError):
    """投递批次不存在。"""


class DeliveryBatchNotReadyError(RuntimeError):
    """批次仍包含未完成输出，不能确认。"""

    def __init__(self, batch_id: int, blocking_statuses: dict[str, int]) -> None:
        self.batch_id = batch_id
        self.blocking_statuses = blocking_statuses
        super().__init__(f"批次 {batch_id} 尚未完成: {blocking_statuses}")


class DeliveryConsistencyError(RuntimeError):
    """数据库中出现仓储正常路径不可能生成的投递状态。"""


class DeliveryDeletionBlockedError(RuntimeError):
    """未解决批次或 inbox 阻止 owner/成员删除。"""

    def __init__(self, blocker_counts: dict[str, int]) -> None:
        self.blocker_counts = blocker_counts
        super().__init__(f"可靠投递数据尚未消费: {blocker_counts}")


class DeliveryRepository(Protocol):
    """统一 inbox 与批次事务的持久化边界。"""

    async def store_inbox_items(
        self,
        owner: DeliveryOwner,
        items: Sequence[DeliveryInboxItemDraft],
    ) -> InboxStoreResult: ...

    async def list_inbox_items(
        self,
        owner: DeliveryOwner,
        *,
        claimed: bool | None = None,
    ) -> list[DeliveryInboxItem]: ...

    async def claim_batch(
        self,
        owner: DeliveryOwner,
        batch: DeliveryBatchDraft,
        outputs: Sequence[PushHistory],
        *,
        item_ids: Sequence[int] | None = None,
    ) -> DeliveryBatch: ...

    async def get_batch(self, batch_id: int) -> DeliveryBatch | None: ...

    async def get_pending_batch(self, owner: DeliveryOwner) -> DeliveryBatch | None: ...

    async def confirm_batch(self, batch_id: int) -> DeliveryBatch: ...

    async def discard_batch(
        self,
        batch_id: int,
        *,
        reason: str | None = None,
    ) -> DeliveryBatch: ...

    async def reconcile_batch(self, batch_id: int) -> DeliveryBatch: ...

    async def ensure_owner_deletable(self, owner: DeliveryOwner) -> None: ...

    async def ensure_bundle_member_removable(self, bundle_feed_id: int) -> None: ...

    async def delete_owner(self, owner: DeliveryOwner) -> bool: ...

    async def remove_bundle_member(self, bundle_feed_id: int) -> bool: ...
