"""测试事件系统和扩展系统"""

from __future__ import annotations

import pytest


class TestEventBus:
    """测试事件总线"""

    @pytest.mark.asyncio
    async def test_basic_publish_subscribe(self):
        """测试基本事件发布/订阅"""
        from astrbot_plugin_rsshub.src.infrastructure.fetcher.rss.parser import (
            EntryParsed,
        )
        from astrbot_plugin_rsshub.src.infrastructure.messaging import (
            EventBus,
            FeedParseEvent,
        )

        bus = EventBus()
        received = []

        @bus.on(FeedParseEvent)
        async def handler(event):
            received.append(event)

        event = FeedParseEvent(entries=[EntryParsed(title="Test")])
        await bus.emit(event)

        assert len(received) == 1
        assert received[0].entries[0].title == "Test"

    @pytest.mark.asyncio
    async def test_event_cancellation(self):
        """测试事件取消"""
        from astrbot_plugin_rsshub.src.infrastructure.messaging import (
            EventBus,
            FeedParseEvent,
        )

        bus = EventBus()
        handler2_called = False

        @bus.on(FeedParseEvent)
        async def handler1(event):
            event.cancel()

        @bus.on(FeedParseEvent)
        async def handler2(event):
            nonlocal handler2_called
            handler2_called = True

        event = FeedParseEvent(entries=[])
        await bus.emit(event)

        assert not handler2_called

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        """测试多个处理器"""
        from astrbot_plugin_rsshub.src.infrastructure.messaging import (
            EventBus,
            FeedParseEvent,
        )

        bus = EventBus()
        calls = []

        @bus.on(FeedParseEvent)
        async def handler1(event):
            calls.append(1)

        @bus.on(FeedParseEvent)
        async def handler2(event):
            calls.append(2)

        @bus.on(FeedParseEvent)
        async def handler3(event):
            calls.append(3)

        event = FeedParseEvent(entries=[])
        await bus.emit(event)

        assert calls == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_handler_off(self):
        """测试取消订阅"""
        from astrbot_plugin_rsshub.src.infrastructure.messaging import (
            EventBus,
            FeedParseEvent,
        )

        bus = EventBus()
        calls = []

        @bus.on(FeedParseEvent)
        async def handler(event):
            calls.append(1)

        event = FeedParseEvent(entries=[])
        await bus.emit(event)
        assert calls == [1]

        bus.off(FeedParseEvent, handler)
        await bus.emit(event)
        assert calls == [1]  # 不应该再增加

    @pytest.mark.asyncio
    async def test_event_metadata(self):
        """测试事件元数据"""
        from astrbot_plugin_rsshub.src.infrastructure.messaging import FeedParseEvent

        event = FeedParseEvent(entries=[])
        event.set_metadata("key", "value")

        assert event.get_metadata("key") == "value"
        assert event.get_metadata("nonexistent", "default") == "default"
