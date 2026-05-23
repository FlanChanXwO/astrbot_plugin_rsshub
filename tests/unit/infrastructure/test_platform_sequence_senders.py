from __future__ import annotations

import sys
from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.domain.entities.content_types import LayoutFragment
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.factory import (
    get_sender_for_platform,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.qq_official_sender import (
    QQOfficialMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegram_sender import (
    TelegramMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegraph_client import (
    TelegraphClient,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    ChannelInfo,
    MessageContext,
    PreparedMedia,
    SendRequest,
    SendResult,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.weixin_oc_sender import (
    WeixinOCMessageSender,
)


class _Plain:
    def __init__(self, text: str) -> None:
        self.text = text


class _Image:
    def __init__(self, file: str) -> None:
        self.file = file


class _Video:
    def __init__(self, file: str) -> None:
        self.file = file


class _Record:
    def __init__(self, file: str, text: str = "") -> None:
        self.file = file
        self.text = text


class _File:
    def __init__(self, name: str, file: str, url: str) -> None:
        self.name = name
        self.file = file
        self.url = url


def _patch_components(monkeypatch) -> None:
    module = sys.modules["astrbot.api.message_components"]
    monkeypatch.setattr(module, "Plain", _Plain, raising=False)
    monkeypatch.setattr(module, "Image", _Image, raising=False)
    monkeypatch.setattr(module, "Video", _Video, raising=False)
    monkeypatch.setattr(module, "Record", _Record, raising=False)
    monkeypatch.setattr(module, "File", _File, raising=False)


def _request() -> SendRequest:
    return SendRequest(
        session_id="default:UserMessage:1",
        message="entry text",
        prepared_media=[
            PreparedMedia(
                media_type="image",
                original_url="https://example.com/1.jpg",
                local_path=Path("/tmp/1.jpg"),
            ),
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/2.mp4",
                local_path=Path("/tmp/2.mp4"),
            ),
        ],
    )


@pytest.mark.asyncio
async def test_qq_official_plain_text_uses_single_send(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="entry text"),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "entry text"


@pytest.mark.asyncio
async def test_qq_official_sends_media_before_text(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_Image, _Video, _Plain]
    assert calls[-1][0].text == "entry text"


@pytest.mark.asyncio
async def test_qq_official_single_image_and_text_share_one_chain(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.jpg",
                    local_path=Path("/tmp/1.jpg"),
                )
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Image)
    assert isinstance(calls[0][1], _Plain)
    assert calls[0][1].text == "entry text"


@pytest.mark.asyncio
async def test_qq_official_original_style_pairs_image_with_following_text(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            layout=[
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/1.jpg",
                ),
                LayoutFragment(kind="text", text="caption 1"),
                LayoutFragment(
                    kind="video",
                    media_type="video",
                    url="https://example.com/2.mp4",
                ),
                LayoutFragment(kind="text", text="caption 2"),
            ],
        ),
        context=MessageContext(platform_name="qq_official", style=2),
    )

    assert result.ok is True
    assert len(calls) == 3
    assert isinstance(calls[0][0], _Image)
    assert isinstance(calls[0][1], _Plain)
    assert calls[0][1].text == "caption 1"
    assert isinstance(calls[1][0], _Video)
    assert isinstance(calls[2][0], _Plain)
    assert calls[2][0].text == "caption 2"


@pytest.mark.asyncio
async def test_qq_official_partial_media_failure_continues_and_appends_url(
    monkeypatch,
):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        if isinstance(chain[0], _Image):
            return SendResult(ok=False, transient=True, detail="image failed")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is False
    assert result.transient is True
    assert "partial send" in result.detail
    assert [type(chain[0]) for chain in calls] == [_Image, _Video, _Plain]
    assert "媒体原始链接:" in calls[-1][0].text
    assert "https://example.com/1.jpg" in calls[-1][0].text
    assert "https://example.com/2.mp4" not in calls[-1][0].text


@pytest.mark.asyncio
async def test_weixin_oc_plain_text_uses_single_send(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="entry text"),
        context=MessageContext(platform_name="weixin_oc"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "entry text"


@pytest.mark.asyncio
async def test_weixin_oc_sends_single_image_and_text_as_two_messages(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.jpg",
                    local_path=Path("/tmp/1.jpg"),
                )
            ],
        ),
        context=MessageContext(platform_name="weixin_oc"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_Image, _Plain]


@pytest.mark.asyncio
async def test_weixin_oc_multimedia_is_sent_one_by_one(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="weixin_oc"),
    )

    assert result.ok is True
    assert len(calls) == 3
    assert all(len(chain) == 1 for chain in calls)
    assert [type(chain[0]) for chain in calls] == [_Image, _Video, _Plain]


@pytest.mark.asyncio
async def test_weixin_oc_original_style_preserves_order_without_combining(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            layout=[
                LayoutFragment(kind="text", text="lead"),
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/1.jpg",
                ),
                LayoutFragment(kind="text", text="caption"),
            ],
        ),
        context=MessageContext(platform_name="weixin_oc", style=2),
    )

    assert result.ok is True
    assert len(calls) == 3
    assert [type(chain[0]) for chain in calls] == [_Plain, _Image, _Plain]
    assert all(len(chain) == 1 for chain in calls)


@pytest.mark.asyncio
async def test_weixin_oc_partial_media_failure_continues_and_appends_url(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        if isinstance(chain[0], _Video):
            return SendResult(ok=False, needs_rebind=True, detail="video failed")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="weixin_oc"),
    )

    assert result.ok is False
    assert result.needs_rebind is True
    assert [type(chain[0]) for chain in calls] == [_Image, _Video, _Plain]
    assert "https://example.com/1.jpg" not in calls[-1][0].text
    assert "https://example.com/2.mp4" in calls[-1][0].text


def test_factory_maps_weixin_aliases_to_dedicated_sender():
    assert get_sender_for_platform("weixin_oc") is WeixinOCMessageSender
    assert get_sender_for_platform("wechat") is WeixinOCMessageSender


@pytest.mark.asyncio
async def test_telegram_large_local_image_is_sent_as_file(monkeypatch, tmp_path):
    _patch_components(monkeypatch)
    image_path = tmp_path / "large.jpg"
    image_path.write_bytes(b"0" * (10 * 1024 * 1024 + 1))
    sender = TelegramMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="telegram:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/large.jpg",
                    local_path=image_path,
                )
            ],
        ),
        context=MessageContext(platform_name="telegram"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert isinstance(calls[0][1], _File)
    assert calls[0][1].file == str(image_path)


@pytest.mark.asyncio
async def test_telegram_telegraph_uses_entry_title_and_plain_url(monkeypatch):
    _patch_components(monkeypatch)
    created: dict[str, object] = {}

    async def fake_create_page(self, **kwargs):
        created.update(kwargs)
        return "https://telegra.ph/entry-title"

    monkeypatch.setattr(TelegraphClient, "create_media_page", fake_create_page)

    sender = TelegramMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="telegram:UserMessage:1",
            message="Entry title\n\nBody text\n\nvia https://example.com/post | Feed",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.webp",
                ),
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/2.webp",
                ),
            ],
        ),
        context=MessageContext(
            platform_name="telegram",
            send_mode=0,
            entry_title="Entry title",
            entry_link="https://example.com/post",
            channel=ChannelInfo(title="Feed", link="https://example.com/feed"),
            sender_strategy={
                "enable_telegraph": True,
                "telegraph_token": "token",
            },
        ),
    )

    assert result.ok is True
    assert created["title"] == "Entry title"
    assert created["media_urls"] == [
        "https://example.com/1.webp",
        "https://example.com/2.webp",
    ]
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert "https://telegra.ph/entry-title" in calls[0][0].text
    assert "Telegraph:" not in calls[0][0].text
