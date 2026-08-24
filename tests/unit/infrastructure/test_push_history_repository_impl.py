from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.domain.entities.push_history import (
    MAX_FAIL_REASON_LENGTH,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence import (
    push_history_repository_impl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import (
    RSSHubBaseModel,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.models import (
    DeliveryBatchORM,
    PushHistoryORM,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.push_history_repository_impl import (
    PushHistoryRepositoryImpl,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_to_entity_truncates_overlong_legacy_fail_reason_without_crashing():
    now = datetime.now(timezone.utc)
    orm = PushHistoryORM(
        id=1,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="content",
        entry_title="entry title",
        entry_link="https://example.com/entry",
        feed_title="feed title",
        feed_link="https://example.com/feed",
        status="failed",
        retry_count=0,
        max_retries=3,
        fail_reason="seed",
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    dirty_reason = "x" * (MAX_FAIL_REASON_LENGTH + 128)
    orm.fail_reason = dirty_reason

    entity = PushHistoryRepositoryImpl._to_entity(orm)

    assert entity.fail_reason is not None
    assert entity.fail_reason != dirty_reason
    assert len(entity.fail_reason) <= MAX_FAIL_REASON_LENGTH
    assert entity.status == "failed"


def test_to_entity_normalizes_empty_fail_reason_for_failed_status():
    orm = PushHistoryORM(
        id=2,
        sub_id=1,
        user_id="u1",
        feed_id=1,
        content="seed",
        entry_title="title",
        entry_link="https://example.com/post",
        feed_title="feed",
        feed_link="https://example.com/feed",
        status="failed",
        retry_count=0,
        max_retries=3,
        fail_reason="   ",
    )

    entity = PushHistoryRepositoryImpl._to_entity(orm)

    assert entity.fail_reason is None


def test_to_entity_keeps_empty_fail_reason_empty_for_success_status():
    orm = PushHistoryORM(
        id=3,
        sub_id=1,
        user_id="u1",
        feed_id=1,
        content="seed",
        entry_title="title",
        entry_link="https://example.com/post",
        feed_title="feed",
        feed_link="https://example.com/feed",
        status="success",
        retry_count=0,
        max_retries=3,
        fail_reason="   ",
    )

    entity = PushHistoryRepositoryImpl._to_entity(orm)

    assert entity.fail_reason is None


def test_to_entity_hides_legacy_fail_reason_for_success_status():
    orm = PushHistoryORM(
        id=4,
        sub_id=1,
        user_id="u1",
        feed_id=1,
        content="seed",
        entry_title="title",
        entry_link="https://example.com/post",
        feed_title="feed",
        feed_link="https://example.com/feed",
        status="success",
        retry_count=0,
        max_retries=3,
        fail_reason="",
    )

    entity = PushHistoryRepositoryImpl._to_entity(orm)

    assert entity.fail_reason is None


def test_to_entity_preserves_agent_source_fields():
    now = datetime.now(timezone.utc)
    orm = PushHistoryORM(
        id=2,
        sub_id=None,
        user_id="user-2",
        feed_id=None,
        source_type="agent",
        source_key="daily:ai-news",
        content="content",
        raw_xml="<entry><p>Hello</p></entry>",
        entry_title="entry title",
        entry_link="https://example.com/entry",
        feed_title="feed title",
        feed_link="https://example.com/feed",
        status="success",
        retry_count=0,
        max_retries=3,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )

    entity = PushHistoryRepositoryImpl._to_entity(orm)

    assert entity.source_type == "agent"
    assert entity.source_key == "daily:ai-news"
    assert entity.sub_id is None
    assert entity.feed_id is None
    assert entity.raw_xml == "<entry><p>Hello</p></entry>"


@pytest.mark.asyncio
async def test_delete_many_ignores_invalid_ids_and_returns_rowcount(
    monkeypatch, tmp_path
):
    repo = PushHistoryRepositoryImpl()
    rows = [
        _build_history_row(
            user_id="u1",
            status="success",
            retry_count=0,
            max_retries=3,
        ),
        _build_history_row(
            user_id="u2",
            status="success",
            retry_count=0,
            max_retries=3,
        ),
    ]
    rows[0].id = 3
    rows[1].id = 5
    db = await _build_test_database(tmp_path / "push_history_delete_many.db", rows)
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    removed = await repo.delete_many([3, 0, -1, 5, 3])

    assert removed == 2
    assert await repo.get_all(limit=10) == []


@pytest.mark.asyncio
async def test_delete_many_skips_every_output_of_pending_batch(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    db = await _build_test_database(
        tmp_path / "push_history_delete_pending_batch.db",
        [
            DeliveryBatchORM(
                id=77,
                owner_type="subscription",
                owner_id=1,
                status="pending",
                target_sessions=["test:Group:1"],
                output_manifest=[
                    {
                        "target_session": "test:Group:1",
                        "output_kind": "card",
                        "output_order": 0,
                    },
                    {
                        "target_session": "test:Group:1",
                        "output_kind": "standard",
                        "output_order": 1,
                    },
                ],
            ),
            _build_history_row(
                user_id="pending-owner",
                status="success",
                retry_count=0,
                max_retries=3,
                batch_id=77,
            ),
            _build_history_row(
                user_id="pending-owner",
                status="failed",
                retry_count=0,
                max_retries=3,
                batch_id=77,
            ),
            _build_history_row(
                user_id="legacy-owner",
                status="success",
                retry_count=0,
                max_retries=3,
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    result = await repo.delete_many([1, 2, 3])

    assert int(result) == 1
    assert [item.history_id for item in result.skipped] == [1, 2]
    assert [item.batch_id for item in result.skipped] == [77, 77]
    assert sorted(item.id for item in await repo.get_all(limit=10)) == [1, 2]


@pytest.mark.asyncio
async def test_cleanup_preserves_old_outputs_in_pending_batch(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    old = datetime.now(timezone.utc) - timedelta(days=40)
    pending = DeliveryBatchORM(
        id=88,
        owner_type="bundle",
        owner_id=3,
        status="pending",
        target_sessions=["test:Group:1"],
        output_manifest=[
            {
                "target_session": "test:Group:1",
                "output_kind": "standard",
                "output_order": 0,
            }
        ],
    )
    protected = _build_history_row(
        user_id="pending-bundle",
        status="success",
        retry_count=0,
        max_retries=3,
        created_at=old,
        updated_at=old,
        completed_at=old,
        batch_id=88,
    )
    legacy = _build_history_row(
        user_id="legacy",
        status="success",
        retry_count=0,
        max_retries=3,
        created_at=old,
        updated_at=old,
        completed_at=old,
    )
    protected.id = 1
    legacy.id = 2
    db = await _build_test_database(
        tmp_path / "push_history_cleanup_pending_batch.db",
        [pending, protected, legacy],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    result = await repo.delete_old_records(days=30)

    assert int(result) == 1
    assert [item.history_id for item in result.skipped] == [1]
    assert [item.id for item in await repo.get_all(limit=10)] == [1]


class _TestDatabase:
    def __init__(self, session_maker):
        self._session_maker = session_maker

    def get_session(self):
        return self._session_maker()


async def _build_test_database(
    db_path: Path, rows: list[PushHistoryORM] | None = None
) -> _TestDatabase:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(RSSHubBaseModel.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        if rows:
            session.add_all(rows)
        await session.commit()

    return _TestDatabase(session_maker)


def _build_history_row(
    *,
    user_id: str,
    status: str,
    retry_count: int,
    max_retries: int,
    sub_id: int | None = None,
    feed_id: int | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    completed_at: datetime | None = None,
    batch_id: int | None = None,
) -> PushHistoryORM:
    now = datetime.now(timezone.utc)
    return PushHistoryORM(
        sub_id=sub_id,
        batch_id=batch_id,
        user_id=user_id,
        feed_id=feed_id,
        content=status,
        entry_title=status,
        entry_link=f"https://example.com/{user_id}",
        feed_title="feed",
        feed_link="https://example.com/feed",
        status=status,
        retry_count=retry_count,
        max_retries=max_retries,
        created_at=created_at or now,
        updated_at=updated_at or now,
        completed_at=completed_at,
    )


@pytest.mark.asyncio
async def test_count_retryable_failures_counts_failed_and_retrying_only(
    monkeypatch, tmp_path
):
    repo = PushHistoryRepositoryImpl()
    db = await _build_test_database(
        tmp_path / "push_history_retryable.db",
        [
            _build_history_row(
                user_id="user-failed",
                status="failed",
                retry_count=0,
                max_retries=3,
            ),
            _build_history_row(
                user_id="user-retrying",
                status="retrying",
                retry_count=1,
                max_retries=3,
            ),
            _build_history_row(
                user_id="user-zero",
                status="failed",
                retry_count=0,
                max_retries=0,
            ),
            _build_history_row(
                user_id="user-exhausted",
                status="retrying",
                retry_count=3,
                max_retries=3,
            ),
            _build_history_row(
                user_id="user-success",
                status="success",
                retry_count=0,
                max_retries=3,
            ),
            _build_history_row(
                user_id="user-batch",
                status="failed",
                retry_count=0,
                max_retries=3,
                batch_id=99,
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    count = await repo.count_retryable_failures()

    assert count == 2


@pytest.mark.asyncio
async def test_count_retryable_failures_excludes_zero_max_retries_and_exhausted_records(
    monkeypatch, tmp_path
):
    repo = PushHistoryRepositoryImpl()
    db = await _build_test_database(
        tmp_path / "push_history_retryable_excluded.db",
        [
            _build_history_row(
                user_id="user-zero",
                status="failed",
                retry_count=0,
                max_retries=0,
            ),
            _build_history_row(
                user_id="user-exhausted",
                status="retrying",
                retry_count=2,
                max_retries=2,
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    count = await repo.count_retryable_failures()

    assert count == 0


@pytest.mark.asyncio
async def test_count_retryable_alias_matches_primary_method(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    db = await _build_test_database(
        tmp_path / "push_history_retryable_alias.db",
        [
            _build_history_row(
                user_id="user-failed",
                status="failed",
                retry_count=0,
                max_retries=1,
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    assert await repo.count_retryable() == 1


@pytest.mark.asyncio
async def test_delete_by_sub_ids_deletes_matching_history(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    db = await _build_test_database(
        tmp_path / "push_history_delete_sub_ids.db",
        [
            _build_history_row(
                user_id="u1",
                status="success",
                retry_count=0,
                max_retries=3,
                sub_id=1,
                feed_id=10,
            ),
            _build_history_row(
                user_id="u1",
                status="failed",
                retry_count=0,
                max_retries=3,
                sub_id=2,
                feed_id=10,
            ),
            _build_history_row(
                user_id="u1",
                status="success",
                retry_count=0,
                max_retries=3,
                sub_id=3,
                feed_id=11,
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    removed = await repo.delete_by_sub_ids([1, 2, 2, 0])
    remaining = await repo.get_all(limit=10)

    assert removed == 2
    assert [item.sub_id for item in remaining] == [3]


@pytest.mark.asyncio
async def test_delete_by_feed_ids_deletes_matching_history(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    db = await _build_test_database(
        tmp_path / "push_history_delete_feed_ids.db",
        [
            _build_history_row(
                user_id="u1",
                status="success",
                retry_count=0,
                max_retries=3,
                sub_id=1,
                feed_id=10,
            ),
            _build_history_row(
                user_id="u1",
                status="failed",
                retry_count=0,
                max_retries=3,
                sub_id=2,
                feed_id=10,
            ),
            _build_history_row(
                user_id="u1",
                status="success",
                retry_count=0,
                max_retries=3,
                sub_id=3,
                feed_id=11,
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    removed = await repo.delete_by_feed_ids([10, 10, -1])
    remaining = await repo.get_all(limit=10)

    assert removed == 2
    assert [item.feed_id for item in remaining] == [11]


@pytest.mark.asyncio
async def test_get_all_sorts_by_last_activity_timestamp(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    base = datetime(2026, 5, 25, 12, tzinfo=timezone.utc)
    db = await _build_test_database(
        tmp_path / "push_history_sort_all.db",
        [
            _build_history_row(
                user_id="new-created",
                status="success",
                retry_count=0,
                max_retries=3,
                created_at=base,
                updated_at=base,
            ),
            _build_history_row(
                user_id="old-created-recent-updated",
                status="failed",
                retry_count=0,
                max_retries=3,
                created_at=base - timedelta(days=7),
                updated_at=base + timedelta(hours=1),
            ),
            _build_history_row(
                user_id="old-created-recent-completed",
                status="success",
                retry_count=0,
                max_retries=3,
                created_at=base - timedelta(days=14),
                updated_at=base - timedelta(days=14),
                completed_at=base + timedelta(hours=2),
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    histories = await repo.get_all(limit=10)

    assert [item.user_id for item in histories] == [
        "old-created-recent-completed",
        "old-created-recent-updated",
        "new-created",
    ]


@pytest.mark.asyncio
async def test_history_queries_expose_current_batch_status(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    db = await _build_test_database(
        tmp_path / "push_history_batch_status.db",
        [
            DeliveryBatchORM(
                id=91,
                owner_type="bundle",
                owner_id=8,
                status="pending",
                target_sessions=["test:Group:1"],
                output_manifest=[
                    {
                        "target_session": "test:Group:1",
                        "output_kind": "standard",
                        "output_order": 0,
                    }
                ],
            ),
            _build_history_row(
                user_id="batch-owner",
                status="success",
                retry_count=0,
                max_retries=3,
                batch_id=91,
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    histories = await repo.get_all(limit=10)

    assert histories[0].batch_id == 91
    assert histories[0].batch_status == "pending"


@pytest.mark.asyncio
async def test_grouped_history_page_keeps_a_multi_output_batch_intact(
    monkeypatch, tmp_path
):
    repo = PushHistoryRepositoryImpl()
    outputs = []
    for output_order in range(21):
        output = _build_history_row(
            user_id="batch-owner",
            status="success" if output_order else "waiting",
            retry_count=0,
            max_retries=3,
            batch_id=77,
        )
        output.bundle_id = 9
        output.output_kind = "card" if output_order == 0 else "standard"
        output.output_order = output_order
        output.target_session = (
            "test:Group:1" if output_order % 2 == 0 else "test:Group:2"
        )
        outputs.append(output)

    db = await _build_test_database(
        tmp_path / "push_history_grouped_page.db",
        [
            DeliveryBatchORM(
                id=77,
                owner_type="bundle",
                owner_id=9,
                status="pending",
                target_sessions=["test:Group:1", "test:Group:2"],
                output_manifest=[
                    {
                        "target_session": output.target_session,
                        "output_kind": output.output_kind,
                        "output_order": output.output_order,
                    }
                    for output in outputs
                ],
            ),
            *outputs,
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    page = await repo.get_grouped_page(page=1, page_size=20)

    assert page.total == 21
    assert page.group_total == 1
    assert len(page.items) == 21
    assert [item.output_order for item in page.items] == list(range(21))
    assert {item.output_kind for item in page.items} == {"card", "standard"}
    assert {item.target_session for item in page.items} == {
        "test:Group:1",
        "test:Group:2",
    }
    assert all(item.batch_status == "pending" for item in page.items)

    success_page = await repo.get_grouped_page(
        page=1,
        page_size=20,
        status="success",
    )

    assert success_page.total == 20
    assert success_page.group_total == 1
    assert len(success_page.items) == 20
    assert all(item.batch_status == "pending" for item in success_page.items)


@pytest.mark.asyncio
async def test_grouped_history_page_moves_to_the_next_logical_unit_without_duplicates(
    monkeypatch, tmp_path
):
    repo = PushHistoryRepositoryImpl()
    base = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)
    outputs = []
    for output_order in range(21):
        output = _build_history_row(
            user_id="batch-owner",
            status="success",
            retry_count=0,
            max_retries=3,
            created_at=base,
            updated_at=base,
            completed_at=base,
            batch_id=78,
        )
        output.output_kind = "card" if output_order == 0 else "standard"
        output.output_order = output_order
        outputs.append(output)

    ordinary = _build_history_row(
        user_id="legacy-owner",
        status="success",
        retry_count=0,
        max_retries=3,
        created_at=base - timedelta(days=1),
        updated_at=base - timedelta(days=1),
        completed_at=base - timedelta(days=1),
    )
    db = await _build_test_database(
        tmp_path / "push_history_grouped_page_two_pages.db",
        [
            DeliveryBatchORM(
                id=78,
                owner_type="subscription",
                owner_id=1,
                status="confirmed",
                target_sessions=["test:Group:1"],
                output_manifest=[
                    {
                        "target_session": "test:Group:1",
                        "output_kind": output.output_kind,
                        "output_order": output.output_order,
                    }
                    for output in outputs
                ],
            ),
            *outputs,
            ordinary,
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    first_page = await repo.get_grouped_page(page=1, page_size=1)
    second_page = await repo.get_grouped_page(page=2, page_size=1)

    assert first_page.total == second_page.total == 22
    assert first_page.group_total == second_page.group_total == 2
    assert len(first_page.items) == 21
    assert {item.batch_id for item in first_page.items} == {78}
    assert [item.output_order for item in first_page.items] == list(range(21))
    assert len(second_page.items) == 1
    assert second_page.items[0].batch_id is None
    assert second_page.items[0].user_id == "legacy-owner"


@pytest.mark.asyncio
async def test_grouped_history_page_preserves_singleton_row_pagination(
    monkeypatch, tmp_path
):
    repo = PushHistoryRepositoryImpl()
    base = datetime(2026, 6, 2, 12, tzinfo=timezone.utc)
    rows = [
        _build_history_row(
            user_id=f"legacy-owner-{index}",
            status="success",
            retry_count=0,
            max_retries=3,
            created_at=base - timedelta(minutes=index),
            updated_at=base - timedelta(minutes=index),
            completed_at=base - timedelta(minutes=index),
        )
        for index in range(21)
    ]
    db = await _build_test_database(
        tmp_path / "push_history_grouped_page_singletons.db",
        rows,
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    first_page = await repo.get_grouped_page(page=1, page_size=20)
    second_page = await repo.get_grouped_page(page=2, page_size=20)

    assert first_page.total == second_page.total == 21
    assert first_page.group_total == second_page.group_total == 21
    assert len(first_page.items) == 20
    assert len(second_page.items) == 1
    assert all(item.batch_id is None for item in first_page.items + second_page.items)


@pytest.mark.asyncio
async def test_get_by_user_sorts_by_last_activity_timestamp(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    base = datetime(2026, 5, 25, 12, tzinfo=timezone.utc)
    db = await _build_test_database(
        tmp_path / "push_history_sort_user.db",
        [
            _build_history_row(
                user_id="u1",
                status="success",
                retry_count=0,
                max_retries=3,
                created_at=base,
                updated_at=base,
            ),
            _build_history_row(
                user_id="u1",
                status="failed",
                retry_count=0,
                max_retries=3,
                created_at=base - timedelta(days=7),
                updated_at=base + timedelta(hours=1),
            ),
            _build_history_row(
                user_id="u2",
                status="success",
                retry_count=0,
                max_retries=3,
                created_at=base + timedelta(days=1),
                updated_at=base + timedelta(days=1),
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    histories = await repo.get_by_user(user_id="u1", limit=10)

    assert [item.status for item in histories] == ["failed", "success"]


@pytest.mark.asyncio
async def test_delete_old_records_uses_last_activity_timestamp(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)
    recent = now - timedelta(hours=1)
    db = await _build_test_database(
        tmp_path / "push_history_cleanup.db",
        [
            _build_history_row(
                user_id="old-created-recent-updated",
                status="failed",
                retry_count=0,
                max_retries=3,
                created_at=old,
                updated_at=recent,
            ),
            _build_history_row(
                user_id="all-old",
                status="failed",
                retry_count=0,
                max_retries=3,
                created_at=old,
                updated_at=old,
                completed_at=old,
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    removed = await repo.delete_old_records(days=30)
    remaining = await repo.get_all(limit=10)

    assert removed == 1
    assert [item.user_id for item in remaining] == ["old-created-recent-updated"]


@pytest.mark.asyncio
async def test_delete_all_removes_every_push_history_row(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    db = await _build_test_database(
        tmp_path / "push_history_delete_all.db",
        [
            _build_history_row(
                user_id="u1",
                status="success",
                retry_count=0,
                max_retries=3,
            ),
            _build_history_row(
                user_id="u2",
                status="failed",
                retry_count=0,
                max_retries=3,
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    removed = await repo.delete_all()

    assert removed == 2
    assert await repo.get_all(limit=10) == []


@pytest.mark.asyncio
async def test_get_status_buckets_groups_by_last_activity(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    base = datetime(2026, 5, 25, 12, tzinfo=timezone.utc)
    db = await _build_test_database(
        tmp_path / "push_history_status_buckets.db",
        [
            _build_history_row(
                user_id="created-old-updated-current",
                status="success",
                retry_count=0,
                max_retries=3,
                created_at=base - timedelta(days=3),
                updated_at=base,
            ),
            _build_history_row(
                user_id="completed-next-day",
                status="skipped",
                retry_count=0,
                max_retries=3,
                created_at=base,
                updated_at=base,
                completed_at=base + timedelta(days=1, hours=2),
            ),
            _build_history_row(
                user_id="too-old",
                status="failed",
                retry_count=0,
                max_retries=3,
                created_at=base - timedelta(days=10),
                updated_at=base - timedelta(days=10),
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    rows = await repo.get_status_buckets(since=base - timedelta(days=1), bucket="day")

    assert rows == [
        {
            "bucket": "2026-05-25T00:00:00+00:00",
            "status": "success",
            "count": 1,
        },
        {
            "bucket": "2026-05-26T00:00:00+00:00",
            "status": "skipped",
            "count": 1,
        },
    ]


@pytest.mark.asyncio
async def test_get_status_buckets_supports_hour_bucket(monkeypatch, tmp_path):
    repo = PushHistoryRepositoryImpl()
    base = datetime(2026, 5, 25, 12, 30, tzinfo=timezone.utc)
    db = await _build_test_database(
        tmp_path / "push_history_status_hour_buckets.db",
        [
            _build_history_row(
                user_id="u1",
                status="success",
                retry_count=0,
                max_retries=3,
                created_at=base,
                updated_at=base,
            ),
            _build_history_row(
                user_id="u2",
                status="failed",
                retry_count=0,
                max_retries=3,
                created_at=base.replace(minute=50),
                updated_at=base.replace(minute=50),
            ),
        ],
    )
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    rows = await repo.get_status_buckets(since=base - timedelta(hours=1), bucket="hour")

    assert rows == [
        {
            "bucket": "2026-05-25T12:00:00+00:00",
            "status": "failed",
            "count": 1,
        },
        {
            "bucket": "2026-05-25T12:00:00+00:00",
            "status": "success",
            "count": 1,
        },
    ]
