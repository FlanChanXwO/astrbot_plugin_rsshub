from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.infrastructure.messaging.notification_service import (
    NotificationServiceImpl,
)


def _service_with_dispatcher(dispatcher: AsyncMock) -> NotificationServiceImpl:
    service = NotificationServiceImpl(
        subscription_repo=MagicMock(),
        push_history_repo=MagicMock(),
    )
    service._dispatcher = dispatcher
    return service


@pytest.mark.asyncio
async def test_notify_feed_update_passes_raw_xml_to_dispatcher():
    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
    }
    service = _service_with_dispatcher(dispatcher)
    feed = Feed(id=1, link="https://example.com/rss.xml", title="Example")

    result = await service.notify_feed_update(
        feed=feed,
        subscriptions=[],
        entries=[
            {
                "title": "Title",
                "link": "https://example.com/post",
                "guid": "guid-1",
                "summary": "Summary",
                "author": "Author",
                "raw_xml": "<item><title>Title</title></item>",
                "media_content": [{"url": "https://example.com/image.jpg"}],
            }
        ],
    )

    assert result is True
    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert call_kwargs["raw_entry"].raw_xml == "<item><title>Title</title></item>"
    assert call_kwargs["raw_entry"].media_urls == ("https://example.com/image.jpg",)
    assert call_kwargs["raw_entry"].author == "Author"


@pytest.mark.asyncio
async def test_notify_feed_update_cleans_entity_escaped_html_before_dispatcher():
    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
    }
    service = _service_with_dispatcher(dispatcher)
    feed = Feed(id=1, link="https://example.com/rss.xml", title="Example")

    result = await service.notify_feed_update(
        feed=feed,
        subscriptions=[],
        entries=[
            {
                "title": "Title",
                "link": "https://example.com/post",
                "guid": "guid-1",
                "summary": (
                    "Title&lt;br&gt;Body&lt;br&gt;"
                    '&lt;img src="https://example.com/image.jpg"&gt;'
                ),
            }
        ],
    )

    assert result is True
    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert "&lt;br" not in call_kwargs["content"]
    assert "&lt;img" not in call_kwargs["content"]
    assert "<img" not in call_kwargs["content"]
    assert "Body" in call_kwargs["content"]
    assert call_kwargs["raw_entry"].content == "Title\nBody"


@pytest.mark.asyncio
async def test_notify_feed_update_without_raw_xml_does_not_synthesize_xml():
    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
    }
    service = _service_with_dispatcher(dispatcher)
    feed = Feed(id=1, link="https://example.com/rss.xml", title="Example")

    result = await service.notify_feed_update(
        feed=feed,
        subscriptions=[],
        entries=[
            {
                "title": "Title",
                "link": "https://example.com/post",
                "guid": "guid-1",
                "summary": "Summary",
            }
        ],
    )

    assert result is True
    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert call_kwargs["raw_entry"].raw_xml == ""
