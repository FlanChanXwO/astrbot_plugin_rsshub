from __future__ import annotations

import sys
from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.domain.entities.content_types import LayoutFragment
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.base_sender import (
    DefaultMessageSender,
)
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
    MediaVariant,
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


@pytest.fixture(autouse=True)
def _reset_sender_behavior():
    DefaultMessageSender.configure_runtime(timeout_seconds=30, proxy="")
    DefaultMessageSender.configure_behavior()
    yield
    DefaultMessageSender.configure_runtime(timeout_seconds=30, proxy="")
    DefaultMessageSender.configure_behavior()


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

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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
async def test_qq_official_markdown_force_keeps_active_push_plain(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[dict] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(kwargs)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="**entry**"),
        context=MessageContext(
            platform_name="qq_official",
            sender_strategy={"markdown_mode": "force"},
        ),
    )

    assert result.ok is True
    assert calls == [{"use_markdown": False}]


@pytest.mark.asyncio
async def test_qq_official_markdown_plain_sets_message_chain_flag_false(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[dict] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(kwargs)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="entry text"),
        context=MessageContext(
            platform_name="qq_official",
            sender_strategy={"markdown_mode": "plain"},
        ),
    )

    assert result.ok is True
    assert calls == [{"use_markdown": False}]


@pytest.mark.asyncio
async def test_qq_official_markdown_auto_keeps_active_push_plain(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[dict] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(kwargs)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="**entry**"),
        context=MessageContext(
            platform_name="qq_official",
            sender_strategy={"markdown_mode": "auto"},
        ),
    )

    assert result.ok is True
    assert calls == [{"use_markdown": False}]


@pytest.mark.asyncio
async def test_qq_official_multimedia_default_sends_media_components_then_text(
    monkeypatch,
):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_Image, _Video, _Plain]
    assert calls[0][0].file == "/tmp/1.jpg"
    assert calls[1][0].file == "/tmp/2.mp4"
    assert calls[-1][0].text == "entry text"


@pytest.mark.asyncio
async def test_qq_official_multimedia_exceeding_threshold_degrades_to_files_then_text(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_media_threshold=1,
        qq_official_degrade_strategy="file_then_link",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_File, _File, _Plain]
    assert calls[0][0].file == "/tmp/1.jpg"
    assert calls[1][0].file == "/tmp/2.mp4"
    assert calls[-1][0].text == "entry text"


@pytest.mark.asyncio
async def test_qq_official_single_image_and_text_share_one_chain(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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
async def test_qq_official_single_video_sends_video_before_text(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=Path("/tmp/2.mp4"),
                )
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_Video, _Plain]
    assert calls[0][0].file == "/tmp/2.mp4"
    assert calls[1][0].text == "entry text"
    assert not any(isinstance(chain[0], _File) for chain in calls)


@pytest.mark.asyncio
async def test_qq_official_single_video_from_media_download_uses_video(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_prepare_media(media, timeout=30, proxy=""):
        assert media == [("video", "https://example.com/2.mp4")]
        return [
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/2.mp4",
                local_path=Path("/tmp/2.mp4"),
            )
        ]

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "prepare_media", fake_prepare_media)
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            media=[("video", "https://example.com/2.mp4")],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_Video, _Plain]
    assert calls[0][0].file == "/tmp/2.mp4"
    assert not any(isinstance(chain[0], _File) for chain in calls)


@pytest.mark.asyncio
async def test_qq_official_single_video_failure_tries_file_then_link(monkeypatch):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_degrade_strategy="file_then_link",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        if isinstance(chain[0], _Video):
            return SendResult(ok=False, transient=True, detail="video failed")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=Path("/tmp/2.mp4"),
                )
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is False
    assert result.transient is True
    assert "partial send" in result.detail
    assert [type(chain[0]) for chain in calls] == [_Video, _File, _Plain]
    assert calls[1][0].file == "/tmp/2.mp4"
    assert calls[2][0].text == "entry text"
    assert "媒体原始链接:" not in calls[2][0].text


@pytest.mark.asyncio
async def test_qq_official_single_video_failure_can_link_only(monkeypatch):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_degrade_strategy="link_only",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        if isinstance(chain[0], _Video):
            return SendResult(ok=False, transient=True, detail="video failed")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=Path("/tmp/2.mp4"),
                )
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is False
    assert "partial send" in result.detail
    assert [type(chain[0]) for chain in calls] == [_Video, _Plain]
    assert "媒体原始链接:" in calls[-1][0].text
    assert "https://example.com/2.mp4" in calls[-1][0].text


@pytest.mark.asyncio
async def test_qq_official_single_video_failure_can_fail_without_fallback(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_degrade_strategy="fail",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=False, transient=False, detail="video rejected")

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=Path("/tmp/2.mp4"),
                )
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is False
    assert result.detail == "send_video: video rejected"
    assert [type(chain[0]) for chain in calls] == [_Video]


@pytest.mark.asyncio
async def test_qq_official_original_style_pairs_image_with_following_text(monkeypatch):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(qq_official_media_threshold=0)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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
async def test_qq_official_original_style_single_video_uses_video_then_fallback(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_degrade_strategy="file_then_link",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        if isinstance(chain[0], _Video):
            return SendResult(ok=False, transient=True, detail="video failed")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=Path("/tmp/2.mp4"),
                )
            ],
            layout=[
                LayoutFragment(
                    kind="video",
                    media_type="video",
                    url="https://example.com/2.mp4",
                ),
                LayoutFragment(kind="text", text="caption"),
            ],
        ),
        context=MessageContext(platform_name="qq_official", style=2),
    )

    assert result.ok is False
    assert "partial send" in result.detail
    assert [type(chain[0]) for chain in calls] == [_Video, _File, _Plain]
    assert calls[0][0].file == "/tmp/2.mp4"
    assert calls[1][0].file == "/tmp/2.mp4"
    assert calls[2][0].text == "caption"


@pytest.mark.asyncio
async def test_qq_official_original_style_file_fragment_uses_file_component(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(qq_official_media_threshold=0)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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
                    url="https://example.com/cover.jpg",
                ),
                LayoutFragment(kind="text", text="caption"),
                LayoutFragment(
                    kind="file",
                    media_type="file",
                    url="https://example.com/report.pdf",
                    name="report.pdf",
                ),
                LayoutFragment(kind="text", text="after file"),
            ],
        ),
        context=MessageContext(platform_name="qq_official", style=2),
    )

    assert result.ok is True
    assert len(calls) == 3
    assert isinstance(calls[0][0], _Image)
    assert isinstance(calls[0][1], _Plain)
    assert isinstance(calls[1][0], _File)
    assert not isinstance(calls[1][0], _Image)
    assert calls[1][0].file == "https://example.com/report.pdf"
    assert calls[1][0].url == "https://example.com/report.pdf"
    assert calls[1][0].name == "report.pdf"
    assert isinstance(calls[2][0], _Plain)
    assert calls[2][0].text == "after file"


@pytest.mark.asyncio
async def test_qq_official_file_degrade_failure_continues_and_appends_url(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_media_threshold=1,
        qq_official_degrade_strategy="file_then_link",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        if isinstance(chain[0], _File) and chain[0].file == "/tmp/1.jpg":
            return SendResult(ok=False, transient=True, detail="file failed")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is False
    assert result.transient is True
    assert "partial send" in result.detail
    assert [type(chain[0]) for chain in calls] == [_File, _File, _Plain]
    assert "媒体原始链接:" in calls[-1][0].text
    assert "https://example.com/1.jpg" in calls[-1][0].text
    assert "https://example.com/2.mp4" not in calls[-1][0].text


@pytest.mark.asyncio
async def test_qq_official_single_image_failure_tries_file_then_link(monkeypatch):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_degrade_strategy="file_then_link",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        if isinstance(chain[0], _Image):
            return SendResult(ok=False, transient=True, detail="image failed")
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

    assert result.ok is False
    assert "partial send" in result.detail
    assert [type(chain[0]) for chain in calls] == [_Image, _File, _Plain]
    assert calls[1][0].file == "/tmp/1.jpg"
    assert calls[2][0].text == "entry text"


@pytest.mark.asyncio
async def test_qq_official_single_image_failure_can_fail_without_link_fallback(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_degrade_strategy="fail",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=False, transient=False, detail="image rejected")

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

    assert result.ok is False
    assert result.detail == "send_image_text: image rejected"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_qq_official_media_threshold_link_only_degrade(monkeypatch):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_media_threshold=1,
        qq_official_degrade_strategy="link_only",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert "媒体原始链接:" in calls[0][0].text
    assert "https://example.com/1.jpg" in calls[0][0].text
    assert "https://example.com/2.mp4" in calls[0][0].text


@pytest.mark.asyncio
async def test_qq_official_original_style_multimedia_threshold_still_degrades(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_media_threshold=1,
        qq_official_degrade_strategy="file_then_link",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
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
    assert [type(chain[0]) for chain in calls] == [_File, _File, _Plain]
    assert calls[0][0].file == "/tmp/1.jpg"
    assert calls[1][0].file == "/tmp/2.mp4"
    assert calls[-1][0].text == "caption 1\ncaption 2"


@pytest.mark.asyncio
async def test_weixin_oc_plain_text_uses_single_send(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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
    assert [type(chain[0]) for chain in calls] == [_Image, _Video, _File, _Plain]
    assert "https://example.com/1.jpg" not in calls[-1][0].text
    assert "https://example.com/2.mp4" not in calls[-1][0].text


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

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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
async def test_telegram_gif_over_photo_limit_stays_animation(monkeypatch, tmp_path):
    _patch_components(monkeypatch)
    gif_path = tmp_path / "animation.gif"
    gif_path.write_bytes(b"0" * (10 * 1024 * 1024 + 1))
    sender = TelegramMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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
                    original_url="https://example.com/animation.gif",
                    local_path=gif_path,
                    detected_suffix=".gif",
                )
            ],
        ),
        context=MessageContext(platform_name="telegram"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Image)
    assert calls[0][0].file == str(gif_path)


@pytest.mark.asyncio
async def test_telegram_telegraph_uses_entry_title_and_plain_url(monkeypatch):
    _patch_components(monkeypatch)
    created: dict[str, object] = {}
    client_kwargs: dict[str, object] = {}

    async def fake_create_page(self, **kwargs):
        created.update(kwargs)
        return "https://telegra.ph/entry-title"

    original_init = TelegraphClient.__init__

    def fake_init(self, **kwargs):
        client_kwargs.update(kwargs)
        original_init(self, **kwargs)

    monkeypatch.setattr(TelegraphClient, "__init__", fake_init)
    monkeypatch.setattr(TelegraphClient, "create_media_page", fake_create_page)

    DefaultMessageSender.configure_runtime(
        timeout_seconds=30,
        proxy="socks5://127.0.0.1:7890",
    )
    sender = TelegramMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
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
                "telegraph_proxy": "http://tg-proxy:8080",
            },
        ),
    )

    assert result.ok is True
    assert created["title"] == "Entry title"
    assert created["media_urls"] == [
        "https://example.com/1.webp",
        "https://example.com/2.webp",
    ]
    # Telegraph 使用其专属代理，不继承通用 HTTP 代理（socks5 那条）。
    assert client_kwargs["proxy"] == "http://tg-proxy:8080"
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert "https://telegra.ph/entry-title" in calls[0][0].text
    assert "Telegraph:" not in calls[0][0].text


# ------------------------------------------------------------------
# GIF conversion regression
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qq_official_gif_from_video_counts_as_single_image_with_text(monkeypatch):
    """转换 GIF（video + *.gif）在 QQ Official 中应与单图+文本合发。"""
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/video.mp4",
                    local_path=Path("/tmp/video.gif"),
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
async def test_qq_official_gif_failure_tries_compressed_then_original_video(
    monkeypatch,
):
    """GIF 图文上传失败后应尝试压缩 GIF，再回退原视频。"""
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        first = chain[0]
        if isinstance(first, _Image):
            return SendResult(
                ok=False, transient=False, detail="413 Request Entity Too Large"
            )
        if isinstance(first, _Video):
            return SendResult(ok=True)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    prepared = PreparedMedia(
        media_type="image",
        original_url="https://example.com/video.mp4",
        local_path=Path("/tmp/video.gif"),
        detected_suffix=".gif",
    )
    prepared.variants = [
        MediaVariant(
            "gif",
            "image",
            Path("/tmp/video.gif"),
            suffix=".gif",
            size_bytes=11 * 1024 * 1024,
        ),
        MediaVariant(
            "compressed_gif",
            "image",
            Path("/tmp/video-small.gif"),
            suffix=".gif",
            size_bytes=5 * 1024 * 1024,
        ),
        MediaVariant(
            "original",
            "video",
            Path("/tmp/video.mp4"),
            suffix=".mp4",
            size_bytes=900 * 1024,
        ),
    ]

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[prepared],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is False
    assert isinstance(calls[0][0], _Image)
    assert calls[0][0].file == "/tmp/video-small.gif"
    assert isinstance(calls[1][0], _Video)
    assert calls[1][0].file == "/tmp/video.mp4"
    assert isinstance(calls[-1][0], _Plain)
    assert calls[-1][0].text == "entry text"


@pytest.mark.asyncio
async def test_qq_official_oversize_video_starts_with_file_candidate(
    monkeypatch,
    tmp_path,
):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []
    video_path = tmp_path / "huge.mp4"
    video_path.write_bytes(b"0")

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    prepared = PreparedMedia(
        media_type="video",
        original_url="https://example.com/huge.mp4",
        local_path=video_path,
        detected_suffix=".mp4",
    )
    prepared.variants = [
        MediaVariant(
            "original",
            "video",
            video_path,
            suffix=".mp4",
            size_bytes=101 * 1024 * 1024,
        )
    ]

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[prepared],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert isinstance(calls[0][0], _File)
    assert calls[0][0].file == str(video_path)
    assert not any(isinstance(chain[0], _Video) for chain in calls)


@pytest.mark.asyncio
async def test_qq_official_planned_file_failure_does_not_retry_same_file(
    monkeypatch,
    tmp_path,
):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []
    video_path = tmp_path / "huge.mp4"
    video_path.write_bytes(b"0")

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        if isinstance(chain[0], _File):
            return SendResult(ok=False, transient=False, detail="file rejected")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    prepared = PreparedMedia(
        media_type="video",
        original_url="https://example.com/huge.mp4",
        local_path=video_path,
        detected_suffix=".mp4",
    )
    prepared.variants = [
        MediaVariant(
            "original",
            "video",
            video_path,
            suffix=".mp4",
            size_bytes=101 * 1024 * 1024,
        )
    ]

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[prepared],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is False
    assert [type(chain[0]) for chain in calls] == [_File, _Plain]
    assert "https://example.com/huge.mp4" in calls[-1][0].text


@pytest.mark.asyncio
async def test_qq_official_original_style_gif_from_layout_matches_prepared(monkeypatch):
    """style=original 中 layout URL 命中转换后的 PreparedMedia 时按图片发送。"""
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    prepared = [
        PreparedMedia(
            media_type="video",
            original_url="https://example.com/video.gif",
            local_path=Path("/tmp/video.gif"),
        )
    ]

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            prepared_media=prepared,
            layout=[
                LayoutFragment(
                    kind="video",
                    media_type="video",
                    url="https://example.com/video.gif",
                ),
                LayoutFragment(kind="text", text="caption"),
            ],
        ),
        context=MessageContext(platform_name="qq_official", style=2),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Image)
    assert isinstance(calls[0][1], _Plain)
    assert calls[0][1].text == "caption"


@pytest.mark.asyncio
async def test_qq_official_original_style_gif_from_downloaded_media(monkeypatch):
    """真实推送路径中 request.media 预下载成 GIF 后，original layout 也按图片发送。"""
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_prepare_media(media, timeout=30, proxy=""):
        assert media == [("video", "https://example.com/video.mp4")]
        return [
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/video.mp4",
                local_path=Path("/tmp/video.gif"),
            )
        ]

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "prepare_media", fake_prepare_media)
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
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
        context=MessageContext(platform_name="qq_official", style=2),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Image)
    assert calls[0][0].file == "/tmp/video.gif"
    assert isinstance(calls[0][1], _Plain)
