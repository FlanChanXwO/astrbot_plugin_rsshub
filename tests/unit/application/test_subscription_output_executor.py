"""Subscription 批次固化输出执行器测试。"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.application.services.subscription_output_executor import (
    SubscriptionOutputExecutor,
)
from astrbot_plugin_rsshub.src.domain.entities.push_history import PushHistory


@pytest.mark.asyncio
async def test_standard_output_replays_frozen_send_payload() -> None:
    dispatcher = MagicMock()
    dispatcher.send_to_session = AsyncMock(return_value={"ok": True})
    executor = SubscriptionOutputExecutor(
        notification_dispatcher=dispatcher,
        card_renderer=MagicMock(),
    )
    history = PushHistory(
        id=8,
        sub_id=7,
        batch_id=19,
        user_id="user-1",
        feed_id=3,
        output_kind="standard",
        target_session="platform:GroupMessage:1",
        platform_name="test",
        entry_title="标题",
        entry_link="https://example.com/1",
        feed_title="Feed",
        feed_link="https://example.com/feed",
        source_context={
            "send": {
                "content": "固化正文",
                "media_urls": ["https://example.com/a.jpg"],
                "media_items": [["image", "https://example.com/a.jpg"]],
                "layout": [],
                "send_mode": 1,
                "style": 2,
            }
        },
    )

    result = await executor.execute(history)

    assert result.ok is True
    call = dispatcher.send_to_session.await_args.kwargs
    assert call["content"] == "固化正文"
    assert call["media_items"] == [("image", "https://example.com/a.jpg")]
    assert call["send_mode"] == 1
    assert call["style"] == 2


@pytest.mark.asyncio
async def test_card_output_renders_frozen_snapshot_then_sends_png() -> None:
    dispatcher = MagicMock()
    dispatcher.send_to_session = AsyncMock(return_value={"ok": True})
    card_renderer = MagicMock()
    card_renderer.render = AsyncMock(
        return_value=MagicMock(png_path=Path("/tmp/card.png"))
    )
    executor = SubscriptionOutputExecutor(
        notification_dispatcher=dispatcher,
        card_renderer=card_renderer,
    )
    history = PushHistory(
        id=9,
        sub_id=7,
        batch_id=19,
        user_id="user-1",
        feed_id=3,
        output_kind="card",
        target_session="platform:GroupMessage:1",
        platform_name="test",
        feed_title="Feed",
        feed_link="https://example.com/feed",
        source_context={
            "template_snapshot": {
                "metadata": {
                    "id": "astrbot_plugin_rsshub_card_demo",
                    "name": "Demo",
                    "version": "1.0.0",
                    "author": "Author",
                    "description": "Demo template",
                    "repository": "https://example.com/template",
                    "targets": ["feed"],
                    "feed_patterns": [],
                },
                "templates": {"template.html": "{{ entries|length }}"},
                "assets": {},
            },
            "document_snapshot": {
                "entries": [],
                "document": {"text": "", "rss_xml": ""},
                "rendered_at": "2026-08-24T08:00:00+00:00",
            },
        },
    )

    result = await executor.execute(history)

    assert result.ok is True
    render_context = card_renderer.render.await_args.args[2]
    assert render_context["source"] == {"type": "feed", "owner_id": 7}
    assert render_context["meta"]["batch_id"] == 19
    assert render_context["meta"]["rendered_at"] == "2026-08-24T08:00:00+00:00"
    send = dispatcher.send_to_session.await_args.kwargs
    assert send["media_items"] == [("image", Path("/tmp/card.png").as_uri())]
