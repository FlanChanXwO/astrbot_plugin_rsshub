from __future__ import annotations

from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegraph_client import (
    TelegraphClient,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import ChannelInfo


def test_telegraph_page_uses_images_instead_of_media_link_list():
    nodes = TelegraphClient._build_html(
        title="Entry title",
        content=(
            "Entry title\n\nBody text\n\nvia https://example.com/post | Feed title"
        ),
        media_urls=[
            "https://proxy.example/image/1.webp",
            "https://proxy.example/image/2.jpg",
        ],
        channel=ChannelInfo(
            title="Feed title",
            link="https://example.com/feed",
        ),
    )

    assert nodes[0] == {
        "tag": "p",
        "children": [
            {
                "tag": "a",
                "attrs": {"href": "https://example.com/feed"},
                "children": ["Feed title"],
            }
        ],
    }
    assert {"tag": "p", "children": ["Body text"]} in nodes
    assert all("via " not in str(node) for node in nodes)
    assert [node["tag"] for node in nodes[-2:]] == ["img", "img"]
    assert nodes[-2]["attrs"]["src"] == "https://proxy.example/image/1.webp"


def test_telegraph_page_keeps_non_image_media_as_link():
    nodes = TelegraphClient._build_html(
        title="Entry title",
        content="Body text",
        media_urls=["https://example.com/archive.zip"],
        channel=None,
    )

    assert nodes[-1]["tag"] == "p"
    assert nodes[-1]["children"][0]["tag"] == "a"


def test_telegraph_meta_line_rejects_unsafe_channel_link():
    nodes = TelegraphClient._build_html(
        title="Entry title",
        content="Body text",
        media_urls=[],
        channel=ChannelInfo(
            title="Feed title",
            link="javascript:alert(1)",
        ),
    )

    assert nodes[0] == {"tag": "p", "children": ["Feed title"]}
    assert "javascript:" not in str(nodes)
