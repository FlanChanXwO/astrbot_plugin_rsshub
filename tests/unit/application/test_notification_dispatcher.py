from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from astrbot_plugin_rsshub.src.application.ports import SendResult
from astrbot_plugin_rsshub.src.application.services.content_handlers import (
    ContentHandlerRuntime,
    EntryContentContext,
)
from astrbot_plugin_rsshub.src.application.services.notification_dispatcher import (
    NotificationDispatcher,
    SendTarget,
    append_media_links_to_text,
    infer_media_type,
    normalize_media_items,
    strip_appended_media_links_from_text,
)
from astrbot_plugin_rsshub.src.application.services.session_push_queue import (
    PushJobResult,
    SessionPushQueue,
)
from astrbot_plugin_rsshub.src.domain.entities.content_types import LayoutFragment
from astrbot_plugin_rsshub.src.domain.entities.push_history import PushHistory
from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription
from astrbot_plugin_rsshub.src.domain.entities.user import User
from astrbot_plugin_rsshub.src.infrastructure.config import ContentHandlerSettings


class FakeSender:
    def __init__(self, result: SendResult | None = None) -> None:
        self.result = result or SendResult(ok=True)
        self.requests = []

    async def send_to_user(self, request, context=None):
        self.requests.append((request, context))
        return self.result


class FakeSenderProvider:
    def __init__(self, sender: FakeSender) -> None:
        self.sender = sender

    def get(self, platform_name: str | None):
        return self.sender


class FakeProviderResponse:
    def __init__(self, completion_text: str) -> None:
        self.completion_text = completion_text


class FakeProvider:
    def __init__(self, completion_text: str) -> None:
        self.completion_text = completion_text
        self.prompts = []

    async def text_chat(self, **kwargs):
        self.prompts.append(kwargs)
        return FakeProviderResponse(self.completion_text)

    def meta(self):
        return SimpleNamespace(id="fake-provider")


class FakeProviderContext:
    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider

    def get_using_provider(self, session_id=None):
        return self.provider

    async def tool_loop_agent(self, **kwargs):
        prompt = kwargs.get("prompt", "")
        self.provider.prompts.append(
            {
                "prompt": prompt,
                "system_prompt": kwargs.get("system_prompt", ""),
                "tools": [
                    tool.name for tool in getattr(kwargs.get("tools"), "tools", [])
                ],
            }
        )
        return FakeProviderResponse(self.provider.completion_text)


class FakeProviderSelectorContext:
    def __init__(
        self, *, default_provider: FakeProvider, selected_provider: FakeProvider
    ):
        self.default_provider = default_provider
        self.selected_provider = selected_provider
        self.requested_provider_ids = []
        self.persona_manager = self

    def get_using_provider(self, session_id=None):
        return self.default_provider

    def get_provider_by_id(self, provider_id):
        self.requested_provider_ids.append(provider_id)
        return self.selected_provider

    def get_persona_v3_by_id(self, persona_id):
        return {"name": persona_id, "prompt": "persona system prompt"}

    async def tool_loop_agent(self, **kwargs):
        self.selected_provider.prompts.append(
            {
                "prompt": kwargs.get("prompt", ""),
                "system_prompt": kwargs.get("system_prompt", ""),
                "tools": [
                    tool.name for tool in getattr(kwargs.get("tools"), "tools", [])
                ],
            }
        )
        return FakeProviderResponse(self.selected_provider.completion_text)


def test_content_handler_runtime_resolves_handlers_mode_semantics():
    runtime = ContentHandlerRuntime()
    user = User(id="user-1")
    inherit_sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        handlers_mode="inherit",
        handlers=[
            {
                "id": "builtin.ai_transform.default",
                "type": "builtin",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "ignored"},
            }
        ],
    )
    override_sub = Subscription(
        id=2,
        user_id="user-1",
        feed_id=10,
        handlers_mode="override",
        handlers=[
            {
                "id": "builtin.ai_transform.default",
                "type": "builtin",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "used"},
            }
        ],
    )
    disabled_sub = Subscription(
        id=3,
        user_id="user-1",
        feed_id=10,
        handlers_mode="disabled",
        handlers=[
            {
                "id": "builtin.ai_transform.default",
                "type": "builtin",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "ignored"},
            }
        ],
    )

    inherit = runtime.resolve_handlers(subscription=inherit_sub, user=user)
    override = runtime.resolve_handlers(subscription=override_sub, user=user)
    disabled = runtime.resolve_handlers(subscription=disabled_sub, user=user)

    assert inherit == []
    assert [spec.name for spec in override] == ["ai_transform"]
    assert disabled == []


@pytest.mark.asyncio
async def test_ai_filter_invalid_json_allows_with_trace():
    provider = FakeProvider("not json")
    runtime = ContentHandlerRuntime(FakeProviderContext(provider))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        handlers_mode="override",
        handlers=[
            {
                "id": "builtin.ai_filter.default",
                "type": "builtin",
                "name": "ai_filter",
                "status": 1,
                "config": {"prompt": "keep only important", "input_scope": "both"},
            }
        ],
    )

    result = await runtime.process_entry_with_trace(
        subscription=sub,
        user=None,
        entry=EntryContentContext(
            title="title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            raw_xml="<item>raw</item>",
        ),
    )

    assert result.allow is True
    assert result.trace[0]["name"] == "ai_filter"
    assert result.trace[0]["allow"] is True
    assert result.trace[0]["reason"] == "invalid json"
    assert "raw_xml" in provider.prompts[0]["prompt"]


@pytest.mark.asyncio
async def test_ai_handlers_use_global_provider_and_persona_system_prompt():
    default_provider = FakeProvider('{"allow": false, "reason": "wrong provider"}')
    selected_provider = FakeProvider('{"allow": true, "reason": "ok"}')
    context = FakeProviderSelectorContext(
        default_provider=default_provider,
        selected_provider=selected_provider,
    )
    runtime = ContentHandlerRuntime(
        context,
        settings=ContentHandlerSettings(
            ai_provider_id="provider-1",
            ai_persona_id="persona-1",
        ),
    )
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        handlers_mode="override",
        handlers=[
            {
                "id": "builtin.ai_filter.default",
                "type": "builtin",
                "name": "ai_filter",
                "status": 1,
                "config": {"prompt": "allow useful entries"},
            }
        ],
    )

    result = await runtime.process_entry_with_trace(
        subscription=sub,
        user=None,
        entry=EntryContentContext(
            title="title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            raw_xml="<item>raw</item>",
        ),
        session_id="session-1",
    )

    assert result.allow is True
    assert context.requested_provider_ids == ["provider-1"]
    assert default_provider.prompts == []
    assert selected_provider.prompts[0]["system_prompt"] == "persona system prompt"


@pytest.mark.asyncio
async def test_ai_transform_plaintext_uses_agent_and_updates_text_fields():
    provider = FakeProvider('{"title":"新标题","summary":"新摘要","content":"新正文"}')
    runtime = ContentHandlerRuntime(FakeProviderContext(provider))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        handlers_mode="override",
        handlers=[
            {
                "id": "builtin.ai_transform.default",
                "type": "builtin",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "压缩成简短摘要", "scope": "plaintext"},
            }
        ],
    )

    result = await runtime.process_entry_with_trace(
        subscription=sub,
        user=None,
        entry=EntryContentContext(
            title="原标题",
            summary="原摘要",
            content="原正文",
            link="https://example.com/entry",
            author="author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            raw_xml="<item><title>原标题</title></item>",
        ),
    )

    assert result.entry.title == "新标题"
    assert result.entry.summary == "新摘要"
    assert result.entry.content == "新正文"
    assert result.trace[0]["scope"] == "plaintext"
    assert result.trace[0]["fallback"] is False


@pytest.mark.asyncio
async def test_ai_transform_xml_reparses_raw_xml_and_updates_entry():
    provider = FakeProvider(
        '{"raw_xml":"<item><title>新标题</title><link>https://example.com/new</link><description><![CDATA[<p>新的正文</p><img src=\\"https://example.com/image.jpg\\"></p>]]></description><author>new-author</author></item>"}'
    )
    runtime = ContentHandlerRuntime(FakeProviderContext(provider))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        handlers_mode="override",
        handlers=[
            {
                "id": "builtin.ai_transform.default",
                "type": "builtin",
                "name": "ai_transform",
                "status": 1,
                "config": {"prompt": "清理广告并重写 XML", "scope": "xml"},
            }
        ],
    )

    result = await runtime.process_entry_with_trace(
        subscription=sub,
        user=None,
        entry=EntryContentContext(
            title="原标题",
            summary="原摘要",
            content="原正文",
            link="https://example.com/entry",
            author="author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            raw_xml="<item><title>原标题</title></item>",
        ),
    )

    assert result.entry.title == "新标题"
    assert result.entry.link == "https://example.com/new"
    assert "新的正文" in result.entry.content
    assert "https://example.com/image.jpg" in result.entry.media_urls
    assert result.entry.raw_xml.startswith("<item>")
    assert result.trace[0]["scope"] == "xml"


@pytest.mark.asyncio
async def test_dispatch_sends_via_injected_sender_provider():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )

    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = User(id="user-1")

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    user_repo.get_or_create.assert_awaited_once_with("user-1")
    assert len(sender.requests) == 1
    request, context = sender.requests[0]
    assert request.session_id == "telegram:Group:1"
    assert request.message == "content"
    assert context.platform_name == "telegram"
    assert history_repo.save.await_count == 2
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.media_urls is None


@pytest.mark.asyncio
async def test_dispatch_guard_skips_already_successful_entry_guid():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = True

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats == {"success": 0, "failed": 0, "pending": 0, "skipped": 1}
    assert sender.requests == []
    history_repo.save.assert_awaited_once()
    saved = history_repo.save.await_args.args[0]
    assert saved.status == "skipped"
    assert saved.fail_reason == "dispatch guard: already successful entry_guid"
    assert saved.max_retries == 0
    assert saved.entry_guid == "guid-1"


@pytest.mark.asyncio
async def test_qq_official_degraded_success_is_acked_by_success_guard():
    sender = FakeSender(SendResult(ok=True))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="qq_official",
        target_session="qqofficial:FriendMessage:openid-1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.side_effect = [False, True]
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    first = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content\n媒体原始链接:\nhttps://example.com/huge.jpg",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_urls=["https://example.com/huge.jpg"],
        entry_guid="guid-qq-degraded",
    )
    second = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content\n媒体原始链接:\nhttps://example.com/huge.jpg",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_urls=["https://example.com/huge.jpg"],
        entry_guid="guid-qq-degraded",
    )

    assert first == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    assert second == {"success": 0, "failed": 0, "pending": 0, "skipped": 1}
    assert len(sender.requests) == 1
    success_history = history_repo.save.await_args_list[1].args[0]
    skipped_history = history_repo.save.await_args_list[2].args[0]
    assert success_history.status == "success"
    assert success_history.fail_reason is None
    assert success_history.entry_guid == "guid-qq-degraded"
    assert skipped_history.status == "skipped"
    assert (
        skipped_history.fail_reason == "dispatch guard: already successful entry_guid"
    )


@pytest.mark.asyncio
async def test_dispatch_can_limit_to_selected_subscription_ids():
    sender = FakeSender()
    subs = [
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:2",
        ),
    ]

    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subs
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        subscription_ids=[2],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    assert len(sender.requests) == 1
    assert sender.requests[0][0].session_id == "telegram:Group:2"


@pytest.mark.asyncio
async def test_dispatch_uses_session_queue_for_same_session():
    sender = FakeSender()
    queue = SessionPushQueue()
    subs = [
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
    ]

    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subs
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        push_job_queue=queue,
        basic_settings=SimpleNamespace(
            failed_queue_capacity=50,
            failed_queue_max_retries=3,
            deduplicate_multi_bot=False,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
    )

    assert stats == {"success": 2, "failed": 0, "pending": 0, "skipped": 0}
    assert len(sender.requests) == 2
    assert queue.get_current_job("telegram:Group:1") is None


@pytest.mark.asyncio
async def test_send_to_session_returns_cancelled_result_from_queue():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    queue = SessionPushQueue()
    queue.enqueue = AsyncMock(
        return_value=PushJobResult(
            job_id="rss-000123",
            session_id="telegram:Group:1",
            ok=False,
            cancelled=True,
            error="job cancelled",
        )
    )

    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=AsyncMock(),
        sender_provider=FakeSenderProvider(sender),
        push_job_queue=queue,
    )

    result = await dispatcher.send_to_session(
        target=SendTarget(
            user_id=sub.user_id,
            platform_name=sub.platform_name,
            target_session=sub.target_session,
            sub_id=sub.id,
        ),
        content="content",
        media_urls=None,
    )

    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["job_id"] == "rss-000123"
    assert "Cancelled by System or Command" in result["error"]
    assert sender.requests == []


def test_infer_media_type_detects_rsshub_wrapped_video_url():
    url = (
        "https://proxy.example/?url=https%3A%2F%2Fvideo.twimg.com%2Fext_tw_video"
        "%2F123%2Fpu%2Fvid%2Favc1%2F720x1280%2Fclip.mp4%3Ftag%3D14"
    )

    assert infer_media_type(url) == "video"


def test_normalize_media_items_preserves_explicit_video_type_without_extension():
    url = "https://example.com/media/play?id=123"

    assert normalize_media_items(media_items=[("video", url)]) == [("video", url)]


def test_append_media_links_to_text_is_idempotent():
    text = "hello\n媒体原始链接:\nhttps://example.com/a.mp4"

    result = append_media_links_to_text(
        text,
        media_urls=["https://example.com/a.mp4"],
    )

    assert result == text


def test_strip_appended_media_links_from_text_removes_failure_suffix():
    text = "hello\n媒体原始链接:\nhttps://example.com/a.mp4"

    result = strip_appended_media_links_from_text(
        text,
        media_urls=["https://example.com/a.mp4"],
    )

    assert result == "hello"


def test_strip_appended_media_links_from_text_keeps_unrelated_suffix():
    text = "hello\n媒体原始链接:\nhttps://example.com/a.mp4\nhttps://example.com/extra"

    result = strip_appended_media_links_from_text(
        text,
        media_urls=["https://example.com/a.mp4"],
    )

    assert result == text


@pytest.mark.asyncio
async def test_send_to_session_preserves_video_media_type():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=AsyncMock(),
        sender_provider=FakeSenderProvider(sender),
    )
    video_url = "https://example.com/video.mp4?tag=14"

    result = await dispatcher.send_to_session(
        target=SendTarget(
            user_id=sub.user_id,
            platform_name=sub.platform_name,
            target_session=sub.target_session,
            sub_id=sub.id,
        ),
        content="content",
        media_urls=[video_url],
    )

    assert result["ok"] is True
    request, _context = sender.requests[0]
    assert request.media == [("video", video_url)]


@pytest.mark.asyncio
async def test_send_to_session_preserves_explicit_video_media_item():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=AsyncMock(),
        sender_provider=FakeSenderProvider(sender),
    )
    video_url = "https://example.com/media/play?id=123"

    result = await dispatcher.send_to_session(
        target=SendTarget(
            user_id=sub.user_id,
            platform_name=sub.platform_name,
            target_session=sub.target_session,
            sub_id=sub.id,
        ),
        content="content",
        media_urls=[video_url],
        media_items=[("video", video_url)],
    )

    assert result["ok"] is True
    request, _context = sender.requests[0]
    assert request.media == [("video", video_url)]


@pytest.mark.asyncio
async def test_send_to_session_passes_entry_context_to_sender():
    sender = FakeSender()
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=AsyncMock(),
        sender_provider=FakeSenderProvider(sender),
    )

    result = await dispatcher.send_to_session(
        target=SendTarget(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
            sub_id=1,
        ),
        content="content",
        media_urls=None,
        channel_title="Feed",
        channel_link="https://example.com/feed",
        entry_title="Entry title",
        entry_link="https://example.com/post",
    )

    assert result["ok"] is True
    _request, context = sender.requests[0]
    assert context.entry_title == "Entry title"
    assert context.entry_link == "https://example.com/post"


@pytest.mark.asyncio
async def test_dispatch_persists_media_urls_and_appends_links_on_failure():
    sender = FakeSender(SendResult(ok=False, detail="forward failed"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )
    media_url = "https://example.com/video.mp4"

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_urls=[media_url],
    )

    assert stats == {"success": 0, "failed": 0, "pending": 1, "skipped": 0}
    assert history_repo.save.await_count == 2
    first_saved = history_repo.save.await_args_list[0].args[0]
    second_saved = history_repo.save.await_args_list[1].args[0]
    assert first_saved.media_urls == [media_url]
    assert second_saved.media_urls == [media_url]
    assert "媒体原始链接:" in second_saved.content
    assert media_url in second_saved.content


@pytest.mark.asyncio
async def test_dispatch_feed_entry_persists_raw_xml_in_history():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            raw_xml="<item><title>title</title></item>",
        ),
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.raw_xml == "<item><title>title</title></item>"


@pytest.mark.asyncio
async def test_dispatch_with_raw_entry_keeps_cleaned_content_when_not_processed():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    clean_content = (
        "[ -50 Squad ] #エンドフィールド #WakeofSpringCC\n\n"
        "via https://x.com/NoUgrad/status/2057138522574971385 | "
        "Twitter following timeline (author: NoUGraD)"
    )
    html_body = (
        "[ -50 Squad ]<br />#エンドフィールド #WakeofSpringCC<br />"
        '<img src="https://example.com/image.jpg" />'
        '<div class="rsshub-quote"><video src="https://example.com/video.mp4">'
        "</video></div>"
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content=clean_content,
        entry_title="[ -50 Squad ] #エンドフィールド #WakeofSpringCC",
        entry_link="https://x.com/NoUgrad/status/2057138522574971385",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="[ -50 Squad ] #エンドフィールド #WakeofSpringCC",
            summary=html_body,
            content=html_body,
            link="https://x.com/NoUgrad/status/2057138522574971385",
            author="NoUGraD",
            feed_title="Twitter following timeline",
            feed_link="https://rsshub.example/twitter",
            raw_xml="<item><description>raw</description></item>",
        ),
        media_items=[
            ("image", "https://example.com/image.jpg"),
            ("video", "https://example.com/video.mp4"),
        ],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.content == clean_content
    assert first_saved.raw_xml == "<item><description>raw</description></item>"
    assert "<br" not in first_saved.content
    assert "<img" not in first_saved.content
    assert "<video" not in first_saved.content
    request, _context = sender.requests[0]
    assert request.message == clean_content


@pytest.mark.asyncio
async def test_dispatch_formats_raw_entry_with_effective_options_from_subscription():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        length_limit=4,
        display_title=-1,
        display_author=-1,
        display_via=-2,
        display_media=-1,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="Title",
            summary="abcdef<br>&lt;img src=&quot;https://example.com/a.jpg&quot;&gt;",
            content="abcdef<br>&lt;img src=&quot;https://example.com/a.jpg&quot;&gt;",
            link="https://example.com/entry",
            author="Author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
        ),
        media_items=[("image", "https://example.com/a.jpg")],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.content == "a..."
    assert first_saved.media_urls is None
    request, _context = sender.requests[0]
    assert request.message == "a..."
    assert request.media is None


@pytest.mark.asyncio
async def test_dispatch_limits_original_layout_text_with_effective_length_limit():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        length_limit=8,
        style=2,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-original-limit",
        raw_entry=EntryContentContext(
            title="Title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            layout=(
                LayoutFragment(kind="text", text="abcdefghij"),
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/a.jpg",
                ),
                LayoutFragment(kind="text", text="tail"),
                LayoutFragment(
                    kind="file",
                    media_type="file",
                    url="https://example.com/report.pdf",
                    name="report.pdf",
                ),
            ),
        ),
        media_items=[
            ("image", "https://example.com/a.jpg"),
            ("file", "https://example.com/report.pdf"),
        ],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    request, context = sender.requests[0]
    assert context.style == 2
    assert request.layout is not None
    assert [(item.kind, item.text, item.url) for item in request.layout] == [
        ("text", "abcde...", ""),
        ("image", "", "https://example.com/a.jpg"),
        ("file", "", "https://example.com/report.pdf"),
    ]
    assert request.media == [
        ("image", "https://example.com/a.jpg"),
        ("file", "https://example.com/report.pdf"),
    ]


@pytest.mark.asyncio
async def test_dispatch_keeps_original_layout_text_when_length_limit_disabled():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        length_limit=0,
        style=2,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-original-no-limit",
        raw_entry=EntryContentContext(
            title="Title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            layout=(LayoutFragment(kind="text", text="abcdefghij"),),
        ),
    )

    request, _context = sender.requests[0]
    assert request.layout is not None
    assert request.layout[0].text == "abcdefghij"


@pytest.mark.asyncio
async def test_dispatch_clears_original_layout_when_media_hidden():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        display_media=-1,
        style=2,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-original-media-hidden",
        raw_entry=EntryContentContext(
            title="Title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            layout=(
                LayoutFragment(kind="text", text="lead"),
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/a.jpg",
                ),
            ),
        ),
        media_items=[("image", "https://example.com/a.jpg")],
    )

    request, _context = sender.requests[0]
    assert request.media is None
    assert request.layout is None


@pytest.mark.asyncio
async def test_dispatch_link_only_clears_original_layout():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        send_mode=-1,
        style=2,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        entry_guid="guid-original-link-only",
        raw_entry=EntryContentContext(
            title="Title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            layout=(
                LayoutFragment(kind="text", text="lead"),
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/a.jpg",
                ),
            ),
        ),
        media_items=[("image", "https://example.com/a.jpg")],
    )

    request, _context = sender.requests[0]
    assert request.message == "Title\nhttps://example.com/entry"
    assert request.media is None
    assert request.layout is None


@pytest.mark.asyncio
async def test_dispatch_inherits_effective_options_from_user():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    user = User(id="user-1", notify=0)
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    user_repo = AsyncMock()
    user_repo.get_or_create.return_value = user
    history_repo = AsyncMock()

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        user_repo=user_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="fallback",
        entry_title="Title",
        entry_link="https://example.com/entry",
        raw_entry=EntryContentContext(
            title="Title",
            summary="Body",
            content="Body",
            link="https://example.com/entry",
            author="Author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
        ),
    )

    assert stats == {"success": 0, "failed": 0, "pending": 0, "skipped": 1}
    assert sender.requests == []
    history_repo.save.assert_awaited_once()
    saved = history_repo.save.await_args.args[0]
    assert saved.status == "skipped"
    assert saved.fail_reason == "notify disabled"
    assert saved.max_retries == 0


@pytest.mark.asyncio
async def test_dispatch_strips_removed_xml_parse_handler_and_keeps_clean_content():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        handlers_mode="override",
        handlers=[
            {
                "id": "builtin.xml_parse.default",
                "type": "builtin",
                "name": "xml_parse",
                "status": 1,
                "config": {},
            }
        ],
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="clean caller content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="title",
            summary="Before<br />After",
            content="Before<br />After",
            link="https://example.com/entry",
            author="author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
            raw_xml="<item><title>title</title></item>",
        ),
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 0}
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert "Before\nAfter" in first_saved.content
    assert "<br" not in first_saved.content
    assert "clean caller content" not in first_saved.content
    request, _context = sender.requests[0]
    assert request.message == first_saved.content


@pytest.mark.asyncio
async def test_dispatch_ai_filter_false_writes_skipped_history_without_send():
    sender = FakeSender()
    provider = FakeProvider('{"allow":false,"reason":"广告"}')
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        handlers_mode="override",
        handlers=[
            {
                "id": "builtin.ai_filter.default",
                "type": "builtin",
                "name": "ai_filter",
                "status": 1,
                "config": {"prompt": "跳过广告", "input_scope": "text"},
            }
        ],
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        content_handler_runtime=ContentHandlerRuntime(FakeProviderContext(provider)),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        entry_guid="guid-1",
        raw_entry=EntryContentContext(
            title="title",
            summary="summary",
            content="content",
            link="https://example.com/entry",
            author="author",
            feed_title="Feed",
            feed_link="https://example.com/feed.xml",
        ),
    )

    assert stats == {"success": 0, "failed": 0, "pending": 0, "skipped": 1}
    assert sender.requests == []
    history_repo.save.assert_awaited_once()
    saved = history_repo.save.await_args.args[0]
    assert saved.status == "skipped"
    assert saved.max_retries == 0
    assert saved.fail_reason == "广告"
    assert saved.handler_trace[0]["allow"] is False
    assert saved.handler_trace[0]["reason"] == "广告"


@pytest.mark.asyncio
async def test_dispatch_failure_uses_configured_retry_limit_and_capacity():
    sender = FakeSender(SendResult(ok=False, detail="forward failed"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.count_retryable_failures = AsyncMock(return_value=1)
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        basic_settings=SimpleNamespace(
            failed_queue_capacity=2,
            failed_queue_max_retries=7,
            deduplicate_multi_bot=True,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
    )

    assert stats == {"success": 0, "failed": 0, "pending": 1, "skipped": 0}
    first_saved = history_repo.save.await_args_list[0].args[0]
    second_saved = history_repo.save.await_args_list[1].args[0]
    assert first_saved.max_retries == 7
    assert second_saved.max_retries == 7


@pytest.mark.asyncio
async def test_dispatch_failure_disables_retry_when_capacity_full():
    sender = FakeSender(SendResult(ok=False, detail="forward failed"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.count_retryable_failures = AsyncMock(return_value=2)
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        basic_settings=SimpleNamespace(
            failed_queue_capacity=2,
            failed_queue_max_retries=7,
            deduplicate_multi_bot=True,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
    )

    assert stats == {"success": 0, "failed": 1, "pending": 0, "skipped": 0}
    second_saved = history_repo.save.await_args_list[1].args[0]
    assert second_saved.max_retries == 0


@pytest.mark.asyncio
async def test_dispatch_same_session_equivalent_payload_deduplicates_to_smallest_sub_id():
    sender = FakeSender()
    subs = [
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
    ]
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subs
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        basic_settings=SimpleNamespace(
            failed_queue_capacity=50,
            failed_queue_max_retries=3,
            deduplicate_multi_bot=True,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="same-content",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_urls=["https://example.com/a.jpg"],
    )

    assert stats == {"success": 1, "failed": 0, "pending": 0, "skipped": 1}
    assert len(sender.requests) == 1
    saved_histories = [call.args[0] for call in history_repo.save.await_args_list]
    skipped = [item for item in saved_histories if item.status == "skipped"]
    assert len(skipped) == 1
    assert skipped[0].sub_id == 2
    assert skipped[0].fail_reason == "multi-bot dedup: reused sub_id=1"


@pytest.mark.asyncio
async def test_dispatch_same_session_different_payload_does_not_deduplicate():
    sender = FakeSender()
    subs = [
        Subscription(
            id=1,
            user_id="user-1",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
            send_mode=0,
        ),
        Subscription(
            id=2,
            user_id="user-2",
            feed_id=10,
            platform_name="telegram",
            target_session="telegram:Group:1",
            send_mode=-1,
        ),
    ]
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = subs
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        basic_settings=SimpleNamespace(
            failed_queue_capacity=50,
            failed_queue_max_retries=3,
            deduplicate_multi_bot=True,
        ),
    )

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="same-content",
        entry_title="title",
        entry_link="https://example.com/entry",
    )

    assert stats == {"success": 2, "failed": 0, "pending": 0, "skipped": 0}
    assert len(sender.requests) == 2


@pytest.mark.asyncio
async def test_dispatch_pending_retries_marks_cancelled_history_failed():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=99,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    queue = SessionPushQueue()
    queue.enqueue = AsyncMock(
        return_value=PushJobResult(
            job_id="rss-000456",
            session_id="telegram:Group:1",
            ok=False,
            cancelled=True,
            error="job cancelled",
        )
    )

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        push_job_queue=queue,
    )

    stats = await dispatcher.dispatch_pending_retries(limit=10)

    assert stats == {"success": 1, "failed": 0, "skipped": 0}
    assert history.status == "stopped"
    assert history.max_retries == 0
    assert "Cancelled by System or Command" in (history.fail_reason or "")
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_dispatch_pending_retries_marks_successful_retry_success():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=100,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content\n媒体原始链接:\nhttps://example.com/video.mp4",
        media_urls=["https://example.com/video.mp4"],
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
        fail_reason="未知错误",
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 1, "failed": 0, "skipped": 0}
    assert history.status == "success"
    assert history.retry_count == 1
    assert history.fail_reason is None
    assert history.content == "retry content"
    assert len(sender.requests) == 1
    assert sender.requests[0][0].message == "retry content"
    assert sender.requests[0][0].media == [("video", "https://example.com/video.mp4")]
    history_repo.get_and_mark_retrying.assert_awaited_once_with(5)
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_retry_push_history_once_updates_same_record_on_failure():
    sender = FakeSender(SendResult(ok=False, transient=True, detail="upload failed"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=104,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="old content",
        media_urls=["https://example.com/image.jpg"],
        entry_title="title",
        entry_link="https://example.com/entry",
        status="success",
        retry_count=0,
        max_retries=3,
    ).mark_success()
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_by_id.return_value = history
    saved_snapshots = []

    async def save_history(value):
        saved_snapshots.append((value.id, value.status, value.content))
        return value

    history_repo.save.side_effect = save_history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    result = await dispatcher.retry_push_history_once(104)

    assert result["ok"] is False
    retry_history = result["history"]
    assert retry_history is history
    assert retry_history.id == 104
    assert retry_history.status == "failed"
    assert retry_history.retry_count == 0
    assert retry_history.max_retries == 0
    assert retry_history.fail_reason == "upload failed"
    assert retry_history.completed_at is not None
    assert "媒体原始链接:" in retry_history.content
    assert "https://example.com/image.jpg" in retry_history.content
    assert len(sender.requests) == 1
    assert sender.requests[0][0].message == "old content"
    assert sender.requests[0][0].media == [("image", "https://example.com/image.jpg")]
    history_repo.get_by_id.assert_awaited_once_with(104)
    assert history_repo.save.await_count == 2
    assert saved_snapshots[0] == (104, "retrying", "old content")
    assert saved_snapshots[1][0] == 104
    assert saved_snapshots[1][1] == "failed"


@pytest.mark.asyncio
async def test_retry_push_history_once_updates_same_record_on_success():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=105,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content\n媒体原始链接:\nhttps://example.com/video.mp4",
        media_urls=["https://example.com/video.mp4"],
        entry_title="title",
        entry_link="https://example.com/entry",
        status="failed",
        retry_count=3,
        max_retries=3,
        fail_reason="previous failure",
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_by_id.return_value = history
    saved_snapshots = []

    async def save_history(value):
        saved_snapshots.append((value.id, value.status, value.content))
        return value

    history_repo.save.side_effect = save_history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    result = await dispatcher.retry_push_history_once(105)

    assert result["ok"] is True
    retry_history = result["history"]
    assert retry_history is history
    assert retry_history.id == 105
    assert retry_history.status == "success"
    assert retry_history.retry_count == 0
    assert retry_history.max_retries == 0
    assert retry_history.fail_reason is None
    assert retry_history.content == "retry content"
    assert len(sender.requests) == 1
    assert sender.requests[0][0].message == "retry content"
    assert sender.requests[0][0].media == [("video", "https://example.com/video.mp4")]
    history_repo.get_by_id.assert_awaited_once_with(105)
    assert history_repo.save.await_count == 2
    assert saved_snapshots[0] == (105, "retrying", "retry content")
    assert saved_snapshots[1] == (105, "success", "retry content")


@pytest.mark.asyncio
async def test_dispatch_pending_retries_records_recoverable_failure():
    sender = FakeSender(SendResult(ok=False, transient=True, detail="timeout"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=101,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content",
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 0, "failed": 1, "skipped": 0}
    assert history.status == "failed"
    assert history.retry_count == 2
    assert history.max_retries == 3
    assert history.fail_reason == "timeout"
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_dispatch_pending_retries_stops_unrecoverable_failure():
    sender = FakeSender(SendResult(ok=False, detail="permission denied"))
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=102,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content",
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 0, "failed": 1, "skipped": 0}
    assert history.status == "failed"
    assert history.retry_count == 1
    assert history.max_retries == 0
    assert history.fail_reason == "permission denied"
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_dispatch_pending_retries_skips_disabled_subscription():
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        state=0,
        platform_name="telegram",
        target_session="telegram:Group:1",
    )
    history = PushHistory(
        id=103,
        sub_id=1,
        user_id="user-1",
        feed_id=10,
        content="retry content",
        entry_title="title",
        entry_link="https://example.com/entry",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = sub
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 0, "failed": 0, "skipped": 1}
    assert history.status == "failed"
    assert history.fail_reason == "Subscription not available"
    assert sender.requests == []
    history_repo.save.assert_awaited_once_with(history)


@pytest.mark.asyncio
async def test_dispatch_agent_entry_deduplicates_only_success_records():
    sender = FakeSender()
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = True
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    result = await dispatcher.dispatch_agent_entry(
        source_key="agent:test",
        target=SendTarget(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        content="content",
        raw_xml="<entry><p>Hello</p></entry>",
        entry_title="title",
        entry_guid="guid-1",
    )

    assert result["ok"] is True
    assert result["deduplicated"] is True
    history_repo.save.assert_not_awaited()
    assert sender.requests == []


@pytest.mark.asyncio
async def test_dispatch_agent_entry_persists_raw_xml_in_history():
    sender = FakeSender()
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history
    user_repo = AsyncMock()
    dispatcher = NotificationDispatcher(
        subscription_repo=AsyncMock(),
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
        user_repo=user_repo,
    )

    result = await dispatcher.dispatch_agent_entry(
        source_key="agent:test",
        target=SendTarget(
            user_id="user-1",
            platform_name="telegram",
            target_session="telegram:Group:1",
        ),
        content="content",
        raw_xml="<entry><p>Hello</p></entry>",
        entry_title="title",
        entry_guid="guid-raw",
    )

    assert result["ok"] is True
    user_repo.get_or_create.assert_awaited_once_with("user-1")
    first_saved = history_repo.save.await_args_list[0].args[0]
    assert first_saved.raw_xml == "<entry><p>Hello</p></entry>"


@pytest.mark.asyncio
async def test_dispatch_pending_retries_reuses_agent_history_without_subscription():
    sender = FakeSender()
    history = PushHistory(
        id=104,
        sub_id=None,
        user_id="user-1",
        feed_id=None,
        source_type="agent",
        source_key="agent:test",
        content="retry content\n媒体原始链接:\nhttps://example.com/video.mp4",
        media_urls=["https://example.com/video.mp4"],
        entry_title="title",
        entry_link="https://example.com/entry",
        platform_name="telegram",
        target_session="telegram:Group:1",
        status="retrying",
        retry_count=1,
        max_retries=3,
    )

    sub_repo = AsyncMock()
    history_repo = AsyncMock()
    history_repo.get_and_mark_retrying.return_value = [history]
    history_repo.save.side_effect = lambda value: value

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    stats = await dispatcher.dispatch_pending_retries(limit=5)

    assert stats == {"success": 1, "failed": 0, "skipped": 0}
    sub_repo.get_by_id.assert_not_awaited()
    assert history.status == "success"
    assert sender.requests[0][0].session_id == "telegram:Group:1"


@pytest.mark.asyncio
async def test_dispatch_auto_mode_prefers_telegraph_when_multiple_media(monkeypatch):
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        send_mode=0,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    called: dict[str, object] = {}

    async def fake_send(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs
        return {
            "ok": True,
            "used_telegraph": True,
            "fallback_native": False,
        }

    monkeypatch.setattr(dispatcher, "_send_to_session", fake_send, raising=False)

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_items=[
            ("image", "https://example.com/1.jpg"),
            ("video", "https://example.com/2.mp4"),
        ],
    )

    assert stats["success"] == 1
    assert called["kwargs"]["media_items"] == [
        ("image", "https://example.com/1.jpg"),
        ("video", "https://example.com/2.mp4"),
    ]
    assert called["kwargs"]["send_mode"] == 0


@pytest.mark.asyncio
async def test_dispatch_telegraph_failure_falls_back_to_native_send(monkeypatch):
    sender = FakeSender()
    sub = Subscription(
        id=1,
        user_id="user-1",
        feed_id=10,
        platform_name="telegram",
        target_session="telegram:Group:1",
        send_mode=0,
    )
    sub_repo = AsyncMock()
    sub_repo.get_active_by_feed_id.return_value = [sub]
    history_repo = AsyncMock()
    history_repo.exists_success_by_scope_and_guid.return_value = False
    history_repo.save.side_effect = lambda history: history

    dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        push_history_repo=history_repo,
        sender_provider=FakeSenderProvider(sender),
    )

    async def fake_send(*args, **kwargs):
        return {
            "ok": True,
            "used_telegraph": False,
            "telegraph_error": "create page failed",
            "fallback_native": True,
        }

    monkeypatch.setattr(dispatcher, "_send_to_session", fake_send, raising=False)

    stats = await dispatcher.dispatch_to_feed_subscribers(
        feed_id=10,
        content="content",
        entry_title="title",
        entry_link="https://example.com/entry",
        media_items=[
            ("image", "https://example.com/1.jpg"),
            ("image", "https://example.com/2.jpg"),
        ],
    )

    assert stats["success"] == 1
