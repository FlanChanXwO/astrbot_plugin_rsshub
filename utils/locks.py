"""RSS-to-AstrBot Locks

并发锁管理模块，提供通用锁装饰器支持。

使用示例:
    >>> from .locks import locked

    >>> @locked("#feed.id")
    ... async def process_feed(self, feed: Feed):
    ...     # 自动在 feed.id 上加锁
    ...     pass

    >>> @locked("#user_id")
    ... async def handle_user(self, event, user_id: str):
    ...     # 自动在 user_id 上加锁
    ...     pass

    >>> @locked("#url")
    ... async def fetch_rss(self, url: str):
    ...     # 自动在 url 主机名上加信号量
    ...     pass

    >>> @locked("'global_web'")
    ... async def network_request(self):
    ...     # 使用全局网络信号量
    ...     pass
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections import defaultdict
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urlparse

from .el_parse import ExpressionParser

F = TypeVar("F", bound=Callable[..., Any])


class LockManager:
    """锁管理器 - 管理各种类型的锁，避免并发冲突"""

    def __init__(self):
        # Feed 更新锁（防止同一 Feed 被同时更新）
        self._feed_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

        # 用户操作锁（防止用户同时执行多个命令）
        self._user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        # 主机名锁（限制对同一主机的并发请求）
        self._hostname_locks: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(3)
        )

        # 全局网络锁（限制总并发数）
        self._global_web_lock = asyncio.Semaphore(20)

        # 数据库写锁
        self._db_write_lock = asyncio.Lock()

        # 自定义锁（用于固定名称的锁）
        self._custom_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def feed_lock(self, feed_id: int) -> asyncio.Lock:
        """获取 Feed 更新锁"""
        return self._feed_locks[feed_id]

    def user_lock(self, user_id: str) -> asyncio.Lock:
        """获取用户操作锁"""
        return self._user_locks[user_id]

    def hostname_semaphore(
        self, hostname: str, parse: bool = True
    ) -> asyncio.Semaphore:
        """获取主机名信号量

        Args:
            hostname: 主机名或完整URL
            parse: 是否需要解析URL
        """
        if parse and hostname.startswith("http"):
            hostname = urlparse(hostname).hostname or hostname
        return self._hostname_locks[hostname]

    @property
    def global_web_semaphore(self) -> asyncio.Semaphore:
        """获取全局网络信号量"""
        return self._global_web_lock

    @property
    def db_write_lock(self) -> asyncio.Lock:
        """获取数据库写锁"""
        return self._db_write_lock

    def custom_lock(self, name: str) -> asyncio.Lock:
        """获取自定义锁"""
        return self._custom_locks[name]


def _get_lock_manager() -> LockManager:
    """获取全局锁管理器单例"""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager()
    return _lock_manager


_lock_manager: LockManager | None = None


def _infer_lock_type(expr: str) -> tuple[str, Callable[[Any], Any]]:
    """从表达式推断锁类型

    Returns:
        (lock_type, key_transform): 锁类型和键转换函数

    Raises:
        ValueError: 无法推断锁类型
    """
    expr = expr.strip()

    # 1. 字面量 - 自定义锁或特殊全局锁
    if expr.startswith("'") and expr.endswith("'"):
        lock_name = expr[1:-1]
        if lock_name == "global_web":
            return "global_web", lambda x: x
        elif lock_name == "db_write":
            return "db_write", lambda x: x
        else:
            # 自定义锁
            return "custom", lambda x: lock_name

    # 2. 引用表达式 - 根据参数名推断
    if expr.startswith("#"):
        # 检查是否为 .id 结尾 - feed 锁
        if ".id" in expr.lower():
            return "feed", lambda x: int(x) if isinstance(x, (int, str)) else x

        # 检查是否含 user - user 锁
        if "user" in expr.lower():
            return "user", lambda x: str(x)

        # 检查是否含 url/hostname/host - hostname 锁
        if any(kw in expr.lower() for kw in ["url", "hostname", "host"]):
            return "hostname", lambda x: x

    # 无法推断
    raise ValueError(
        f"Cannot infer lock type from expression: {expr}. "
        f"Supported patterns: "
        f"'#*.id' (feed lock), "
        f"'#*user*' (user lock), "
        f"'#*url*' / '#*hostname*' / '#*host*' (hostname semaphore), "
        f"'global_web' (global web semaphore), "
        f"'db_write' (db write lock), "
        f"'custom_name' (custom lock)"
    )


def locked(key: str) -> Callable[[F], F]:
    """通用锁装饰器

    根据 key 表达式自动推断锁类型并加锁。

    Args:
        key: SpEL 表达式，用于提取锁键值

    Returns:
        装饰器函数

    Raises:
        ValueError: 无法从 key 推断锁类型

    Examples:
        >>> @locked("#feed.id")
        ... async def process_feed(self, feed: Feed):
        ...     pass  # 自动在 feed.id 上加 asyncio.Lock

        >>> @locked("#user_id")
        ... async def handle_user(self, event, user_id: str):
        ...     pass  # 自动在 user_id 上加 asyncio.Lock

        >>> @locked("#url")
        ... async def fetch_rss(self, url: str):
        ...     pass  # 自动在 url 主机名上加 asyncio.Semaphore(3)

        >>> @locked("'global_web'")
        ... async def network_request(self):
        ...     pass  # 使用全局 asyncio.Semaphore(20)
    """
    lock_type, key_transform = _infer_lock_type(key)
    manager = _get_lock_manager()

    def decorator(func: F) -> F:
        # 获取函数签名中的参数名列表
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 解析表达式获取锁键值（传递参数名列表用于位置参数映射）
            raw_value = ExpressionParser.parse(key, args, kwargs, param_names)
            lock_key = key_transform(raw_value)

            # 获取对应的锁对象
            if lock_type == "feed":
                lock_obj = manager.feed_lock(lock_key)
            elif lock_type == "user":
                lock_obj = manager.user_lock(lock_key)
            elif lock_type == "hostname":
                # hostname 锁支持 URL 自动解析
                lock_obj = manager.hostname_semaphore(str(lock_key), parse=True)
            elif lock_type == "global_web":
                lock_obj = manager.global_web_semaphore
            elif lock_type == "db_write":
                lock_obj = manager.db_write_lock
            elif lock_type == "custom":
                lock_obj = manager.custom_lock(lock_key)
            else:
                raise ValueError(f"Unknown lock type: {lock_type}")

            # 加锁执行
            async with lock_obj:
                return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


# 向后兼容 - 保留原有的便捷访问函数


def feed_lock(feed_id: int) -> asyncio.Lock:
    """获取 Feed 更新锁（向后兼容）"""
    return _get_lock_manager().feed_lock(feed_id)


def user_lock(user_id: str) -> asyncio.Lock:
    """获取用户操作锁（向后兼容）"""
    return _get_lock_manager().user_lock(user_id)


def hostname_semaphore(hostname: str, parse: bool = True) -> asyncio.Semaphore:
    """获取主机名信号量（向后兼容）"""
    return _get_lock_manager().hostname_semaphore(hostname, parse)


def global_web_semaphore() -> asyncio.Semaphore:
    """获取全局网络信号量（向后兼容）"""
    return _get_lock_manager().global_web_semaphore


def db_write_lock() -> asyncio.Lock:
    """获取数据库写锁（向后兼容）"""
    return _get_lock_manager().db_write_lock
