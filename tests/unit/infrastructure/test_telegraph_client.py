from __future__ import annotations

import pytest
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegraph_client import (
    TelegraphClient,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import ChannelInfo


class _FakeResponse:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        pass

    async def json(self, content_type=None):
        return self._data


class _FakeSession:
    calls: list[dict[str, object]] = []
    response_data: dict[str, object] = {
        "ok": True,
        "result": {"url": "https://telegra.ph/page"},
    }

    def __init__(self, **kwargs) -> None:
        self.__class__.calls.append({"session_kwargs": kwargs})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        pass

    def post(self, url: str, **kwargs):
        self.__class__.calls[-1].update({"url": url, "post_kwargs": kwargs})
        return _FakeResponse(self.__class__.response_data)


def _install_fake_session(monkeypatch, response_data: dict[str, object] | None = None):
    _FakeSession.calls = []
    _FakeSession.response_data = response_data or {
        "ok": True,
        "result": {"url": "https://telegra.ph/page"},
    }
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegraph_client.aiohttp.ClientSession",
        _FakeSession,
    )
    return _FakeSession.calls


async def _create_page(proxy: str = "") -> str:
    client = TelegraphClient(
        access_token="token",
        timeout_seconds=12,
        proxy=proxy,
    )
    return await client.create_media_page(
        title="Title",
        content="Body",
        media_urls=["https://example.com/1.jpg"],
        channel=None,
    )


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


@pytest.mark.asyncio
async def test_telegraph_create_page_without_proxy_uses_direct_session(monkeypatch):
    calls = _install_fake_session(monkeypatch)

    url = await _create_page()

    assert url == "https://telegra.ph/page"
    assert "connector" not in calls[0]["session_kwargs"]
    assert "proxy" not in calls[0]["post_kwargs"]


@pytest.mark.asyncio
async def test_telegraph_create_page_uses_http_proxy(monkeypatch):
    calls = _install_fake_session(monkeypatch)

    await _create_page(proxy="http://127.0.0.1:7890")

    assert "connector" not in calls[0]["session_kwargs"]
    assert calls[0]["post_kwargs"]["proxy"] == "http://127.0.0.1:7890"


@pytest.mark.asyncio
async def test_telegraph_create_page_uses_socks5_connector(monkeypatch):
    calls = _install_fake_session(monkeypatch)
    connector_calls: list[str] = []

    class _FakeConnector:
        @classmethod
        def from_url(cls, url: str):
            connector_calls.append(url)
            return "connector"

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegraph_client.ProxyConnector",
        _FakeConnector,
    )

    await _create_page(proxy="socks5://127.0.0.1:7890")

    assert connector_calls == ["socks5://127.0.0.1:7890"]
    assert calls[0]["session_kwargs"]["connector"] == "connector"
    assert "proxy" not in calls[0]["post_kwargs"]


@pytest.mark.asyncio
async def test_telegraph_create_page_uses_socks4_connector(monkeypatch):
    calls = _install_fake_session(monkeypatch)
    connector_calls: list[str] = []

    class _FakeConnector:
        @classmethod
        def from_url(cls, url: str):
            connector_calls.append(url)
            return "connector"

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegraph_client.ProxyConnector",
        _FakeConnector,
    )

    await _create_page(proxy="socks4://127.0.0.1:7890")

    assert connector_calls == ["socks4://127.0.0.1:7890"]
    assert calls[0]["session_kwargs"]["connector"] == "connector"
    assert "proxy" not in calls[0]["post_kwargs"]


@pytest.mark.asyncio
async def test_telegraph_create_page_uses_socks5h_connector(monkeypatch):
    calls = _install_fake_session(monkeypatch)
    connector_calls: list[str] = []

    class _FakeConnector:
        @classmethod
        def from_url(cls, url: str):
            connector_calls.append(url)
            return "connector"

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegraph_client.ProxyConnector",
        _FakeConnector,
    )

    await _create_page(proxy="socks5h://127.0.0.1:7890")

    assert connector_calls == ["socks5h://127.0.0.1:7890"]
    assert calls[0]["session_kwargs"]["connector"] == "connector"
    assert "proxy" not in calls[0]["post_kwargs"]


@pytest.mark.asyncio
async def test_telegraph_create_page_keeps_api_error(monkeypatch):
    _install_fake_session(monkeypatch, response_data={"ok": False, "error": "bad"})

    with pytest.raises(RuntimeError, match="telegraph createPage failed"):
        await _create_page(proxy="http://127.0.0.1:7890")
