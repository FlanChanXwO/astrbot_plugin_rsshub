from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
from astrbot_plugin_rsshub.src.infrastructure.persistence.models import PushHistoryORM
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
async def test_delete_many_ignores_invalid_ids_and_returns_rowcount(monkeypatch):
    repo = PushHistoryRepositoryImpl()
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.rowcount = 2
    session.execute = AsyncMock(return_value=execute_result)

    session_manager = AsyncMock()
    session_manager.__aenter__.return_value = session
    session_manager.__aexit__.return_value = False

    db = MagicMock()
    db.get_session.return_value = session_manager
    monkeypatch.setattr(push_history_repository_impl, "get_database", lambda: db)

    removed = await repo.delete_many([3, 0, -1, 5, 3])

    assert removed == 2
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


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
) -> PushHistoryORM:
    now = datetime.now(timezone.utc)
    return PushHistoryORM(
        sub_id=sub_id,
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
