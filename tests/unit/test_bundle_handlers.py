from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_handle_bundle_create_preserves_quoted_name_and_greedy_args() -> None:
    from astrbot_plugin_rsshub.src.interfaces.handlers.bundle import (
        handle_bundle_create,
    )

    event = MagicMock()
    event.get_sender_id.return_value = "user-1"
    event.unified_msg_origin = "telegram:group:1"
    command = MagicMock()
    command.create = AsyncMock(return_value=SimpleNamespace(message="created"))

    result = await handle_bundle_create(
        event,
        '"My Daily Bundle" 1 2 --targets telegram:group:1,telegram:group:2 --interval 15',
        {"bundle_cmd": command},
    )

    assert result["plain"] == "created"
    command.create.assert_awaited_once_with(
        user_id="user-1",
        name="My Daily Bundle",
        feed_ids=[1, 2],
        target_sessions=["telegram:group:1", "telegram:group:2"],
        interval=15,
    )


@pytest.mark.asyncio
async def test_handle_bundle_remove_rejects_invalid_member_batch_atomically() -> None:
    from astrbot_plugin_rsshub.src.interfaces.handlers.bundle import (
        handle_bundle_remove,
    )

    event = MagicMock()
    event.get_sender_id.return_value = "user-1"
    command = MagicMock()
    command.remove = AsyncMock()

    result = await handle_bundle_remove(event, "7 101 nope", {"bundle_cmd": command})

    assert "数字" in result["plain"]
    command.remove.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_bundle_list_reports_unmatched_quotes_as_user_error() -> None:
    from astrbot_plugin_rsshub.src.interfaces.handlers.bundle import handle_bundle_list

    event = MagicMock()
    command = MagicMock()

    result = await handle_bundle_list(event, '"unterminated', {"bundle_cmd": command})

    assert "参数无效" in result["plain"]
    command.list.assert_not_called()
