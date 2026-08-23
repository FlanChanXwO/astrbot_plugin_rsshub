"""可靠批次的 card→standard 输出编排状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from ...domain.entities.delivery import DeliveryBatch
from ...domain.entities.push_history import PushHistory
from ...domain.repositories.push_history_repository import PushHistoryRepository
from ..ports.message_sender import SendResult


class DeliveryOutputExecutor(Protocol):
    """执行一条已固化输出的系统边界。"""

    async def execute(self, history: PushHistory) -> SendResult:
        """渲染（如需要）并发送一条输出。"""
        ...


@dataclass(frozen=True, slots=True)
class OutputOrchestrationResult:
    """一次编排结束后的批次可观测状态。"""

    ready_to_confirm: bool
    attempted_history_ids: tuple[int, ...]


class OutputOrchestrator:
    """按 target 隔离执行，并把 card 作为 standard 的严格前置门。"""

    _CONFIRMED_OUTPUT_STATUSES = frozenset({"success", "skipped"})
    _TERMINAL_OUTPUT_STATUSES = frozenset({"success", "skipped", "discarded"})

    def __init__(
        self,
        history_repository: PushHistoryRepository,
        executor: DeliveryOutputExecutor,
    ) -> None:
        self._history_repository = history_repository
        self._executor = executor

    async def run(
        self,
        batch: DeliveryBatch,
        *,
        retry_failed: bool = False,
    ) -> OutputOrchestrationResult:
        """执行当前可运行输出；card 未成功或 skip 时保持 standard waiting。"""
        if not self._manifest_is_complete(batch):
            return OutputOrchestrationResult(
                ready_to_confirm=False,
                attempted_history_ids=(),
            )
        attempted: list[int] = []
        grouped: dict[str, list[PushHistory]] = {}
        for output in batch.outputs:
            grouped.setdefault(output.target_session or "", []).append(output)

        ordered_targets = list(batch.target_sessions)
        ordered_targets.extend(
            target for target in grouped if target not in batch.target_sessions
        )
        for target in ordered_targets:
            outputs = sorted(
                grouped.get(target, []), key=lambda item: item.output_order
            )
            cards = [output for output in outputs if output.output_kind == "card"]
            standards = [
                output for output in outputs if output.output_kind == "standard"
            ]
            gate_open = True
            for card in cards:
                if self._is_actionable(card, retry_failed=retry_failed):
                    await self._attempt(card)
                    if card.id is not None:
                        attempted.append(card.id)
                if card.status not in self._CONFIRMED_OUTPUT_STATUSES:
                    gate_open = False
                    break
            if not gate_open:
                continue
            for standard in standards:
                if self._is_actionable(standard, retry_failed=retry_failed):
                    await self._attempt(standard)
                    if standard.id is not None:
                        attempted.append(standard.id)

        return OutputOrchestrationResult(
            ready_to_confirm=self._manifest_is_complete(batch)
            and all(
                output.status in self._CONFIRMED_OUTPUT_STATUSES
                for output in batch.outputs
            ),
            attempted_history_ids=tuple(attempted),
        )

    @staticmethod
    def _manifest_is_complete(batch: DeliveryBatch) -> bool:
        expected = [
            (item.target_session, item.output_kind, item.output_order)
            for item in batch.output_manifest
        ]
        actual = [
            (output.target_session, output.output_kind, output.output_order)
            for output in batch.outputs
        ]
        return (
            bool(expected)
            and len(set(expected)) == len(expected)
            and set(expected) == set(actual)
            and len(actual) == len(expected)
        )

    async def discard(
        self,
        batch: DeliveryBatch,
        *,
        reason: str = "批次已显式丢弃",
    ) -> list[int]:
        """保留已完成输出，并终结批次内其余输出。"""
        discarded: list[int] = []
        for output in batch.outputs:
            if output.status in self._TERMINAL_OUTPUT_STATUSES:
                continue
            output.mark_discarded(reason)
            await self._history_repository.save(output)
            if output.id is not None:
                discarded.append(output.id)
        return discarded

    @staticmethod
    def _is_actionable(output: PushHistory, *, retry_failed: bool) -> bool:
        if output.status in {None, "waiting", "pending"}:
            return True
        if output.status == "retrying":
            return True
        return retry_failed and output.can_retry()

    async def _attempt(self, output: PushHistory) -> None:
        is_retry = output.status in {"failed", "retrying"}
        output.status = "retrying" if is_retry else "pending"
        output.completed_at = None
        output.updated_at = datetime.now(timezone.utc)
        await self._history_repository.save(output)
        try:
            result = await self._executor.execute(output)
        # 执行器是外部发送边界，必须把任意业务失败持久化后再继续同批其他输出。
        except Exception as exc:  # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"
            if is_retry:
                output.record_retry_failure(reason)
            else:
                output.record_first_failure(reason)
            await self._history_repository.save(output)
            return
        if result.ok:
            output.mark_success()
        elif is_retry:
            output.record_retry_failure(result.detail or "输出执行失败")
        else:
            output.record_first_failure(result.detail or "输出执行失败")
        await self._history_repository.save(output)
