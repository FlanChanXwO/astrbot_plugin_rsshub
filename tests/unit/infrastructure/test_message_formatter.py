from __future__ import annotations

import pytest
from astrbot_plugin_rsshub.src.application.services.html_parser import HTMLParser
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    PreparedMedia,
)
from astrbot_plugin_rsshub.src.infrastructure.pipeline import (
    EffectivePushOptions,
    EntryFormatInput,
    EntryTextFormatter,
    MessageChainFormatter,
    MessageComponentSorter,
    MessageFormatter,
)

from astrbot.api.message_components import Plain


def test_default_chain_keeps_failed_media_as_url_component():
    Plain.reset_mock()
    formatter = MessageFormatter()
    chain = formatter.build_chain(
        prepared_media=[
            PreparedMedia(
                media_type="image",
                original_url="https://example.com/a.jpg",
                local_path=None,
                download_failed=True,
            )
        ],
        text="hello",
        failed_urls=[],
        platform="",
    )
    assert len(chain) == 1
    assert Plain.call_args.args[0] == "hello\n媒体原始链接:\nhttps://example.com/a.jpg"


def test_telegram_chain_keeps_failed_media_as_url_component():
    Plain.reset_mock()
    formatter = MessageFormatter()
    chain = formatter.build_chain(
        prepared_media=[
            PreparedMedia(
                media_type="image",
                original_url="https://example.com/a.jpg",
                local_path=None,
                download_failed=True,
            )
        ],
        text="hello",
        failed_urls=[],
        platform="telegram",
    )
    assert len(chain) == 1
    assert Plain.call_args.args[0] == "hello\n媒体原始链接:\nhttps://example.com/a.jpg"


def test_failed_video_is_not_sent_as_remote_video_component():
    formatter = MessageFormatter()

    components = formatter.build_components(
        prepared_media=[
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/playlist.m3u8",
                local_path=None,
                download_failed=True,
            )
        ],
        text="hello",
        failed_urls=[],
        platform="onebot",
    )

    assert [(item.kind, item.media_type) for item in components] == [("text", "")]
    assert components[0].text == (
        "hello\n媒体原始链接:\nhttps://example.com/playlist.m3u8"
    )


def test_telegram_chain_does_not_truncate_caption_text():
    Plain.reset_mock()
    formatter = MessageFormatter()
    text = "x" * 1100

    chain = formatter.build_chain(
        prepared_media=[
            PreparedMedia(
                media_type="image",
                original_url="https://example.com/a.jpg",
                local_path="/tmp/a.jpg",
                download_failed=False,
            )
        ],
        text=text,
        failed_urls=[],
        platform="telegram",
    )

    assert len(chain) == 2
    assert Plain.call_args.args[0] == text


def test_message_component_sorter_orders_media_before_text_for_onebot():
    sorter = MessageComponentSorter()

    components = sorter.build_components(
        prepared_media=[
            PreparedMedia(
                media_type="file",
                original_url="https://example.com/archive.zip",
                local_path=None,
            ),
            PreparedMedia(
                media_type="image",
                original_url="https://example.com/a.jpg",
                local_path=None,
            ),
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/v.mp4",
                local_path=None,
            ),
        ],
        text="hello",
        failed_urls=[],
        platform="onebot",
    )

    assert [(item.kind, item.media_type) for item in components] == [
        ("media", "image"),
        ("media", "video"),
        ("tail", "file"),
        ("text", ""),
    ]


def test_message_formatter_build_components_keeps_default_media_text_tail_order():
    formatter = MessageFormatter()

    components = formatter.build_components(
        prepared_media=[
            PreparedMedia(
                media_type="audio",
                original_url="https://example.com/a.mp3",
                local_path=None,
            ),
            PreparedMedia(
                media_type="image",
                original_url="https://example.com/a.jpg",
                local_path=None,
            ),
        ],
        text="hello",
        failed_urls=[],
    )

    assert [(item.kind, item.media_type) for item in components] == [
        ("media", "image"),
        ("text", ""),
        ("tail", "audio"),
    ]


def test_message_formatter_alias_keeps_message_chain_formatter_compatibility():
    assert MessageFormatter is MessageChainFormatter


@pytest.mark.asyncio
async def test_entry_text_formatter_decodes_entity_escaped_html():
    formatter = EntryTextFormatter()

    text = await formatter.format_entry(
        EntryFormatInput(
            title="Title",
            content=(
                "Title&lt;br&gt;Body&lt;br&gt;"
                '&lt;img src="https://example.com/image.jpg"&gt;'
            ),
            link="https://example.com/post",
            author="Author",
            feed_title="Feed",
        ),
        EffectivePushOptions(),
    )

    assert "&lt;br" not in text
    assert "&lt;img" not in text
    assert "<img" not in text
    assert "Body" in text
    assert "via https://example.com/post | Feed (author: Author)" in text


@pytest.mark.asyncio
async def test_entry_text_formatter_omits_empty_via_suffix():
    formatter = EntryTextFormatter()

    text = await formatter.format_entry(
        EntryFormatInput(
            title="",
            content="Body only",
            link="",
            author="",
            feed_title="",
            feed_link="",
        ),
        EffectivePushOptions(),
    )

    assert text == "Body only"
    assert "via" not in text
    assert "|" not in text


@pytest.mark.asyncio
async def test_entry_text_formatter_keeps_body_prefix_when_title_hidden():
    formatter = EntryTextFormatter()

    text = await formatter.format_entry(
        EntryFormatInput(
            title="Lead text before hashtags",
            content="Lead text before hashtags<br><br>#tag",
            link="https://example.com/post",
            feed_title="Feed",
        ),
        EffectivePushOptions(display_title=-1),
    )

    assert "Lead text before hashtags" in text
    assert "#tag" in text
    assert not text.startswith("#tag")


@pytest.mark.asyncio
async def test_entry_text_formatter_removes_repeated_title_when_title_visible():
    formatter = EntryTextFormatter()

    text = await formatter.format_entry(
        EntryFormatInput(
            title="Lead text before hashtags",
            content="Lead text before hashtags<br><br>#tag",
            link="https://example.com/post",
            feed_title="Feed",
        ),
        EffectivePushOptions(display_title=0),
    )

    assert text.startswith("Lead text before hashtags\n\n#tag")
    assert text.count("Lead text before hashtags") == 1


@pytest.mark.asyncio
async def test_entry_text_formatter_omits_broken_separator_when_link_missing():
    formatter = EntryTextFormatter()

    text = await formatter.format_entry(
        EntryFormatInput(
            title="",
            content="Body only",
            link="",
            author="Author",
            feed_title="Timeline",
            feed_link="",
        ),
        EffectivePushOptions(),
    )

    assert text == "Body only\n\nTimeline (author: Author)"
    assert "via  |" not in text
    assert " | " not in text


@pytest.mark.asyncio
async def test_html_parser_builds_ordered_layout_fragments():
    parsed = await HTMLParser(
        '<p>Lead</p><img src="https://example.com/1.jpg" />'
        '<p>Caption</p><video src="https://example.com/2.mp4"></video>'
    ).parse()

    assert [(item.kind, item.text, item.url) for item in parsed.layout] == [
        ("text", "Lead", ""),
        ("image", "", "https://example.com/1.jpg"),
        ("text", "Caption", ""),
        ("video", "", "https://example.com/2.mp4"),
    ]
