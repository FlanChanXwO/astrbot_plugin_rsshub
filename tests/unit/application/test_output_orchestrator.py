"""可靠批次输出编排状态机测试。"""

import asyncio
from datetime import datetime, timezone

import pytest
from astrbot_plugin_rsshub.src.application.ports.message_sender import SendResult
from astrbot_plugin_rsshub.src.application.services.output_orchestrator import (
    OutputOrchestrator,
)
from astrbot_plugin_rsshub.src.domain.entities.delivery import (
    DeliveryBatch,
    DeliveryOutputIdentity,
    DeliveryOwner,
)
from astrbot_plugin_rsshub.src.domain.entities.push_history import PushHistory


class RecordingHistoryRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[int | None, str | None]] = []

    async def save(self, history: PushHistory) -> PushHistory:
        self.saved.append((history.id, history.status))
        return history


class RecordingDeliveryRepository:
    def __init__(self, result: DeliveryBatch) -> None:
        self.result = result
        self.discard_calls: list[tuple[int, str | None]] = []

    async def discard_batch(
        self,
        batch_id: int,
        *,
        reason: str | None = None,
    ) -> DeliveryBatch:
        self.discard_calls.append((batch_id, reason))
        return self.result


class ScriptedOutputExecutor:
    def __init__(self, results: dict[int, list[SendResult]]) -> None:
        self.results = results
        self.calls: list[int] = []

    async def execute(self, history: PushHistory) -> SendResult:
        assert history.id is not None
        self.calls.append(history.id)
        return self.results[history.id].pop(0)


def _history(
    history_id: int,
    kind: str,
    order: int,
    *,
    status: str = "waiting",
) -> PushHistory:
    return PushHistory(
        id=history_id,
        user_id="user",
        target_session="platform:GroupMessage:1",
        output_kind=kind,
        output_order=order,
        status=status,
    )


def _batch(outputs: list[PushHistory]) -> DeliveryBatch:
    return DeliveryBatch(
        id=1,
        owner=DeliveryOwner(owner_type="subscription", owner_id=1),
        status="pending",
        created_at=datetime.now(timezone.utc),
        target_sessions=["platform:GroupMessage:1"],
        output_manifest=[
            DeliveryOutputIdentity(
                target_session=output.target_session or "",
                output_kind=output.output_kind,
                output_order=output.output_order,
            )
            for output in outputs
        ],
        outputs=outputs,
    )


@pytest.mark.asyncio
async def test_card_gate_partial_success_and_retry_are_isolated_per_output() -> None:
    card = _history(1, "card", 0)
    standard_1 = _history(2, "standard", 1)
    standard_2 = _history(3, "standard", 2)
    standard_3 = _history(4, "standard", 3)
    batch = _batch([standard_3, card, standard_2, standard_1])
    repository = RecordingHistoryRepository()
    executor = ScriptedOutputExecutor(
        {
            1: [SendResult(ok=False, detail="card failed"), SendResult(ok=True)],
            2: [SendResult(ok=True)],
            3: [
                SendResult(ok=False, detail="entry failed"),
                SendResult(ok=False, detail="retry failed"),
                SendResult(ok=True),
            ],
            4: [SendResult(ok=True)],
        }
    )
    orchestrator = OutputOrchestrator(
        repository,
        executor,
        RecordingDeliveryRepository(batch),
    )

    first = await orchestrator.run(batch)

    assert executor.calls == [1]
    assert card.status == "failed"
    assert [standard_1.status, standard_2.status, standard_3.status] == [
        "waiting",
        "waiting",
        "waiting",
    ]
    assert first.ready_to_confirm is False

    second = await orchestrator.run(batch, retry_failed=True)

    assert executor.calls == [1, 1, 2, 3, 4]
    assert [output.status for output in (card, standard_1, standard_2, standard_3)] == [
        "success",
        "success",
        "failed",
        "success",
    ]
    assert second.ready_to_confirm is False

    third = await orchestrator.run(batch, retry_failed=True)

    assert executor.calls == [1, 1, 2, 3, 4, 3]
    assert third.ready_to_confirm is False
    assert standard_2.retry_count == 1

    fourth = await orchestrator.run(batch, retry_failed=True)

    assert executor.calls == [1, 1, 2, 3, 4, 3, 3]
    assert fourth.ready_to_confirm is True


@pytest.mark.asyncio
async def test_discard_delegates_the_whole_batch_to_delivery_repository() -> None:
    failed = _history(1, "card", 0, status="failed")
    waiting = _history(2, "standard", 1)
    success = _history(3, "standard", 2, status="success")
    pending_batch = _batch([failed, waiting, success])
    discarded_batch = pending_batch.model_copy(update={"status": "discarded"})
    history_repository = RecordingHistoryRepository()
    delivery_repository = RecordingDeliveryRepository(discarded_batch)
    orchestrator = OutputOrchestrator(
        history_repository,
        ScriptedOutputExecutor({}),
        delivery_repository,
    )

    result = await orchestrator.discard(pending_batch, reason="用户明确丢弃")

    assert result is discarded_batch
    assert delivery_repository.discard_calls == [(pending_batch.id, "用户明确丢弃")]
    assert history_repository.saved == []


@pytest.mark.asyncio
async def test_missing_manifest_output_never_reports_ready_to_confirm() -> None:
    success = _history(1, "card", 0, status="success")
    batch = _batch([success])
    batch.output_manifest.append(
        DeliveryOutputIdentity(
            target_session="platform:GroupMessage:1",
            output_kind="standard",
            output_order=1,
        )
    )
    orchestrator = OutputOrchestrator(
        RecordingHistoryRepository(),
        ScriptedOutputExecutor({}),
        RecordingDeliveryRepository(batch),
    )

    result = await orchestrator.run(batch)

    assert result.ready_to_confirm is False


@pytest.mark.asyncio
async def test_output_outside_manifest_is_not_executed() -> None:
    expected = _history(1, "card", 0, status="success")
    unexpected = _history(2, "standard", 1)
    batch = _batch([expected])
    batch.outputs.append(unexpected)
    executor = ScriptedOutputExecutor({2: [SendResult(ok=True)]})
    orchestrator = OutputOrchestrator(
        RecordingHistoryRepository(),
        executor,
        RecordingDeliveryRepository(batch),
    )

    result = await orchestrator.run(batch)

    assert result.ready_to_confirm is False
    assert executor.calls == []
    assert unexpected.status == "waiting"


@pytest.mark.asyncio
async def test_cancelled_output_is_persisted_as_stopped_and_blocks_confirmation() -> (
    None
):
    history = _history(1, "standard", 0)
    batch = _batch([history])
    executor = ScriptedOutputExecutor(
        {1: [SendResult(ok=False, cancelled=True, detail="queue stopped")]}
    )
    orchestrator = OutputOrchestrator(
        RecordingHistoryRepository(),
        executor,
        RecordingDeliveryRepository(batch),
    )

    result = await orchestrator.run(batch)

    assert result.ready_to_confirm is False
    assert history.status == "stopped"
    assert history.fail_reason == "queue stopped"


@pytest.mark.asyncio
async def test_runtime_cancellation_persists_stopped_before_propagating() -> None:
    history = _history(1, "standard", 0)
    batch = _batch([history])

    class RuntimeCancellationExecutor:
        async def execute(self, _history: PushHistory) -> SendResult:
            raise asyncio.CancelledError

    repository = RecordingHistoryRepository()
    orchestrator = OutputOrchestrator(
        repository,
        RuntimeCancellationExecutor(),
        RecordingDeliveryRepository(batch),
    )

    with pytest.raises(asyncio.CancelledError):
        await orchestrator.run(batch)

    assert history.status == "stopped"
    assert history.fail_reason == "运行关闭，输出已取消"
    assert repository.saved[-1] == (1, "stopped")


@pytest.mark.asyncio
async def test_manual_retry_can_reuse_an_exhausted_output() -> None:
    history = _history(1, "standard", 0, status="failed")
    history.retry_count = history.max_retries
    batch = _batch([history])
    executor = ScriptedOutputExecutor({1: [SendResult(ok=True)]})
    orchestrator = OutputOrchestrator(
        RecordingHistoryRepository(),
        executor,
        RecordingDeliveryRepository(batch),
    )

    result = await orchestrator.run(batch, retry_failed=True, force_retry=True)

    assert result.ready_to_confirm is True
    assert executor.calls == [1]
    assert history.status == "success"


@pytest.mark.asyncio
async def test_manual_retry_failure_does_not_consume_automatic_retry_budget() -> None:
    history = _history(1, "standard", 0, status="failed")
    history.retry_count = history.max_retries
    batch = _batch([history])
    executor = ScriptedOutputExecutor({1: [SendResult(ok=False, detail="仍然失败")]})
    orchestrator = OutputOrchestrator(
        RecordingHistoryRepository(),
        executor,
        RecordingDeliveryRepository(batch),
    )

    result = await orchestrator.run(batch, retry_failed=True, force_retry=True)

    assert result.ready_to_confirm is False
    assert history.status == "failed"
    assert history.retry_count == history.max_retries


@pytest.mark.asyncio
async def test_manual_retry_does_not_resend_resolved_outputs() -> None:
    history = _history(1, "standard", 0, status="success")
    batch = _batch([history])
    executor = ScriptedOutputExecutor({})
    orchestrator = OutputOrchestrator(
        RecordingHistoryRepository(),
        executor,
        RecordingDeliveryRepository(batch),
    )

    result = await orchestrator.run(batch, retry_failed=True, force_retry=True)

    assert result.ready_to_confirm is True
    assert executor.calls == []
