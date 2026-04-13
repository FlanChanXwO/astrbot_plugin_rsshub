"""
RSS-to-AstrBot Locks
并发锁管理模块
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from urllib.parse import urlparse


class LockManager:
    """
    锁管理器

    管理各种类型的锁，避免并发冲突
    """

    def __init__(self):
        # 主机名锁（限制对同一主机的并发请求）
        self._hostname_locks: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(3)  # 每个主机最多3个并发
        )

        # 全局网络锁（限制总并发数）
        self._global_web_lock = asyncio.Semaphore(20)

        # 数据库写锁
        self._db_write_lock = asyncio.Lock()

        # 用户操作锁（防止用户同时执行多个命令）
        self._user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        # Feed 更新锁（防止同一 Feed 被同时更新）
        self._feed_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def hostname_semaphore(
        self, hostname: str, parse: bool = True
    ) -> asyncio.Semaphore:
        """
        获取主机名信号量

        Args:
            hostname: 主机名或完整URL
            parse: 是否需要解析URL

        Returns:
            信号量
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

    def user_lock(self, user_id: str) -> asyncio.Lock:
        """
        获取用户操作锁

        Args:
            user_id: 用户ID

        Returns:
            锁
        """
        return self._user_locks[user_id]

    def feed_lock(self, feed_id: int) -> asyncio.Lock:
        """
        获取 Feed 更新锁

        Args:
            feed_id: Feed ID

        Returns:
            锁
        """
        return self._feed_locks[feed_id]

    async def with_hostname_lock(self, hostname: str, coro):
        """
        使用主机名锁执行协程

        Args:
            hostname: 主机名
            coro: 协程

        Returns:
            协程结果
        """
        sem = self.hostname_semaphore(hostname)
        async with sem:
            return await coro

    async def with_user_lock(self, user_id: str, coro):
        """
        使用用户锁执行协程

        Args:
            user_id: 用户ID
            coro: 协程

        Returns:
            协程结果
        """
        async with self.user_lock(user_id):
            return await coro


# 全局锁管理器实例
_lock_manager: LockManager | None = None


def get_lock_manager() -> LockManager:
    """获取全局锁管理器"""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager()
    return _lock_manager


# 便捷访问
def hostname_semaphore(hostname: str, parse: bool = True) -> asyncio.Semaphore:
    """获取主机名信号量"""
    return get_lock_manager().hostname_semaphore(hostname, parse)


def global_web_semaphore() -> asyncio.Semaphore:
    """获取全局网络信号量"""
    return get_lock_manager().global_web_semaphore


def user_lock(user_id: str) -> asyncio.Lock:
    """获取用户锁"""
    return get_lock_manager().user_lock(user_id)


def feed_lock(feed_id: int) -> asyncio.Lock:
    """获取Feed锁"""
    return get_lock_manager().feed_lock(feed_id)
