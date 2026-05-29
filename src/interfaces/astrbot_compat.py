"""AstrBot 入口兼容工具。"""

from __future__ import annotations

try:
    from astrbot.core.star.filter.command import GreedyStr
except Exception:  # pragma: no cover - 旧测试桩或旧 AstrBot 环境
    GreedyStr = str  # type: ignore[misc, assignment]


def event_message_type_or_noop(filter_module):
    """返回 event_message_type 装饰器；不可用时返回 no-op 装饰器。"""
    decorator = getattr(filter_module, "event_message_type", None)
    if callable(decorator):
        return decorator

    def _noop_event_message_type(*_args, **_kwargs):
        return lambda fn: fn

    return _noop_event_message_type


def event_message_type_all_or_none(filter_module):
    event_message_type = getattr(filter_module, "EventMessageType", None)
    return getattr(event_message_type, "ALL", None)


def all_message_event_filter(filter_module):
    """兼容注册全部消息事件的装饰器。"""
    return event_message_type_or_noop(filter_module)(
        event_message_type_all_or_none(filter_module)
    )
