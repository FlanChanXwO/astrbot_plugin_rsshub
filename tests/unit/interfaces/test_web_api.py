from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.dto.subscription_dto import SubscriptionDTO
from astrbot_plugin_rsshub.src.application.services.feed_polling_service import (
    FeedPollingResult,
)
from astrbot_plugin_rsshub.src.infrastructure.config import RsshubPluginConfig
from astrbot_plugin_rsshub.src.interfaces import web_api
from astrbot_plugin_rsshub.src.interfaces.web_api import WebApiHandler
from quart import Quart


class _WritableConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = False

    def save_config(self):
        self.saved = True


def _handler(
    *,
    polling_service,
    config=None,
    raw_config=None,
    subscribe_cmd=None,
    unsubscribe_cmd=None,
    update_sub_cmd=None,
    batch_activate_cmd=None,
    batch_deactivate_cmd=None,
    batch_unsub_cmd=None,
    export_cmd=None,
    import_cmd=None,
    get_user_settings_cmd=None,
    set_user_settings_cmd=None,
    test_sub_cmd=None,
    route_knowledge_service=None,
    push_history_repo=None,
    notification_dispatcher=None,
    sub_repo=None,
    user_repo=None,
):
    return WebApiHandler(
        subscribe_cmd=subscribe_cmd or MagicMock(),
        unsubscribe_cmd=unsubscribe_cmd or MagicMock(),
        update_sub_cmd=update_sub_cmd or MagicMock(),
        batch_activate_cmd=batch_activate_cmd or MagicMock(),
        batch_deactivate_cmd=batch_deactivate_cmd or MagicMock(),
        batch_unsub_cmd=batch_unsub_cmd or MagicMock(),
        export_cmd=export_cmd or MagicMock(),
        import_cmd=import_cmd or MagicMock(),
        get_user_settings_cmd=get_user_settings_cmd or MagicMock(),
        set_user_settings_cmd=set_user_settings_cmd or MagicMock(),
        test_sub_cmd=test_sub_cmd or MagicMock(),
        get_items_query=MagicMock(),
        polling_service=polling_service,
        feed_repo=MagicMock(),
        sub_repo=sub_repo or MagicMock(),
        user_repo=user_repo or MagicMock(),
        push_history_repo=push_history_repo or MagicMock(),
        notification_dispatcher=notification_dispatcher,
        route_knowledge_service=route_knowledge_service,
        config=config or MagicMock(),
        raw_config=raw_config,
    )


@pytest.mark.asyncio
async def test_refresh_feed_endpoint_uses_unified_polling_service():
    polling_service = MagicMock()
    polling_service.poll_feed = AsyncMock(
        return_value=FeedPollingResult(
            success=True,
            status="updated",
            message="ok",
            feed_id=12,
            total_entries=3,
            new_entries=1,
            dispatched=0,
        )
    )
    handler = _handler(polling_service=polling_service)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/refresh",
        method="POST",
        json={"feed_id": "12"},
    ):
        response = await handler.handle_refresh_feed()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["status"] == "updated"
    assert payload["feed_id"] == 12
    assert payload["total_entries"] == 3
    assert payload["new_entries"] == 1
    polling_service.poll_feed.assert_awaited_once_with(12)


@pytest.mark.asyncio
async def test_plugin_settings_endpoint_ignores_removed_pipeline_config():
    raw_config = _WritableConfig()
    config = RsshubPluginConfig.from_astrbot_config({})
    handler = _handler(
        polling_service=MagicMock(),
        config=config,
        raw_config=raw_config,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/plugin-settings",
        method="POST",
        json={
            "pipeline": {
                "keyword_blacklist": ["spam"],
                "ai_filter_enabled": True,
                "ai_timeout_seconds": 8,
            }
        },
    ):
        response = await handler.handle_set_plugin_settings()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert "pipeline" not in payload
    assert raw_config.saved is True
    assert "pipeline" not in raw_config


@pytest.mark.asyncio
async def test_plugin_settings_endpoint_updates_subscription_defaults():
    raw_config = _WritableConfig()
    config = RsshubPluginConfig.from_astrbot_config({})
    handler = _handler(
        polling_service=MagicMock(),
        config=config,
        raw_config=raw_config,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/plugin-settings",
        method="POST",
        json={
            "subscription_defaults": {
                "interval": 25,
                "notify": False,
                "send_mode": "仅链接",
                "translate": True,
            }
        },
    ):
        response = await handler.handle_set_plugin_settings()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["subscription_defaults"]["interval"] == 25
    assert payload["subscription_defaults"]["notify"] is False
    assert payload["subscription_defaults"]["send_mode"] == "仅链接"
    assert "translate" not in payload["subscription_defaults"]
    assert raw_config.saved is True
    assert raw_config["global_config"]["interval"] == 25
    assert raw_config["global_config"]["notify"] is False
    assert "translate" not in raw_config["global_config"]


@pytest.mark.asyncio
async def test_plugin_settings_endpoint_rejects_interval_below_minimal():
    raw_config = _WritableConfig()
    config = RsshubPluginConfig.from_astrbot_config(
        {"basic_config": {"minimal_interval": 5}}
    )
    handler = _handler(
        polling_service=MagicMock(),
        config=config,
        raw_config=raw_config,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/plugin-settings",
        method="POST",
        json={
            "subscription_defaults": {
                "interval": 4,
            }
        },
    ):
        response = await handler.handle_set_plugin_settings()

    payload = await response.get_json()
    assert payload["ok"] is False
    assert "最小监控间隔 5 分钟" in payload["error"]
    assert raw_config.saved is False


@pytest.mark.asyncio
async def test_plugin_settings_endpoint_ignores_history_retention_days_payload():
    raw_config = _WritableConfig()
    config = RsshubPluginConfig.from_astrbot_config(
        {"basic_config": {"history_retention_days": 30}}
    )
    handler = _handler(
        polling_service=MagicMock(),
        config=config,
        raw_config=raw_config,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/plugin-settings",
        method="POST",
        json={
            "history_retention_days": 7,
            "subscription_defaults": {"notify": False},
        },
    ):
        response = await handler.handle_set_plugin_settings()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert "history_retention_days" not in payload
    assert raw_config.saved is True
    assert raw_config["global_config"]["notify"] is False
    assert raw_config["basic_config"]["history_retention_days"] == 30


@pytest.mark.asyncio
async def test_handlers_endpoint_returns_registry_schema():
    handler = _handler(polling_service=MagicMock())

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/handlers",
        method="GET",
    ):
        response = await handler.handle_handlers()

    payload = await response.get_json()
    assert payload["ok"] is True
    names = {item["name"] for item in payload["items"]}
    assert names == {"ai_filter", "ai_transform"}
    ai_filter = next(item for item in payload["items"] if item["name"] == "ai_filter")
    assert any(field["type"] == "select" for field in ai_filter["schema"])
    ai_transform = next(
        item for item in payload["items"] if item["name"] == "ai_transform"
    )
    scope_field = next(
        field for field in ai_transform["schema"] if field["key"] == "scope"
    )
    assert scope_field["default"] == "plaintext"


@pytest.mark.asyncio
async def test_plugin_settings_endpoint_ignores_removed_translation_payload():
    raw_config = _WritableConfig()
    config = RsshubPluginConfig.from_astrbot_config({})
    handler = _handler(
        polling_service=MagicMock(),
        config=config,
        raw_config=raw_config,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/plugin-settings",
        method="POST",
        json={
            "translation": {
                "target_lang": "ja",
                "auto_translate": True,
                "google_translate_api_key": "",
                "baidu_translate_app_id": "",
                "baidu_translate_secret_key": "",
            }
        },
    ):
        response = await handler.handle_set_plugin_settings()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert "translation" not in payload
    assert "translation" not in raw_config


@pytest.mark.asyncio
async def test_import_endpoint_uses_import_command():
    import_cmd = MagicMock()
    import_cmd.execute = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            message="成功导入 1 个订阅",
            data=None,
        )
    )
    handler = _handler(polling_service=MagicMock(), import_cmd=import_cmd)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/import",
        method="POST",
        json={
            "content": "[[subscriptions]]\nurl='https://example.com/rss'",
            "user_id": "alice",
        },
    ):
        response = await handler.handle_import()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert "成功导入" in payload["message"]
    import_cmd.execute.assert_awaited_once_with(
        content="[[subscriptions]]\nurl='https://example.com/rss'",
        user_id="alice",
        target_session=None,
        platform_name=None,
        skip_existing=True,
    )


@pytest.mark.asyncio
async def test_subscriptions_endpoint_uses_dashboard_filters():
    sub_repo = MagicMock()
    sub_repo.list_for_dashboard = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=3,
                state=1,
                user_id="alice",
                feed_id=12,
                title="自定义标题",
                tags="pixiv,art",
                target_session="default:GroupMessage:1",
                platform_name="aiocqhttp",
                interval=15,
                notify=1,
                send_mode=0,
                handlers_mode="inherit",
                get_handlers=lambda: [],
                length_limit=0,
                display_author=0,
                display_via=0,
                display_title=0,
                display_entry_tags=0,
                style=0,
                display_media=0,
                created_at=None,
                updated_at=None,
            )
        ]
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=12, title="Pixiv Feed", link="https://example.com/feed"
        )
    )
    handler = _handler(polling_service=MagicMock())
    handler._sub_repo = sub_repo
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/subscriptions?"
        "user_id=alice&user_id=bob&feed_id=12&feed_id=15&"
        "feed_link=https%3A%2F%2Fexample.com%2Ffeed%3Ftag%3Da%2Cb&"
        "sub_id=3&sub_id=4&keyword=pixiv&keyword=art",
        method="GET",
    ):
        response = await handler.handle_list_subscriptions()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == 3
    assert payload["items"][0]["feed_title"] == "Pixiv Feed"
    sub_repo.list_for_dashboard.assert_awaited_once_with(
        user_ids=["alice", "bob"],
        feed_ids=[12, 15],
        feed_links=["https://example.com/feed?tag=a,b"],
        sub_ids=[3, 4],
        keywords=["pixiv", "art"],
    )


@pytest.mark.asyncio
async def test_subscriptions_endpoint_accepts_array_style_filter_params():
    sub_repo = MagicMock()
    sub_repo.list_for_dashboard = AsyncMock(return_value=[])
    handler = _handler(polling_service=MagicMock(), sub_repo=sub_repo)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/subscriptions?"
        "sub_id%5B%5D=1&feed_id%5B%5D=2&"
        "feed_link%5B%5D=https%3A%2F%2Fexample.com%2Ffeed&"
        "user_id%5B%5D=alice&keyword%5B%5D=pixiv",
        method="GET",
    ):
        response = await handler.handle_list_subscriptions()

    payload = await response.get_json()
    assert payload["ok"] is True
    sub_repo.list_for_dashboard.assert_awaited_once_with(
        user_ids=["alice"],
        feed_ids=[2],
        feed_links=["https://example.com/feed"],
        sub_ids=[1],
        keywords=["pixiv"],
    )


@pytest.mark.asyncio
async def test_push_history_endpoint_filters_by_user_session_and_status():
    push_history_repo = MagicMock()
    push_history_repo.get_by_user = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=11,
                user_id="alice",
                feed_id=None,
                source_type="agent",
                source_key="daily:ai-news",
                content="hello",
                raw_xml="<entry><p>Hello</p></entry>",
                media_urls=["https://example.com/a.jpg"],
                handler_trace=[
                    {
                        "id": "builtin.ai_filter.default",
                        "name": "ai_filter",
                        "status": "ok",
                        "allow": False,
                        "reason": "广告",
                    }
                ],
                entry_title="日报",
                entry_link="https://example.com/post",
                entry_guid="guid-11",
                feed_title="AI Daily",
                feed_link="https://example.com/feed",
                platform_name="aiocqhttp",
                target_session="default:GroupMessage:1",
                status="failed",
                retry_count=1,
                max_retries=3,
                fail_reason="boom",
                created_at=None,
                updated_at=None,
                completed_at=None,
                sub_id=None,
            )
        ]
    )
    push_history_repo.count_by_user = AsyncMock(return_value=1)
    handler = WebApiHandler(
        subscribe_cmd=MagicMock(),
        unsubscribe_cmd=MagicMock(),
        update_sub_cmd=MagicMock(),
        batch_activate_cmd=MagicMock(),
        batch_deactivate_cmd=MagicMock(),
        batch_unsub_cmd=MagicMock(),
        export_cmd=MagicMock(),
        import_cmd=MagicMock(),
        get_user_settings_cmd=MagicMock(),
        set_user_settings_cmd=MagicMock(),
        test_sub_cmd=MagicMock(),
        get_items_query=MagicMock(),
        polling_service=MagicMock(),
        feed_repo=MagicMock(),
        sub_repo=MagicMock(),
        user_repo=MagicMock(),
        push_history_repo=push_history_repo,
        route_knowledge_service=None,
        config=MagicMock(),
        raw_config=None,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/push-history?user_id=alice&target_session=default:GroupMessage:1&status=failed&feed_link=https%3A%2F%2Fexample.com%2Ffeed&page=1&page_size=20",
        method="GET",
    ):
        response = await handler.handle_push_history()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["items"][0]["raw_xml"] == "<entry><p>Hello</p></entry>"
    assert payload["items"][0]["handler_trace"][0]["name"] == "ai_filter"
    assert payload["items"][0]["fail_reason"] == "boom"
    assert payload["items"][0]["sub_id"] is None
    push_history_repo.get_by_user.assert_awaited_once_with(
        user_id="alice",
        limit=20,
        offset=0,
        target_session="default:GroupMessage:1",
        status="failed",
        keywords=["https://example.com/feed"],
    )
    push_history_repo.count_by_user.assert_awaited_once_with(
        user_id="alice",
        target_session="default:GroupMessage:1",
        status="failed",
        keywords=["https://example.com/feed"],
    )


@pytest.mark.asyncio
async def test_push_history_endpoint_keeps_empty_fail_reason_empty_for_success():
    push_history_repo = MagicMock()
    push_history_repo.get_by_user = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=12,
                user_id="alice",
                feed_id=1,
                source_type="feed",
                source_key=None,
                content="ok",
                raw_xml=None,
                media_urls=None,
                handler_trace=None,
                entry_title="成功记录",
                entry_link="https://example.com/post",
                entry_guid="guid-12",
                feed_title="AI Daily",
                feed_link="https://example.com/feed",
                platform_name="aiocqhttp",
                target_session="default:GroupMessage:1",
                status="success",
                retry_count=0,
                max_retries=3,
                fail_reason=None,
                created_at=None,
                updated_at=None,
                completed_at=None,
                sub_id=1,
            )
        ]
    )
    push_history_repo.count_by_user = AsyncMock(return_value=1)
    handler = WebApiHandler(
        subscribe_cmd=MagicMock(),
        unsubscribe_cmd=MagicMock(),
        update_sub_cmd=MagicMock(),
        batch_activate_cmd=MagicMock(),
        batch_deactivate_cmd=MagicMock(),
        batch_unsub_cmd=MagicMock(),
        export_cmd=MagicMock(),
        import_cmd=MagicMock(),
        get_user_settings_cmd=MagicMock(),
        set_user_settings_cmd=MagicMock(),
        test_sub_cmd=MagicMock(),
        get_items_query=MagicMock(),
        polling_service=MagicMock(),
        feed_repo=MagicMock(),
        sub_repo=MagicMock(),
        user_repo=MagicMock(),
        push_history_repo=push_history_repo,
        route_knowledge_service=None,
        config=MagicMock(),
        raw_config=None,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/push-history?user_id=alice&target_session=default:GroupMessage:1&status=success&page=1&page_size=20",
        method="GET",
    ):
        response = await handler.handle_push_history()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["items"][0]["fail_reason"] is None
    assert payload["items"][0]["sub_id"] == 1


@pytest.mark.asyncio
async def test_delete_push_history_endpoint_supports_batch_delete():
    push_history_repo = MagicMock()
    push_history_repo.delete_many = AsyncMock(return_value=2)
    handler = WebApiHandler(
        subscribe_cmd=MagicMock(),
        unsubscribe_cmd=MagicMock(),
        update_sub_cmd=MagicMock(),
        batch_activate_cmd=MagicMock(),
        batch_deactivate_cmd=MagicMock(),
        batch_unsub_cmd=MagicMock(),
        export_cmd=MagicMock(),
        import_cmd=MagicMock(),
        get_user_settings_cmd=MagicMock(),
        set_user_settings_cmd=MagicMock(),
        test_sub_cmd=MagicMock(),
        get_items_query=MagicMock(),
        polling_service=MagicMock(),
        feed_repo=MagicMock(),
        sub_repo=MagicMock(),
        user_repo=MagicMock(),
        push_history_repo=push_history_repo,
        route_knowledge_service=None,
        config=MagicMock(),
        raw_config=None,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/push-history/delete",
        method="POST",
        json={"history_ids": [11, 12, 12]},
    ):
        response = await handler.handle_delete_push_history()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 2
    push_history_repo.delete_many.assert_awaited_once_with([11, 12])


@pytest.mark.asyncio
async def test_retry_push_history_endpoint_delegates_to_dispatcher():
    dispatcher = MagicMock()
    dispatcher.retry_push_history_once = AsyncMock(
        return_value={
            "ok": True,
            "message": "重试发送成功",
            "history": SimpleNamespace(
                id=12,
                status="success",
                updated_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
                completed_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
            ),
        }
    )
    handler = _handler(
        polling_service=MagicMock(),
        notification_dispatcher=dispatcher,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/push-history/retry",
        method="POST",
        json={"history_id": 12},
    ):
        response = await handler.handle_retry_push_history()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["message"] == "重试发送成功"
    assert payload["source_history_id"] == 12
    assert payload["history_id"] == 12
    assert payload["status"] == "success"
    dispatcher.retry_push_history_once.assert_awaited_once_with(12)


@pytest.mark.asyncio
async def test_retry_push_history_endpoint_rejects_non_numeric_history_id():
    dispatcher = MagicMock()
    dispatcher.retry_push_history_once = AsyncMock()
    handler = _handler(
        polling_service=MagicMock(),
        notification_dispatcher=dispatcher,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/push-history/retry",
        method="POST",
        json={"history_id": "abc"},
    ):
        response = await handler.handle_retry_push_history()

    payload = await response.get_json()
    assert payload == {"ok": False, "error": "history_id 不能为空"}
    dispatcher.retry_push_history_once.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_push_history_endpoint_returns_removed_count():
    push_history_repo = MagicMock()
    push_history_repo.delete_old_records = AsyncMock(return_value=42)
    handler = _handler(
        polling_service=MagicMock(),
        push_history_repo=push_history_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/push-history/cleanup",
        method="POST",
        json={"days": 7},
    ):
        response = await handler.handle_cleanup_push_history()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 42
    assert payload["message"] == "已清理 42 条记录"
    push_history_repo.delete_old_records.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_clear_push_history_endpoint_deletes_all_history_rows():
    push_history_repo = MagicMock()
    push_history_repo.delete_all = AsyncMock(return_value=9607)
    handler = _handler(
        polling_service=MagicMock(),
        push_history_repo=push_history_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/push-history/clear",
        method="POST",
        json={},
    ):
        response = await handler.handle_clear_push_history()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 9607
    assert payload["message"] == "已清空 9607 条记录"
    push_history_repo.delete_all.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_user_details_endpoint_supports_keyword_filtering():
    user_repo = MagicMock()
    user_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id="alice",
                state=1,
                interval=-100,
                notify=-100,
                send_mode=-100,
                length_limit=-100,
                display_author=-100,
                display_via=-100,
                display_title=-100,
                display_entry_tags=-100,
                style=-100,
                display_media=-100,
                default_target_session="group:1",
                get_handlers=lambda: [],
                created_at=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id="bob",
                state=1,
                interval=-100,
                notify=-100,
                send_mode=-100,
                length_limit=-100,
                display_author=-100,
                display_via=-100,
                display_title=-100,
                display_entry_tags=-100,
                style=-100,
                display_media=-100,
                default_target_session="private:2",
                get_handlers=lambda: [],
                created_at=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.list_for_dashboard = AsyncMock(
        return_value=[
            SimpleNamespace(id=1, user_id="alice", state=1),
            SimpleNamespace(id=2, user_id="alice", state=0),
            SimpleNamespace(id=3, user_id="bob", state=1),
        ]
    )
    handler = WebApiHandler(
        subscribe_cmd=MagicMock(),
        unsubscribe_cmd=MagicMock(),
        update_sub_cmd=MagicMock(),
        batch_activate_cmd=MagicMock(),
        batch_deactivate_cmd=MagicMock(),
        batch_unsub_cmd=MagicMock(),
        export_cmd=MagicMock(),
        import_cmd=MagicMock(),
        get_user_settings_cmd=MagicMock(),
        set_user_settings_cmd=MagicMock(),
        test_sub_cmd=MagicMock(),
        get_items_query=MagicMock(),
        polling_service=MagicMock(),
        feed_repo=MagicMock(),
        sub_repo=sub_repo,
        user_repo=user_repo,
        push_history_repo=MagicMock(),
        route_knowledge_service=None,
        config=MagicMock(),
        raw_config=None,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/users/detail?keyword=group",
        method="GET",
    ):
        response = await handler.handle_user_details()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["items"][0]["user_id"] == "alice"
    assert payload["items"][0]["subscription_count"] == 2
    assert payload["items"][0]["active_subscription_count"] == 1


@pytest.mark.asyncio
async def test_user_details_keyword_matches_subscription_and_feed_titles_case_insensitive():
    user_repo = MagicMock()
    user_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id="alice",
                state=1,
                interval=-100,
                notify=-100,
                send_mode=-100,
                length_limit=-100,
                display_author=-100,
                display_via=-100,
                display_title=-100,
                display_entry_tags=-100,
                style=-100,
                display_media=-100,
                default_target_session=None,
                get_handlers=lambda: [],
                created_at=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id="bob",
                state=1,
                interval=-100,
                notify=-100,
                send_mode=-100,
                length_limit=-100,
                display_author=-100,
                display_via=-100,
                display_title=-100,
                display_entry_tags=-100,
                style=-100,
                display_media=-100,
                default_target_session=None,
                get_handlers=lambda: [],
                created_at=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.list_for_dashboard = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=1,
                user_id="alice",
                feed_id=10,
                state=1,
                title="Daily Drawings",
                tags="pixiv",
            ),
            SimpleNamespace(
                id=2,
                user_id="bob",
                feed_id=20,
                state=1,
                title="News",
                tags="",
            ),
        ]
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(
        side_effect=lambda feed_id: SimpleNamespace(
            id=feed_id,
            title="Blue Archive Art" if feed_id == 10 else "Tech News",
            link=f"https://example.com/{feed_id}",
        )
    )
    handler = _handler(
        polling_service=MagicMock(),
        sub_repo=sub_repo,
        user_repo=user_repo,
    )
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/users/detail?keyword=ARCHIVE",
        method="GET",
    ):
        response = await handler.handle_user_details()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["items"][0]["user_id"] == "alice"


@pytest.mark.asyncio
async def test_user_details_endpoint_supports_multi_user_id_filtering():
    user_repo = MagicMock()
    user_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id="alice",
                state=1,
                interval=-100,
                notify=-100,
                send_mode=-100,
                length_limit=-100,
                display_author=-100,
                display_via=-100,
                display_title=-100,
                display_entry_tags=-100,
                style=-100,
                display_media=-100,
                default_target_session="group:1",
                get_handlers=lambda: [],
                created_at=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id="bob",
                state=1,
                interval=-100,
                notify=-100,
                send_mode=-100,
                length_limit=-100,
                display_author=-100,
                display_via=-100,
                display_title=-100,
                display_entry_tags=-100,
                style=-100,
                display_media=-100,
                default_target_session="group:2",
                get_handlers=lambda: [],
                created_at=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id="carol",
                state=1,
                interval=-100,
                notify=-100,
                send_mode=-100,
                length_limit=-100,
                display_author=-100,
                display_via=-100,
                display_title=-100,
                display_entry_tags=-100,
                style=-100,
                display_media=-100,
                default_target_session="group:3",
                get_handlers=lambda: [],
                created_at=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.list_for_dashboard = AsyncMock(return_value=[])
    handler = _handler(polling_service=MagicMock())
    handler._user_repo = user_repo
    handler._sub_repo = sub_repo

    app = Quart(__name__)
    async with app.test_request_context(
        '/astrbot_plugin_rsshub/users/detail?user_id=["alice","bob"]',
        method="GET",
    ):
        response = await handler.handle_user_details()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 2
    assert [item["user_id"] for item in payload["items"]] == ["alice", "bob"]
    sub_repo.list_for_dashboard.assert_awaited_once_with(user_ids=["alice", "bob"])


@pytest.mark.asyncio
async def test_user_details_endpoint_returns_empty_for_unknown_user_id_without_sub_query():
    user_repo = MagicMock()
    user_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id="alice",
                state=1,
                interval=-100,
                notify=-100,
                send_mode=-100,
                length_limit=-100,
                display_author=-100,
                display_via=-100,
                display_title=-100,
                display_entry_tags=-100,
                style=-100,
                display_media=-100,
                default_target_session="group:1",
                get_handlers=lambda: [],
                created_at=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.list_for_dashboard = AsyncMock(return_value=[])
    handler = _handler(
        polling_service=MagicMock(), user_repo=user_repo, sub_repo=sub_repo
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/users/detail?user_id=missing",
        method="GET",
    ):
        response = await handler.handle_user_details()

    payload = await response.get_json()
    assert payload == {"ok": True, "items": [], "total": 0}
    sub_repo.list_for_dashboard.assert_not_awaited()


@pytest.mark.asyncio
async def test_string_query_values_do_not_split_legacy_separators():
    feed_repo = MagicMock()
    feed_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=1,
                title="Pixiv,Blue Archive",
                link="https://example.com/rss",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.get_all_active = AsyncMock(return_value=[])
    handler = _handler(polling_service=MagicMock(), sub_repo=sub_repo)
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds?keyword=Pixiv,Blue",
        method="GET",
    ):
        response = await handler.handle_feeds()

    payload = await response.get_json()
    assert payload["total"] == 1


@pytest.mark.asyncio
async def test_int_query_values_keep_legacy_separator_compatibility():
    feed_repo = MagicMock()
    feed_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=1,
                title="One",
                link="https://example.com/1",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id=2,
                title="Two",
                link="https://example.com/2",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id=3,
                title="Three",
                link="https://example.com/3",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.get_all_active = AsyncMock(return_value=[])
    handler = _handler(polling_service=MagicMock(), sub_repo=sub_repo)
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds?feed_id=1,2%EF%BC%8C3",
        method="GET",
    ):
        response = await handler.handle_feeds()

    payload = await response.get_json()
    assert [item["id"] for item in payload["items"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_feeds_endpoint_supports_keyword_filtering():
    feed_repo = MagicMock()
    feed_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=1,
                title="Pixiv Feed",
                link="https://example.com/pixiv",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id=2,
                title="Twitter Feed",
                link="https://example.com/x",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.get_all_active = AsyncMock(return_value=[])
    handler = WebApiHandler(
        subscribe_cmd=MagicMock(),
        unsubscribe_cmd=MagicMock(),
        update_sub_cmd=MagicMock(),
        batch_activate_cmd=MagicMock(),
        batch_deactivate_cmd=MagicMock(),
        batch_unsub_cmd=MagicMock(),
        export_cmd=MagicMock(),
        import_cmd=MagicMock(),
        get_user_settings_cmd=MagicMock(),
        set_user_settings_cmd=MagicMock(),
        test_sub_cmd=MagicMock(),
        get_items_query=MagicMock(),
        polling_service=MagicMock(),
        feed_repo=feed_repo,
        sub_repo=sub_repo,
        user_repo=MagicMock(),
        push_history_repo=MagicMock(),
        route_knowledge_service=None,
        config=MagicMock(),
        raw_config=None,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds?keyword=pixiv",
        method="GET",
    ):
        response = await handler.handle_feeds()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == 1


@pytest.mark.asyncio
async def test_feeds_endpoint_keyword_matches_title_case_insensitive():
    feed_repo = MagicMock()
    feed_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=1,
                title="Pixiv Feed",
                link="https://example.com/pixiv",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id=2,
                title="Blue Archive Updates",
                link="https://example.com/archive",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.get_all_active = AsyncMock(return_value=[])
    handler = _handler(polling_service=MagicMock(), sub_repo=sub_repo)
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds?keyword=ARCHIVE",
        method="GET",
    ):
        response = await handler.handle_feeds()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == 2


@pytest.mark.asyncio
async def test_feeds_endpoint_supports_multi_feed_id_filtering():
    feed_repo = MagicMock()
    feed_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=1,
                title="Pixiv Feed",
                link="https://example.com/pixiv",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id=2,
                title="Twitter Feed",
                link="https://example.com/x",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id=3,
                title="Bili Feed",
                link="https://example.com/bili",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.get_all_active = AsyncMock(return_value=[])
    handler = _handler(polling_service=MagicMock())
    handler._feed_repo = feed_repo
    handler._sub_repo = sub_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds?feed_id=1&feed_id=3",
        method="GET",
    ):
        response = await handler.handle_feeds()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 2
    assert [item["id"] for item in payload["items"]] == [1, 3]


@pytest.mark.asyncio
async def test_feeds_endpoint_accepts_array_style_feed_id_filtering():
    feed_repo = MagicMock()
    feed_repo.get_all = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=1,
                title="Pixiv Feed",
                link="https://example.com/pixiv",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id=2,
                title="Twitter Feed",
                link="https://example.com/x",
                state=1,
                last_modified=None,
                updated_at=None,
            ),
        ]
    )
    sub_repo = MagicMock()
    sub_repo.get_all_active = AsyncMock(return_value=[])
    handler = _handler(polling_service=MagicMock())
    handler._feed_repo = feed_repo
    handler._sub_repo = sub_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds?feed_id%5B%5D=2",
        method="GET",
    ):
        response = await handler.handle_feeds()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == 2


@pytest.mark.asyncio
async def test_filter_values_do_not_split_commas_or_newlines():
    sub_repo = MagicMock()
    sub_repo.list_for_dashboard = AsyncMock(return_value=[])
    handler = _handler(polling_service=MagicMock(), sub_repo=sub_repo)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/subscriptions?"
        "user_id=alice,bob&keyword=pixiv%0Aart&"
        "feed_link=https%3A%2F%2Fexample.com%2Ffeed%3Ftag%3Da%2Cb",
        method="GET",
    ):
        response = await handler.handle_list_subscriptions()

    payload = await response.get_json()
    assert payload["ok"] is True
    sub_repo.list_for_dashboard.assert_awaited_once_with(
        user_ids=["alice,bob"],
        feed_ids=None,
        feed_links=["https://example.com/feed?tag=a,b"],
        sub_ids=None,
        keywords=["pixiv\nart"],
    )


@pytest.mark.asyncio
async def test_refresh_feed_endpoint_supports_batch_refresh():
    polling_service = MagicMock()
    polling_service.poll_feed = AsyncMock(
        side_effect=[
            FeedPollingResult(
                success=True,
                status="updated",
                message="ok",
                feed_id=1,
                total_entries=3,
                new_entries=1,
                dispatched=0,
            ),
            FeedPollingResult(
                success=False,
                status="failed",
                message="boom",
                feed_id=2,
                total_entries=0,
                new_entries=0,
                dispatched=0,
                error="boom",
            ),
        ]
    )
    handler = _handler(polling_service=polling_service)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/refresh",
        method="POST",
        json={"feed_ids": [1, 2]},
    ):
        response = await handler.handle_refresh_feed()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["success_count"] == 1
    assert len(payload["results"]) == 2


@pytest.mark.asyncio
async def test_update_feed_endpoint_updates_basic_fields():
    feed = SimpleNamespace(
        id=3,
        title="Old title",
        link="https://example.com/old.xml",
        state=1,
        updated_at=None,
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.get_by_link = AsyncMock(return_value=None)
    feed_repo.save = AsyncMock(side_effect=lambda item: item)
    handler = _handler(polling_service=MagicMock())
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/update",
        method="POST",
        json={
            "feed_id": 3,
            "options": {
                "title": " New title ",
                "link": "https://example.com/new.xml",
                "state": 0,
            },
        },
    ):
        response = await handler.handle_update_feed()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["id"] == 3
    assert feed.title == "New title"
    assert feed.link == "https://example.com/new.xml"
    assert feed.state == 0
    assert feed.updated_at is not None
    feed_repo.get_by_id.assert_awaited_once_with(3)
    feed_repo.get_by_link.assert_awaited_once_with("https://example.com/new.xml")
    feed_repo.save.assert_awaited_once_with(feed)


@pytest.mark.asyncio
async def test_update_feed_endpoint_rejects_invalid_link():
    feed = SimpleNamespace(
        id=3,
        title="Old title",
        link="https://example.com/old.xml",
        state=1,
        updated_at=None,
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.get_by_link = AsyncMock()
    feed_repo.save = AsyncMock()
    handler = _handler(polling_service=MagicMock())
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/update",
        method="POST",
        json={"feed_id": 3, "options": {"link": "javascript:alert(1)"}},
    ):
        response = await handler.handle_update_feed()

    payload = await response.get_json()
    assert payload["ok"] is False
    assert "http/https" in payload["error"]
    feed_repo.get_by_id.assert_awaited_once_with(3)
    feed_repo.get_by_link.assert_not_awaited()
    feed_repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_feed_endpoint_rejects_duplicate_link():
    feed = SimpleNamespace(
        id=3,
        title="Old title",
        link="https://example.com/old.xml",
        state=1,
        updated_at=None,
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.get_by_link = AsyncMock(
        return_value=SimpleNamespace(id=4, link="https://example.com/new.xml")
    )
    feed_repo.save = AsyncMock()
    handler = _handler(polling_service=MagicMock())
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/update",
        method="POST",
        json={"feed_id": 3, "options": {"link": "https://example.com/new.xml"}},
    ):
        response = await handler.handle_update_feed()

    payload = await response.get_json()
    assert payload["ok"] is False
    assert "已存在" in payload["error"]
    feed_repo.get_by_id.assert_awaited_once_with(3)
    feed_repo.get_by_link.assert_awaited_once_with("https://example.com/new.xml")
    feed_repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_feed_endpoint_uses_new_link_for_blank_title():
    feed = SimpleNamespace(
        id=3,
        title="Old title",
        link="https://example.com/old.xml",
        state=1,
        updated_at=None,
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.get_by_link = AsyncMock(return_value=None)
    feed_repo.save = AsyncMock(side_effect=lambda item: item)
    handler = _handler(polling_service=MagicMock())
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/update",
        method="POST",
        json={
            "feed_id": 3,
            "options": {"title": "  ", "link": "https://example.com/new.xml"},
        },
    ):
        response = await handler.handle_update_feed()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert feed.link == "https://example.com/new.xml"
    assert feed.title == "https://example.com/new.xml"


@pytest.mark.asyncio
async def test_delete_feeds_endpoint_deletes_feeds_and_subscriptions_without_history():
    feed_repo = MagicMock()
    feed_repo.delete_many = AsyncMock(return_value=2)
    sub_repo = MagicMock()
    sub_repo.delete_all_by_feed_ids = AsyncMock(return_value=5)
    push_history_repo = MagicMock()
    push_history_repo.delete_by_feed_ids = AsyncMock(return_value=0)
    handler = _handler(
        polling_service=MagicMock(),
        sub_repo=sub_repo,
        push_history_repo=push_history_repo,
    )
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/delete",
        method="POST",
        json={"feed_ids": [1, 2]},
    ):
        response = await handler.handle_delete_feeds()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 2
    assert payload["deleted_subscriptions"] == 5
    assert payload["deleted_push_history"] == 0
    sub_repo.delete_all_by_feed_ids.assert_awaited_once_with([1, 2])
    feed_repo.delete_many.assert_awaited_once_with([1, 2])
    push_history_repo.delete_by_feed_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_feeds_endpoint_can_delete_push_history():
    feed_repo = MagicMock()
    feed_repo.delete_many = AsyncMock(return_value=1)
    sub_repo = MagicMock()
    sub_repo.delete_all_by_feed_ids = AsyncMock(return_value=2)
    push_history_repo = MagicMock()
    push_history_repo.delete_by_feed_ids = AsyncMock(return_value=7)
    handler = _handler(
        polling_service=MagicMock(),
        sub_repo=sub_repo,
        push_history_repo=push_history_repo,
    )
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/delete",
        method="POST",
        json={"feed_id": 9, "delete_push_history": True},
    ):
        response = await handler.handle_delete_feeds()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 1
    assert payload["deleted_subscriptions"] == 2
    assert payload["deleted_push_history"] == 7
    sub_repo.delete_all_by_feed_ids.assert_awaited_once_with([9])
    push_history_repo.delete_by_feed_ids.assert_awaited_once_with([9])
    feed_repo.delete_many.assert_awaited_once_with([9])


@pytest.mark.asyncio
async def test_delete_feeds_endpoint_rejects_non_numeric_feed_ids_without_500():
    feed_repo = MagicMock()
    feed_repo.delete_many = AsyncMock()
    sub_repo = MagicMock()
    sub_repo.delete_all_by_feed_ids = AsyncMock()
    handler = _handler(polling_service=MagicMock(), sub_repo=sub_repo)
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/delete",
        method="POST",
        json={"feed_ids": ["abc"]},
    ):
        response = await handler.handle_delete_feeds()

    payload = await response.get_json()
    assert payload == {"ok": False, "error": "feed_id 或 feed_ids 不能为空"}
    sub_repo.delete_all_by_feed_ids.assert_not_awaited()
    feed_repo.delete_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_feeds_endpoint_ok_when_only_related_data_was_removed():
    feed_repo = MagicMock()
    feed_repo.delete_many = AsyncMock(return_value=0)
    sub_repo = MagicMock()
    sub_repo.delete_all_by_feed_ids = AsyncMock(return_value=2)
    handler = _handler(polling_service=MagicMock(), sub_repo=sub_repo)
    handler._feed_repo = feed_repo

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/delete",
        method="POST",
        json={"feed_id": 9},
    ):
        response = await handler.handle_delete_feeds()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 0
    assert payload["deleted_subscriptions"] == 2
    assert payload["message"] == "Feed 未删除，但已清理关联数据"


@pytest.mark.asyncio
async def test_delete_user_endpoint_supports_batch_delete():
    sub_repo = MagicMock()
    sub_repo.delete_all_by_user = AsyncMock(return_value=1)
    user_repo = MagicMock()
    user_repo.delete = AsyncMock(side_effect=[True, True])
    push_history_repo = MagicMock()
    push_history_repo.delete_by_user = AsyncMock(return_value=0)
    handler = WebApiHandler(
        subscribe_cmd=MagicMock(),
        unsubscribe_cmd=MagicMock(),
        update_sub_cmd=MagicMock(),
        batch_activate_cmd=MagicMock(),
        batch_deactivate_cmd=MagicMock(),
        batch_unsub_cmd=MagicMock(),
        export_cmd=MagicMock(),
        import_cmd=MagicMock(),
        get_user_settings_cmd=MagicMock(),
        set_user_settings_cmd=MagicMock(),
        test_sub_cmd=MagicMock(),
        get_items_query=MagicMock(),
        polling_service=MagicMock(),
        feed_repo=MagicMock(),
        sub_repo=sub_repo,
        user_repo=user_repo,
        push_history_repo=push_history_repo,
        route_knowledge_service=None,
        config=MagicMock(),
        raw_config=None,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/users/delete",
        method="POST",
        json={"user_ids": ["alice", "bob"]},
    ):
        response = await handler.handle_delete_user()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 2
    assert payload["deleted_subscriptions"] == 2
    assert payload["deleted_push_history"] == 0
    push_history_repo.delete_by_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_user_endpoint_can_delete_push_history():
    sub_repo = MagicMock()
    sub_repo.delete_all_by_user = AsyncMock(return_value=2)
    user_repo = MagicMock()
    user_repo.delete = AsyncMock(return_value=True)
    push_history_repo = MagicMock()
    push_history_repo.delete_by_user = AsyncMock(return_value=5)
    handler = _handler(
        polling_service=MagicMock(),
        sub_repo=sub_repo,
        user_repo=user_repo,
        push_history_repo=push_history_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/users/delete",
        method="POST",
        json={"user_id": "alice", "delete_push_history": True},
    ):
        response = await handler.handle_delete_user()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 1
    assert payload["deleted_subscriptions"] == 2
    assert payload["deleted_push_history"] == 5
    assert payload["message"] == "用户 alice 已删除"
    push_history_repo.delete_by_user.assert_awaited_once_with("alice")


@pytest.mark.asyncio
async def test_delete_user_endpoint_cleans_orphan_user_resources():
    sub_repo = MagicMock()
    sub_repo.delete_all_by_user = AsyncMock(return_value=1)
    user_repo = MagicMock()
    user_repo.delete = AsyncMock(return_value=False)
    push_history_repo = MagicMock()
    push_history_repo.delete_by_user = AsyncMock(return_value=0)
    handler = _handler(
        polling_service=MagicMock(),
        sub_repo=sub_repo,
        user_repo=user_repo,
        push_history_repo=push_history_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/users/delete",
        method="POST",
        json={"user_id": "orphan"},
    ):
        response = await handler.handle_delete_user()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 1
    assert payload["deleted_subscriptions"] == 1
    assert payload["message"] == "已清理用户 orphan 的关联数据"
    push_history_repo.delete_by_user.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "command_attr", "json_payload"),
    [
        ("handle_subscribe", "_subscribe_cmd", {"url": "https://example.com/rss"}),
        ("handle_unsubscribe", "_unsubscribe_cmd", {"sub_id": 1}),
        ("handle_update_subscription", "_update_sub_cmd", {"sub_id": 1}),
        ("handle_get_settings", "_get_user_settings_cmd", None),
        ("handle_set_settings", "_set_user_settings_cmd", {"settings": {}}),
        ("handle_test_subscription", "_test_sub_cmd", {"sub_id": 1}),
        ("handle_batch_activate", "_batch_activate_cmd", {"sub_ids": [1]}),
        ("handle_batch_deactivate", "_batch_deactivate_cmd", {"sub_ids": [1]}),
        ("handle_batch_unsubscribe", "_batch_unsub_cmd", {"sub_ids": [1]}),
        ("handle_export", "_export_cmd", {}),
        (
            "handle_import",
            "_import_cmd",
            {"content": "[[subscriptions]]\nurl='https://example.com/rss'"},
        ),
    ],
)
async def test_user_command_endpoints_reject_missing_user_id(
    handler_name, command_attr, json_payload
):
    handler = _handler(polling_service=MagicMock())
    command = getattr(handler, command_attr)
    command.execute = AsyncMock()

    app = Quart(__name__)
    method = "GET" if handler_name == "handle_get_settings" else "POST"
    async with app.test_request_context(
        f"/astrbot_plugin_rsshub/{handler_name}",
        method=method,
        json=json_payload,
    ):
        response = await getattr(handler, handler_name)()

    payload = await response.get_json()
    assert payload == {"ok": False, "error": "user_id 不能为空"}
    command.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "command_attr", "json_payload", "path"),
    [
        (
            "handle_subscribe",
            "_subscribe_cmd",
            {"url": "https://example.com/rss", "user_id": " "},
            "/astrbot_plugin_rsshub/subscribe",
        ),
        (
            "handle_unsubscribe",
            "_unsubscribe_cmd",
            {"sub_id": 1, "user_id": ""},
            "/astrbot_plugin_rsshub/unsubscribe",
        ),
        (
            "handle_update_subscription",
            "_update_sub_cmd",
            {"sub_id": 1, "user_id": " "},
            "/astrbot_plugin_rsshub/subscriptions/update",
        ),
        (
            "handle_get_settings",
            "_get_user_settings_cmd",
            None,
            "/astrbot_plugin_rsshub/settings?user_id=",
        ),
        (
            "handle_set_settings",
            "_set_user_settings_cmd",
            {"settings": {}, "user_id": ""},
            "/astrbot_plugin_rsshub/settings",
        ),
        (
            "handle_test_subscription",
            "_test_sub_cmd",
            {"sub_id": 1, "user_id": " "},
            "/astrbot_plugin_rsshub/test-subscription",
        ),
        (
            "handle_batch_activate",
            "_batch_activate_cmd",
            {"sub_ids": [1], "user_id": ""},
            "/astrbot_plugin_rsshub/batch/activate",
        ),
        (
            "handle_batch_deactivate",
            "_batch_deactivate_cmd",
            {"sub_ids": [1], "user_id": " "},
            "/astrbot_plugin_rsshub/batch/deactivate",
        ),
        (
            "handle_batch_unsubscribe",
            "_batch_unsub_cmd",
            {"sub_ids": [1], "user_id": ""},
            "/astrbot_plugin_rsshub/batch/unsubscribe",
        ),
        (
            "handle_export",
            "_export_cmd",
            {"user_id": " "},
            "/astrbot_plugin_rsshub/export",
        ),
        (
            "handle_import",
            "_import_cmd",
            {
                "content": "[[subscriptions]]\nurl='https://example.com/rss'",
                "user_id": "",
            },
            "/astrbot_plugin_rsshub/import",
        ),
    ],
)
async def test_user_command_endpoints_reject_blank_user_id(
    handler_name, command_attr, json_payload, path
):
    handler = _handler(polling_service=MagicMock())
    command = getattr(handler, command_attr)
    command.execute = AsyncMock()

    app = Quart(__name__)
    method = "GET" if handler_name == "handle_get_settings" else "POST"
    async with app.test_request_context(path, method=method, json=json_payload):
        response = await getattr(handler, handler_name)()

    payload = await response.get_json()
    assert payload == {"ok": False, "error": "user_id 不能为空"}
    command.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_subscription_passes_real_user_id():
    command = MagicMock()
    command.execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="ok")
    )
    handler = _handler(polling_service=MagicMock(), update_sub_cmd=command)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/subscriptions/update",
        method="POST",
        json={
            "sub_id": 12,
            "user_id": "alice",
            "options": {"notify": False, "handlers_mode": "override"},
        },
    ):
        response = await handler.handle_update_subscription()

    payload = await response.get_json()
    assert payload["ok"] is True
    command.execute.assert_awaited_once_with(
        sub_id=12,
        user_id="alice",
        handlers_mode="override",
        notify=False,
    )


@pytest.mark.asyncio
async def test_list_subscriptions_returns_handlers_mode():
    sub_repo = MagicMock()
    feed_repo = MagicMock()
    sub_repo.list_for_dashboard = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=1,
                state=1,
                user_id="alice",
                feed_id=2,
                title="Daily",
                tags="news",
                target_session="default:GroupMessage:1",
                platform_name="aiocqhttp",
                interval=15,
                notify=1,
                send_mode=0,
                handlers_mode="disabled",
                handlers=[],
                get_handlers=lambda: [],
                length_limit=300,
                display_author=1,
                display_via=0,
                display_title=1,
                display_entry_tags=0,
                style=0,
                display_media=0,
                created_at=None,
                updated_at=None,
            )
        ]
    )
    feed_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            title="Feed Title",
            link="https://example.com/feed.xml",
        )
    )
    handler = WebApiHandler(
        subscribe_cmd=MagicMock(),
        unsubscribe_cmd=MagicMock(),
        update_sub_cmd=MagicMock(),
        batch_activate_cmd=MagicMock(),
        batch_deactivate_cmd=MagicMock(),
        batch_unsub_cmd=MagicMock(),
        export_cmd=MagicMock(),
        import_cmd=MagicMock(),
        get_user_settings_cmd=MagicMock(),
        set_user_settings_cmd=MagicMock(),
        test_sub_cmd=MagicMock(),
        get_items_query=MagicMock(),
        polling_service=MagicMock(),
        feed_repo=feed_repo,
        sub_repo=sub_repo,
        user_repo=MagicMock(),
        push_history_repo=MagicMock(),
        route_knowledge_service=None,
        config=MagicMock(),
        raw_config=None,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/subscriptions",
        method="GET",
    ):
        response = await handler.handle_list_subscriptions()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["items"][0]["handlers_mode"] == "disabled"
    sub_repo.list_for_dashboard.assert_awaited_once_with(
        user_ids=None,
        feed_ids=None,
        feed_links=None,
        sub_ids=None,
        keywords=None,
    )


@pytest.mark.asyncio
async def test_unsubscribe_passes_real_user_id():
    command = MagicMock()
    command.execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="ok")
    )
    push_history_repo = MagicMock()
    push_history_repo.delete_by_sub_ids = AsyncMock(return_value=0)
    handler = _handler(
        polling_service=MagicMock(),
        unsubscribe_cmd=command,
        push_history_repo=push_history_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/unsubscribe",
        method="POST",
        json={"sub_id": 12, "user_id": "alice"},
    ):
        response = await handler.handle_unsubscribe()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["deleted_push_history"] == 0
    command.execute.assert_awaited_once_with(sub_id=12, user_id="alice")
    push_history_repo.delete_by_sub_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsubscribe_can_delete_push_history_by_sub_id():
    command = MagicMock()
    command.execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="ok")
    )
    push_history_repo = MagicMock()
    push_history_repo.delete_by_sub_ids = AsyncMock(return_value=3)
    handler = _handler(
        polling_service=MagicMock(),
        unsubscribe_cmd=command,
        push_history_repo=push_history_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/unsubscribe",
        method="POST",
        json={"sub_id": 12, "user_id": "alice", "delete_push_history": True},
    ):
        response = await handler.handle_unsubscribe()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["deleted_push_history"] == 3
    command.execute.assert_awaited_once_with(sub_id=12, user_id="alice")
    push_history_repo.delete_by_sub_ids.assert_awaited_once_with([12])


@pytest.mark.asyncio
async def test_test_subscription_passes_real_user_id():
    command = MagicMock()
    command.execute_target = AsyncMock(
        return_value=SimpleNamespace(success=True, message="ok", data={"sent": True})
    )
    handler = _handler(polling_service=MagicMock(), test_sub_cmd=command)
    handler._sub_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=12,
            user_id="alice",
            target_session="default:GroupMessage:1",
            platform_name="aiocqhttp",
        )
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/test-subscription",
        method="POST",
        json={"sub_id": 12, "user_id": "alice"},
    ):
        response = await handler.handle_test_subscription()

    payload = await response.get_json()
    assert payload["ok"] is True
    command.execute_target.assert_awaited_once_with(
        target="12",
        user_id="alice",
        target_session="default:GroupMessage:1",
        platform_name="aiocqhttp",
    )


@pytest.mark.asyncio
async def test_test_subscription_serializes_nested_dto_payload():
    command = MagicMock()
    command.execute_target = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            message="ok",
            data={
                "subscription": SubscriptionDTO(
                    id=12,
                    user_id="alice",
                    feed_id=34,
                    title="示例订阅",
                    tags="pixiv",
                    target_session="default:GroupMessage:1",
                    platform_name="aiocqhttp",
                    state=1,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
                "test_result": SimpleNamespace(
                    entry_count=1,
                    sample_entries=[{"title": "Entry"}],
                ),
            },
        )
    )
    handler = _handler(polling_service=MagicMock(), test_sub_cmd=command)
    handler._sub_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=12,
            user_id="alice",
            target_session="default:GroupMessage:1",
            platform_name="aiocqhttp",
        )
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/test-subscription",
        method="POST",
        json={"sub_id": 12, "user_id": "alice"},
    ):
        response = await handler.handle_test_subscription()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["subscription"]["feed_id"] == 34
    assert payload["data"]["subscription"]["title"] == "示例订阅"
    assert payload["data"]["test_result"]["entry_count"] == 1


@pytest.mark.asyncio
async def test_test_subscription_uses_user_default_target_when_subscription_target_missing():
    command = MagicMock()
    command.execute_target = AsyncMock(
        return_value=SimpleNamespace(success=True, message="ok", data={"sent": True})
    )
    handler = _handler(polling_service=MagicMock(), test_sub_cmd=command)
    handler._sub_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=12,
            user_id="alice",
            target_session="",
            platform_name="aiocqhttp",
        )
    )
    handler._user_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(default_target_session="default:GroupMessage:9")
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/test-subscription",
        method="POST",
        json={"sub_id": 12, "user_id": "alice"},
    ):
        response = await handler.handle_test_subscription()

    payload = await response.get_json()
    assert payload["ok"] is True
    command.execute_target.assert_awaited_once_with(
        target="12",
        user_id="alice",
        target_session="default:GroupMessage:9",
        platform_name="aiocqhttp",
    )


@pytest.mark.asyncio
async def test_test_subscription_rejects_missing_target_and_platform():
    command = MagicMock()
    command.execute_target = AsyncMock()
    handler = _handler(polling_service=MagicMock(), test_sub_cmd=command)
    handler._sub_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=12,
            user_id="alice",
            target_session="",
            platform_name="",
        )
    )
    handler._user_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(default_target_session="")
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/test-subscription",
        method="POST",
        json={"sub_id": 12, "user_id": "alice"},
    ):
        response = await handler.handle_test_subscription()

    payload = await response.get_json()
    assert payload == {"ok": False, "error": "订阅和用户都未配置推送目标会话"}
    command.execute_target.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_operations_pass_real_user_id():
    activate_cmd = MagicMock()
    activate_cmd.execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="activated")
    )
    deactivate_cmd = MagicMock()
    deactivate_cmd.execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="deactivated")
    )
    unsub_cmd = MagicMock()
    unsub_cmd.execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="unsubscribed")
    )
    push_history_repo = MagicMock()
    push_history_repo.delete_by_sub_ids = AsyncMock(return_value=0)
    handler = _handler(
        polling_service=MagicMock(),
        batch_activate_cmd=activate_cmd,
        batch_deactivate_cmd=deactivate_cmd,
        batch_unsub_cmd=unsub_cmd,
        push_history_repo=push_history_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/batch/activate",
        method="POST",
        json={"sub_ids": [1, 2], "user_id": "alice"},
    ):
        activate_response = await handler.handle_batch_activate()
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/batch/deactivate",
        method="POST",
        json={"sub_ids": [3], "user_id": "alice"},
    ):
        deactivate_response = await handler.handle_batch_deactivate()
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/batch/unsubscribe",
        method="POST",
        json={"sub_ids": [4], "user_id": "alice"},
    ):
        unsub_response = await handler.handle_batch_unsubscribe()

    assert (await activate_response.get_json())["ok"] is True
    assert (await deactivate_response.get_json())["ok"] is True
    unsub_payload = await unsub_response.get_json()
    assert unsub_payload["ok"] is True
    assert unsub_payload["deleted_push_history"] == 0
    activate_cmd.execute.assert_awaited_once_with(sub_ids=[1, 2], user_id="alice")
    deactivate_cmd.execute.assert_awaited_once_with(sub_ids=[3], user_id="alice")
    unsub_cmd.execute.assert_awaited_once_with(sub_ids=[4], user_id="alice")
    push_history_repo.delete_by_sub_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_unsubscribe_can_delete_push_history_by_sub_ids():
    unsub_cmd = MagicMock()
    unsub_cmd.execute = AsyncMock(
        return_value=SimpleNamespace(success=True, message="unsubscribed")
    )
    push_history_repo = MagicMock()
    push_history_repo.delete_by_sub_ids = AsyncMock(return_value=6)
    handler = _handler(
        polling_service=MagicMock(),
        batch_unsub_cmd=unsub_cmd,
        push_history_repo=push_history_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/batch/unsubscribe",
        method="POST",
        json={
            "sub_ids": [4, "5"],
            "user_id": "alice",
            "delete_push_history": True,
        },
    ):
        response = await handler.handle_batch_unsubscribe()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["deleted_push_history"] == 6
    unsub_cmd.execute.assert_awaited_once_with(sub_ids=[4, 5], user_id="alice")
    push_history_repo.delete_by_sub_ids.assert_awaited_once_with([4, 5])


@pytest.mark.asyncio
async def test_batch_unsubscribe_rejects_non_numeric_sub_ids_without_500():
    unsub_cmd = MagicMock()
    unsub_cmd.execute = AsyncMock()
    push_history_repo = MagicMock()
    push_history_repo.delete_by_sub_ids = AsyncMock(return_value=0)
    handler = _handler(
        polling_service=MagicMock(),
        batch_unsub_cmd=unsub_cmd,
        push_history_repo=push_history_repo,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/batch/unsubscribe",
        method="POST",
        json={"sub_ids": ["abc"], "user_id": "alice"},
    ):
        response = await handler.handle_batch_unsubscribe()

    payload = await response.get_json()
    assert payload == {"ok": False, "error": "sub_ids 不能为空"}
    unsub_cmd.execute.assert_not_awaited()
    push_history_repo.delete_by_sub_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_export_passes_real_user_id():
    command = MagicMock()
    command.execute = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            message="ok",
            data=SimpleNamespace(content="toml", filename="subs.toml", count=1),
        )
    )
    handler = _handler(polling_service=MagicMock(), export_cmd=command)

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/export",
        method="POST",
        json={"user_id": "alice"},
    ):
        response = await handler.handle_export()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["data"]["filename"] == "subs.toml"
    command.execute.assert_awaited_once_with(user_id="alice")


@pytest.mark.asyncio
async def test_route_kb_status_endpoint_returns_service_status():
    service = MagicMock()
    service.get_status = AsyncMock(
        return_value=SimpleNamespace(
            kb_name="RSSHub Routes",
            kb_id="kb-1",
            source_version="v1",
            source_generated_at="",
            last_sync_at="2026-05-19T00:00:00Z",
            managed_files=3,
            kb_docs=3,
            last_error="",
            task=SimpleNamespace(status="idle", task_id="", processed=0, total=0),
        )
    )
    handler = _handler(
        polling_service=MagicMock(),
        route_knowledge_service=service,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/route-kb/status",
        method="GET",
    ):
        response = await handler.handle_route_kb_status()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["status"]["kb_name"] == "RSSHub Routes"
    assert payload["status"]["task"]["status"] == "idle"
    service.get_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_kb_sync_endpoint_starts_service_task():
    service = MagicMock()
    service.start_sync = AsyncMock(
        return_value=SimpleNamespace(
            task_id="task-1",
            status="queued",
            kb_name="RSSHub Routes",
            processed=0,
            total=0,
        )
    )
    handler = _handler(
        polling_service=MagicMock(),
        route_knowledge_service=service,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/route-kb/sync",
        method="POST",
        json={},
    ):
        response = await handler.handle_route_kb_sync()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["task"]["task_id"] == "task-1"
    assert payload["task"]["status"] == "queued"
    service.start_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_kb_task_endpoint_returns_latest_task():
    service = MagicMock()
    service.get_task_status.return_value = SimpleNamespace(
        task_id="task-1",
        status="running",
        processed=2,
        total=5,
    )
    handler = _handler(
        polling_service=MagicMock(),
        route_knowledge_service=service,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/route-kb/task",
        method="GET",
    ):
        response = await handler.handle_route_kb_task()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["task"]["status"] == "running"
    assert payload["task"]["processed"] == 2
    service.get_task_status.assert_called_once()


def _write_file(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_data_management_overview_returns_cache_and_export_stats(
    monkeypatch, tmp_path
):
    cache_dir = tmp_path / "cache"
    export_dir = tmp_path / "exports"
    _write_file(cache_dir / "media" / "a.jpg", b"1234")
    _write_file(cache_dir / "gif" / "b.gif", b"12")
    _write_file(export_dir / "feeds.toml", "name='a'\n")
    _write_file(export_dir / "nested" / "backup.toml", "name='b'\n")

    monkeypatch.setattr(
        web_api, "get_plugin_cache_dir", lambda *parts: cache_dir.joinpath(*parts)
    )
    monkeypatch.setattr(web_api, "get_plugin_export_dir", lambda: export_dir)

    handler = _handler(polling_service=MagicMock())
    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/data-management/overview",
        method="GET",
    ):
        response = await handler.handle_data_management_overview()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["cache"]["file_count"] == 2
    assert payload["exports"]["file_count"] == 2
    assert payload["totals"]["file_count"] == 4
    assert payload["cache"]["breakdown"][0]["name"] == "media"
    assert {item["name"] for item in payload["exports"]["breakdown"]} == {".toml"}


@pytest.mark.asyncio
async def test_list_exports_returns_toml_files_and_breakdown(monkeypatch, tmp_path):
    export_dir = tmp_path / "exports"
    _write_file(export_dir / "first.toml", "a=1\n")
    _write_file(export_dir / "nested" / "second.toml", "b=2\n")
    _write_file(export_dir / "ignored.txt", "x")

    monkeypatch.setattr(web_api, "get_plugin_export_dir", lambda: export_dir)

    handler = _handler(polling_service=MagicMock())
    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/data-management/exports",
        method="GET",
    ):
        response = await handler.handle_list_exports()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["file_count"] == 2
    assert [item["name"] for item in payload["items"]] == [
        "first.toml",
        "nested/second.toml",
    ]
    assert payload["breakdown"] == [
        {
            "name": ".toml",
            "size": sum(item["size"] for item in payload["items"]),
            "file_count": 2,
        },
        {"name": ".txt", "size": 1, "file_count": 1},
    ]


@pytest.mark.asyncio
async def test_download_export_returns_attachment_headers(monkeypatch, tmp_path):
    export_dir = tmp_path / "exports"
    export_file = export_dir / "feeds.toml"
    _write_file(export_file, "title='rss'\n")

    monkeypatch.setattr(web_api, "get_plugin_export_dir", lambda: export_dir)

    handler = _handler(polling_service=MagicMock())
    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/data-management/exports/download?name=feeds.toml",
        method="GET",
    ):
        response = await handler.handle_download_export()

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/toml")
    assert "attachment;" in response.headers["Content-Disposition"]
    assert "feeds.toml" in response.headers["Content-Disposition"]
    body = await response.get_data()
    assert body == b"title='rss'\n"


@pytest.mark.asyncio
async def test_export_content_returns_toml_text(monkeypatch, tmp_path):
    export_dir = tmp_path / "exports"
    export_file = export_dir / "preview.toml"
    _write_file(export_file, "title='preview'\n")

    monkeypatch.setattr(web_api, "get_plugin_export_dir", lambda: export_dir)

    handler = _handler(polling_service=MagicMock())
    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/data-management/exports/content?name=preview.toml",
        method="GET",
    ):
        response = await handler.handle_export_content()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["name"] == "preview.toml"
    assert payload["content"] == "title='preview'\n"
    assert payload["size"] == len(b"title='preview'\n")


@pytest.mark.asyncio
async def test_delete_export_removes_named_file(monkeypatch, tmp_path):
    export_dir = tmp_path / "exports"
    export_file = export_dir / "delete-me.toml"
    _write_file(export_file, "x=1\n")

    monkeypatch.setattr(web_api, "get_plugin_export_dir", lambda: export_dir)

    handler = _handler(polling_service=MagicMock())
    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/data-management/exports/delete",
        method="POST",
        json={"name": "delete-me.toml"},
    ):
        response = await handler.handle_delete_export()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert export_file.exists() is False


@pytest.mark.asyncio
async def test_clear_exports_removes_all_export_files(monkeypatch, tmp_path):
    export_dir = tmp_path / "exports"
    _write_file(export_dir / "a.toml", "a=1\n")
    _write_file(export_dir / "nested" / "b.toml", "b=2\n")

    monkeypatch.setattr(web_api, "get_plugin_export_dir", lambda: export_dir)

    handler = _handler(polling_service=MagicMock())
    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/data-management/exports/clear",
        method="POST",
        json={},
    ):
        response = await handler.handle_clear_exports()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 2
    assert list(export_dir.rglob("*")) == []


@pytest.mark.asyncio
async def test_clear_cache_removes_all_cached_files(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    _write_file(cache_dir / "media" / "a.jpg", b"a")
    _write_file(cache_dir / "gif" / "b.gif", b"bb")

    monkeypatch.setattr(
        web_api, "get_plugin_cache_dir", lambda *parts: cache_dir.joinpath(*parts)
    )

    handler = _handler(polling_service=MagicMock())
    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/data-management/cache/clear",
        method="POST",
        json={},
    ):
        response = await handler.handle_clear_cache()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert payload["removed_count"] == 2
    assert list(cache_dir.rglob("*")) == []
