"""主模块集成测试."""

from __future__ import annotations

import inspect
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_context():
    """模拟 AstrBot 上下文."""
    context = MagicMock()
    context.platform_manager = MagicMock()
    context.platform_manager.platform_insts = []
    return context


@pytest.fixture
def mock_config():
    """模拟 AstrBot 配置."""
    return {
        "rsshub": {
            "db": {"database": "test.db"},
            "basic": {"timeout": 30, "proxy": ""},
            "ffmpeg": {"video_transcode": False},
        }
    }


@pytest.fixture
def main_module(monkeypatch):
    """导入带最小 AstrBot 假对象的 main 模块."""

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

        @staticmethod
        def event_message_type(*_args, **_kwargs):
            return lambda fn: fn

        class EventMessageType:
            ALL = "all"

    api_mod = sys.modules["astrbot.api"]
    api_mod.AstrBotConfig = dict

    event_mod = sys.modules["astrbot.api.event"]
    event_mod.AstrMessageEvent = object
    event_mod.filter = FakeFilter()

    star_mod = sys.modules["astrbot.api.star"]
    star_mod.Context = object
    star_mod.Star = FakeStar

    monkeypatch.delitem(sys.modules, "astrbot_plugin_rsshub.main", raising=False)

    import astrbot_plugin_rsshub.main as main

    return main


class TestRSSHubPluginIntegration:
    """插件入口集成测试."""

    def test_plugin_initialization(self, main_module, mock_context, mock_config):
        """测试插件对象初始化."""
        plugin = main_module.RSSHubPlugin(mock_context, mock_config)

        assert plugin._config == mock_config
        assert plugin._scheduler is None
        assert plugin._deps == {}
        assert not hasattr(main_module, "Main")


class TestCommandIntegration:
    """命令集成测试."""

    def test_command_registration(self, main_module):
        """测试当前插件入口暴露的命令方法."""
        methods = [
            name
            for name, _ in inspect.getmembers(
                main_module.RSSHubPlugin, predicate=inspect.isfunction
            )
        ]

        command_methods = [
            "sub_feed",
            "unsub_feed",
            "sub_list",
            "stop_rss_job",
            "sub_status",
            "sub_state",
            "sub_profile_set",
            "sub_profile_get",
            "sub_set_session",
            "sub_get_session",
            "batch_activate",
            "batch_deactivate",
            "unsub_all",
            "export_subs",
            "import_subs",
            "import_upload_listener",
            "rsshelp",
            "test_sub",
        ]

        for cmd in command_methods:
            assert cmd in methods, f"Command method {cmd} not found"

    def test_import_upload_listener_finds_file_like_component(self, main_module):
        plugin = main_module.RSSHubPlugin(MagicMock(), {})

        class UploadedFile:
            async def get_file(self):
                return "/tmp/subs.toml"

        event = MagicMock()
        event.message_obj = MagicMock(message=[UploadedFile()])

        assert plugin._find_uploaded_file(event) is event.message_obj.message[0]

    def test_pending_import_prune_removes_expired_entries(
        self, main_module, monkeypatch
    ):
        plugin = main_module.RSSHubPlugin(MagicMock(), {})
        plugin._pending_imports = {
            "expired": 100.0,
            "active": 300.0,
        }

        monkeypatch.setattr(main_module.time, "time", lambda: 200.0)

        plugin._prune_pending_imports()

        assert plugin._pending_imports == {"active": 300.0}


class TestSchedulerIntegration:
    """调度器集成测试."""

    @pytest.mark.asyncio
    async def test_scheduler_start_stop(self):
        """调度器测试需要完整插件环境."""


class TestConfigurationIntegration:
    """配置集成测试."""

    def test_config_loading(self, mock_config):
        """测试配置加载."""
        from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

        config = RsshubPluginConfig.from_astrbot_config(mock_config)

        assert config is not None
        assert config.basic_config.timeout == 30


class TestLLMToolLifecycle:
    """LLM 工具生命周期测试."""

    @pytest.mark.asyncio
    async def test_terminate_unregisters_llm_tools(self, main_module, mock_context):
        plugin = main_module.RSSHubPlugin(mock_context, {})
        plugin._runtime = MagicMock()
        plugin._runtime.stop = AsyncMock()
        plugin._registered_llm_tools = ["rss_subscribe", "rss_unsubscribe"]

        await plugin.terminate()

        assert mock_context.unregister_llm_tool.call_count == 2
        mock_context.unregister_llm_tool.assert_any_call("rss_subscribe")
        mock_context.unregister_llm_tool.assert_any_call("rss_unsubscribe")
        plugin._runtime.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_terminate_unregister_fallback_remove_func(
        self, main_module, mock_context
    ):
        plugin = main_module.RSSHubPlugin(mock_context, {})
        plugin._runtime = None
        plugin._push_job_queue.stop_all = AsyncMock()
        plugin._registered_llm_tools = ["rss_subscribe"]

        manager = MagicMock()
        mock_context.get_llm_tool_manager.return_value = manager
        mock_context.unregister_llm_tool.side_effect = RuntimeError("boom")

        await plugin.terminate()

        manager.remove_func.assert_called_once_with("rss_subscribe")
        plugin._push_job_queue.stop_all.assert_awaited_once()
