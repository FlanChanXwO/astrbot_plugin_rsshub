"""Schema regression tests."""

from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def test_conf_schema_is_scoped_to_startup_credentials_and_sender_strategies():
    schema = json.loads((PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

    assert set(schema) == {
        "basic_config",
        "content_handlers",
        "http_config",
        "media",
        "route_knowledge",
        "sender_strategies",
    }
    content_handler_items = schema["content_handlers"]["items"]
    assert content_handler_items["ai_provider_id"]["_special"] == "select_provider"
    assert content_handler_items["ai_provider_id"]["default"] == ""
    assert content_handler_items["ai_persona_id"]["_special"] == "select_persona"
    assert content_handler_items["ai_persona_id"]["default"] == ""

    route_knowledge_items = schema["route_knowledge"]["items"]
    assert route_knowledge_items["kb_name"]["default"] == "RSSHub Routes"
    assert route_knowledge_items["embedding_provider_id"]["default"] == ""
    assert (
        route_knowledge_items["embedding_provider_id"]["_special"]
        == "select_provider:embedding"
    )
    assert route_knowledge_items["rerank_provider_id"]["default"] == ""
    assert (
        route_knowledge_items["rerank_provider_id"]["_special"]
        == "select_provider:rerank"
    )
    assert route_knowledge_items["source_mode"]["default"] == "speed_test"
    assert route_knowledge_items["source_mode"]["options"] == [
        "speed_test",
        "mirror",
        "auto",
        "github",
        "local",
    ]
    source_options = [
        "https://raw.githubusercontent.com/FlanChanXwO/rsshub-routes-knowledgebase/main",
        "https://ghfast.top/https://raw.githubusercontent.com/FlanChanXwO/rsshub-routes-knowledgebase/main",
    ]
    assert route_knowledge_items["source_base_url"]["default"] == source_options[0]
    assert route_knowledge_items["source_base_url"]["options"] == source_options
    assert route_knowledge_items["fallback_base_url"]["options"] == source_options
    assert route_knowledge_items["timeout"]["slider"] == {
        "min": 1,
        "max": 300,
        "step": 1,
    }
    assert route_knowledge_items["batch_size"]["slider"] == {
        "min": 1,
        "max": 256,
        "step": 1,
    }
    assert route_knowledge_items["tasks_limit"]["slider"] == {
        "min": 1,
        "max": 32,
        "step": 1,
    }
    assert route_knowledge_items["max_retries"]["slider"] == {
        "min": 0,
        "max": 10,
        "step": 1,
    }
    assert "global_config" not in schema
    assert "pipeline" not in schema
    assert "translation" not in schema

    basic_config_items = schema["basic_config"]["items"]
    assert "download_media_before_send" not in basic_config_items
    assert "proxy" not in basic_config_items
    assert "timeout" not in basic_config_items
    assert basic_config_items["minimal_interval"]["slider"] == {
        "min": 1,
        "max": 1440,
        "step": 1,
    }
    assert basic_config_items["hash_history_min"]["slider"] == {
        "min": 1,
        "max": 20000,
        "step": 50,
    }
    assert basic_config_items["failed_queue_capacity"]["slider"] == {
        "min": 0,
        "max": 1000,
        "step": 10,
    }
    assert basic_config_items["failed_queue_max_retries"]["slider"] == {
        "min": 0,
        "max": 10,
        "step": 1,
    }
    assert "download_media_timeout" not in basic_config_items

    http_config_items = schema["http_config"]["items"]
    assert set(http_config_items) == {"proxy", "timeout", "media_timeout"}
    assert http_config_items["timeout"]["slider"] == {
        "min": 1,
        "max": 300,
        "step": 1,
    }
    assert http_config_items["media_timeout"]["slider"] == {
        "min": 1,
        "max": 1800,
        "step": 1,
    }

    assert "ffmpeg" not in schema
    media_items = schema["media"]["items"]
    assert "telegraph_proxy" not in media_items
    assert media_items["image_relay_base_url"]["default"] == ""
    assert media_items["media_relay_base_url"]["default"] == ""
    assert media_items["media_download_concurrency"]["default"] == 1
    assert media_items["media_download_concurrency"]["slider"] == {
        "min": 1,
        "max": 32,
        "step": 1,
    }
    assert media_items["cache_enabled"]["type"] == "bool"
    assert media_items["cache_enabled"]["default"] is True
    assert "GIF" in media_items["cache_enabled"]["hint"]
    assert "MP4" in media_items["cache_enabled"]["hint"]
    assert media_items["cache_ttl_seconds"]["type"] == "int"
    assert media_items["cache_ttl_seconds"]["default"] == 900
    assert "GIF" in media_items["cache_ttl_seconds"]["hint"]
    assert "MP4" in media_items["cache_ttl_seconds"]["hint"]
    assert media_items["cache_ttl_seconds"]["slider"] == {
        "min": 60,
        "max": 604800,
        "step": 60,
    }
    assert media_items["table_to_image"]["default"] is True
    assert media_items["video_transcode_timeout"]["slider"] == {
        "min": 10,
        "max": 1800,
        "step": 10,
    }
    assert media_items["gif_transcode_timeout"]["slider"] == {
        "min": 10,
        "max": 1800,
        "step": 10,
    }
    assert media_items["ffmpeg_source"]["default"] == "auto"
    assert media_items["ffmpeg_source"]["options"] == ["auto", "system"]
    assert media_items["ffmpeg_mirror"]["default"] == "auto"
    assert media_items["ffmpeg_mirror"]["options"] == [
        "auto",
        "default",
        "ghfast",
        "ghproxy",
        "mirror_ghproxy",
        "gh_proxy",
        "custom",
    ]
    assert media_items["ffmpeg_mirror_custom_url"]["default"] == ""

    sender_strategies = schema["sender_strategies"]
    sender_strategy_options = [
        "telegram",
        "aiocqhttp",
        "qq_official",
    ]
    assert sender_strategies["type"] == "object"
    enabled_platforms = sender_strategies["items"]["enabled_platforms"]
    assert enabled_platforms["type"] == "list"
    assert enabled_platforms["default"] == sender_strategy_options
    assert enabled_platforms["options"] == sender_strategy_options
    assert enabled_platforms["items"]["type"] == "string"


def test_conf_schema_exposes_single_platform_strategy_template_list():
    schema = json.loads((PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    sender_items = schema["sender_strategies"]["items"]

    assert "telegram" not in sender_items
    assert "aiocqhttp" not in sender_items
    platform_strategies = sender_items["platform_strategies"]
    assert platform_strategies["type"] == "template_list"
    assert platform_strategies["default"] == []
    assert "dict" not in json.dumps(schema)

    templates = platform_strategies["templates"]
    telegram_items = templates["telegram_strategy"]["items"]
    onebot_items = templates["onebot_strategy"]["items"]
    qq_official_items = templates["qq_official_strategy"]["items"]
    assert telegram_items["enable_telegraph"]["type"] == "bool"
    assert telegram_items["telegraph_token"]["type"] == "string"
    assert telegram_items["telegraph_proxy"]["type"] == "string"
    assert telegram_items["telegraph_proxy"]["default"] == ""
    assert "napcat_stream_mode" not in telegram_items
    assert "markdown_mode" not in telegram_items
    assert "enable_telegraph" not in onebot_items
    assert "telegraph_token" not in onebot_items
    assert "markdown_mode" not in onebot_items
    assert onebot_items["napcat_stream_mode"]["type"] == "string"
    assert onebot_items["napcat_stream_mode"]["default"] == "fallback"
    assert onebot_items["napcat_stream_mode"]["options"] == [
        "disabled",
        "fallback",
        "always",
    ]
    assert qq_official_items["markdown_mode"]["type"] == "string"
    assert qq_official_items["markdown_mode"]["default"] == "auto"
    assert qq_official_items["markdown_mode"]["options"] == [
        "auto",
        "force",
        "plain",
    ]
    assert "enable_telegraph" not in qq_official_items
    assert "napcat_stream_mode" not in qq_official_items
