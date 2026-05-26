from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from astrbot_plugin_rsshub.src.application.services.agent_xml_push_service import (
    AgentXmlPushService,
    AgentXmlValidationError,
)
from astrbot_plugin_rsshub.src.shared.constants import (
    SEND_MODE_LINK_ONLY,
    STYLE_ORIGINAL,
    STYLE_RSSRT,
)


@pytest.mark.asyncio
async def test_agent_xml_push_service_rejects_doctype():
    service = AgentXmlPushService(notification_dispatcher=AsyncMock())

    with pytest.raises(AgentXmlValidationError, match="DOCTYPE"):
        await service.push_entry(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
            source_key="agent:test",
            title="Title",
            xml="<!DOCTYPE foo><entry><p>bad</p></entry>",
        )


@pytest.mark.asyncio
async def test_agent_xml_push_service_rejects_bad_xml():
    service = AgentXmlPushService(notification_dispatcher=AsyncMock())

    with pytest.raises(AgentXmlValidationError, match="格式错误"):
        await service.push_entry(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
            source_key="agent:test",
            title="Title",
            xml="<entry><p>oops</entry>",
        )


@pytest.mark.asyncio
async def test_agent_xml_push_service_rejects_oversized_xml():
    service = AgentXmlPushService(notification_dispatcher=AsyncMock())

    with pytest.raises(AgentXmlValidationError, match="过大"):
        await service.push_entry(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
            source_key="agent:test",
            title="Title",
            xml="<entry>" + ("x" * (256 * 1024)) + "</entry>",
        )


@pytest.mark.asyncio
async def test_agent_xml_push_service_dry_run_returns_preview():
    dispatcher = AsyncMock()
    service = AgentXmlPushService(notification_dispatcher=dispatcher)

    result = await service.push_entry(
        user_id="user-1",
        platform_name="telegram",
        target_session="telegram:Group:1",
        source_key="agent:test",
        title="Hello",
        xml="<entry><p>World</p><img src='https://example.com/a.png'/></entry>",
        link="https://example.com/post",
        author="Alice",
        feed_title="Feed Name",
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    preview = result["preview"]
    assert preview["entry_guid"].startswith("agent:")
    assert (
        "via https://example.com/post | Feed Name (author: Alice)" in preview["content"]
    )
    assert preview["media_urls"] == ["https://example.com/a.png"]
    dispatcher.dispatch_agent_entry.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_xml_push_service_dispatches_with_explicit_guid():
    dispatcher = AsyncMock()
    dispatcher.dispatch_agent_entry.return_value = {
        "ok": True,
        "deduplicated": False,
        "stats": {"success": 1, "failed": 0, "pending": 0},
        "history_id": 11,
    }
    service = AgentXmlPushService(notification_dispatcher=dispatcher)

    result = await service.push_entry(
        user_id="user-1",
        platform_name="telegram",
        target_session="telegram:Group:1",
        source_key="agent:test",
        title="Hello",
        xml="<entry><p>World</p></entry>",
        entry_guid="guid-123",
    )

    assert result["ok"] is True
    call = dispatcher.dispatch_agent_entry.await_args.kwargs
    assert call["entry_guid"] == "guid-123"
    assert call["source_key"] == "agent:test"
    assert call["raw_xml"] == "<entry><p>World</p></entry>"
    assert call["target"].target_session == "telegram:Group:1"


@pytest.mark.asyncio
async def test_agent_xml_push_service_display_media_false_clears_dispatch_media():
    dispatcher = AsyncMock()
    dispatcher.dispatch_agent_entry.return_value = {
        "ok": True,
        "deduplicated": False,
        "stats": {"success": 1, "failed": 0, "pending": 0},
        "history_id": 12,
    }
    service = AgentXmlPushService(notification_dispatcher=dispatcher)

    result = await service.push_entry(
        user_id="user-1",
        platform_name="telegram",
        target_session="telegram:Group:1",
        source_key="agent:test",
        title="Hello",
        xml="<entry><p>World</p><img src='https://example.com/a.png'/></entry>",
        display_media=False,
        style="rssrt",
    )

    assert result["ok"] is True
    call = dispatcher.dispatch_agent_entry.await_args.kwargs
    assert call["media_urls"] == []
    assert call["media_items"] == []
    assert call["layout"] == []
    assert call["style"] == STYLE_RSSRT
    assert result["preview"]["media_urls"] == ["https://example.com/a.png"]


@pytest.mark.asyncio
async def test_agent_xml_push_service_link_only_clears_media_and_converts_modes():
    dispatcher = AsyncMock()
    dispatcher.dispatch_agent_entry.return_value = {
        "ok": True,
        "deduplicated": False,
        "stats": {"success": 1, "failed": 0, "pending": 0},
        "history_id": 13,
    }
    service = AgentXmlPushService(notification_dispatcher=dispatcher)

    result = await service.push_entry(
        user_id="user-1",
        platform_name="telegram",
        target_session="telegram:Group:1",
        source_key="agent:test",
        title="Hello",
        xml="<entry><p>World</p><img src='https://example.com/a.png'/></entry>",
        link="https://example.com/post",
        send_mode="link_only",
        style="original",
    )

    assert result["ok"] is True
    call = dispatcher.dispatch_agent_entry.await_args.kwargs
    assert call["content"] == "Hello\nhttps://example.com/post"
    assert call["media_urls"] == []
    assert call["media_items"] == []
    assert call["layout"] == []
    assert call["send_mode"] == SEND_MODE_LINK_ONLY
    assert call["style"] == STYLE_ORIGINAL


@pytest.mark.asyncio
async def test_agent_xml_push_service_omits_broken_via_suffix_when_tail_fields_missing():
    dispatcher = AsyncMock()
    service = AgentXmlPushService(notification_dispatcher=dispatcher)

    result = await service.push_entry(
        user_id="user-1",
        platform_name="telegram",
        target_session="telegram:Group:1",
        source_key="agent:test",
        title="Hello",
        xml="<entry><p>Hello</p></entry>",
        link="",
        author="",
        feed_title="",
        dry_run=True,
    )

    assert result["ok"] is True
    preview = result["preview"]
    assert preview["content"] == "Hello"
    assert "via" not in preview["content"]
    assert "|" not in preview["content"]


@pytest.mark.asyncio
async def test_agent_xml_push_service_json_wrapper_serializes_validation_error():
    service = AgentXmlPushService(notification_dispatcher=AsyncMock())

    with pytest.raises(AgentXmlValidationError):
        await service.push_entry(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
            source_key="",
            title="Hello",
            xml="<entry><p>World</p></entry>",
        )

    payload = await service.push_entry_json(
        user_id="user-1",
        platform_name="telegram",
        target_session="telegram:Group:1",
        source_key="agent:test",
        title="Hello",
        xml="<entry><p>World</p></entry>",
        dry_run=True,
    )
    data = json.loads(payload)
    assert data["ok"] is True
