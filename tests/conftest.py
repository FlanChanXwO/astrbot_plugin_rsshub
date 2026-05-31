"""Pytest configuration and shared fixtures for astrbot_plugin_rsshub tests."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# 注册当前插件的 src/ 为 astrbot_plugin_rsshub 包
# 注意：不能把 PLUGINS_DIR 加入 sys.path，否则 Python 会发现
# 多个同名目录（base + 各 feature 分支），作为 namespace package
# 合并后可能解析到非当前分支的源码。
PLUGIN_DIR = Path(__file__).parent.parent
_src_dir = PLUGIN_DIR / "src"

_pkg_spec = importlib.util.spec_from_file_location(
    "astrbot_plugin_rsshub",
    str(_src_dir / "__init__.py"),
    submodule_search_locations=[str(_src_dir)],
)
_pkg = importlib.util.module_from_spec(_pkg_spec)
sys.modules["astrbot_plugin_rsshub"] = _pkg
_pkg_spec.loader.exec_module(_pkg)

# astrbot_plugin_rsshub.src 也需预注册，否则嵌套导入失败
_src_spec = importlib.util.spec_from_file_location(
    "astrbot_plugin_rsshub.src",
    str(_src_dir / "__init__.py"),
    submodule_search_locations=[str(_src_dir)],
)
_src_mod = importlib.util.module_from_spec(_src_spec)
sys.modules["astrbot_plugin_rsshub.src"] = _src_mod
_src_spec.loader.exec_module(_src_mod)
# 将 .src 子包链接为顶层包的属性，使 monkeypatch 路径遍历正常工作
_pkg.src = _src_mod

# 注册 bootstrap 模块（位于插件根目录，不属于 src/ 子包）
_bootstrap_path = PLUGIN_DIR / "bootstrap.py"
_bootstrap_spec = importlib.util.spec_from_file_location(
    "astrbot_plugin_rsshub.bootstrap",
    str(_bootstrap_path),
)
_bootstrap_mod = importlib.util.module_from_spec(_bootstrap_spec)
sys.modules["astrbot_plugin_rsshub.bootstrap"] = _bootstrap_mod
_bootstrap_spec.loader.exec_module(_bootstrap_mod)
_pkg.bootstrap = _bootstrap_mod

# 模拟 AstrBot 相关导入
sys.modules["astrbot"] = MagicMock()
sys.modules["astrbot.api"] = MagicMock()
sys.modules["astrbot.api.event"] = MagicMock()
sys.modules["astrbot.api.provider"] = MagicMock()
sys.modules["astrbot.api.star"] = MagicMock()
message_components = MagicMock()
for component_name in (
    "File",
    "Image",
    "Node",
    "Nodes",
    "Plain",
    "Record",
    "Video",
):
    setattr(message_components, component_name, MagicMock(name=component_name))
sys.modules["astrbot.api.message_components"] = message_components
sys.modules["astrbot.core"] = MagicMock()
sys.modules["astrbot.core.message"] = MagicMock()
sys.modules["astrbot.core.message.message_event_result"] = MagicMock()
sys.modules["astrbot.core.star.star_tools"] = MagicMock()
sys.modules["astrbot.core.star"] = MagicMock()
sys.modules["astrbot.core.star.filter"] = MagicMock()
sys.modules["astrbot.core.utils"] = MagicMock()
sys.modules["astrbot.core.utils.astrbot_path"] = MagicMock()
sys.modules["astrbot.core.utils.http_ssl"] = MagicMock()
sys.modules[
    "astrbot.core.utils.astrbot_path"
].get_astrbot_plugin_data_path.return_value = str(PLUGIN_DIR / "data" / "plugin_data")


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def fixtures_dir() -> Path:
    """返回 fixtures 目录路径."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_rss_feed(fixtures_dir: Path) -> str:
    """返回简单 RSS feed XML 内容."""
    return (fixtures_dir / "feeds" / "simple_rss.xml").read_text(encoding="utf-8")


@pytest.fixture
def sample_atom_feed(fixtures_dir: Path) -> str:
    """返回 Atom feed XML 内容."""
    return (fixtures_dir / "feeds" / "atom_feed.xml").read_text(encoding="utf-8")


@pytest.fixture
def sample_media_feed(fixtures_dir: Path) -> str:
    """返回带媒体附件的 RSS feed XML 内容."""
    return (fixtures_dir / "feeds" / "rss_with_media.xml").read_text(encoding="utf-8")


@pytest.fixture
def sample_duplicate_feed(fixtures_dir: Path) -> str:
    """返回带重复条目的 RSS feed XML 内容."""
    return (fixtures_dir / "feeds" / "rss_with_duplicate.xml").read_text(
        encoding="utf-8"
    )


@pytest.fixture
def sample_entries():
    """提供示例条目列表."""
    from astrbot_plugin_rsshub.src.infrastructure.fetcher import EntryParsed

    return [
        EntryParsed(
            title="Test Entry 1",
            link="https://example.com/entry1",
            summary="Summary 1",
            content="Content 1",
            author="Author 1",
            enclosures=[],
            published=datetime.now(timezone.utc),
            tags=["tag1"],
        ),
        EntryParsed(
            title="Test Entry 2",
            link="https://example.com/entry2",
            summary="Summary 2",
            content="Content 2",
            author="Author 2",
            enclosures=[],
            published=datetime.now(timezone.utc),
            tags=["tag2"],
        ),
    ]


@pytest.fixture
def mock_feed_entity():
    """提供模拟 Feed 实体."""
    from astrbot_plugin_rsshub.src.domain.entities.feed import Feed

    return Feed(
        id=1,
        url="https://example.com/rss.xml",
        title="Test Feed",
        description="Test feed description",
    )


@pytest.fixture
def mock_subscription_entity():
    """提供模拟 Subscription 实体."""
    from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription

    return Subscription(
        id=1,
        feed_id=1,
        user_id="user123",
        platform="telegram",
        interval=5,
        notify=True,
    )


@pytest.fixture
def mock_feed_entry() -> dict:
    """返回模拟的 feed entry 数据."""
    return {
        "id": "test-entry-001",
        "title": "Test Entry",
        "link": "https://example.com/test",
        "summary": "Test summary",
        "published": "2024-01-01T00:00:00+00:00",
        "author": "Test Author",
    }


@pytest.fixture
def mock_subscription() -> dict:
    """返回模拟的订阅数据."""
    return {
        "id": 1,
        "user_id": "test_user_123",
        "feed_id": 1,
        "target_session": "test:Group:12345",
        "interval": 10,
        "notify": True,
        "send_mode": 0,
        "length_limit": 0,
        "display_author": 0,
        "display_via": 0,
        "display_title": 0,
        "display_entry_tags": False,
        "style": 0,
        "display_media": True,
        "tags": "",
        "title": "Test Subscription",
    }


@pytest.fixture
def temp_db_path():
    """创建临时数据库路径."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.fixture
def temp_data_dir():
    """提供临时数据目录."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class AsyncContextManagerMock:
    """异步上下文管理器 mock."""

    def __init__(self, return_value: Any = None):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def async_context_mock():
    """提供 AsyncContextManagerMock 工厂."""
    return AsyncContextManagerMock
