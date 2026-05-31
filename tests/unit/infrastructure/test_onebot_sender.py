from __future__ import annotations

import sys
from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.domain.entities.content_types import LayoutFragment
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender import (
    OneBotMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    ChannelInfo,
    MessageContext,
    PreparedMedia,
    SendRequest,
    SendResult,
)


class _Plain:
    def __init__(self, text: str) -> None:
        self.text = text


class _Node:
    def __init__(self, content: list, name: str) -> None:
        self.content = content
        self.name = name


class _Nodes:
    def __init__(self, nodes: list) -> None:
        self.nodes = nodes


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


@pytest.mark.asyncio
async def test_onebot_sender_falls_back_to_text_nodes_when_merged_forward_fails(
    monkeypatch,
):
    sender = OneBotMessageSender()
    calls: list[tuple[str, list]] = []

    async def fake_send_chain(session_id: str, chain: list, **_kwargs):
        calls.append((session_id, chain))
        if len(calls) == 1:
            return SendResult(ok=False, detail="forward failed")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Node",
        _Node,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Nodes",
        _Nodes,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Plain",
        _Plain,
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Image", _Image, raising=False
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Video", _Video, raising=False
    )

    request = SendRequest(
        session_id="default:GroupMessage:1",
        message="entry content",
        prepared_media=[
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/video.mp4",
                local_path=Path("/tmp/video.mp4"),
            ),
            PreparedMedia(
                media_type="image",
                original_url="https://example.com/image.jpg",
                local_path=Path("/tmp/image.jpg"),
            ),
        ],
    )

    result = await sender.send_to_user(
        request,
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
        ),
    )

    assert result.ok is True
    assert len(calls) == 2
    fallback_nodes = calls[1][1][0].nodes
    assert len(fallback_nodes) == 1
    assert fallback_nodes[0].content[0].text.startswith("entry content")
    assert "https://example.com/video.mp4" in fallback_nodes[0].content[0].text
    assert "https://example.com/image.jpg" in fallback_nodes[0].content[0].text


@pytest.mark.asyncio
async def test_onebot_sender_places_media_nodes_before_text(monkeypatch):
    sender = OneBotMessageSender()
    calls: list[tuple[str, list]] = []

    async def fake_send_chain(session_id: str, chain: list, **_kwargs):
        calls.append((session_id, chain))
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Node",
        _Node,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Nodes",
        _Nodes,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Plain",
        _Plain,
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Image", _Image, raising=False
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Video", _Video, raising=False
    )

    request = SendRequest(
        session_id="default:GroupMessage:1",
        message="entry content",
        prepared_media=[
            PreparedMedia(
                media_type="image",
                original_url="https://example.com/image.jpg",
                local_path=Path("/tmp/image.jpg"),
            ),
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/video.mp4",
                local_path=Path("/tmp/video.mp4"),
            ),
        ],
    )

    result = await sender.send_to_user(
        request,
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
        ),
    )

    assert result.ok is True
    nodes = calls[0][1][0].nodes
    assert isinstance(nodes[0].content[0], _Image)
    assert isinstance(nodes[1].content[0], _Video)
    assert isinstance(nodes[2].content[0], _Plain)
    assert nodes[2].content[0].text == "entry content"


@pytest.mark.asyncio
async def test_onebot_sender_prefers_local_video_path_by_default(monkeypatch):
    sender = OneBotMessageSender()
    calls: list[tuple[str, list]] = []

    async def fake_send_chain(session_id: str, chain: list, **_kwargs):
        calls.append((session_id, chain))
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Node",
        _Node,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Nodes",
        _Nodes,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Plain",
        _Plain,
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Image", _Image, raising=False
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Video", _Video, raising=False
    )

    request = SendRequest(
        session_id="default:GroupMessage:1",
        message="entry content",
        prepared_media=[
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/video.mp4",
                local_path=Path("/tmp/video.mp4"),
            ),
        ],
    )

    result = await sender.send_to_user(
        request,
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
        ),
    )

    assert result.ok is True
    assert len(calls) == 1
    media_node = calls[0][1][0].nodes[0]
    assert media_node.content[0].file == "/tmp/video.mp4"


@pytest.mark.asyncio
async def test_onebot_sender_video_uses_local_file(
    monkeypatch,
):
    sender = OneBotMessageSender()
    calls: list[tuple[str, list]] = []

    async def fake_send_chain(session_id: str, chain: list, **_kwargs):
        calls.append((session_id, chain))
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Node",
        _Node,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Nodes",
        _Nodes,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Plain",
        _Plain,
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Video", _Video, raising=False
    )

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:GroupMessage:1",
            message="entry content",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/video.mp4",
                    local_path=Path("/tmp/video.mp4"),
                )
            ],
        ),
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
        ),
    )

    assert result.ok is True
    media_node = calls[0][1][0].nodes[0]
    assert media_node.content[0].file == "/tmp/video.mp4"


@pytest.mark.asyncio
async def test_onebot_sender_ignores_telegraph_strategy(monkeypatch):
    sender = OneBotMessageSender()
    calls: list[tuple[str, list]] = []

    async def fake_send_chain(session_id: str, chain: list, **_kwargs):
        calls.append((session_id, chain))
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Node",
        _Node,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Nodes",
        _Nodes,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Plain",
        _Plain,
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Image", _Image, raising=False
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Video", _Video, raising=False
    )

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:GroupMessage:1",
            message="entry content",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.jpg",
                ),
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/2.jpg",
                ),
            ],
        ),
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
            send_mode=0,
            sender_strategy={
                "enable_telegraph": True,
                "telegraph_token": "ignored-token",
            },
        ),
    )

    assert result.ok is True
    assert len(calls) == 1
    nodes = calls[0][1][0].nodes
    assert len(nodes) == 3
    text_nodes = [
        node.content[0].text for node in nodes if isinstance(node.content[0], _Plain)
    ]
    assert text_nodes == ["entry content"]
    assert all("Telegraph:" not in text for text in text_nodes)


@pytest.mark.asyncio
async def test_onebot_original_style_sends_layout_without_merged_forward(monkeypatch):
    sender = OneBotMessageSender()
    calls: list[tuple[str, list]] = []

    async def fake_send_chain(session_id: str, chain: list, **_kwargs):
        calls.append((session_id, chain))
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Plain", _Plain, raising=False
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Image", _Image, raising=False
    )

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:GroupMessage:1",
            message="fallback text",
            layout=[
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/1.jpg",
                ),
                LayoutFragment(kind="text", text="caption 1"),
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/2.jpg",
                ),
                LayoutFragment(kind="text", text="caption 2"),
            ],
        ),
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
            style=2,
        ),
    )

    assert result.ok is True
    assert len(calls) == 2
    assert isinstance(calls[0][1][0], _Image)
    assert isinstance(calls[0][1][1], _Plain)
    assert calls[0][1][1].text == "caption 1"
    assert isinstance(calls[1][1][0], _Image)
    assert isinstance(calls[1][1][1], _Plain)
    assert calls[1][1][1].text == "caption 2"


# ------------------------------------------------------------------
# GIF conversion regression
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onebot_merged_forward_uses_image_for_gif(monkeypatch):
    """OneBot 合并转发对 video + *.gif 应生成 Image(file=...)。"""
    sender = OneBotMessageSender()
    calls: list[tuple[str, list]] = []

    async def fake_send_chain(session_id: str, chain: list, **_kwargs):
        calls.append((session_id, chain))
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Node",
        _Node,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Nodes",
        _Nodes,
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender.Plain",
        _Plain,
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Image", _Image, raising=False
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Video", _Video, raising=False
    )

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:GroupMessage:1",
            message="entry content",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/video.mp4",
                    local_path=Path("/tmp/video.gif"),
                )
            ],
        ),
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
        ),
    )

    assert result.ok is True
    nodes = calls[0][1][0].nodes
    assert len(nodes) == 2  # image node + text node
    assert isinstance(nodes[0].content[0], _Image)
    assert nodes[0].content[0].file == "/tmp/video.gif"


@pytest.mark.asyncio
async def test_onebot_original_style_gif_from_downloaded_media(monkeypatch):
    """original layout 使用真实预下载结果时，video→gif 应按 Image 发送。"""
    sender = OneBotMessageSender()
    calls: list[tuple[str, list]] = []

    async def fake_prepare_media(media, timeout=30, proxy=""):
        assert media == [("video", "https://example.com/video.mp4")]
        return [
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/video.mp4",
                local_path=Path("/tmp/video.gif"),
            )
        ]

    async def fake_send_chain(session_id: str, chain: list, **_kwargs):
        calls.append((session_id, chain))
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "prepare_media", fake_prepare_media)
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Plain", _Plain, raising=False
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Image", _Image, raising=False
    )
    monkeypatch.setattr(
        sys.modules["astrbot.api.message_components"], "Video", _Video, raising=False
    )

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:GroupMessage:1",
            message="fallback",
            media=[("video", "https://example.com/video.mp4")],
            layout=[
                LayoutFragment(
                    kind="video",
                    media_type="video",
                    url="https://example.com/video.mp4",
                ),
                LayoutFragment(kind="text", text="caption"),
            ],
        ),
        context=MessageContext(platform_name="aiocqhttp", style=2),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][1][0], _Image)
    assert calls[0][1][0].file == "/tmp/video.gif"
    assert isinstance(calls[0][1][1], _Plain)
    assert calls[0][1][1].text == "caption"
