from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.services.feed_polling_service import (
    FeedPollingService,
)
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.infrastructure.fetcher.rss.parser import (
    EntryParsed,
    RSSParser,
)
from astrbot_plugin_rsshub.src.infrastructure.config import RSSSettings


def _web_feed(**kwargs):
    data = {
        "status": 200,
        "error": None,
        "content": b"<rss />",
        "etag": None,
        "last_modified": None,
        "rss_d": MagicMock(feed={}),
    }
    data.update(kwargs)
    return MagicMock(**data)


def _json_feed_content() -> bytes:
    return json.dumps(
        {
            "version": "https://jsonfeed.org/version/1.1",
            "title": "JSON Timeline",
            "home_page_url": "https://example.com/",
            "feed_url": "https://example.com/feed.json",
            "items": [
                {
                    "id": "json-1",
                    "url": "https://example.com/posts/json-1",
                    "title": "JSON Feed Entry",
                    "content_html": "<p>JSON body</p>",
                    "summary": "JSON summary",
                    "authors": [{"name": "JSON Author"}],
                    "date_published": "2026-06-01T09:00:00Z",
                    "attachments": [
                        {
                            "url": "https://example.com/clip.mp4",
                            "mime_type": "video/mp4",
                            "size_in_bytes": 123,
                        }
                    ],
                    "image": "https://example.com/card.jpg",
                }
            ],
        }
    ).encode("utf-8")


@pytest.mark.asyncio
async def test_poll_feed_records_new_entries_and_metadata():
    feed = Feed(id=1, link="https://example.com/rss.xml", title="Old")
    entries = [
        EntryParsed(guid="guid-1", title="One", link="https://example.com/1"),
        EntryParsed(guid="guid-2", title="Two", link="https://example.com/2"),
    ]
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)
    sub_repo = MagicMock()

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed(
        rss_d=MagicMock(feed={"title": "New Title"}),
        etag="etag-1",
        last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = (entries, None)

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=sub_repo,
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
    )

    result = await service.poll_feed(1)

    assert result.success is True
    assert result.status == "updated"
    assert result.total_entries == 2
    assert result.new_entries == 2
    assert result.feed.title == "New Title"
    assert result.feed.etag == "etag-1"
    assert result.feed.entry_hashes is not None
    assert len(result.feed.entry_hashes) == 2
    assert result.feed.entry_hashes[0][0].startswith("sid:")
    assert "guid-1" in result.feed.entry_hashes[0]
    assert "guid-2" in result.feed.entry_hashes[1]
    feed_repo.save.assert_awaited_once_with(feed)
    fetcher.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_feed_not_modified_does_not_save():
    feed = Feed(id=1, link="https://example.com/rss.xml")
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock()

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed(status=304, content=None)
    fetcher.close = AsyncMock()

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=MagicMock(),
    )

    result = await service.poll_feed(1)

    assert result.success is True
    assert result.status == "not_modified"
    feed_repo.save.assert_not_called()


@pytest.mark.asyncio
async def test_poll_feed_parse_error_is_reported():
    feed = Feed(id=1, link="https://example.com/rss.xml")
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock()

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([], "bad xml")

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
    )

    result = await service.poll_feed(1)

    assert result.success is False
    assert result.status == "parse_error"
    assert "bad xml" in result.message
    feed_repo.save.assert_not_called()


@pytest.mark.asyncio
async def test_poll_feed_fetch_exception_is_reported():
    feed = Feed(id=1, link="https://example.com/rss.xml")
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock()

    fetcher = AsyncMock()
    fetcher.fetch.side_effect = RuntimeError("network boom")
    fetcher.close = AsyncMock()

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=MagicMock(),
    )

    result = await service.poll_feed(1)

    assert result.success is False
    assert result.status == "fetch_error"
    assert "network boom" in result.message
    assert result.error == "network boom"
    feed_repo.save.assert_not_called()
    fetcher.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_feed_empty_content_is_reported_without_parsing():
    feed = Feed(id=1, link="https://example.com/rss.xml")
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock()

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed(status=200, content=None)
    fetcher.close = AsyncMock()

    parser = MagicMock()

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
    )

    result = await service.poll_feed(1)

    assert result.success is False
    assert result.status == "empty_content"
    assert "RSS 内容为空" in result.message
    parser.parse.assert_not_called()
    feed_repo.save.assert_not_called()


@pytest.mark.asyncio
async def test_poll_feed_dispatches_new_entries_when_enabled():
    feed = Feed(id=1, link="https://example.com/rss.xml")
    entry = EntryParsed(
        guid="guid-1",
        title="One",
        link="https://example.com/1",
        summary="Summary",
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([entry], None)

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
    }

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    assert result.dispatched == 1
    dispatcher.dispatch_to_feed_subscribers.assert_awaited_once()
    dispatched_content = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs[
        "content"
    ]
    assert (
        "via https://example.com/1 | https://example.com/rss.xml" in dispatched_content
    )


@pytest.mark.asyncio
async def test_poll_feed_dispatches_json_feed_entries_with_synthetic_raw_xml():
    feed = Feed(id=1, link="https://example.com/feed.json", title="Old")
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed(
        content=_json_feed_content(),
        rss_d=MagicMock(feed={"title": "JSON Timeline"}),
    )
    fetcher.close = AsyncMock()

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
        "skipped": 0,
    }

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=RSSParser(),
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    assert result.dispatched == 1
    assert result.feed.title == "JSON Timeline"
    assert result.feed.entry_hashes is not None
    assert result.feed.entry_hashes[0][0].startswith("sid:")

    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert call_kwargs["entry_guid"] == "json-1"
    assert call_kwargs["entry_link"] == "https://example.com/posts/json-1"
    assert call_kwargs["media_urls"] == [
        "https://example.com/clip.mp4",
        "https://example.com/card.jpg",
    ]
    assert call_kwargs["raw_entry"].raw_xml.startswith("<item>")
    assert '<guid isPermaLink="false">json-1</guid>' in call_kwargs["raw_entry"].raw_xml


@pytest.mark.parametrize(
    "stats",
    [
        {"success": 0, "failed": 1, "pending": 0, "skipped": 0},
        {"success": 0, "failed": 0, "pending": 1, "skipped": 0},
    ],
)
@pytest.mark.asyncio
async def test_poll_feed_keeps_unacknowledged_entries_retryable(stats):
    old_last_modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new_last_modified = datetime(2026, 1, 2, tzinfo=timezone.utc)
    feed = Feed(
        id=1,
        link="https://example.com/rss.xml",
        etag="old-etag",
        last_modified=old_last_modified,
    )
    entry = EntryParsed(
        guid="guid-1",
        title="One",
        link="https://example.com/1",
        summary="Summary",
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed(
        etag="new-etag",
        last_modified=new_last_modified,
    )
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([entry], None)

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = stats

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    assert result.dispatched == 1
    assert feed.entry_hashes is None
    assert feed.etag == "old-etag"
    assert feed.last_modified == old_last_modified


@pytest.mark.asyncio
async def test_poll_feed_marks_explicitly_skipped_entries_seen():
    feed = Feed(id=1, link="https://example.com/rss.xml", etag="old-etag")
    entry = EntryParsed(
        guid="guid-1",
        title="One",
        link="https://example.com/1",
        summary="Summary",
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed(etag="new-etag")
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([entry], None)

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 0,
        "failed": 0,
        "pending": 0,
        "skipped": 1,
    }

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    assert result.dispatched == 0
    assert feed.entry_hashes
    assert "guid-1" in feed.entry_hashes[0]
    assert feed.etag == "new-etag"


@pytest.mark.asyncio
async def test_poll_feed_dispatches_parsed_entry_without_content_processing():
    feed = Feed(id=1, link="https://example.com/rss.xml", title="Timeline")
    entry = EntryParsed(
        guid="guid-1",
        title="Title",
        link="https://example.com/1",
        summary="Summary",
        author="Author",
        raw_xml="<item><title>Title</title><link>https://example.com/1</link></item>",
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([entry], None)

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
    }

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert call_kwargs["entry_title"] == "Title"
    assert "Summary" in call_kwargs["content"]
    assert (
        "via https://example.com/1 | Timeline (author: Author)"
        in call_kwargs["content"]
    )
    assert call_kwargs["media_urls"] == []
    assert call_kwargs["raw_entry"].raw_xml == entry.raw_xml


@pytest.mark.asyncio
async def test_poll_feed_dispatch_parses_html_summary_and_media():
    feed = Feed(id=1, link="https://example.com/rss.xml", title="Timeline")
    entry = EntryParsed(
        guid="guid-1",
        title="Title",
        link="https://example.com/1",
        summary=(
            "Title<br /><br />Body<br />"
            '<img src="https://example.com/image.jpg" width="100" />'
        ),
        author="Author",
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([entry], None)

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
    }

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert "<br" not in call_kwargs["content"]
    assert "<img" not in call_kwargs["content"]
    assert "Body" in call_kwargs["content"]
    assert (
        "via https://example.com/1 | Timeline (author: Author)"
        in call_kwargs["content"]
    )
    assert call_kwargs["media_urls"] == ["https://example.com/image.jpg"]


@pytest.mark.asyncio
async def test_format_dispatch_content_omits_broken_via_when_all_tail_fields_missing():
    content = FeedPollingService._format_dispatch_content(
        title="",
        body="Body only",
        link="",
        feed_title="",
        feed_link="",
        author="",
    )

    assert content == "Body only"
    assert "via" not in content
    assert "|" not in content


@pytest.mark.asyncio
async def test_poll_feed_dispatch_decodes_entity_escaped_html_summary():
    feed = Feed(id=1, link="https://example.com/rss.xml", title="Timeline")
    entry = EntryParsed(
        guid="guid-1",
        title="Title",
        link="https://example.com/1",
        summary=(
            "Title&lt;br&gt;Body&lt;br&gt;"
            '&lt;img src="https://example.com/image.jpg"&gt;'
        ),
        author="Author",
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([entry], None)

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
    }

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert "&lt;br" not in call_kwargs["content"]
    assert "&lt;img" not in call_kwargs["content"]
    assert "<img" not in call_kwargs["content"]
    assert "Body" in call_kwargs["content"]
    assert call_kwargs["media_urls"] == ["https://example.com/image.jpg"]


@pytest.mark.asyncio
async def test_poll_feed_dispatch_preserves_video_media_without_text_placeholder():
    feed = Feed(id=1, link="https://example.com/rss.xml", title="Timeline")
    video_url = "https://example.com/media/play?id=123"
    entry = EntryParsed(
        guid="guid-1",
        title="Title",
        link="https://example.com/1",
        summary=f'Body<br /><video src="{video_url}" controls="controls"></video>',
        author="Author",
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([entry], None)

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
    }

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert "Body" in call_kwargs["content"]
    assert "[视频]" not in call_kwargs["content"]
    assert (
        "via https://example.com/1 | Timeline (author: Author)"
        in call_kwargs["content"]
    )
    assert call_kwargs["media_urls"] == [video_url]
    assert call_kwargs["media_items"] == [("video", video_url)]


@pytest.mark.asyncio
async def test_poll_feed_group_limits_dispatch_to_selected_subscriptions():
    feed = Feed(id=1, link="https://example.com/rss.xml")
    entries = [
        EntryParsed(guid="guid-1", title="One", link="https://example.com/1"),
        EntryParsed(guid="guid-2", title="Two", link="https://example.com/2"),
    ]
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = (entries, None)

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
    }

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
        history_entry_limit=1,
    )

    result = await service.poll_feed_group(1, [10, 20, 10])

    assert result.success is True
    assert result.dispatched == 1
    dispatcher.dispatch_to_feed_subscribers.assert_awaited_once()
    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert call_kwargs["subscription_ids"] == [10, 20]


@pytest.mark.asyncio
async def test_history_entry_limit_does_not_mark_unattempted_entries_seen():
    old_last_modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = EntryParsed(
        guid="guid-newer",
        title="Newer",
        link="https://example.com/newer",
        published=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    older = EntryParsed(
        guid="guid-older",
        title="Older",
        link="https://example.com/older",
        published=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    feed = Feed(
        id=1,
        link="https://example.com/rss.xml",
        etag="old-etag",
        last_modified=old_last_modified,
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed(
        etag="new-etag",
        last_modified=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([older, newer], None)

    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
        "skipped": 0,
    }

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=False),
        history_entry_limit=1,
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    assert result.new_entries == 2
    assert result.dispatched == 1
    assert dispatcher.dispatch_to_feed_subscribers.await_count == 1
    assert feed.entry_hashes
    assert "guid-newer" in feed.entry_hashes[0]
    assert all("guid-older" not in group for group in feed.entry_hashes)
    assert feed.etag == "old-etag"
    assert feed.last_modified == old_last_modified


@pytest.mark.asyncio
async def test_poll_feed_bootstrap_records_history_without_dispatching():
    feed = Feed(id=1, link="https://example.com/rss.xml")
    entry = EntryParsed(
        guid="guid-1",
        title="One",
        link="https://example.com/1",
        summary="Summary",
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([entry], None)
    dispatcher = AsyncMock()

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
        notification_dispatcher=dispatcher,
        rss_settings=RSSSettings(bootstrap_skip_history=True),
    )

    result = await service.poll_feed(1, notify_new_entries=True)

    assert result.success is True
    assert result.status == "bootstrapped"
    assert result.new_entries == 1
    assert result.dispatched == 0
    assert result.bootstrap_skipped is True
    assert feed.entry_hashes
    assert feed.entry_hashes[0][0].startswith("sid:")
    dispatcher.dispatch_to_feed_subscribers.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_feed_uses_stable_identity_when_content_changes():
    seed_entry = EntryParsed(
        guid="guid-1",
        title="Original",
        link="https://example.com/1?utm_source=test",
        summary="Original summary",
    )
    changed_entry = EntryParsed(
        guid="guid-1",
        title="Updated title",
        link="https://example.com/1",
        summary="Changed summary with timestamp",
    )

    seed_service = FeedPollingService(
        feed_repo=MagicMock(),
        subscription_repo=MagicMock(),
    )
    existing_hashes = [seed_service._hash_entry(seed_entry, "https://example.com/rss")]

    feed = Feed(
        id=1,
        link="https://example.com/rss.xml",
        entry_hashes=existing_hashes,
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([changed_entry], None)

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
    )

    result = await service.poll_feed(1)

    assert result.success is True
    assert result.status == "no_new_entries"
    assert result.new_entries == 0
    assert len(feed.entry_hashes or []) == 1


@pytest.mark.asyncio
async def test_poll_feed_accepts_legacy_flat_hash_history():
    entry = EntryParsed(
        guid="",
        title="Legacy",
        link="https://example.com/legacy",
    )
    service_for_hash = FeedPollingService(
        feed_repo=MagicMock(),
        subscription_repo=MagicMock(),
    )
    legacy_hash = service_for_hash._legacy_crc32(entry)
    feed = Feed(
        id=1,
        link="https://example.com/rss.xml",
        entry_hashes=[legacy_hash],
    )
    feed_repo = MagicMock()
    feed_repo.get_by_id = AsyncMock(return_value=feed)
    feed_repo.save = AsyncMock(side_effect=lambda value: value)

    fetcher = AsyncMock()
    fetcher.fetch.return_value = _web_feed()
    fetcher.close = AsyncMock()

    parser = MagicMock()
    parser.parse.return_value = ([entry], None)

    service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=MagicMock(),
        fetcher_factory=MagicMock(return_value=fetcher),
        parser=parser,
    )

    result = await service.poll_feed(1)

    assert result.success is True
    assert result.new_entries == 0
    assert feed.entry_hashes
    assert legacy_hash in feed.entry_hashes[0]


def test_tracking_query_params_stripped_for_hash_and_dispatch_link():
    entry = EntryParsed(
        guid="",
        title="Tracked entry",
        link="https://example.com/post?utm_source=newsletter&foo=bar",
    )
    entry_with_other_tracking = EntryParsed(
        guid="",
        title="Tracked entry",
        link="https://example.com/post?utm_source=other&foo=bar",
    )

    service = FeedPollingService(
        feed_repo=MagicMock(),
        subscription_repo=MagicMock(),
        rss_settings=RSSSettings(tracking_query_params=("utm_source",)),
    )

    assert (
        service._strip_tracking_params(entry.link) == "https://example.com/post?foo=bar"
    )
    assert service._resolve_entry_link(entry) == "https://example.com/post?foo=bar"
    assert service._resolve_entry_link(entry_with_other_tracking) == (
        "https://example.com/post?foo=bar"
    )
    assert (
        service._hash_entry(entry)[0]
        == service._hash_entry(entry_with_other_tracking)[0]
    )


def test_pixiv_artwork_url_is_stable_identity_when_content_changes():
    original = EntryParsed(
        guid="https://www.pixiv.net/artworks/145521627",
        title="フランちゃんと海！！！",
        link="https://www.pixiv.net/artworks/145521627",
        summary="First summary",
    )
    changed = EntryParsed(
        guid="https://www.pixiv.net/artworks/145521627",
        title="Updated title",
        link="https://www.pixiv.net/artworks/145521627",
        summary="Changed summary",
    )
    service = FeedPollingService(
        feed_repo=MagicMock(),
        subscription_repo=MagicMock(),
    )

    assert service._hash_entry(original)[0] == service._hash_entry(changed)[0]


def test_build_conditional_headers_from_feed_etag_and_last_modified():
    last_modified = datetime(2015, 10, 21, 7, 28, tzinfo=timezone.utc)
    feed = Feed(
        id=1,
        link="https://example.com/feed",
        etag='"abcdef"',
        last_modified=last_modified,
    )
    service = FeedPollingService(
        feed_repo=MagicMock(),
        subscription_repo=MagicMock(),
    )

    headers = service._build_conditional_headers(feed)

    assert headers["If-None-Match"] == '"abcdef"'
    assert headers["If-Modified-Since"] == format_datetime(last_modified)
