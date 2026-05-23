from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.commands.export_subscriptions_cmd import (
    ExportSubscriptionsCommand,
)
from astrbot_plugin_rsshub.src.application.commands.test_subscription_cmd import (
    TestSubscriptionCommand,
)
from astrbot_plugin_rsshub.src.application.commands.unsubscribe_feed_cmd import (
    UnsubscribeFeedCommand,
)
from astrbot_plugin_rsshub.src.application.services.content_handlers import (
    EntryContentContext,
)
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription
from astrbot_plugin_rsshub.src.infrastructure.fetcher import EntryParsed


@pytest.mark.asyncio
async def test_sub_test_execute_target_dispatches_messages():
    sub_repo = MagicMock()
    feed_repo = MagicMock()
    dispatcher = MagicMock()
    dispatcher.send_to_session = AsyncMock(return_value={"ok": True})

    now = datetime.now(timezone.utc)
    entries = [
        EntryParsed(title="t1", link="l1", summary="s1", published=now),
        EntryParsed(title="t2", link="l2", summary="s2", published=now),
    ]
    polling = MagicMock()
    polling.fetch_feed_entries = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            entries=entries,
            message="ok",
            web_feed=SimpleNamespace(rss_d=SimpleNamespace(feed={"title": "timeline"})),
        )
    )

    cmd = TestSubscriptionCommand(
        subscription_repo=sub_repo,
        feed_repo=feed_repo,
        polling_service=polling,
        notification_dispatcher=dispatcher,
    )

    result = await cmd.execute_target(
        target="https://a.com/rss",
        user_id="u1",
        target_session="sess",
        platform_name="telegram",
        start=1,
        end=2,
    )
    assert result.success is True
    assert "范围" not in result.message
    assert "最新 2 条" in result.message
    assert dispatcher.send_to_session.await_count == 2
    first_call = dispatcher.send_to_session.await_args_list[0].kwargs
    assert "<br" not in first_call["content"]
    assert "via l1 | timeline" in first_call["content"]


@pytest.mark.asyncio
async def test_sub_test_execute_target_by_sub_id_uses_dispatcher_chain():
    sub_repo = MagicMock()
    feed_repo = MagicMock()
    dispatcher = MagicMock()
    dispatcher.dispatch_to_feed_subscribers = AsyncMock(
        return_value={"success": 1, "failed": 0, "pending": 0}
    )
    dispatcher.send_to_session = AsyncMock()

    subscription = Subscription(
        id=7,
        user_id="u1",
        feed_id=10,
        target_session="sess",
        platform_name="telegram",
    )
    feed = Feed(id=10, link="https://a.com/rss", title="timeline")
    sub_repo.get_by_id = AsyncMock(return_value=subscription)
    feed_repo.get_by_id = AsyncMock(return_value=feed)

    entry = EntryParsed(
        title="t1",
        link="https://entry.example/1",
        summary="t1<br /><img src='https://example.com/a.jpg' />",
        content="t1<br /><img src='https://example.com/a.jpg' />",
        raw_xml="<item><title>t1</title></item>",
        guid="guid-1",
        published=datetime.now(timezone.utc),
    )
    polling = MagicMock()
    polling.fetch_feed_entries = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            entries=[entry],
            message="ok",
            web_feed=SimpleNamespace(rss_d=SimpleNamespace(feed={"title": "timeline"})),
        )
    )

    cmd = TestSubscriptionCommand(
        subscription_repo=sub_repo,
        feed_repo=feed_repo,
        polling_service=polling,
        notification_dispatcher=dispatcher,
    )

    result = await cmd.execute_target(
        target="7",
        user_id="u1",
        target_session="sess",
        platform_name="telegram",
        start=1,
        end=1,
    )

    assert result.success is True
    assert "范围" not in result.message
    assert "最新 1 条" in result.message
    dispatcher.send_to_session.assert_not_called()
    dispatcher.dispatch_to_feed_subscribers.assert_awaited_once()
    call = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert call["feed_id"] == 10
    assert call["subscription_ids"] == [7]
    assert "<br" not in call["content"]
    assert "via https://entry.example/1 | timeline" in call["content"]
    assert call["media_items"] == [("image", "https://example.com/a.jpg")]
    assert call["media_urls"] == ["https://example.com/a.jpg"]
    assert isinstance(call["raw_entry"], EntryContentContext)
    assert (
        call["raw_entry"].content == "t1<br /><img src='https://example.com/a.jpg' />"
    )
    assert (
        call["raw_entry"].summary == "t1<br /><img src='https://example.com/a.jpg' />"
    )
    assert call["raw_entry"].raw_xml == "<item><title>t1</title></item>"


@pytest.mark.asyncio
async def test_sub_test_execute_target_by_sub_id_reports_real_send_failure():
    sub_repo = MagicMock()
    feed_repo = MagicMock()
    dispatcher = MagicMock()
    dispatcher.dispatch_to_feed_subscribers = AsyncMock(
        return_value={
            "success": 0,
            "failed": 1,
            "pending": 0,
            "skipped": 0,
            "last_error": "File of size 22961780 bytes is too big for a photo",
        }
    )

    subscription = Subscription(
        id=7,
        user_id="u1",
        feed_id=10,
        target_session="sess",
        platform_name="telegram",
    )
    feed = Feed(id=10, link="https://a.com/rss", title="timeline")
    sub_repo.get_by_id = AsyncMock(return_value=subscription)
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    polling = MagicMock()
    polling.fetch_feed_entries = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            entries=[EntryParsed(title="t1", link="l1", summary="s1")],
            message="ok",
            web_feed=SimpleNamespace(rss_d=SimpleNamespace(feed={"title": "timeline"})),
        )
    )

    cmd = TestSubscriptionCommand(
        subscription_repo=sub_repo,
        feed_repo=feed_repo,
        polling_service=polling,
        notification_dispatcher=dispatcher,
    )

    result = await cmd.execute_target(
        target="7",
        user_id="u1",
        target_session="sess",
        platform_name="telegram",
    )

    assert result.success is False
    assert "测试推送发送失败" in result.message
    assert "too big for a photo" in result.message
    assert (
        dispatcher.dispatch_to_feed_subscribers.await_args.kwargs[
            "include_error_detail"
        ]
        is True
    )


@pytest.mark.asyncio
async def test_sub_test_execute_target_preserves_video_media_item():
    sub_repo = MagicMock()
    feed_repo = MagicMock()
    dispatcher = MagicMock()
    dispatcher.send_to_session = AsyncMock(return_value={"ok": True})

    entry = EntryParsed(
        title="t1",
        link="l1",
        summary='body<video src="https://example.com/media/play?id=1"></video>',
        published=datetime.now(timezone.utc),
    )
    polling = MagicMock()
    polling.fetch_feed_entries = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            entries=[entry],
            message="ok",
            web_feed=SimpleNamespace(rss_d=SimpleNamespace(feed={"title": "timeline"})),
        )
    )

    cmd = TestSubscriptionCommand(
        subscription_repo=sub_repo,
        feed_repo=feed_repo,
        polling_service=polling,
        notification_dispatcher=dispatcher,
    )

    result = await cmd.execute_target(
        target="https://a.com/rss",
        user_id="u1",
        target_session="sess",
        platform_name="telegram",
        start=1,
        end=1,
    )

    assert result.success is True
    call = dispatcher.send_to_session.await_args.kwargs
    assert "[视频]" not in call["content"]
    assert call["media_urls"] == ["https://example.com/media/play?id=1"]
    assert call["media_items"] == [("video", "https://example.com/media/play?id=1")]


@pytest.mark.asyncio
async def test_sub_test_execute_target_omits_broken_via_separator_when_entry_link_missing():
    sub_repo = MagicMock()
    feed_repo = MagicMock()
    dispatcher = MagicMock()
    dispatcher.send_to_session = AsyncMock(return_value={"ok": True})

    entry = EntryParsed(
        title="t1",
        link="",
        summary="body",
        author="Author",
        published=datetime.now(timezone.utc),
    )
    polling = MagicMock()
    polling.fetch_feed_entries = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            entries=[entry],
            message="ok",
            web_feed=SimpleNamespace(rss_d=SimpleNamespace(feed={"title": "timeline"})),
        )
    )

    cmd = TestSubscriptionCommand(
        subscription_repo=sub_repo,
        feed_repo=feed_repo,
        polling_service=polling,
        notification_dispatcher=dispatcher,
    )

    result = await cmd.execute_target(
        target="https://a.com/rss",
        user_id="u1",
        target_session="sess",
        platform_name="telegram",
        start=1,
        end=1,
    )

    assert result.success is True
    call = dispatcher.send_to_session.await_args.kwargs
    assert "via  |" not in call["content"]
    assert "timeline (author: Author)" in call["content"]


@pytest.mark.asyncio
async def test_unsubscribe_by_url_checks_and_deletes():
    sub_repo = MagicMock()
    feed_repo = MagicMock()

    feed_repo.get_by_link = AsyncMock(
        return_value=Feed(id=10, link="https://a.com/rss", title="a")
    )
    sub_repo.get_by_user = AsyncMock(
        return_value=[
            Subscription(id=1, user_id="u1", feed_id=10, target_session="sess")
        ]
    )
    sub_repo.delete = AsyncMock()

    cmd = UnsubscribeFeedCommand(sub_repo, feed_repo)
    result = await cmd.execute_by_url(
        url="https://a.com/rss",
        user_id="u1",
        current_session="sess",
    )
    assert result.success is True
    sub_repo.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_scope_all_non_admin_denied():
    sub_repo = MagicMock()
    feed_repo = MagicMock()
    cmd = ExportSubscriptionsCommand(sub_repo, feed_repo)
    result = await cmd.execute(user_id="u1", is_admin=False, scope="all")
    assert result.success is False
    assert "管理员" in result.message
