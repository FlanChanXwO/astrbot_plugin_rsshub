"""Bundle 聚合 RSS 与文档级 handler 服务测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from astrbot_plugin_rsshub.src.application.services.bundle_document_service import (
    BundleAggregateDocument,
    BundleDocumentBuilder,
    BundleDocumentHandlerRuntime,
    BundleDocumentService,
    BundleDocumentValidationError,
    BundleRssDocumentValidator,
)
from astrbot_plugin_rsshub.src.domain.entities.bundle import Bundle
from astrbot_plugin_rsshub.src.domain.entities.bundle_feed import BundleFeed
from astrbot_plugin_rsshub.src.domain.entities.delivery import (
    DeliveryInboxItem,
    DeliveryOwner,
)
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed


def test_bundle_document_services_are_available_from_compatibility_exports() -> None:
    from astrbot_plugin_rsshub.src.application.services import (
        BundleDocumentBuilder as ExportedBuilder,
    )

    assert ExportedBuilder is BundleDocumentBuilder


def _item(
    *,
    item_key: str,
    feed_id: int,
    title: str,
    published: datetime | None = None,
    updated: datetime | None = None,
    media_items: list[dict[str, object]] | None = None,
) -> DeliveryInboxItem:
    return DeliveryInboxItem(
        id=hash(item_key) & 0xFFFF,
        owner=DeliveryOwner(owner_type="bundle", owner_id=7),
        feed_id=feed_id,
        bundle_feed_id=feed_id + 100,
        member_position=0 if feed_id == 11 else 1,
        item_key=item_key,
        hash_group=[item_key],
        discovery_key=f"discovery:{item_key}",
        entry_payload={
            "title": title,
            "link": f"https://example.com/{item_key}",
            "summary": "summary <with> & characters",
            "content": "content & <html>",
            "author": "Author & Co.",
            "tags": ["tag & one"],
        },
        media_items=media_items or [],
        published_at=published,
        entry_updated_at=updated,
    )


def test_builds_stable_rss_items_with_source_media_and_escaping() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Daily <&>",
        target_sessions=["test:Group:1"],
        interval=30,
    )
    members = [
        BundleFeed(id=111, bundle_id=7, feed_id=11, position=0),
        BundleFeed(id=112, bundle_id=7, feed_id=12, position=1),
    ]
    feeds = {
        11: Feed(id=11, title="First & Feed", link="https://example.com/first"),
        12: Feed(id=12, title="Second Feed", link="https://example.com/second"),
    }
    first_day = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    second_day = datetime(2026, 8, 21, 10, tzinfo=timezone.utc)
    items = [
        _item(item_key="first-old", feed_id=11, title="First old", published=first_day),
        _item(
            item_key="first-new",
            feed_id=11,
            title="First <new>",
            published=second_day,
            media_items=[
                {
                    "url": "https://cdn.example.com/image.jpg?a=1&b=2",
                    "type": "image/jpeg",
                    "length": 42,
                }
            ],
        ),
        _item(item_key="first-no-time", feed_id=11, title="First no time"),
        _item(
            item_key="second-entry",
            feed_id=12,
            title="Second entry",
            updated=second_day,
        ),
    ]

    document = BundleDocumentBuilder().build(
        bundle=bundle,
        members=members,
        feeds=feeds,
        inbox_items=items,
    )

    root = ElementTree.fromstring(document.rss_xml)
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"
    channel = root.find("channel")
    assert channel is not None
    rss_items = channel.findall("item")
    assert [item.findtext("guid") for item in rss_items] == [
        "first-new",
        "first-old",
        "first-no-time",
        "second-entry",
    ]
    assert [entry.item_key for entry in document.entries] == [
        "first-new",
        "first-old",
        "first-no-time",
        "second-entry",
    ]
    assert document.consumption_item_keys == (
        "first-new",
        "first-old",
        "first-no-time",
        "second-entry",
    )
    assert rss_items[0].findtext("source") == "First & Feed"
    assert rss_items[0].find("source").attrib["url"] == "https://example.com/first"
    enclosure = rss_items[0].find("enclosure")
    assert enclosure is not None
    assert enclosure.attrib == {
        "url": "https://cdn.example.com/image.jpg?a=1&b=2",
        "type": "image/jpeg",
        "length": "42",
    }
    assert "First &amp; Feed" in document.rss_xml
    assert "First &lt;new&gt;" in document.rss_xml
    assert "content &amp; &lt;html&gt;" in document.rss_xml


def test_validates_empty_rss_and_rejects_malformed_or_unsafe_xml() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Empty",
        target_sessions=["test:Group:1"],
        interval=30,
    )
    member = BundleFeed(id=111, bundle_id=7, feed_id=11, position=0)
    feed = Feed(id=11, title="Feed", link="https://example.com/feed")
    empty_document = BundleDocumentBuilder().build(
        bundle=bundle,
        members=[member],
        feeds={11: feed},
        inbox_items=[],
    )

    root = BundleRssDocumentValidator().validate(empty_document.rss_xml)
    assert root.find("channel") is not None
    assert root.findall(".//item") == []

    for invalid_xml in (
        "<rss><channel></rss>",
        "<!DOCTYPE rss><rss version='2.0'><channel /></rss>",
        "<not-rss />",
    ):
        try:
            BundleRssDocumentValidator().validate(invalid_xml)
        except BundleDocumentValidationError:
            pass
        else:
            raise AssertionError(f"expected invalid XML: {invalid_xml}")


def test_history_limit_is_applied_per_member_without_a_bundle_total_limit() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Limited",
        target_sessions=["test:Group:1"],
        interval=30,
    )
    members = [
        BundleFeed(id=111, bundle_id=7, feed_id=11, position=0),
        BundleFeed(id=112, bundle_id=7, feed_id=12, position=1),
    ]
    # 故意以反向插入顺序提供映射，验证输出仍以成员 position 为准。
    feeds = {
        12: Feed(id=12, title="Second", link="https://example.com/second"),
        11: Feed(id=11, title="First", link="https://example.com/first"),
    }
    items = [
        _item(item_key="first-one", feed_id=11, title="First one"),
        _item(item_key="first-two", feed_id=11, title="First two"),
        _item(item_key="second-one", feed_id=12, title="Second one"),
        _item(item_key="second-two", feed_id=12, title="Second two"),
    ]

    document = BundleDocumentBuilder().build(
        bundle=bundle,
        members=members,
        feeds=feeds,
        inbox_items=items,
        history_entry_limit=1,
    )

    assert document.consumption_item_keys == ("first-one", "second-one")
    root = ElementTree.fromstring(document.rss_xml)
    assert root.findtext("channel/link") == "https://example.com/first"


class _Provider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def text_chat(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(completion_text=self.response)

    def meta(self) -> SimpleNamespace:
        return SimpleNamespace(id="provider-1")


class _ProviderContext:
    def __init__(self, provider: _Provider | None) -> None:
        self.provider = provider

    def get_using_provider(self, _session_id: str | None = None) -> _Provider | None:
        return self.provider


class _ToolLoopContext(_ProviderContext):
    def __init__(self, provider: _Provider) -> None:
        super().__init__(provider)
        self.tool_calls: list[dict[str, object]] = []

    async def tool_loop_agent(self, **kwargs: object) -> SimpleNamespace:
        self.tool_calls.append(kwargs)
        return SimpleNamespace(completion_text=self.provider.response)


@pytest.mark.asyncio
async def test_document_plaintext_transform_updates_snapshot_and_trace() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Transform",
        target_sessions=["test:Group:1"],
        interval=30,
        handlers=[
            {
                "id": "bundle.transform",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "rewrite", "scope": "plaintext"},
            }
        ],
    )
    original = BundleAggregateDocument(
        entries=(),
        text="before",
        rss_xml='<rss version="2.0"><channel /></rss>',
        consumption_item_keys=("input-key",),
    )
    provider = _Provider('{"text":"after"}')

    result = await BundleDocumentHandlerRuntime(_ProviderContext(provider)).process(
        bundle=bundle,
        document=original,
        session_id="test:Group:1",
    )

    assert result.allowed is True
    assert result.document.text == "after"
    assert result.document.rss_xml == original.rss_xml
    assert result.document.consumption_item_keys == ("input-key",)
    assert result.trace[0]["name"] == "ai_transform"
    assert result.trace[0]["scope"] == "plaintext"
    assert result.trace[0]["steps_used"] == 1
    assert result.trace[0]["fallback"] is False
    snapshot = result.to_snapshot()
    assert snapshot["input_document"]["document"]["text"] == "before"
    assert snapshot["document"]["text"] == "after"


@pytest.mark.asyncio
async def test_document_transform_reuses_tool_loop_agent_when_context_provides_one() -> (
    None
):
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Tool loop",
        target_sessions=["test:Group:1"],
        interval=30,
        handlers=[
            {
                "id": "bundle.transform",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "rewrite", "scope": "plaintext"},
            }
        ],
    )
    original = BundleAggregateDocument(
        entries=(),
        text="before",
        rss_xml='<rss version="2.0"><channel /></rss>',
        consumption_item_keys=("input-key",),
    )
    context = _ToolLoopContext(_Provider('{"text":"after"}'))

    result = await BundleDocumentHandlerRuntime(context).process(
        bundle=bundle,
        document=original,
    )

    assert result.document.text == "after"
    assert context.tool_calls[0]["chat_provider_id"] == "provider-1"
    assert context.tool_calls[0]["max_steps"] == 1


@pytest.mark.asyncio
async def test_document_filter_rejects_whole_document_without_changing_input_keys() -> (
    None
):
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Filter",
        target_sessions=["test:Group:1"],
        interval=30,
        handlers=[
            {
                "id": "bundle.filter",
                "name": "ai_filter",
                "status": 1,
                "config": {"prompt": "skip ads"},
            }
        ],
    )
    original = BundleAggregateDocument(
        entries=(),
        text="content",
        rss_xml='<rss version="2.0"><channel><item /></channel></rss>',
        consumption_item_keys=("original-one", "original-two"),
    )

    result = await BundleDocumentHandlerRuntime(
        _ProviderContext(_Provider('{"allow":false,"reason":"广告"}'))
    ).process(bundle=bundle, document=original)

    assert result.allowed is False
    assert result.reason == "广告"
    assert result.document is original
    assert result.document.consumption_item_keys == (
        "original-one",
        "original-two",
    )
    assert result.trace[0]["allow"] is False
    assert (
        result.to_snapshot()["input_document"]["document"]["rss_xml"]
        == original.rss_xml
    )


@pytest.mark.asyncio
async def test_document_transform_invalid_json_falls_back_with_error_trace() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Fallback",
        target_sessions=["test:Group:1"],
        interval=30,
        handlers=[
            {
                "id": "bundle.transform",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "rewrite", "scope": "plaintext"},
            }
        ],
    )
    original = BundleAggregateDocument(
        entries=(),
        text="before",
        rss_xml='<rss version="2.0"><channel /></rss>',
        consumption_item_keys=("input-key",),
    )

    result = await BundleDocumentHandlerRuntime(
        _ProviderContext(_Provider("not-json"))
    ).process(bundle=bundle, document=original)

    assert result.allowed is True
    assert result.document is original
    assert result.trace[0]["status"] == "error"
    assert result.trace[0]["fallback"] is True
    assert "JSON" in result.trace[0]["reason"]


@pytest.mark.asyncio
async def test_document_transform_rejects_unknown_contract_fields() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Strict transform",
        target_sessions=["test:Group:1"],
        interval=30,
        handlers=[
            {
                "id": "bundle.transform",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "rewrite", "scope": "plaintext"},
            }
        ],
    )
    original = BundleAggregateDocument(
        entries=(),
        text="before",
        rss_xml='<rss version="2.0"><channel /></rss>',
        consumption_item_keys=("input-key",),
    )

    result = await BundleDocumentHandlerRuntime(
        _ProviderContext(_Provider('{"text":"after","unexpected":true}'))
    ).process(bundle=bundle, document=original)

    assert result.document is original
    assert result.trace[0]["status"] == "error"
    assert result.trace[0]["fallback"] is True
    assert "非法字段" in result.trace[0]["reason"]


@pytest.mark.asyncio
async def test_document_xml_transform_validates_output_and_keeps_input_identity() -> (
    None
):
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="XML Transform",
        target_sessions=["test:Group:1"],
        interval=30,
        handlers=[
            {
                "id": "bundle.xml-transform",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "rewrite xml", "scope": "xml"},
            }
        ],
    )
    original = BundleAggregateDocument(
        entries=(),
        text="before",
        rss_xml='<rss version="2.0"><channel><item><guid>input</guid></item></channel></rss>',
        consumption_item_keys=("input-key",),
    )
    transformed = (
        '<rss version="2.0"><channel><title>After</title>'
        "<item><guid>provider-key</guid><description>after body</description>"
        "</item></channel></rss>"
    )

    result = await BundleDocumentHandlerRuntime(
        _ProviderContext(_Provider(json.dumps({"rss_xml": transformed})))
    ).process(bundle=bundle, document=original)

    assert result.document.text == "after body"
    assert result.document.rss_xml == transformed
    assert result.document.consumption_item_keys == ("input-key",)
    assert result.trace[0]["scope"] == "xml"
    assert result.trace[0]["fallback"] is False
    snapshot = result.to_snapshot()
    assert snapshot["input_document"]["document"]["rss_xml"] == original.rss_xml
    assert snapshot["document"]["rss_xml"] == transformed


@pytest.mark.asyncio
async def test_document_xml_transform_updates_entries_for_delete_add_edit_and_reorder() -> (
    None
):
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="XML entries",
        target_sessions=["test:Group:1"],
        interval=30,
        handlers=[
            {
                "id": "bundle.xml-transform",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "rewrite xml", "scope": "xml"},
            }
        ],
    )
    member = BundleFeed(id=111, bundle_id=7, feed_id=11, position=0)
    feed = Feed(id=11, title="Feed", link="https://example.com/feed")
    original = BundleDocumentBuilder().build(
        bundle=bundle,
        members=[member],
        feeds={11: feed},
        inbox_items=[
            _item(item_key="first", feed_id=11, title="First"),
            _item(item_key="second", feed_id=11, title="Second"),
        ],
    )
    transformed = (
        '<rss version="2.0"><channel>'
        "<item><guid>second</guid><title>Second edited</title>"
        "<link>https://example.com/second</link><description>edited</description>"
        "</item>"
        "<item><guid>new</guid><title>New item</title>"
        "<link>https://example.com/new</link><description>added</description>"
        '<source url="https://example.com/feed">Feed</source>'
        '<enclosure url="https://cdn.example.com/new.png" type="image/png" />'
        "</item></channel></rss>"
    )

    result = await BundleDocumentHandlerRuntime(
        _ProviderContext(_Provider(json.dumps({"rss_xml": transformed})))
    ).process(bundle=bundle, document=original)

    assert [entry.item_key for entry in result.document.entries] == ["second", "new"]
    assert result.document.entries[0].title == "Second edited"
    assert result.document.entries[1].content_html == "added"
    assert result.document.entries[1].feed_id == 11
    assert result.document.entries[1].media_items == (
        {"url": "https://cdn.example.com/new.png", "type": "image/png"},
    )
    assert result.document.consumption_item_keys == ("first", "second")


@pytest.mark.asyncio
async def test_document_transform_without_provider_keeps_document_and_traces_fallback() -> (
    None
):
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="No Provider",
        target_sessions=["test:Group:1"],
        interval=30,
        handlers=[
            {
                "id": "bundle.transform",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "rewrite", "scope": "xml"},
            }
        ],
    )
    original = BundleAggregateDocument(
        entries=(),
        text="before",
        rss_xml='<rss version="2.0"><channel /></rss>',
        consumption_item_keys=("input-key",),
    )

    result = await BundleDocumentHandlerRuntime().process(
        bundle=bundle,
        document=original,
    )

    assert result.document is original
    assert result.trace[0]["status"] == "ok"
    assert result.trace[0]["fallback"] is True
    assert result.trace[0]["fallback_reason"] == "provider unavailable"


@pytest.mark.asyncio
async def test_document_xml_transform_invalid_xml_falls_back_to_previous_snapshot() -> (
    None
):
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Invalid XML",
        target_sessions=["test:Group:1"],
        interval=30,
        handlers=[
            {
                "id": "bundle.xml-transform",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "rewrite xml", "scope": "xml"},
            }
        ],
    )
    original = BundleAggregateDocument(
        entries=(),
        text="before",
        rss_xml='<rss version="2.0"><channel /></rss>',
        consumption_item_keys=("input-key",),
    )

    result = await BundleDocumentHandlerRuntime(
        _ProviderContext(_Provider(json.dumps({"rss_xml": "<rss>"})))
    ).process(bundle=bundle, document=original)

    assert result.document is original
    assert result.trace[0]["status"] == "error"
    assert result.trace[0]["fallback"] is True
    assert "RSS" in result.trace[0]["reason"]


def test_builder_rejects_unpersisted_owner_and_mismatched_member_source() -> None:
    bundle = Bundle(
        id=None,
        user_id="user-1",
        name="Invalid owner",
        target_sessions=["test:Group:1"],
        interval=30,
    )
    member = BundleFeed(id=111, bundle_id=7, feed_id=11, position=0)
    feed = Feed(id=11, title="Feed", link="https://example.com/feed")

    with pytest.raises(ValueError, match="已持久化"):
        BundleDocumentBuilder().build(
            bundle=bundle,
            members=[member],
            feeds={11: feed},
            inbox_items=[_item(item_key="owner", feed_id=11, title="Owner")],
        )

    persisted_bundle = bundle.model_copy(update={"id": 7})
    wrong_source = _item(item_key="source", feed_id=12, title="Wrong").model_copy(
        update={"bundle_feed_id": 111}
    )
    with pytest.raises(ValueError, match="来源"):
        BundleDocumentBuilder().build(
            bundle=persisted_bundle,
            members=[member],
            feeds={11: feed},
            inbox_items=[wrong_source],
        )


def test_builder_orders_mixed_naive_and_aware_timestamps_as_utc() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Mixed time",
        target_sessions=["test:Group:1"],
        interval=30,
    )
    member = BundleFeed(id=111, bundle_id=7, feed_id=11, position=0)
    feed = Feed(id=11, title="Feed", link="https://example.com/feed")
    items = [
        _item(
            item_key="naive-old",
            feed_id=11,
            title="Old",
            # 用 fromisoformat 明确构造历史中的 naive 时间，验证 UTC 兼容排序。
            published=datetime.fromisoformat("2026-08-20T10:00:00"),
        ),
        _item(
            item_key="aware-new",
            feed_id=11,
            title="New",
            published=datetime(2026, 8, 21, 10, tzinfo=timezone.utc),
        ),
    ]

    document = BundleDocumentBuilder().build(
        bundle=bundle,
        members=[member],
        feeds={11: feed},
        inbox_items=items,
    )

    assert document.consumption_item_keys == ("aware-new", "naive-old")


@pytest.mark.asyncio
async def test_document_service_builds_and_processes_final_bundle_context() -> None:
    bundle = Bundle(
        id=7,
        user_id="user-1",
        name="Pipeline",
        target_sessions=["test:Group:1"],
        interval=30,
    )
    member = BundleFeed(id=111, bundle_id=7, feed_id=11, position=0)
    feed = Feed(id=11, title="Feed", link="https://example.com/feed")
    item = _item(item_key="pipeline-item", feed_id=11, title="Pipeline item")

    result = await BundleDocumentService().build_and_process(
        bundle=bundle,
        members=[member],
        feeds={11: feed},
        inbox_items=[item],
    )

    assert result.allowed is True
    assert result.document.consumption_item_keys == ("pipeline-item",)
    assert ElementTree.fromstring(result.document.rss_xml).find(".//item") is not None
