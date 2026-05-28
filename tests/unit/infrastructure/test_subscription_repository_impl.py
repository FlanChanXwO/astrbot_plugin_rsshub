from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.infrastructure.persistence.subscription_repository_impl import (
    SubscriptionRepositoryImpl,
)


class _DummyExecuteResult:
    def __init__(self, existing):
        self._existing = existing
        self.rowcount = 0

    def scalar_one_or_none(self):
        return self._existing


class _DummySession:
    def __init__(self, existing=None):
        self._existing = existing
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.execute = AsyncMock(return_value=_DummyExecuteResult(existing))


class _DummyCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_update_options_serializes_handlers(monkeypatch):
    existing = SimpleNamespace(
        id=2,
        state=1,
        user_id="u1",
        feed_id=10,
        title="",
        tags="",
        target_session=None,
        platform_name=None,
        interval=-100,
        next_check_time=None,
        notify=-100,
        send_mode=-100,
        handlers_mode="inherit",
        handlers="[]",
        length_limit=-100,
        display_author=-100,
        display_via=-100,
        display_title=-100,
        display_entry_tags=-100,
        style=-100,
        display_media=-100,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    session = _DummySession(existing=existing)
    db = MagicMock()
    db.get_session.return_value = _DummyCtx(session)

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.persistence.subscription_repository_impl.get_database",
        lambda: db,
    )

    repo = SubscriptionRepositoryImpl()
    result = await repo.update_options(
        2,
        "u1",
        handlers=[
            {
                "id": "builtin.xml_parse.default",
                "type": "builtin",
                "name": "xml_parse",
                "status": 1,
                "config": {},
            }
        ],
        handlers_mode="override",
    )

    assert result is not None
    assert existing.handlers_mode == "override"
    assert isinstance(existing.handlers, str)
    assert existing.handlers == "[]"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_all_by_feed_ids_deduplicates_ids_and_returns_rowcount(
    monkeypatch,
):
    session = _DummySession()
    execute_result = MagicMock()
    execute_result.rowcount = 3
    session.execute = AsyncMock(return_value=execute_result)
    db = MagicMock()
    db.get_session.return_value = _DummyCtx(session)

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.persistence.subscription_repository_impl.get_database",
        lambda: db,
    )

    repo = SubscriptionRepositoryImpl()
    removed = await repo.delete_all_by_feed_ids([8, 9, 8, 0, -1])

    assert removed == 3
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
