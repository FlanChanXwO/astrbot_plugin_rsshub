from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub import bootstrap
from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig


class _FakeDB:
    def __init__(self):
        self.is_initialized = True
        self.close = AsyncMock()


class _FakeScheduler:
    def __init__(self):
        self.stop = AsyncMock()


class _FakeQueue:
    def __init__(self):
        self.stop_all = AsyncMock()


def test_init_config_heals_dirty_astrbot_config_before_parsing(monkeypatch):
    schema = {
        "basic_config": {
            "type": "object",
            "items": {
                "minimal_interval": {"type": "int", "default": 1},
            },
        },
        "http_config": {
            "type": "object",
            "items": {
                "timeout": {"type": "int", "default": 30},
                "media_timeout": {"type": "int", "default": 30},
                "proxy": {"type": "string", "default": ""},
            },
        },
        "sender_strategies": {
            "type": "object",
            "items": {
                "enabled_platforms": {
                    "type": "list",
                    "default": ["telegram", "aiocqhttp", "qq_official"],
                    "options": ["telegram", "aiocqhttp", "qq_official"],
                    "items": {"type": "string"},
                },
                "platform_strategies": {"type": "template_list", "default": []},
            },
        },
    }

    class FakeAstrBotConfig(dict):
        saved = False

        def __init__(self):
            super().__init__(
                {
                    "basic_config": {
                        "timeout": "12",
                        "download_media_before_send": False,
                    },
                    "sender_strategies": {"telegram": False, "aiocqhttp": True},
                }
            )
            self.schema = schema

        def save_config(self):
            self.saved = True

    fake_config = FakeAstrBotConfig()
    monkeypatch.setattr(bootstrap, "set_config", lambda _config: None)

    plugin_config, settings = bootstrap._init_config(fake_config)

    assert isinstance(plugin_config, RsshubPluginConfig)
    assert fake_config.saved is True
    assert fake_config["basic_config"] == {
        "minimal_interval": 1,
    }
    assert fake_config["http_config"] == {
        "timeout": 12,
        "media_timeout": 30,
        "proxy": "",
    }
    assert fake_config["sender_strategies"] == {
        "enabled_platforms": ["aiocqhttp", "qq_official"],
        "platform_strategies": [],
    }
    assert settings.http.timeout == 12


@pytest.mark.asyncio
async def test_create_runtime_does_not_start_scheduler_when_register_web_api_fails(
    monkeypatch,
):
    fake_db = _FakeDB()
    fake_queue = _FakeQueue()
    start_scheduler = AsyncMock(return_value=_FakeScheduler())

    monkeypatch.setattr(
        bootstrap,
        "_init_config",
        lambda _cfg: (
            MagicMock(),
            MagicMock(
                scheduler=MagicMock(default_interval=10, history_retention_days=30),
                sender_strategies=MagicMock(),
            ),
        ),
    )
    monkeypatch.setattr(bootstrap, "_init_database", AsyncMock())
    monkeypatch.setattr(
        bootstrap,
        "_build_dependencies",
        lambda **_kwargs: ({}, MagicMock()),
    )
    monkeypatch.setattr(
        bootstrap,
        "_start_scheduler",
        start_scheduler,
    )
    monkeypatch.setattr(
        bootstrap,
        "_register_web_api",
        MagicMock(side_effect=RuntimeError("register failed")),
    )
    monkeypatch.setattr(bootstrap, "get_database", lambda: fake_db)

    with pytest.raises(RuntimeError, match="register failed"):
        await bootstrap.create_plugin_runtime(
            context=MagicMock(),
            config={},
            push_job_queue=fake_queue,
        )

    start_scheduler.assert_not_awaited()
    fake_queue.stop_all.assert_awaited_once()
    fake_db.close.assert_awaited_once()
