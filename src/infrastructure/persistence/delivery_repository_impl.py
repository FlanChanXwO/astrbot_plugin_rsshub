"""统一可靠投递仓储的 SQLite 实现。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import delete, func, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import asc, select

from ...domain.entities.delivery import (
    DeliveryBatch,
    DeliveryBatchDraft,
    DeliveryInboxItem,
    DeliveryInboxItemDraft,
    DeliveryOwner,
    InboxStoreResult,
)
from ...domain.entities.push_history import PushHistory, normalize_fail_reason
from ...domain.repositories.delivery_repository import (
    DeliveryBatchConflictError,
    DeliveryBatchNotFoundError,
    DeliveryBatchNotReadyError,
    DeliveryConsistencyError,
    DeliveryDeletionBlockedError,
    DeliveryInboxEmptyError,
    DeliveryOutputMismatchError,
    DeliveryOwnerNotFoundError,
    DeliveryRepository,
    DeliverySourceMismatchError,
)
from .database import DatabaseManager, get_database
from .models import (
    BundleFeedORM,
    BundleORM,
    DeliveryBatchORM,
    DeliveryInboxItemORM,
    PushHistoryORM,
    SubORM,
)
from .push_history_repository_impl import PushHistoryRepositoryImpl


class DeliveryRepositoryImpl:
    """通过数据库唯一键与事务提供可靠入箱语义。"""

    def __init__(self, database: DatabaseManager | None = None) -> None:
        self._database = database

    @property
    def _db(self) -> DatabaseManager:
        return self._database or get_database()

    async def store_inbox_items(
        self,
        owner: DeliveryOwner,
        items: Sequence[DeliveryInboxItemDraft],
    ) -> InboxStoreResult:
        async with self._db.get_session() as session:
            await self._validate_sources(session, owner, items)
            inserted_count = 0
            for item in items:
                values = item.model_dump()
                values.update(
                    owner_type=owner.owner_type,
                    owner_id=owner.owner_id,
                )
                result = await session.execute(
                    sqlite_insert(DeliveryInboxItemORM)
                    .values(**values)
                    .on_conflict_do_nothing(
                        index_elements=("owner_type", "owner_id", "feed_id", "item_key")
                    )
                )
                inserted_count += int(result.rowcount or 0)
            await session.commit()

        return InboxStoreResult(
            inserted_count=inserted_count,
            duplicate_count=len(items) - inserted_count,
        )

    async def list_inbox_items(
        self,
        owner: DeliveryOwner,
        *,
        claimed: bool | None = None,
    ) -> list[DeliveryInboxItem]:
        async with self._db.get_session() as session:
            await self._get_owner_record(session, owner)
            statement = select(DeliveryInboxItemORM).where(
                DeliveryInboxItemORM.owner_type == owner.owner_type,
                DeliveryInboxItemORM.owner_id == owner.owner_id,
            )
            if claimed is True:
                statement = statement.where(DeliveryInboxItemORM.batch_id.is_not(None))
            elif claimed is False:
                statement = statement.where(DeliveryInboxItemORM.batch_id.is_(None))
            result = await session.execute(
                statement.order_by(
                    asc(DeliveryInboxItemORM.discovered_at),
                    asc(DeliveryInboxItemORM.id),
                )
            )
            return [self._to_inbox_item(orm) for orm in result.scalars().all()]

    async def claim_batch(
        self,
        owner: DeliveryOwner,
        batch: DeliveryBatchDraft,
        outputs: Sequence[PushHistory],
        *,
        item_ids: Sequence[int] | None = None,
    ) -> DeliveryBatch:
        if not outputs:
            raise DeliveryOutputMismatchError("可靠批次至少需要一条输出历史")
        if owner.owner_type == "bundle" and item_ids is None:
            raise DeliverySourceMismatchError("Bundle 批次必须显式指定 inbox 条目")
        if owner.owner_type == "subscription" and item_ids is not None:
            raise DeliverySourceMismatchError(
                "Subscription 批次按 discovery 边界认领，不能显式指定条目"
            )

        async with self._db.get_session() as session:
            try:
                # SQLite 没有行级锁；写事务在读取前获取保留锁，确保并发 worker
                # 依次观察 pending 唯一约束与 inbox 认领结果。
                await session.execute(text("BEGIN IMMEDIATE"))
                owner_record = await self._get_owner_record(session, owner)
                self._validate_outputs(owner, owner_record, batch, outputs)
                pending = (
                    await session.execute(
                        select(DeliveryBatchORM.id).where(
                            DeliveryBatchORM.owner_type == owner.owner_type,
                            DeliveryBatchORM.owner_id == owner.owner_id,
                            DeliveryBatchORM.status == "pending",
                        )
                    )
                ).scalar_one_or_none()
                if pending is not None:
                    raise DeliveryBatchConflictError(f"owner 已有未解决批次: {pending}")

                inbox_orms = await self._select_claimable_items(
                    session, owner, item_ids=item_ids
                )
                if not inbox_orms:
                    raise DeliveryInboxEmptyError("owner 没有未认领的 inbox 条目")

                batch_orm = DeliveryBatchORM(
                    owner_type=owner.owner_type,
                    owner_id=owner.owner_id,
                    status="pending",
                    output_manifest=[
                        {
                            "target_session": output.target_session,
                            "output_kind": output.output_kind,
                            "output_order": output.output_order,
                        }
                        for output in outputs
                    ],
                    **batch.model_dump(),
                )
                session.add(batch_orm)
                await session.flush()
                for inbox_orm in inbox_orms:
                    inbox_orm.batch_id = batch_orm.id

                history_orms: list[PushHistoryORM] = []
                for output in outputs:
                    history_orm = PushHistoryRepositoryImpl._to_orm(output)
                    history_orm.batch_id = batch_orm.id
                    session.add(history_orm)
                    history_orms.append(history_orm)
                await session.flush()
                await self._after_claim(session, batch_orm)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

            return self._to_batch(batch_orm, inbox_orms, history_orms)

    async def get_batch(self, batch_id: int) -> DeliveryBatch | None:
        async with self._db.get_session() as session:
            batch_orm = await session.get(DeliveryBatchORM, batch_id)
            if batch_orm is None:
                return None
            inbox_orms, history_orms = await self._load_batch_members(session, batch_id)
            return self._to_batch(batch_orm, inbox_orms, history_orms)

    async def get_pending_batch(self, owner: DeliveryOwner) -> DeliveryBatch | None:
        async with self._db.get_session() as session:
            await self._get_owner_record(session, owner)
            batch_orm = (
                await session.execute(
                    select(DeliveryBatchORM).where(
                        DeliveryBatchORM.owner_type == owner.owner_type,
                        DeliveryBatchORM.owner_id == owner.owner_id,
                        DeliveryBatchORM.status == "pending",
                    )
                )
            ).scalar_one_or_none()
            if batch_orm is None:
                return None
            inbox_orms, history_orms = await self._load_batch_members(
                session, batch_orm.id
            )
            return self._to_batch(batch_orm, inbox_orms, history_orms)

    async def confirm_batch(self, batch_id: int) -> DeliveryBatch:
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                batch_orm = await session.get(DeliveryBatchORM, batch_id)
                if batch_orm is None:
                    raise DeliveryBatchNotFoundError(f"投递批次不存在: {batch_id}")
                inbox_orms, history_orms = await self._load_batch_members(
                    session, batch_id
                )
                self._validate_persisted_batch(batch_orm, inbox_orms, history_orms)
                if batch_orm.status == "confirmed":
                    await session.commit()
                    return self._to_batch(batch_orm, inbox_orms, history_orms)
                if batch_orm.status == "discarded":
                    raise DeliveryConsistencyError("已丢弃批次不能确认")
                blockers = Counter(
                    str(history.status or "null")
                    for history in history_orms
                    if history.status not in {"success", "skipped"}
                )
                if blockers:
                    raise DeliveryBatchNotReadyError(batch_id, dict(blockers))

                batch_orm.status = "confirmed"
                batch_orm.confirmed_at = datetime.now(timezone.utc)
                await session.execute(
                    delete(DeliveryInboxItemORM).where(
                        DeliveryInboxItemORM.batch_id == batch_id
                    )
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

            return self._to_batch(batch_orm, [], history_orms)

    async def discard_batch(
        self,
        batch_id: int,
        *,
        reason: str | None = None,
    ) -> DeliveryBatch:
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                batch_orm = await session.get(DeliveryBatchORM, batch_id)
                if batch_orm is None:
                    raise DeliveryBatchNotFoundError(f"投递批次不存在: {batch_id}")
                inbox_orms, history_orms = await self._load_batch_members(
                    session, batch_id
                )
                self._validate_persisted_batch(batch_orm, inbox_orms, history_orms)
                if batch_orm.status == "discarded":
                    await session.commit()
                    return self._to_batch(batch_orm, inbox_orms, history_orms)
                if batch_orm.status == "confirmed":
                    raise DeliveryConsistencyError("已确认批次不能丢弃")
                now = datetime.now(timezone.utc)
                normalized_reason = normalize_fail_reason(reason)
                for history in history_orms:
                    if history.status not in {"success", "skipped", "discarded"}:
                        history.status = "discarded"
                        history.fail_reason = normalized_reason
                        history.completed_at = now
                        history.updated_at = now
                batch_orm.status = "discarded"
                await session.execute(
                    delete(DeliveryInboxItemORM).where(
                        DeliveryInboxItemORM.batch_id == batch_id
                    )
                )
                await self._after_discard(session, batch_orm)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

            return self._to_batch(batch_orm, [], history_orms)

    async def reconcile_batch(self, batch_id: int) -> DeliveryBatch:
        """修复可证明安全的状态，其余不可能状态显式报错。"""
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                batch_orm = await session.get(DeliveryBatchORM, batch_id)
                if batch_orm is None:
                    raise DeliveryBatchNotFoundError(f"投递批次不存在: {batch_id}")
                inbox_orms, history_orms = await self._load_batch_members(
                    session, batch_id
                )
                self._validate_persisted_batch(
                    batch_orm,
                    inbox_orms,
                    history_orms,
                    allow_resolved_inbox=True,
                )

                if batch_orm.status == "pending":
                    if all(
                        history.status in {"success", "skipped"}
                        for history in history_orms
                    ):
                        batch_orm.status = "confirmed"
                        batch_orm.confirmed_at = datetime.now(timezone.utc)
                        await session.execute(
                            delete(DeliveryInboxItemORM).where(
                                DeliveryInboxItemORM.batch_id == batch_id
                            )
                        )
                        inbox_orms = []
                elif inbox_orms:
                    # resolved 批次残留的已认领输入必然已经消费，删除是可证明的修复。
                    await session.execute(
                        delete(DeliveryInboxItemORM).where(
                            DeliveryInboxItemORM.batch_id == batch_id
                        )
                    )
                    inbox_orms = []
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
            return self._to_batch(batch_orm, inbox_orms, history_orms)

    async def ensure_owner_deletable(self, owner: DeliveryOwner) -> None:
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                await self._get_owner_record(session, owner)
                pending_count = int(
                    (
                        await session.execute(
                            select(func.count())
                            .select_from(DeliveryBatchORM)
                            .where(
                                DeliveryBatchORM.owner_type == owner.owner_type,
                                DeliveryBatchORM.owner_id == owner.owner_id,
                                DeliveryBatchORM.status == "pending",
                            )
                        )
                    ).scalar_one()
                )
                counts = await self._owner_inbox_counts(session, owner)
                if pending_count:
                    counts["pending_batch"] = pending_count
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        if counts:
            raise DeliveryDeletionBlockedError(counts)

    async def ensure_bundle_member_removable(self, bundle_feed_id: int) -> None:
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                member = await session.get(BundleFeedORM, bundle_feed_id)
                if member is None:
                    raise DeliveryOwnerNotFoundError(
                        f"Bundle 成员不存在: {bundle_feed_id}"
                    )
                rows = (
                    await session.execute(
                        select(
                            DeliveryInboxItemORM.batch_id,
                            func.count(),
                        )
                        .where(DeliveryInboxItemORM.bundle_feed_id == bundle_feed_id)
                        .group_by(DeliveryInboxItemORM.batch_id)
                    )
                ).all()
                counts = self._claim_state_counts(rows)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        if counts:
            raise DeliveryDeletionBlockedError(counts)

    async def delete_owner(self, owner: DeliveryOwner) -> bool:
        """在同一写事务内检查可靠数据并删除 owner。"""
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                model = SubORM if owner.owner_type == "subscription" else BundleORM
                record = await session.get(model, owner.owner_id)
                if record is None:
                    await session.commit()
                    return False
                counts = await self._owner_inbox_counts(session, owner)
                pending_count = int(
                    (
                        await session.execute(
                            select(func.count())
                            .select_from(DeliveryBatchORM)
                            .where(
                                DeliveryBatchORM.owner_type == owner.owner_type,
                                DeliveryBatchORM.owner_id == owner.owner_id,
                                DeliveryBatchORM.status == "pending",
                            )
                        )
                    ).scalar_one()
                )
                if pending_count:
                    counts["pending_batch"] = pending_count
                if counts:
                    raise DeliveryDeletionBlockedError(counts)

                # 已解决历史独立保留；解除 owner 外键而不删除审计记录。
                history_owner_column = (
                    PushHistoryORM.sub_id
                    if owner.owner_type == "subscription"
                    else PushHistoryORM.bundle_id
                )
                await session.execute(
                    update(PushHistoryORM)
                    .where(history_owner_column == owner.owner_id)
                    .values({history_owner_column.key: None})
                )
                await session.delete(record)
                await session.commit()
                return True
            except BaseException:
                await session.rollback()
                raise

    async def remove_bundle_member(self, bundle_feed_id: int) -> bool:
        """在同一写事务内检查 inbox、删除成员并压紧 position。"""
        async with self._db.get_session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                member = await session.get(BundleFeedORM, bundle_feed_id)
                if member is None:
                    await session.commit()
                    return False
                rows = (
                    await session.execute(
                        select(DeliveryInboxItemORM.batch_id, func.count())
                        .where(DeliveryInboxItemORM.bundle_feed_id == bundle_feed_id)
                        .group_by(DeliveryInboxItemORM.batch_id)
                    )
                ).all()
                counts = self._claim_state_counts(rows)
                if counts:
                    raise DeliveryDeletionBlockedError(counts)
                bundle_id = member.bundle_id
                removed_position = member.position
                await session.delete(member)
                await session.flush()
                await session.execute(
                    update(BundleFeedORM)
                    .where(
                        BundleFeedORM.bundle_id == bundle_id,
                        BundleFeedORM.position > removed_position,
                    )
                    .values(position=BundleFeedORM.position - 1)
                )
                await session.commit()
                return True
            except BaseException:
                await session.rollback()
                raise

    @staticmethod
    async def _owner_inbox_counts(session, owner):
        rows = (
            await session.execute(
                select(DeliveryInboxItemORM.batch_id, func.count())
                .where(
                    DeliveryInboxItemORM.owner_type == owner.owner_type,
                    DeliveryInboxItemORM.owner_id == owner.owner_id,
                )
                .group_by(DeliveryInboxItemORM.batch_id)
            )
        ).all()
        return DeliveryRepositoryImpl._claim_state_counts(rows)

    @staticmethod
    def _claim_state_counts(rows):
        counts: dict[str, int] = {}
        for batch_id, count in rows:
            key = "unclaimed_inbox" if batch_id is None else "claimed_inbox"
            counts[key] = counts.get(key, 0) + int(count)
        return counts

    @staticmethod
    def _validate_persisted_batch(
        batch,
        inbox_items,
        histories,
        *,
        allow_resolved_inbox: bool = False,
    ) -> None:
        if not histories:
            raise DeliveryConsistencyError("投递批次缺少输出历史")
        expected_outputs = [
            (
                item.get("target_session"),
                item.get("output_kind"),
                item.get("output_order"),
            )
            for item in batch.output_manifest
        ]
        actual_outputs = [
            (history.target_session, history.output_kind, history.output_order)
            for history in histories
        ]
        if (
            not expected_outputs
            or len(expected_outputs) != len(set(expected_outputs))
            or Counter(actual_outputs) != Counter(expected_outputs)
        ):
            raise DeliveryConsistencyError("投递批次输出历史与输出清单不一致")
        if any(
            item.owner_type != batch.owner_type or item.owner_id != batch.owner_id
            for item in inbox_items
        ):
            raise DeliveryConsistencyError("投递批次 inbox 归属不匹配")
        if batch.owner_type == "subscription":
            history_owner_mismatch = any(
                history.sub_id != batch.owner_id or history.bundle_id is not None
                for history in histories
            )
        else:
            history_owner_mismatch = any(
                history.bundle_id != batch.owner_id or history.sub_id is not None
                for history in histories
            )
        if history_owner_mismatch:
            raise DeliveryConsistencyError("投递批次输出历史归属不匹配")
        history_targets = {history.target_session for history in histories}
        missing_targets = set(batch.target_sessions) - history_targets
        if missing_targets:
            raise DeliveryConsistencyError(
                f"投递批次缺少目标输出: {sorted(missing_targets)}"
            )
        extra_targets = history_targets - set(batch.target_sessions)
        if extra_targets:
            raise DeliveryConsistencyError(
                f"投递批次包含未知目标输出: {sorted(extra_targets)}"
            )
        identities = [
            (history.target_session, history.output_kind, history.output_order)
            for history in histories
        ]
        if len(identities) != len(set(identities)):
            raise DeliveryConsistencyError("投递批次包含重复输出身份")
        DeliveryRepositoryImpl._validate_output_layout(
            batch.target_sessions,
            batch.config_snapshot,
            histories,
            DeliveryConsistencyError,
        )
        if batch.status == "pending" and not inbox_items:
            raise DeliveryConsistencyError("pending 批次缺少已认领 inbox")
        if (
            batch.status in {"confirmed", "discarded"}
            and inbox_items
            and not allow_resolved_inbox
        ):
            raise DeliveryConsistencyError("resolved 批次仍保留已认领 inbox")
        if batch.status == "confirmed" and any(
            history.status not in {"success", "skipped"} for history in histories
        ):
            raise DeliveryConsistencyError("confirmed 批次包含未完成输出")
        if batch.status == "discarded" and any(
            history.status not in {"success", "skipped", "discarded"}
            for history in histories
        ):
            raise DeliveryConsistencyError("discarded 批次包含未处理输出")

    @staticmethod
    async def _load_batch_members(session, batch_id):
        inbox_result = await session.execute(
            select(DeliveryInboxItemORM)
            .where(DeliveryInboxItemORM.batch_id == batch_id)
            .order_by(asc(DeliveryInboxItemORM.id))
        )
        history_result = await session.execute(
            select(PushHistoryORM)
            .where(PushHistoryORM.batch_id == batch_id)
            .order_by(
                asc(PushHistoryORM.target_session),
                asc(PushHistoryORM.output_order),
                asc(PushHistoryORM.id),
            )
        )
        return (
            list(inbox_result.scalars().all()),
            list(history_result.scalars().all()),
        )

    async def _select_claimable_items(self, session, owner, *, item_ids):
        statement = select(DeliveryInboxItemORM).where(
            DeliveryInboxItemORM.owner_type == owner.owner_type,
            DeliveryInboxItemORM.owner_id == owner.owner_id,
            DeliveryInboxItemORM.batch_id.is_(None),
        )
        if owner.owner_type == "subscription":
            oldest = (
                await session.execute(
                    statement.order_by(
                        asc(DeliveryInboxItemORM.discovered_at),
                        asc(DeliveryInboxItemORM.id),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if oldest is None:
                return []
            statement = statement.where(
                DeliveryInboxItemORM.discovery_key == oldest.discovery_key
            )
        elif item_ids is not None:
            normalized_ids = sorted({int(item_id) for item_id in item_ids})
            if not normalized_ids:
                return []
            statement = statement.where(DeliveryInboxItemORM.id.in_(normalized_ids))

        result = await session.execute(
            statement.order_by(
                asc(DeliveryInboxItemORM.member_position),
                asc(DeliveryInboxItemORM.discovered_at),
                asc(DeliveryInboxItemORM.id),
            )
        )
        items = list(result.scalars().all())
        if owner.owner_type == "bundle" and item_ids is not None:
            expected_ids = {int(item_id) for item_id in item_ids}
            if {item.id for item in items} != expected_ids:
                raise DeliverySourceMismatchError(
                    "指定的 Bundle inbox 条目不存在、已认领或属于其他 owner"
                )
        return items

    @staticmethod
    async def _get_owner_record(session, owner):
        model = SubORM if owner.owner_type == "subscription" else BundleORM
        record = await session.get(model, owner.owner_id)
        if record is None:
            raise DeliveryOwnerNotFoundError(
                f"{owner.owner_type} owner 不存在: {owner.owner_id}"
            )
        return record

    @staticmethod
    def _validate_outputs(owner, owner_record, batch, outputs) -> None:
        identities: set[tuple[str | None, str, int]] = set()
        for output in outputs:
            identity = (output.target_session, output.output_kind, output.output_order)
            if identity in identities:
                raise DeliveryOutputMismatchError("批次输出身份重复")
            identities.add(identity)
            owner_matches = (
                output.sub_id == owner.owner_id and output.bundle_id is None
                if owner.owner_type == "subscription"
                else output.bundle_id == owner.owner_id and output.sub_id is None
            )
            if (
                output.id is not None
                or output.batch_id is not None
                or not owner_matches
                or output.user_id != owner_record.user_id
                or output.target_session not in batch.target_sessions
                or output.status not in {"waiting", "pending", "skipped"}
            ):
                raise DeliveryOutputMismatchError(
                    "输出历史与批次 owner、目标或初始状态不匹配"
                )
        represented_targets = {output.target_session for output in outputs}
        if represented_targets != set(batch.target_sessions):
            raise DeliveryOutputMismatchError("每个批次目标必须至少有一条输出历史")
        DeliveryRepositoryImpl._validate_output_layout(
            batch.target_sessions,
            batch.config_snapshot,
            outputs,
            DeliveryOutputMismatchError,
        )

    @staticmethod
    def _validate_output_layout(
        target_sessions,
        config_snapshot,
        outputs,
        error_type,
    ) -> None:
        for target_session in target_sessions:
            target_outputs = [
                output for output in outputs if output.target_session == target_session
            ]
            cards = [
                output for output in target_outputs if output.output_kind == "card"
            ]
            if len(cards) > 1:
                raise error_type(
                    f"每个批次目标最多只能有一条 card 输出: {target_session}"
                )
            if config_snapshot.get("send_card") is True and not cards:
                raise error_type(
                    f"send_card=true 时每个批次目标必须有一条 card 输出: {target_session}"
                )
            if config_snapshot.get("send_card") is False and cards:
                raise error_type(
                    f"send_card=false 时批次目标不能有 card 输出: {target_session}"
                )
            if cards and (
                cards[0].output_order != 0
                or any(
                    output.output_order <= cards[0].output_order
                    for output in target_outputs
                    if output.output_kind != "card"
                )
            ):
                raise error_type(
                    f"card 输出必须是目标的 order=0 首条输出: {target_session}"
                )

    @staticmethod
    async def _after_claim(_session, _batch) -> None:
        """故障注入接缝；生产实现不执行额外动作。"""

    @staticmethod
    async def _after_discard(_session, _batch) -> None:
        """故障注入接缝；生产实现不执行额外动作。"""

    @staticmethod
    async def _validate_sources(session, owner, items) -> None:
        if owner.owner_type == "subscription":
            subscription = await session.get(SubORM, owner.owner_id)
            if subscription is None:
                raise DeliveryOwnerNotFoundError(
                    f"Subscription owner 不存在: {owner.owner_id}"
                )
            for item in items:
                if (
                    item.feed_id != subscription.feed_id
                    or item.bundle_feed_id is not None
                    or item.member_position is not None
                ):
                    raise DeliverySourceMismatchError("Subscription inbox 来源不匹配")
            return

        bundle = await session.get(BundleORM, owner.owner_id)
        if bundle is None:
            raise DeliveryOwnerNotFoundError(f"Bundle owner 不存在: {owner.owner_id}")
        for item in items:
            member = (
                await session.get(BundleFeedORM, item.bundle_feed_id)
                if item.bundle_feed_id is not None
                else None
            )
            if (
                member is None
                or member.bundle_id != bundle.id
                or member.feed_id != item.feed_id
                or item.member_position is None
                or member.position != item.member_position
            ):
                raise DeliverySourceMismatchError("Bundle inbox 来源不匹配")

    @staticmethod
    def _to_inbox_item(orm: DeliveryInboxItemORM) -> DeliveryInboxItem:
        return DeliveryInboxItem(
            id=orm.id,
            owner=DeliveryOwner(owner_type=orm.owner_type, owner_id=orm.owner_id),
            feed_id=orm.feed_id,
            bundle_feed_id=orm.bundle_feed_id,
            member_position=orm.member_position,
            item_key=orm.item_key,
            hash_group=orm.hash_group,
            discovery_key=orm.discovery_key,
            entry_payload=orm.entry_payload,
            raw_xml=orm.raw_xml,
            media_items=orm.media_items,
            published_at=DeliveryRepositoryImpl._as_utc(orm.published_at),
            entry_updated_at=DeliveryRepositoryImpl._as_utc(orm.entry_updated_at),
            discovered_at=DeliveryRepositoryImpl._as_utc(orm.discovered_at),
            batch_id=orm.batch_id,
        )

    @classmethod
    def _to_batch(cls, orm, inbox_orms, history_orms) -> DeliveryBatch:
        return DeliveryBatch(
            id=orm.id,
            owner=DeliveryOwner(owner_type=orm.owner_type, owner_id=orm.owner_id),
            status=orm.status,
            target_sessions=orm.target_sessions,
            config_snapshot=orm.config_snapshot,
            template_snapshot=orm.template_snapshot,
            document_snapshot=orm.document_snapshot,
            created_at=cls._as_utc(orm.created_at),
            confirmed_at=cls._as_utc(orm.confirmed_at),
            output_manifest=orm.output_manifest,
            inbox_items=[cls._to_inbox_item(item) for item in inbox_orms],
            outputs=[
                PushHistoryRepositoryImpl._to_entity(history)
                for history in history_orms
            ],
        )

    @staticmethod
    def _as_utc(value):
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)


_delivery_repository: DeliveryRepositoryImpl | None = None


def get_delivery_repository() -> DeliveryRepository:
    """返回进程内共享的可靠投递仓储。"""
    global _delivery_repository
    if _delivery_repository is None:
        _delivery_repository = DeliveryRepositoryImpl()
    return _delivery_repository
