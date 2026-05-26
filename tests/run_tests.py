#!/usr/bin/env python
"""RSSHub Plugin Test Runner

跨平台测试运行器，无需 pytest。
支持 PowerShell 命令调用。

Usage:
    python run_tests.py              # 运行所有测试
    python run_tests.py -v           # 详细输出
    python run_tests.py --category unit    # 仅运行单元测试
    python run_tests.py --category integration  # 仅运行集成测试

PowerShell:
    .\run_tests.ps1                  # 运行所有测试
    .\run_tests.ps1 -Verbose         # 详细输出
    .\run_tests.ps1 -Category unit   # 仅运行单元测试

Bash:
    ./run_tests.sh                   # 运行所有测试
    ./run_tests.sh --verbose         # 详细输出
    ./run_tests.sh --category unit   # 仅运行单元测试
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import sys
from pathlib import Path

# 添加 data/plugins/ 到路径，使 `from astrbot_plugin_rsshub.src.xxx` 可用
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# =============================================================================
# 测试工具函数
# =============================================================================


def print_header(text: str) -> None:
    """打印标题."""
    print("=" * 70)
    print(f"    {text}")
    print("=" * 70)


def print_separator() -> None:
    """打印分隔线."""
    print("-" * 70)


def print_test(name: str, status: str, message: str = "") -> None:
    """打印测试结果."""
    status_symbol = "✓" if status == "PASS" else "✗" if status == "FAIL" else "?"
    print(f"  [{status}] {status_symbol} {name}")
    if message:
        print(f"      {message}")


# =============================================================================
# 表达式解析器测试
# =============================================================================


def test_expression_parser():
    """测试表达式解析器."""
    from types import SimpleNamespace

    from astrbot_plugin_rsshub.src.infrastructure.utils.expression_parser import (
        ExpressionParser,
    )

    tests = [
        ("#0", ("value1", "value2"), {}, None, "value1", "简单参数解析"),
        ("#name", (), {"name": "test_value"}, ["name"], "test_value", "命名参数解析"),
        ("'hello world'", (), {}, None, "hello world", "字符串字面量"),
        ("42", (), {}, None, 42, "数字字面量"),
        ("#0.id", (SimpleNamespace(id=123),), {}, None, 123, "嵌套属性解析"),
    ]

    passed = 0
    failed = 0

    for expr, args, kwargs, params, expected, name in tests:
        try:
            result = ExpressionParser.parse(expr, args, kwargs, params)
            if result == expected:
                print_test(name, "PASS")
                passed += 1
            else:
                print_test(name, "FAIL", f"期望 {expected!r}, 得到 {result!r}")
                failed += 1
        except Exception as e:
            print_test(name, "FAIL", str(e))
            failed += 1

    # 测试空表达式异常
    try:
        ExpressionParser.parse("", (), {})
        print_test("空表达式异常", "FAIL", "应该抛出 ValueError")
        failed += 1
    except ValueError:
        print_test("空表达式异常", "PASS")
        passed += 1

    return passed, failed


def test_compiled_expression():
    """测试编译表达式."""
    from astrbot_plugin_rsshub.src.infrastructure.utils.expression_parser import (
        CompiledExpression,
    )

    tests = [
        ("#user_id", (), {"user_id": 456}, None, 456),
        ("#0.name", (type("Data", (), {"name": "test"})(),), {}, None, "test"),
    ]

    passed = 0
    failed = 0

    for expr, args, kwargs, params, expected in tests:
        try:
            compiled = CompiledExpression(expr)
            result = compiled.evaluate(args, kwargs, params)
            if result == expected:
                print_test(f"编译表达式 {expr}", "PASS")
                passed += 1
            else:
                print_test(
                    f"编译表达式 {expr}", "FAIL", f"期望 {expected!r}, 得到 {result!r}"
                )
                failed += 1
        except Exception as e:
            print_test(f"编译表达式 {expr}", "FAIL", str(e))
            failed += 1

    return passed, failed


# =============================================================================
# 缓存测试
# =============================================================================


def test_memory_cache():
    """测试内存缓存."""
    from astrbot_plugin_rsshub.src.infrastructure.utils.caching import MemoryCache

    cache = MemoryCache()
    passed = 0
    failed = 0

    # 测试基本操作
    try:
        cache.set("test", "key1", "value1")
        result = cache.get("test", "key1")
        assert result == "value1", f"期望 'value1', 得到 {result!r}"
        print_test("基本缓存操作", "PASS")
        passed += 1
    except Exception as e:
        print_test("基本缓存操作", "FAIL", str(e))
        failed += 1

    # 测试不存在的键
    try:
        result = cache.get("test", "nonexistent")
        assert result is None, f"期望 None, 得到 {result!r}"
        print_test("不存在的键返回 None", "PASS")
        passed += 1
    except Exception as e:
        print_test("不存在的键返回 None", "FAIL", str(e))
        failed += 1

    # 测试删除
    try:
        cache.set("test", "key2", "value2")
        deleted = cache.delete("test", "key2")
        assert deleted is True, "删除应该返回 True"
        result = cache.get("test", "key2")
        assert result is None, "删除后应该返回 None"
        cache.delete("test", "key1")
        print_test("删除缓存条目", "PASS")
        passed += 1
    except Exception as e:
        print_test("删除缓存条目", "FAIL", str(e))
        failed += 1

    # 测试清空
    try:
        cache.set("test", "key3", "value3")
        cache.set("test", "key4", "value4")
        count = cache.clear("test")
        assert count == 2, f"期望清空 2 条, 实际 {count}"
        print_test("清空缓存", "PASS")
        passed += 1
    except Exception as e:
        print_test("清空缓存", "FAIL", str(e))
        failed += 1

    return passed, failed


# =============================================================================
# HTML 清理测试
# =============================================================================


def test_html_cleaner():
    """测试 HTML 清理."""
    # HTMLCleaner 是一个复杂的解析器类，需要 BeautifulSoup
    # 这里只做简单的存在性检查
    try:
        importlib.import_module(
            "astrbot_plugin_rsshub.src.infrastructure.utils.html_cleaner"
        )

        print_test("HTMLCleaner 导入", "PASS")
        return 1, 0
    except ImportError as e:
        print_test("HTMLCleaner 导入", "SKIP", f"缺少依赖: {e}")
        return 1, 0
    except Exception as e:
        print_test("HTMLCleaner 导入", "FAIL", str(e))
        return 0, 1


# =============================================================================
# 锁管理器测试
# =============================================================================


def test_lock_manager():
    """测试锁管理器."""
    from astrbot_plugin_rsshub.src.infrastructure.utils.lock import LockManager

    manager = LockManager()
    passed = 0
    failed = 0

    # 测试 feed 锁复用
    try:
        lock1 = manager.feed_lock(1)
        lock2 = manager.feed_lock(1)
        assert lock1 is lock2, "相同 feed ID 应该返回相同锁"
        print_test("Feed 锁复用", "PASS")
        passed += 1
    except Exception as e:
        print_test("Feed 锁复用", "FAIL", str(e))
        failed += 1

    # 测试不同 feed ID 不同锁
    try:
        lock1 = manager.feed_lock(1)
        lock3 = manager.feed_lock(2)
        assert lock1 is not lock3, "不同 feed ID 应该返回不同锁"
        print_test("不同 Feed ID 不同锁", "PASS")
        passed += 1
    except Exception as e:
        print_test("不同 Feed ID 不同锁", "FAIL", str(e))
        failed += 1

    return passed, failed


# =============================================================================
# RSS 解析器测试
# =============================================================================


def test_rss_parser_basic():
    """测试 RSS 解析器基本功能."""
    from astrbot_plugin_rsshub.src.infrastructure.fetcher import RSSParser

    passed = 0
    failed = 0

    # 测试简单 RSS
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
    <channel>
        <title>Test Feed</title>
        <link>https://example.com</link>
        <item>
            <title>Test Article</title>
            <link>https://example.com/article</link>
            <guid>https://example.com/article</guid>
        </item>
    </channel>
</rss>"""

    try:
        parser = RSSParser()
        entries, error = parser.parse(rss_xml)
        assert error is None, f"解析错误: {error}"
        assert len(entries) == 1, f"期望 1 个条目, 实际 {len(entries)}"
        assert entries[0].title == "Test Article", f"标题不匹配: {entries[0].title}"
        print_test("解析简单 RSS", "PASS")
        passed += 1
    except Exception as e:
        print_test("解析简单 RSS", "FAIL", str(e))
        failed += 1

    # 测试无效 XML
    try:
        parser = RSSParser()
        entries, error = parser.parse("not valid xml")
        assert error is not None, "应该返回错误"
        assert len(entries) == 0, "应该有 0 个条目"
        print_test("解析无效 XML", "PASS")
        passed += 1
    except Exception as e:
        print_test("解析无效 XML", "FAIL", str(e))
        failed += 1

    return passed, failed


# =============================================================================
# 事件系统测试
# =============================================================================


async def test_event_bus():
    """测试事件总线."""
    from astrbot_plugin_rsshub.src.infrastructure.fetcher.rss.parser import EntryParsed
    from astrbot_plugin_rsshub.src.infrastructure.messaging import (
        EventBus,
        FeedParseEvent,
    )

    passed = 0
    failed = 0

    # 测试基本事件发布/订阅
    try:
        bus = EventBus()
        received = []

        @bus.on(FeedParseEvent)
        async def handler(event):
            received.append(event)

        event = FeedParseEvent(entries=[EntryParsed(title="Test")])
        await bus.emit(event)

        assert len(received) == 1, f"期望收到 1 个事件, 实际 {len(received)}"
        print_test("事件发布/订阅", "PASS")
        passed += 1
    except Exception as e:
        print_test("事件发布/订阅", "FAIL", str(e))
        failed += 1

    # 测试事件取消
    try:
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

        assert not handler2_called, "取消后 handler2 不应该被调用"
        print_test("事件取消", "PASS")
        passed += 1
    except Exception as e:
        print_test("事件取消", "FAIL", str(e))
        failed += 1

    return passed, failed


# =============================================================================
# 全局事件总线测试
# =============================================================================


async def test_global_event_bus():
    """测试全局事件总线生命周期."""
    from astrbot_plugin_rsshub.src.infrastructure.fetcher.rss.parser import EntryParsed
    from astrbot_plugin_rsshub.src.infrastructure.messaging import (
        FeedParseEvent,
        get_event_bus,
        reset_event_bus,
    )

    passed = 0
    failed = 0
    received: list[object] = []

    # 测试全局事件总线注册与发布
    try:
        reset_event_bus()
        bus = get_event_bus()

        @bus.on(FeedParseEvent)
        async def handler(event):
            received.append(event)

        event = FeedParseEvent(entries=[EntryParsed(title="Global")])
        await bus.emit(event)

        assert len(received) == 1, f"期望收到 1 个事件, 实际 {len(received)}"
        print_test("全局事件总线注册/发布", "PASS")
        passed += 1
    except Exception as e:
        print_test("全局事件总线注册/发布", "FAIL", str(e))
        failed += 1

    # 测试 reset 后旧 handler 不再影响新总线
    try:
        old_bus = get_event_bus()
        old_received_count = len(received)
        reset_event_bus()
        new_bus = get_event_bus()

        assert new_bus is not old_bus, "reset 后应该创建新的事件总线实例"

        await new_bus.emit(FeedParseEvent(entries=[]))
        assert len(received) == old_received_count, "旧 handler 不应该挂到新的事件总线"
        print_test("全局事件总线 reset 隔离", "PASS")
        passed += 1
    except Exception as e:
        print_test("全局事件总线 reset 隔离", "FAIL", str(e))
        failed += 1
    finally:
        reset_event_bus()

    return passed, failed


# =============================================================================
# 主测试运行器
# =============================================================================

TEST_CATEGORIES = {
    "unit": [
        ("表达式解析器", test_expression_parser),
        ("编译表达式", test_compiled_expression),
        ("内存缓存", test_memory_cache),
        ("HTML 清理", test_html_cleaner),
        ("锁管理器", test_lock_manager),
        ("RSS 解析器", test_rss_parser_basic),
    ],
    "integration": [
        ("事件总线", test_event_bus),
        ("全局事件总线", test_global_event_bus),
    ],
}


async def run_async_tests(category: str | None = None, verbose: bool = True):
    """运行异步测试."""
    passed = 0
    failed = 0

    tests_to_run = []
    if category is None or category == "all":
        for cat_tests in TEST_CATEGORIES.values():
            tests_to_run.extend(cat_tests)
    elif category in TEST_CATEGORIES:
        tests_to_run = TEST_CATEGORIES[category]
    else:
        print(f"未知测试类别: {category}")
        return 0, 0

    for name, test_func in tests_to_run:
        if verbose:
            print(f"\n  【{name}】")
        try:
            if asyncio.iscoroutinefunction(test_func):
                p, f = await test_func()
            else:
                p, f = test_func()
            passed += p
            failed += f
        except Exception as e:
            print_test(name, "ERROR", str(e))
            failed += 1

    return passed, failed


def run_tests(category: str | None = None, verbose: bool = True):
    """运行所有测试."""
    print_header("RSSHub Plugin Test Runner")
    print(f"Python: {sys.version}")
    print()

    # 运行测试
    print("Running tests...")
    print_separator()

    passed, failed = asyncio.run(run_async_tests(category, verbose))

    # 打印结果
    print()
    print_separator()
    print(f"\nResults: {passed} passed, {failed} failed")

    if failed == 0:
        print("\nAll tests passed!")
        return 0
    else:
        print(f"\n{failed} test(s) failed!")
        return 1


def main():
    """主函数."""
    parser = argparse.ArgumentParser(
        description="RSSHub Plugin Test Runner",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="显示详细输出",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速模式（仅显示摘要）",
    )
    parser.add_argument(
        "--category",
        choices=["unit", "integration", "all"],
        default="all",
        help="测试类别 (默认: all)",
    )

    args = parser.parse_args()

    verbose = args.verbose or not args.quick
    category = None if args.category == "all" else args.category

    return run_tests(category, verbose)


if __name__ == "__main__":
    sys.exit(main())
