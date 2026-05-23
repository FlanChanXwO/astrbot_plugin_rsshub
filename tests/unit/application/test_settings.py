"""Application settings tests."""

from __future__ import annotations

import pytest


def test_application_settings_maps_fetch_config_and_ignores_pipeline_config():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        RsshubPluginConfig,
        build_application_settings,
    )

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "basic_config": {
                "timeout": 12,
                "proxy": "http://proxy.local",
                "rsshub_base_url": "https://rss.example.test",
                "minimal_interval": 5,
                "failed_queue_capacity": 21,
                "failed_queue_max_retries": 7,
                "deduplicate_multi_bot": False,
            },
            "global_config": {
                "interval": 15,
                "translate": True,
            },
            "translation": {
                "provider": "baidu",
                "target_lang": "zh",
                "display_original": True,
                "cache_enabled": False,
                "baidu_translate_app_id": "app-id",
                "baidu_translate_secret_key": "secret",
            },
            "pipeline": {
                "keyword_blacklist": ["spam"],
                "min_content_length": 18,
                "min_media_count": 1,
                "ai_filter_enabled": True,
                "ai_filter_prompt": "keep only important entries",
                "ai_enrich_enabled": True,
                "ai_enrich_prompt": "summarize as json",
                "ai_timeout_seconds": 9,
                "translate_enabled": True,
                "translate_engine": "baidu",
                "translate_fallback_engine": "google",
                "translate_target_lang": "ja",
                "translate_mark_errors": True,
            },
        }
    )

    settings = build_application_settings(config)

    assert settings.fetch.timeout == 12
    assert settings.fetch.proxy == "http://proxy.local"
    assert settings.fetch.rsshub_base_url == "https://rss.example.test"
    assert settings.basic.minimal_interval == 5
    assert settings.basic.failed_queue_capacity == 21
    assert settings.basic.failed_queue_max_retries == 7
    assert settings.basic.deduplicate_multi_bot is False
    assert settings.scheduler.default_interval == 15
    assert settings.scheduler.history_retention_days == 30
    assert not hasattr(settings.subscription_defaults, "translate")
    assert not hasattr(settings, "translation")
    assert not hasattr(settings, "baidu")
    assert not hasattr(settings, "pipeline")


def test_application_settings_normalizes_proxy_url():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        RsshubPluginConfig,
        build_application_settings,
    )

    settings = build_application_settings(
        RsshubPluginConfig.from_astrbot_config(
            {"basic_config": {"proxy": " localhost:7890 "}}
        )
    )
    assert settings.basic.proxy == "http://localhost:7890"
    assert settings.fetch.proxy == "http://localhost:7890"

    settings = build_application_settings(
        RsshubPluginConfig.from_astrbot_config(
            {"basic_config": {"proxy": "socks5://127.0.0.1:7890"}}
        )
    )
    assert settings.basic.proxy == "socks5://127.0.0.1:7890"
    assert settings.fetch.proxy == "socks5://127.0.0.1:7890"

    settings = build_application_settings(
        RsshubPluginConfig.from_astrbot_config({"basic_config": {"proxy": "  "}})
    )
    assert settings.basic.proxy == ""
    assert settings.fetch.proxy == ""


def test_config_ignores_removed_translation_template_credentials():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "translation": {
                "translation_template": [
                    {
                        "provider": "baidu",
                        "appid": "legacy-app-id",
                        "key": "legacy-secret",
                    }
                ]
            }
        }
    )

    assert not hasattr(config, "translation")
    assert not hasattr(config, "baidu_translate")


def test_config_ignores_removed_pipeline_config():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config(
        {"pipeline": {"ai_filter_enabled": True, "keyword_blacklist": ["spam"]}}
    )

    assert not hasattr(config, "pipeline")


def test_config_ignores_legacy_download_media_before_send_false():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        RsshubPluginConfig,
        build_application_settings,
    )

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "download_image_before_send": False,
            "basic_config": {"download_media_before_send": False},
        }
    )
    settings = build_application_settings(config)

    assert config.download_media_before_send is True
    assert config.download_image_before_send is True
    assert settings.basic.download_media_before_send is True


def test_heal_astrbot_plugin_config_projects_dirty_config_to_schema():
    import json
    from pathlib import Path

    from astrbot_plugin_rsshub.src.infrastructure.config import (
        heal_astrbot_plugin_config,
    )

    schema = json.loads(
        (Path(__file__).resolve().parents[3] / "_conf_schema.json").read_text(
            encoding="utf-8"
        )
    )
    healed, changes = heal_astrbot_plugin_config(
        {
            "download_image_before_send": False,
            "m3u8_download_timeout": "80",
            "unknown_top": True,
            "basic_config": {
                "timeout": "12",
                "minimal_interval": 99999,
                "hash_history_min": "abc",
                "deduplicate_multi_bot": "false",
                "tracking_query_params": ["utm_source", 1, "ref"],
                "download_media_before_send": False,
                "unknown_basic": "x",
            },
            "route_knowledge": {
                "source_mode": "bad",
                "timeout": 999,
            },
            "ffmpeg": {
                "video_transcode": "false",
                "video_transcode_timeout": 1,
            },
            "content_handlers": "bad",
            "sender_strategies": {
                "telegram": False,
                "aiocqhttp": True,
                "qq_official": True,
                "unknown": True,
            },
        },
        schema,
    )

    assert changes
    assert "download_image_before_send" not in healed
    assert "m3u8_download_timeout" not in healed
    assert "unknown_top" not in healed
    assert healed["basic_config"]["timeout"] == 12
    assert healed["basic_config"]["minimal_interval"] == 1440
    assert healed["basic_config"]["hash_history_min"] == 200
    assert healed["basic_config"]["deduplicate_multi_bot"] is True
    assert healed["basic_config"]["tracking_query_params"] == ["utm_source", "ref"]
    assert "download_media_before_send" not in healed["basic_config"]
    assert "unknown_basic" not in healed["basic_config"]
    assert healed["basic_config"]["download_media_timeout"] == 80
    assert healed["route_knowledge"]["source_mode"] == "mirror"
    assert healed["route_knowledge"]["timeout"] == 300
    assert healed["ffmpeg"]["video_transcode"] is False
    assert healed["ffmpeg"]["video_transcode_timeout"] == 10
    assert healed["content_handlers"] == {
        "ai_provider_id": "",
        "ai_persona_id": "",
    }
    assert healed["sender_strategies"] == {
        "enabled_platforms": ["aiocqhttp", "qq_official"],
        "platform_strategies": [],
    }


def test_heal_astrbot_plugin_config_returns_no_changes_for_clean_config():
    import json
    from pathlib import Path

    from astrbot_plugin_rsshub.src.infrastructure.config import (
        heal_astrbot_plugin_config,
    )

    schema = json.loads(
        (Path(__file__).resolve().parents[3] / "_conf_schema.json").read_text(
            encoding="utf-8"
        )
    )
    clean_config = {
        "basic_config": {
            key: value["default"]
            for key, value in schema["basic_config"]["items"].items()
        },
        "route_knowledge": {
            key: value["default"]
            for key, value in schema["route_knowledge"]["items"].items()
        },
        "ffmpeg": {
            key: value["default"] for key, value in schema["ffmpeg"]["items"].items()
        },
        "content_handlers": {
            key: value["default"]
            for key, value in schema["content_handlers"]["items"].items()
        },
        "sender_strategies": {
            key: value["default"]
            for key, value in schema["sender_strategies"]["items"].items()
        },
    }

    healed, changes = heal_astrbot_plugin_config(clean_config, schema)

    assert healed == clean_config
    assert changes == []


def test_sender_strategies_default_to_all_enabled():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config({})

    assert config.sender_strategies.telegram is True
    assert config.sender_strategies.aiocqhttp is True
    assert config.sender_strategies.qq_official is True


def test_sender_strategies_parse_legacy_object_config():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "sender_strategies": {
                "telegram": False,
                "aiocqhttp": True,
                "unknown": True,
            }
        }
    )

    assert config.sender_strategies.telegram is False
    assert config.sender_strategies.aiocqhttp is True
    assert config.sender_strategies.qq_official is True


def test_sender_strategies_parse_new_list_config_and_ignore_unsupported_items():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config(
        {"sender_strategies": ["telegram", "unknown"]}
    )

    assert config.sender_strategies.telegram is True
    assert config.sender_strategies.aiocqhttp is False
    assert config.sender_strategies.qq_official is False


def test_sender_strategies_parse_nested_enabled_platforms_config():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "sender_strategies": {
                "enabled_platforms": ["telegram", "qq_official", "unknown"]
            }
        }
    )

    assert config.sender_strategies.telegram is True
    assert config.sender_strategies.aiocqhttp is False
    assert config.sender_strategies.qq_official is True


def test_sender_strategies_parse_empty_list_as_all_disabled():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config({"sender_strategies": []})

    assert config.sender_strategies.telegram is False
    assert config.sender_strategies.aiocqhttp is False
    assert config.sender_strategies.qq_official is False


def test_sender_strategies_parse_delimited_string_config():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config(
        {"sender_strategies": "telegram, aiocqhttp\nunknown"}
    )

    assert config.sender_strategies.telegram is True
    assert config.sender_strategies.aiocqhttp is True
    assert config.sender_strategies.qq_official is False


def test_config_save_writes_single_sender_strategy_template_list_with_enabled_platforms():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    class FakeAstrBotConfig(dict):
        saved = False

        def save_config(self):
            self.saved = True

    config = RsshubPluginConfig.from_astrbot_config(
        {"sender_strategies": ["telegram", "qq_official"]}
    )
    astrbot_config = FakeAstrBotConfig()

    config.save(astrbot_config)

    assert astrbot_config.saved is True
    assert astrbot_config["sender_strategies"] == {
        "enabled_platforms": ["telegram", "qq_official"],
        "platform_strategies": [],
    }


def test_content_handler_ai_config_maps_to_runtime_settings_and_saves():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        RsshubPluginConfig,
        build_application_settings,
    )

    class FakeAstrBotConfig(dict):
        saved = False

        def save_config(self):
            self.saved = True

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "content_handlers": {
                "ai_provider_id": "provider-1",
                "ai_persona_id": "persona-1",
            }
        }
    )

    settings = build_application_settings(config)

    assert settings.content_handlers.ai_provider_id == "provider-1"
    assert settings.content_handlers.ai_persona_id == "persona-1"

    astrbot_config = FakeAstrBotConfig()
    config.save(astrbot_config)

    assert astrbot_config.saved is True
    assert astrbot_config["content_handlers"] == {
        "ai_provider_id": "provider-1",
        "ai_persona_id": "persona-1",
    }


def test_sender_strategies_parse_platform_strategy_objects_without_breaking_enabled_platforms():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "sender_strategies": {
                "enabled_platforms": ["telegram", "aiocqhttp"],
                "telegram": {
                    "enable_telegraph": True,
                    "telegraph_token": "token-1",
                },
                "aiocqhttp": {
                    "enable_telegraph": False,
                    "prefer_local_video": False,
                },
            }
        }
    )

    assert config.sender_strategies.telegram is True
    assert config.sender_strategies.aiocqhttp is True
    assert config.sender_strategies.qq_official is False
    assert config.sender_strategies.telegram_settings.enable_telegraph is True
    assert config.sender_strategies.telegram_settings.telegraph_token == "token-1"
    assert config.sender_strategies.aiocqhttp_settings.enable_telegraph is False
    assert config.sender_strategies.aiocqhttp_settings.prefer_local_video is False


def test_sender_strategies_parse_unified_template_list_and_use_first_item_per_type():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "sender_strategies": {
                "enabled_platforms": ["telegram", "aiocqhttp"],
                "platform_strategies": [
                    {
                        "__template_key": "telegram_strategy",
                        "enable_telegraph": True,
                        "telegraph_token": "first-token",
                    },
                    {
                        "__template_key": "telegram_strategy",
                        "enable_telegraph": False,
                        "telegraph_token": "second-token",
                    },
                    {
                        "__template_key": "onebot_strategy",
                        "prefer_local_video": True,
                    },
                ],
            }
        }
    )

    assert config.sender_strategies.telegram_settings.enable_telegraph is True
    assert config.sender_strategies.telegram_settings.telegraph_token == "first-token"
    assert config.sender_strategies.aiocqhttp_settings.prefer_local_video is True


def test_config_save_writes_non_default_sender_strategy_to_unified_template_list():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    class FakeAstrBotConfig(dict):
        saved = False

        def save_config(self):
            self.saved = True

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "sender_strategies": {
                "enabled_platforms": ["telegram"],
                "platform_strategies": [
                    {
                        "__template_key": "telegram_strategy",
                        "enable_telegraph": True,
                        "telegraph_token": "token-1",
                    }
                ],
            }
        }
    )
    astrbot_config = FakeAstrBotConfig()

    config.save(astrbot_config)

    assert astrbot_config["sender_strategies"]["platform_strategies"] == [
        {
            "__template_key": "telegram_strategy",
            "enable_telegraph": True,
            "telegraph_token": "token-1",
        }
    ]


def test_config_save_ignores_telegram_onebot_only_strategy_fields():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    class FakeAstrBotConfig(dict):
        def save_config(self):
            pass

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "sender_strategies": {
                "enabled_platforms": ["telegram"],
                "platform_strategies": [
                    {
                        "__template_key": "telegram_strategy",
                        "prefer_local_video": True,
                    }
                ],
            }
        }
    )
    astrbot_config = FakeAstrBotConfig()

    config.save(astrbot_config)

    assert astrbot_config["sender_strategies"]["platform_strategies"] == []


def test_config_save_ignores_onebot_telegraph_strategy_fields():
    from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig

    class FakeAstrBotConfig(dict):
        def save_config(self):
            pass

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "sender_strategies": {
                "enabled_platforms": ["aiocqhttp"],
                "platform_strategies": [
                    {
                        "__template_key": "onebot_strategy",
                        "enable_telegraph": True,
                        "telegraph_token": "ignored-token",
                    }
                ],
            }
        }
    )
    astrbot_config = FakeAstrBotConfig()

    config.save(astrbot_config)

    assert astrbot_config["sender_strategies"]["platform_strategies"] == []


def test_application_settings_maps_unified_sender_strategy_templates():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        build_application_settings,
    )

    settings = build_application_settings(
        {
            "sender_strategies": {
                "enabled_platforms": ["telegram", "aiocqhttp"],
                "platform_strategies": [
                    {
                        "__template_key": "onebot_strategy",
                        "prefer_local_video": True,
                    },
                    {
                        "__template_key": "telegram_strategy",
                        "enable_telegraph": True,
                        "telegraph_token": "telegram-token",
                    },
                    {
                        "__template_key": "telegram_strategy",
                        "enable_telegraph": False,
                        "telegraph_token": "ignored-token",
                    },
                ],
            }
        }
    )

    assert settings.sender_strategies.telegram_settings.enable_telegraph is True
    assert settings.sender_strategies.telegram_settings.telegraph_token == (
        "telegram-token"
    )
    assert settings.sender_strategies.aiocqhttp_settings.enable_telegraph is False
    assert settings.sender_strategies.aiocqhttp_settings.telegraph_token == ""
    assert settings.sender_strategies.aiocqhttp_settings.prefer_local_video is True


def test_application_settings_maps_ffmpeg_config():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        RsshubPluginConfig,
        build_application_settings,
    )

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "ffmpeg": {
                "video_transcode": True,
                "video_transcode_timeout": 333,
                "gif_transcode": True,
                "gif_transcode_timeout": 44,
            }
        }
    )

    settings = build_application_settings(config)

    assert settings.ffmpeg.video_transcode is True
    assert settings.ffmpeg.video_transcode_timeout == 333
    assert settings.ffmpeg.gif_transcode is True
    assert settings.ffmpeg.gif_transcode_timeout == 44


def test_global_config_maps_new_send_mode_direct_send_to_db_values():
    from astrbot_plugin_rsshub.src.infrastructure.config import GlobalConfig

    config = GlobalConfig(send_mode="直接发送")

    assert config.to_db_values()["send_mode"] == 1


def test_global_config_reads_legacy_send_mode_values_as_new_semantics():
    from astrbot_plugin_rsshub.src.infrastructure.config import GlobalConfig

    assert GlobalConfig.from_db_values({"send_mode": 1}).send_mode == "自动"
    assert GlobalConfig.from_db_values({"send_mode": 2}).send_mode == "直接发送"


def test_application_settings_maps_new_sender_strategy_list():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        build_application_settings,
    )

    settings = build_application_settings(
        {"sender_strategies": ["aiocqhttp", "unknown"]}
    )

    assert settings.sender_strategies.telegram is False
    assert settings.sender_strategies.aiocqhttp is True
    assert settings.sender_strategies.qq_official is False


def test_application_settings_maps_nested_sender_strategy_config():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        build_application_settings,
    )

    settings = build_application_settings(
        {"sender_strategies": {"enabled_platforms": ["telegram", "qq_official"]}}
    )

    assert settings.sender_strategies.telegram is True
    assert settings.sender_strategies.aiocqhttp is False
    assert settings.sender_strategies.qq_official is True


@pytest.mark.asyncio
async def test_user_settings_supports_only_user_or_banned_state():
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.set_user_settings_cmd import (
        SetUserSettingsCommand,
    )
    from astrbot_plugin_rsshub.src.domain.entities.user import User

    repo = AsyncMock()
    repo.get_by_id.return_value = User(id="u1")
    repo.save.side_effect = lambda user: user

    cmd = SetUserSettingsCommand(repo)
    ok = await cmd.execute(user_id="u1", settings={"state": -1})

    assert ok.success is True
    saved_user = repo.save.await_args.args[0]
    assert saved_user.state == -1

    bad = await cmd.execute(user_id="u1", settings={"state": 0})
    assert bad.success is False
    assert "只支持 -1" in bad.message


@pytest.mark.asyncio
async def test_user_settings_rejects_unknown_keys_but_allows_default_target_session():
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.set_user_settings_cmd import (
        SetUserSettingsCommand,
    )
    from astrbot_plugin_rsshub.src.domain.entities.user import User

    repo = AsyncMock()
    repo.get_by_id.return_value = User(id="u1")
    repo.save.side_effect = lambda user: user

    cmd = SetUserSettingsCommand(repo)
    ok = await cmd.execute(
        user_id="u1", settings={"default_target_session": "telegram:Chat:1"}
    )

    assert ok.success is True
    saved_user = repo.save.await_args.args[0]
    assert saved_user.default_target_session == "telegram:Chat:1"

    bad = await cmd.execute(user_id="u1", settings={"role": 100})
    assert bad.success is False
    assert "未知配置项" in bad.message


@pytest.mark.asyncio
async def test_user_settings_allows_inherit_value_for_profile_options():
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.set_user_settings_cmd import (
        SetUserSettingsCommand,
    )
    from astrbot_plugin_rsshub.src.domain.entities.user import User

    repo = AsyncMock()
    repo.get_by_id.return_value = User(id="u1")
    repo.save.side_effect = lambda user: user

    cmd = SetUserSettingsCommand(repo)
    ok = await cmd.execute(user_id="u1", settings={"send_mode": -100})

    assert ok.success is True
    saved_user = repo.save.await_args.args[0]
    assert saved_user.send_mode == -100


@pytest.mark.asyncio
async def test_user_settings_rejects_interval_below_configured_minimum(monkeypatch):
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.set_user_settings_cmd import (
        SetUserSettingsCommand,
    )
    from astrbot_plugin_rsshub.src.domain.entities.user import User
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        RsshubPluginConfig,
        config_loader,
    )

    repo = AsyncMock()
    repo.get_by_id.return_value = User(id="u1")
    monkeypatch.setattr(
        config_loader,
        "_config",
        RsshubPluginConfig.from_astrbot_config(
            {"basic_config": {"minimal_interval": 5}}
        ),
    )

    cmd = SetUserSettingsCommand(repo)
    result = await cmd.execute(user_id="u1", settings={"interval": 4})

    assert result.success is False
    assert "最小监控间隔 5 分钟" in result.message
    repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_settings_parses_and_persists_handlers():
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.set_user_settings_cmd import (
        SetUserSettingsCommand,
    )
    from astrbot_plugin_rsshub.src.domain.entities.user import User

    repo = AsyncMock()
    repo.get_by_id.return_value = User(id="u1")
    repo.save.side_effect = lambda user: user

    cmd = SetUserSettingsCommand(repo)
    result = await cmd.execute(
        user_id="u1",
        settings={
            "handlers": '[{"id":"builtin.xml_parse.default","type":"builtin","name":"xml_parse","status":1,"config":{}}]'
        },
    )

    assert result.success is True
    saved_user = repo.save.await_args.args[0]
    assert saved_user.get_handlers() == []


@pytest.mark.asyncio
async def test_user_settings_rejects_removed_inherit_switch():
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.set_user_settings_cmd import (
        SetUserSettingsCommand,
    )
    from astrbot_plugin_rsshub.src.domain.entities.user import User

    repo = AsyncMock()
    repo.get_by_id.return_value = User(id="u1")

    cmd = SetUserSettingsCommand(repo)
    result = await cmd.execute(user_id="u1", settings={"use_user_config": 1})

    assert result.success is False
    assert "已移除" in result.message
    repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_settings_reject_removed_inherit_switch():
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.update_subscription_cmd import (
        UpdateSubscriptionCommand,
    )

    repo = AsyncMock()
    cmd = UpdateSubscriptionCommand(repo)
    result = await cmd.execute(sub_id=1, user_id="u1", use_sub_config=1)

    assert result.success is False
    assert "已移除" in result.message
    repo.update_options.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_settings_accepts_handlers_mode():
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.update_subscription_cmd import (
        UpdateSubscriptionCommand,
    )
    from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription

    repo = AsyncMock()
    repo.update_options.return_value = Subscription(
        id=1,
        user_id="u1",
        feed_id=10,
        handlers_mode="disabled",
    )

    cmd = UpdateSubscriptionCommand(repo)
    result = await cmd.execute(sub_id=1, user_id="u1", handlers_mode="disabled")

    assert result.success is True
    repo.update_options.assert_awaited_once_with(
        1,
        "u1",
        handlers_mode="disabled",
    )


@pytest.mark.asyncio
async def test_subscription_settings_rejects_invalid_handlers_mode():
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.update_subscription_cmd import (
        UpdateSubscriptionCommand,
    )

    repo = AsyncMock()
    cmd = UpdateSubscriptionCommand(repo)
    result = await cmd.execute(sub_id=1, user_id="u1", handlers_mode="follow")

    assert result.success is False
    assert "handlers_mode" in result.message
    repo.update_options.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_settings_rejects_interval_below_configured_minimum(
    monkeypatch,
):
    from unittest.mock import AsyncMock

    from astrbot_plugin_rsshub.src.application.commands.update_subscription_cmd import (
        UpdateSubscriptionCommand,
    )
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        RsshubPluginConfig,
        config_loader,
    )

    repo = AsyncMock()
    monkeypatch.setattr(
        config_loader,
        "_config",
        RsshubPluginConfig.from_astrbot_config(
            {"basic_config": {"minimal_interval": 5}}
        ),
    )

    cmd = UpdateSubscriptionCommand(repo)
    result = await cmd.execute(sub_id=1, user_id="u1", interval=4)

    assert result.success is False
    assert "最小监控间隔 5 分钟" in result.message
    repo.update_options.assert_not_awaited()


def test_application_settings_maps_route_knowledge_provider_ids():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        RsshubPluginConfig,
        build_application_settings,
    )

    config = RsshubPluginConfig.from_astrbot_config(
        {
            "route_knowledge": {
                "embedding_provider_id": "embedding-configured",
                "rerank_provider_id": "rerank-configured",
            },
        }
    )

    settings = build_application_settings(config)

    assert settings.route_knowledge.embedding_provider_id == "embedding-configured"
    assert settings.route_knowledge.rerank_provider_id == "rerank-configured"


def test_application_settings_normalizes_legacy_route_knowledge_urls():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        build_application_settings,
    )

    settings = build_application_settings(
        {
            "route_knowledge": {
                "source_base_url": (
                    "https://ghfast.top/https://raw.githubusercontent.com/"
                    "FlanChanXwO/astrbot_plugin_rsshub/rsshub-routes-knowledgebase"
                ),
                "fallback_base_url": (
                    "https://raw.githubusercontent.com/"
                    "FlanChanXwO/astrbot_plugin_rsshub/rsshub-routes-knowledgebase"
                ),
            }
        }
    )

    assert settings.route_knowledge.source_base_url == (
        "https://ghfast.top/https://raw.githubusercontent.com/"
        "FlanChanXwO/rsshub-routes-knowledgebase/main"
    )
    assert settings.route_knowledge.fallback_base_url == (
        "https://raw.githubusercontent.com/FlanChanXwO/rsshub-routes-knowledgebase/main"
    )


def test_application_settings_maps_history_retention_days():
    from astrbot_plugin_rsshub.src.infrastructure.config import (
        build_application_settings,
    )

    settings = build_application_settings(
        {
            "basic_config": {
                "history_retention_days": "7",
            }
        }
    )

    assert settings.scheduler.history_retention_days == 7
