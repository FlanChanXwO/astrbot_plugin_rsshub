from __future__ import annotations

from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.application.services.html_parser import HTMLParser
from astrbot_plugin_rsshub.src.domain.entities.content_types import (
    FileContent,
    build_generated_media_url,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    PreparedMedia,
)
from astrbot_plugin_rsshub.src.infrastructure.pipeline import (
    EffectivePushOptions,
    EntryFormatInput,
    EntryOutputFormat,
    EntryTextFormatter,
    MessageChainFormatter,
    MessageComponentSorter,
    MessageFormatter,
)
from astrbot_plugin_rsshub.src.infrastructure.rendering import (
    TableImageRenderer,
    TableImageRenderResult,
)

from astrbot.api.message_components import Plain


@pytest.mark.asyncio
async def test_clean_text_cleans_discarded_generated_temp_table_image(
    monkeypatch,
    tmp_path: Path,
):
    async def fake_font_ready():
        return tmp_path / "font.ttf"

    digest = "1" * 64
    source_id = build_generated_media_url("table", digest)
    temp_png = tmp_path / "rsshub_table_clean_text.png"
    temp_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager."
        "ensure_table_font_runtime",
        fake_font_ready,
    )
    monkeypatch.setattr(
        TableImageRenderer,
        "render_table",
        lambda self, table: TableImageRenderResult(
            source_id=source_id,
            path=temp_png,
            digest=digest,
            reused=False,
        ),
    )

    await EntryTextFormatter.clean_text(
        "<table><tr><td>A</td></tr></table>",
        render_tables_as_images=True,
    )

    assert not temp_png.exists()


@pytest.mark.asyncio
async def test_clean_text_keeps_discarded_stable_table_cache_image(
    monkeypatch,
    tmp_path: Path,
):
    async def fake_font_ready():
        return tmp_path / "font.ttf"

    digest = "2" * 64
    source_id = build_generated_media_url("table", digest)
    stable_png = tmp_path / "table_images" / f"table_{digest}.png"
    stable_png.parent.mkdir(parents=True)
    stable_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.get_plugin_cache_dir",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager."
        "ensure_table_font_runtime",
        fake_font_ready,
    )
    monkeypatch.setattr(
        TableImageRenderer,
        "render_table",
        lambda self, table: TableImageRenderResult(
            source_id=source_id,
            path=stable_png,
            digest=digest,
            reused=True,
        ),
    )

    await EntryTextFormatter.clean_text(
        "<table><tr><td>A</td></tr></table>",
        render_tables_as_images=True,
    )

    assert stable_png.exists()


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


def test_failed_generated_media_does_not_append_internal_id():
    formatter = MessageFormatter()
    generated_id = build_generated_media_url("table", "a" * 64)

    components = formatter.build_components(
        prepared_media=[
            PreparedMedia(
                media_type="image",
                original_url=generated_id,
                local_path=None,
                download_failed=True,
                generated=True,
            )
        ],
        text="hello",
        failed_urls=[],
    )

    assert [(item.kind, item.media_type) for item in components] == [("text", "")]
    assert components[0].text == "hello"


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
async def test_entry_text_formatter_removes_table_image_placeholder(tmp_path):
    formatter = EntryTextFormatter()

    text = await formatter.format_entry(
        EntryFormatInput(
            title="",
            content="<table><tr><td>A</td><td>B</td></tr></table>",
        ),
        EffectivePushOptions(),
    )

    assert "[表格已转为图片]" not in text


@pytest.mark.asyncio
async def test_entry_text_formatter_keeps_table_text_when_media_hidden():
    formatter = EntryTextFormatter()

    text = await formatter.format_entry(
        EntryFormatInput(
            title="",
            content="<table><tr><td>A</td><td>B</td></tr></table>",
        ),
        EffectivePushOptions(display_media=False),
    )

    assert "A | B" in text
    assert "[表格已转为图片]" not in text


@pytest.mark.asyncio
async def test_entry_text_formatter_can_render_lightweight_markdown():
    formatter = EntryTextFormatter()

    text = await formatter.format_entry(
        EntryFormatInput(
            title="Title *with* brackets [x]",
            content="Body with **literal** markdown",
            link="https://example.com/post",
            author="Author_Name",
            feed_title="Feed",
            tags=("tag-one", "tag_two"),
        ),
        EffectivePushOptions(display_entry_tags=True),
        output_format=EntryOutputFormat.MARKDOWN,
    )

    assert text.startswith("**Title \\*with\\* brackets \\[x\\]**")
    assert "Body with \\*\\*literal\\*\\* markdown" in text
    assert "#tag-one #tag\\_two" in text
    assert "via [https://example.com/post](https://example.com/post) | Feed" in text
    assert "(author: Author\\_Name)" in text


@pytest.mark.asyncio
async def test_entry_text_formatter_invalid_output_format_falls_back_to_plain():
    formatter = EntryTextFormatter()

    text = await formatter.format_entry(
        EntryFormatInput(
            title="Title",
            content="Body",
            link="https://example.com/post",
            feed_title="Feed",
        ),
        EffectivePushOptions(),
        output_format="bad-format",
    )

    assert text.startswith("Title\n\nBody")
    assert "via https://example.com/post | Feed" in text


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


@pytest.mark.asyncio
async def test_html_parser_builds_interleaved_image_layout_fragments():
    parsed = await HTMLParser(
        '<p>A before</p><img src="https://example.com/a.jpg" />'
        '<p>B middle</p><img src="https://example.com/b.jpg" />'
        "<p>C after</p>"
    ).parse()

    assert [(item.kind, item.text, item.url) for item in parsed.layout] == [
        ("text", "A before", ""),
        ("image", "", "https://example.com/a.jpg"),
        ("text", "B middle", ""),
        ("image", "", "https://example.com/b.jpg"),
        ("text", "C after", ""),
    ]


@pytest.mark.asyncio
async def test_html_parser_keeps_pdf_link_as_file_fragment():
    parsed = await HTMLParser(
        '<p>智谱 IPO 材料：<a href="https://example.com/report.pdf">招股书 PDF</a></p>'
    ).parse()

    assert [(item.kind, item.text, item.url, item.name) for item in parsed.layout] == [
        ("text", "智谱 IPO 材料：", "", ""),
        ("file", "", "https://example.com/report.pdf", "招股书 PDF"),
    ]
    assert len(parsed.media) == 1
    assert isinstance(parsed.media[0], FileContent)
    assert parsed.media[0].url == "https://example.com/report.pdf"
    assert parsed.media[0].name == "招股书 PDF"


# ------------------------------------------------------------------
# GIF conversion dispatch regression
# ------------------------------------------------------------------


def test_sorter_video_gif_becomes_image_component():
    """video + *.gif PreparedMedia 应生成 kind=media, media_type=image 组件。"""
    sorter = MessageComponentSorter()
    components = sorter.build_components(
        prepared_media=[
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/video.mp4",
                local_path=Path("/tmp/video.gif"),
            )
        ],
        text="hello",
        failed_urls=[],
        platform="onebot",
    )
    assert [(item.kind, item.media_type, item.file) for item in components] == [
        ("media", "image", "/tmp/video.gif"),
        ("text", "", ""),
    ]
    assert all(item.text == "hello" for item in components if item.kind == "text")


def test_formatter_build_components_gif_conversion():
    """MessageFormatter.build_components 对 video + *.gif 应生成 media_type=image 组件。"""
    formatter = MessageFormatter()
    components = formatter.build_components(
        prepared_media=[
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/video.mp4",
                local_path=Path("/tmp/video.gif"),
            )
        ],
        text="hello",
        failed_urls=[],
        platform="",
    )
    media_items = [
        (c.kind, c.media_type, c.file) for c in components if c.kind == "media"
    ]
    assert media_items == [("media", "image", "/tmp/video.gif")]
    assert all(c.text == "hello" for c in components if c.kind == "text")
