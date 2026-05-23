from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.interfaces.handlers import data as data_handlers
from astrbot_plugin_rsshub.src.interfaces.handlers.admin import handle_test_sub
from astrbot_plugin_rsshub.src.interfaces.handlers.config import (
    handle_sub_profile_get,
    handle_sub_profile_set,
)
from astrbot_plugin_rsshub.src.interfaces.handlers.data import (
    handle_export,
    handle_import,
)
from astrbot_plugin_rsshub.src.interfaces.handlers.subscription import (
    handle_rss_stop,
    handle_sub_list,
    handle_sub_status,
    handle_unsub,
)


@pytest.mark.asyncio
async def test_handle_test_sub_parse_and_route():
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.unified_msg_origin = "sess"
    event.get_platform_name.return_value = "telegram"

    cmd = MagicMock()
    cmd.execute_target = AsyncMock(return_value=SimpleNamespace(message="ok"))
    result = await handle_test_sub(event, "5", {"test_sub_cmd": cmd})

    assert result["plain"] == "ok"
    cmd.execute_target.assert_awaited_once_with(
        target="5",
        user_id="u1",
        target_session="sess",
        platform_name="telegram",
        event=event,
    )


@pytest.mark.asyncio
async def test_handle_test_sub_rejects_extra_args():
    event = MagicMock()
    cmd = MagicMock()
    cmd.execute_target = AsyncMock()

    result = await handle_test_sub(event, "5 1 3", {"test_sub_cmd": cmd})

    assert result["plain"] == "sub_test 不支持额外参数\n用法: /sub_test <ID|URL>"
    cmd.execute_target.assert_not_called()


@pytest.mark.asyncio
async def test_handle_unsub_mixed_id_url():
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.unified_msg_origin = "sess"
    event.is_admin.return_value = False

    cmd = MagicMock()
    cmd.execute = AsyncMock(return_value=SimpleNamespace(message="id_ok"))
    cmd.execute_by_url = AsyncMock(return_value=SimpleNamespace(message="url_ok"))

    result = await handle_unsub(event, "1 https://a.com/rss", {"unsubscribe_cmd": cmd})
    assert "id_ok" in result["plain"]
    assert "url_ok" in result["plain"]


@pytest.mark.asyncio
async def test_handle_sub_list_paging_current_session_only():
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.unified_msg_origin = "sess"
    event.is_admin.return_value = True

    subs = [
        SimpleNamespace(
            id=i,
            user_id="u1",
            feed_id=i,
            feed_title=f"f{i}",
            feed_link=f"https://f{i}",
            title="",
            state=1,
            target_session="sess",
        )
        for i in range(1, 8)
    ]
    query = MagicMock()
    query.execute = AsyncMock(return_value=SimpleNamespace(subscriptions=subs))

    subs[0].target_session = "other"
    result = await handle_sub_list(event, "2 3", {"get_subs_query": query})
    assert "页码: 2/2" in result["plain"]
    assert "4. [5]" in result["plain"]


@pytest.mark.asyncio
async def test_handle_export_scope_and_permission():
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.unified_msg_origin = "sess"
    event.is_admin.return_value = True

    export_cmd = MagicMock()
    export_cmd.execute = AsyncMock(
        return_value=SimpleNamespace(message="ok", data=None)
    )
    result = await handle_export(event, "all", {"export_cmd": export_cmd})
    assert result["plain"] == "ok"


@pytest.mark.asyncio
async def test_handle_export_onebot_fallback_inline(monkeypatch, tmp_path):
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.unified_msg_origin = "sess"
    event.is_admin.return_value = True
    event.get_platform_name.return_value = "aiocqhttp"

    data = SimpleNamespace(
        content="[[subscriptions]]\nlink='https://a.com/rss'\n",
        filename="test.toml",
        count=1,
    )
    monkeypatch.setattr(data_handlers, "_has_callback_file_service", lambda: False)
    monkeypatch.setattr(data_handlers, "get_plugin_export_dir", lambda: tmp_path)
    export_cmd = MagicMock()
    export_cmd.execute = AsyncMock(
        return_value=SimpleNamespace(message="ok", data=data)
    )
    result = await handle_export(event, "all", {"export_cmd": export_cmd})
    assert "```toml" in result["plain"]
    assert "chain" not in result


@pytest.mark.asyncio
async def test_handle_export_onebot_send_file_when_callback_available(
    monkeypatch, tmp_path
):
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.unified_msg_origin = "sess"
    event.is_admin.return_value = True
    event.get_platform_name.return_value = "aiocqhttp"

    data = SimpleNamespace(
        content="[[subscriptions]]\nlink='https://a.com/rss'\n",
        filename="test.toml",
        count=1,
    )
    monkeypatch.setattr(data_handlers, "_has_callback_file_service", lambda: True)
    monkeypatch.setattr(data_handlers, "get_plugin_export_dir", lambda: tmp_path)
    export_cmd = MagicMock()
    export_cmd.execute = AsyncMock(
        return_value=SimpleNamespace(message="ok", data=data)
    )
    result = await handle_export(event, "all", {"export_cmd": export_cmd})
    assert result["plain"] == "ok"
    assert "chain" in result


@pytest.mark.asyncio
async def test_handle_import_path_and_waiting(tmp_path):
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.unified_msg_origin = "sess"
    event.get_platform_name.return_value = "telegram"

    import_cmd = MagicMock()
    import_cmd.execute = AsyncMock(return_value=SimpleNamespace(message="done"))

    waiting = await handle_import(event, "", {"import_cmd": import_cmd})
    assert "上传 TOML" in waiting["plain"]
    assert waiting["wait_import"] is True

    p = tmp_path / "subs.toml"
    p.write_text("[[subscriptions]]\nlink='https://a.com/rss'\n")
    result = await handle_import(event, str(p), {"import_cmd": import_cmd})
    assert result["plain"] == "done"


def test_handle_sub_status_and_stop_variants():
    event = MagicMock()
    event.unified_msg_origin = "sess"

    queue = MagicMock()
    queue.get_jobs.return_value = [
        SimpleNamespace(
            status="running",
            job_id="rss-000001",
            feed_title="Feed A",
            feed_id=1,
        ),
        SimpleNamespace(
            status="queued",
            job_id="rss-000002",
            feed_title="Feed B",
            feed_id=2,
        ),
    ]
    status_result = handle_sub_status(event, queue)
    assert "rss-000001" in status_result["plain"]
    assert "Feed B" in status_result["plain"]

    queue.stop_current.return_value = SimpleNamespace(
        stopped=True,
        message="ok",
        queued_count=1,
    )
    stop_default = handle_rss_stop(event, queue, "")
    assert "队列中还有 1 个任务" in stop_default["plain"]

    queue.stop_by_feed_id.return_value = SimpleNamespace(message="by-feed")
    stop_feed = handle_rss_stop(event, queue, "2")
    assert stop_feed["plain"] == "by-feed"

    queue.stop_by_job_id.return_value = SimpleNamespace(message="by-job")
    stop_job = handle_rss_stop(event, queue, "rss-000002")
    assert stop_job["plain"] == "by-job"

    queue.stop_all_for_session.return_value = {"stopped": 2, "running": 1, "queued": 1}
    stop_all = handle_rss_stop(event, queue, "all")
    assert "总计 2 个" in stop_all["plain"]


@pytest.mark.asyncio
async def test_handle_sub_profile_set_get_routes():
    event = MagicMock()
    event.get_sender_id.return_value = "u1"

    deps = {
        "update_sub_cmd": MagicMock(),
        "set_user_settings_cmd": MagicMock(),
        "get_user_settings_cmd": MagicMock(),
    }
    deps["update_sub_cmd"].execute = AsyncMock(
        return_value=SimpleNamespace(message="sub-ok")
    )
    deps["set_user_settings_cmd"].execute = AsyncMock(
        return_value=SimpleNamespace(message="user-set-ok")
    )
    deps["get_user_settings_cmd"].execute = AsyncMock(
        return_value=SimpleNamespace(message="user-get-ok")
    )

    r1 = await handle_sub_profile_set(event, "sub 12 interval 30", deps)
    assert r1["plain"] == "sub-ok"

    r2 = await handle_sub_profile_set(
        event,
        'user handlers [{"id":"builtin.ai_transform.default","type":"builtin","name":"ai_transform","status":1,"config":{"prompt":"summarize"}}]',
        deps,
    )
    assert r2["plain"] == "user-set-ok"

    r3 = await handle_sub_profile_get(event, "user", deps)
    assert r3["plain"] == "user-get-ok"


@pytest.mark.asyncio
async def test_rsshelp_returns_image_chain(monkeypatch, tmp_path):
    event = MagicMock()
    event.chain_result.side_effect = lambda chain: {"chain": chain}
    event.plain_result.side_effect = lambda text: {"plain": text}

    class FakeStar:
        def __init__(self, context):
            self.context = context

    class FakePermissionType:
        ADMIN = "admin"

    class FakeFilter:
        PermissionType = FakePermissionType

        @staticmethod
        def command(*_args, **_kwargs):
            return lambda fn: fn

        @staticmethod
        def command_group(*_args, **_kwargs):
            class _Group:
                @staticmethod
                def command(*_a, **_k):
                    return lambda fn: fn

            return lambda fn: _Group()

        @staticmethod
        def permission_type(*_args, **_kwargs):
            return lambda fn: fn

    api_mod = sys.modules["astrbot.api"]
    api_mod.AstrBotConfig = dict
    event_mod = sys.modules["astrbot.api.event"]
    event_mod.AstrMessageEvent = object
    event_mod.filter = FakeFilter()
    star_mod = sys.modules["astrbot.api.star"]
    star_mod.Context = object
    star_mod.Star = FakeStar

    monkeypatch.delitem(sys.modules, "astrbot_plugin_rsshub.main", raising=False)
    main = importlib.import_module("astrbot_plugin_rsshub.main")
    image_path = tmp_path / "rsshelp.png"
    image_path.write_bytes(b"fake")
    monkeypatch.setattr(main, "_HELP_IMAGE_PATH", image_path)

    plugin = main.RSSHubPlugin(MagicMock(), {})
    result = []
    async for item in plugin.rsshelp(event):
        result.append(item)

    assert result
    assert "chain" in result[0]
    assert len(result[0]["chain"]) == 1


def test_main_command_signature_uses_greedy(monkeypatch):
    import sys

    class FakeStar:
        def __init__(self, context):
            self.context = context

    class FakePermissionType:
        ADMIN = "admin"

    class FakeFilter:
        PermissionType = FakePermissionType

        @staticmethod
        def command(*_args, **_kwargs):
            return lambda fn: fn

        @staticmethod
        def command_group(*_args, **_kwargs):
            class _Group:
                @staticmethod
                def command(*_a, **_k):
                    return lambda fn: fn

            return lambda fn: _Group()

        @staticmethod
        def permission_type(*_args, **_kwargs):
            return lambda fn: fn

    class FakeGreedyStr(str):
        pass

    api_mod = sys.modules["astrbot.api"]
    api_mod.AstrBotConfig = dict

    event_mod = sys.modules["astrbot.api.event"]
    event_mod.AstrMessageEvent = object
    event_mod.filter = FakeFilter()

    star_mod = sys.modules["astrbot.api.star"]
    star_mod.Context = object
    star_mod.Star = FakeStar

    filter_mod = sys.modules["astrbot.core.star.filter"]
    filter_mod.GreedyStr = FakeGreedyStr

    monkeypatch.delitem(sys.modules, "astrbot_plugin_rsshub.main", raising=False)
    main = importlib.import_module("astrbot_plugin_rsshub.main")

    assert main.RSSHubPlugin.sub_feed.__annotations__["args"] in (
        FakeGreedyStr,
        "GreedyStr",
    )
    assert main.RSSHubPlugin.unsub_feed.__annotations__["args"] in (
        FakeGreedyStr,
        "GreedyStr",
    )
    assert main.RSSHubPlugin.sub_list.__annotations__["args"] in (
        FakeGreedyStr,
        "GreedyStr",
    )
    assert main.RSSHubPlugin.import_subs.__annotations__["args"] in (
        FakeGreedyStr,
        "GreedyStr",
    )
    assert main.RSSHubPlugin.test_sub.__annotations__["args"] in (
        FakeGreedyStr,
        "GreedyStr",
    )
