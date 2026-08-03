"""缓存工具模块

提供基于内存和磁盘的缓存装饰器，支持 TTL 过期和条件缓存。

功能:
    - caching: 缓存方法返回值（类似 Spring @Cacheable）
    - cacheput: 强制更新缓存（类似 Spring @CachePut）
    - cacheevict: 清除缓存条目（类似 Spring @CacheEvict）

提供方类型:
    - CacheProviderType.MEMORY: 纯内存缓存（默认）
    - CacheProviderType.DISK: 磁盘持久化缓存
    - CacheProviderType.HYBRID: 内存 + 磁盘混合缓存

Examples:
    >>> @caching("feed_meta", key="#feed_id", ttl=300)
    ... async def fetch_feed_meta(self, feed_id: int) -> dict:
    ...     return await expensive_query(feed_id)

    >>> @caching("media", key="#url", ttl=900, provider=CacheProviderType.DISK)
    ... async def download_media(self, url: str) -> Path:
    ...     return await download(url)
"""

from __future__ import annotations

import abc
import asyncio
import functools
import hashlib
import inspect
import json
import pickle
import time
from collections import defaultdict
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from .expression_parser import CompiledExpression, ExpressionParser
from .paths import get_plugin_cache_dir

F = TypeVar("F", bound=Callable[..., Any])


class CacheProviderType(Enum):
    """缓存提供方类型"""

    MEMORY = "memory"  # 纯内存缓存
    DISK = "disk"  # 磁盘持久化缓存
    HYBRID = "hybrid"  # 内存 + 磁盘混合缓存


class BaseCache(abc.ABC):
    """缓存管理器抽象基类

    定义统一的缓存接口。

    所有方法均为线程/协程安全，由具体实现保证。
    """

    @abc.abstractmethod
    def get(self, cache_name: str, key: str) -> Any:
        """获取缓存值

        Args:
            cache_name: 缓存区域名称
            key: 缓存键

        Returns:
            缓存值，不存在或已过期时返回 None
        """

    @abc.abstractmethod
    def set(
        self,
        cache_name: str,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """设置缓存值

        Args:
            cache_name: 缓存区域名称
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 表示永不过期
        """

    @abc.abstractmethod
    def delete(self, cache_name: str, key: str) -> bool:
        """删除缓存条目

        Returns:
            是否成功删除
        """

    @abc.abstractmethod
    def clear(self, cache_name: str) -> int:
        """清空指定缓存区域

        Returns:
            被清除的条目数量
        """


class _CacheEntry:
    """缓存条目"""

    __slots__ = ("expires_at", "value")

    def __init__(self, value: Any, ttl: float | None):
        self.value = value
        self.expires_at = time.time() + ttl if ttl else None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class MemoryCache(BaseCache):
    """内存缓存管理器

    基于字典的内存缓存实现，支持按名称隔离的多个缓存区域和 TTL 过期。
    适合单实例部署场景，不支持分布式缓存。
    """

    def __init__(self):
        self._stores: dict[str, dict[str, _CacheEntry]] = defaultdict(dict)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._cleanup_task: asyncio.Task | None = None
        self._cleanup_interval = 300.0  # 5分钟清理一次
        self._last_cleanup = time.time()

    def get(self, cache_name: str, key: str) -> Any:
        """获取缓存值"""
        store = self._stores.get(cache_name)
        if store is None:
            return None

        entry = store.get(key)
        if entry is None:
            return None

        if entry.is_expired():
            del store[key]
            return None

        return entry.value

    def set(
        self,
        cache_name: str,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """设置缓存值"""
        self._stores[cache_name][key] = _CacheEntry(value, ttl)

    def delete(self, cache_name: str, key: str) -> bool:
        """删除缓存条目"""
        store = self._stores.get(cache_name)
        if store is None:
            return False
        if key in store:
            del store[key]
            return True
        return False

    def clear(self, cache_name: str) -> int:
        """清空指定缓存区域"""
        store = self._stores.get(cache_name)
        if store is None:
            return 0
        count = len(store)
        store.clear()
        return count

    def get_lock(self, cache_name: str) -> asyncio.Lock:
        """获取缓存区域的锁"""
        return self._locks[cache_name]

    async def cleanup_expired(self) -> None:
        """清理所有过期的缓存条目"""
        now = time.time()
        for store in self._stores.values():
            expired_keys = [
                k
                for k, entry in store.items()
                if entry.expires_at and now > entry.expires_at
            ]
            for k in expired_keys:
                del store[k]

    async def start_cleanup_task(self) -> None:
        """启动后台清理任务"""
        if self._cleanup_task is not None:
            return

        async def _cleanup_loop() -> None:
            while True:
                await asyncio.sleep(self._cleanup_interval)
                await self.cleanup_expired()

        self._cleanup_task = asyncio.create_task(_cleanup_loop())

    async def stop_cleanup_task(self) -> None:
        """停止后台清理任务"""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None


class DiskCache(BaseCache):
    """磁盘缓存管理器

    基于文件的磁盘缓存实现，支持按名称隔离的多个缓存区域和 TTL 过期。
    数据持久化到磁盘，重启后仍然有效。
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_size_mb: int = 1024,
        gc_interval_seconds: int = 300,
    ):
        if cache_dir is None:
            cache_dir = get_plugin_cache_dir()
        self._cache_dir = cache_dir
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._gc_interval = gc_interval_seconds
        self._last_gc = 0.0
        self._lock = asyncio.Lock()
        self._gc_lock = asyncio.Lock()

        # 确保目录存在
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_file_path(self, cache_name: str, key: str) -> tuple[Path, Path]:
        """获取缓存文件路径

        Returns:
            (data_path, meta_path)
        """
        # 使用哈希避免文件名问题
        safe_key = hashlib.sha256(key.encode()).hexdigest()
        dir_path = self._cache_dir / cache_name
        dir_path.mkdir(parents=True, exist_ok=True)
        data_path = dir_path / f"{safe_key}.data"
        meta_path = dir_path / f"{safe_key}.meta"
        return data_path, meta_path

    def _serialize_value(self, value: Any) -> bytes:
        """序列化值"""
        return pickle.dumps(value)

    def _deserialize_value(self, data: bytes) -> Any:
        """反序列化值"""
        return pickle.loads(data)

    def get(self, cache_name: str, key: str) -> Any:
        """获取缓存值"""
        data_path, meta_path = self._get_cache_file_path(cache_name, key)

        if not data_path.exists() or not meta_path.exists():
            return None

        try:
            # 读取元数据
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            expire_at = meta.get("expire_at", 0)

            # 检查过期
            if time.time() > expire_at:
                self._delete_files(data_path, meta_path)
                return None

            # 读取数据
            data = data_path.read_bytes()
            return self._deserialize_value(data)

        except Exception:
            self._delete_files(data_path, meta_path)
            return None

    def set(
        self,
        cache_name: str,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """设置缓存值"""
        data_path, meta_path = self._get_cache_file_path(cache_name, key)

        try:
            # 序列化数据
            data = self._serialize_value(value)

            # 写入数据文件
            data_path.write_bytes(data)

            # 写入元数据
            expire_at = time.time() + ttl if ttl else float("inf")
            meta = {
                "expire_at": expire_at,
                "size": len(data),
                "created_at": time.time(),
            }
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False),
                encoding="utf-8",
            )

        except Exception:
            self._delete_files(data_path, meta_path)
            raise

    def delete(self, cache_name: str, key: str) -> bool:
        """删除缓存条目"""
        data_path, meta_path = self._get_cache_file_path(cache_name, key)
        data_exists = data_path.exists()
        self._delete_files(data_path, meta_path)
        return data_exists

    def clear(self, cache_name: str) -> int:
        """清空指定缓存区域"""
        dir_path = self._cache_dir / cache_name
        if not dir_path.exists():
            return 0

        count = 0
        for path in dir_path.glob("*.data"):
            path.unlink(missing_ok=True)
            count += 1
        for path in dir_path.glob("*.meta"):
            path.unlink(missing_ok=True)

        return count

    def _delete_files(self, *paths: Path) -> None:
        """安全删除文件"""
        for path in paths:
            path.unlink(missing_ok=True)

    async def maybe_gc(self) -> None:
        """条件性垃圾回收"""
        now = time.time()
        if now - self._last_gc < self._gc_interval:
            return

        async with self._gc_lock:
            now = time.time()
            if now - self._last_gc < self._gc_interval:
                return

            await self._gc()
            self._last_gc = now

    async def _gc(self) -> None:
        """垃圾回收"""
        if not self._cache_dir.exists():
            return

        now = time.time()
        for meta_path in self._cache_dir.rglob("*.meta"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if now > meta.get("expire_at", 0):
                    data_path = meta_path.with_suffix(".data")
                    self._delete_files(data_path, meta_path)
            except Exception:
                continue

        # 检查总大小
        total_size = sum(
            p.stat().st_size for p in self._cache_dir.rglob("*.data") if p.is_file()
        )

        if total_size > self._max_size_bytes:
            # 按创建时间排序，删除最旧的
            caches: list[tuple[float, Path, Path]] = []
            for meta_path in self._cache_dir.rglob("*.meta"):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    data_path = meta_path.with_suffix(".data")
                    caches.append((meta.get("created_at", 0), data_path, meta_path))
                except Exception:
                    continue

            caches.sort(key=lambda x: x[0])  # 按时间升序

            # 删除最旧的直到总大小符合要求
            for created_at, data_path, meta_path in caches:
                if total_size <= self._max_size_bytes * 0.8:
                    break
                try:
                    size = data_path.stat().st_size
                    self._delete_files(data_path, meta_path)
                    total_size -= size
                except Exception:
                    continue


class HybridCache(BaseCache):
    """混合缓存管理器

    内存 + 磁盘双层缓存。热数据在内存层（快速），冷数据在磁盘层（持久化）。
    读取时优先从内存获取，未命中则查磁盘并回填内存。
    """

    def __init__(
        self,
        memory_max_size: int = 1000,
        disk_cache_dir: Path | None = None,
        disk_max_size_mb: int = 1024,
    ):
        self._memory = MemoryCache()
        self._disk = DiskCache(
            cache_dir=disk_cache_dir,
            max_size_mb=disk_max_size_mb,
        )
        self._memory_max_size = memory_max_size
        self._memory_keys: list[str] = []  # LRU 列表

    def get(self, cache_name: str, key: str) -> Any:
        """获取缓存值（优先内存）"""
        # 先查内存
        value = self._memory.get(cache_name, key)
        if value is not None:
            return value

        # 再查磁盘
        value = self._disk.get(cache_name, key)
        if value is not None:
            # 回填内存
            self._add_to_memory(cache_name, key, value)
            return value

        return None

    def set(
        self,
        cache_name: str,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """设置缓存值（同时写入内存和磁盘）"""
        # 写入内存
        self._add_to_memory(cache_name, key, value)
        self._memory.set(cache_name, key, value, ttl)

        # 写入磁盘
        self._disk.set(cache_name, key, value, ttl)

    def _add_to_memory(self, cache_name: str, key: str, value: Any) -> None:
        """添加到内存缓存（带 LRU）"""
        full_key = f"{cache_name}:{key}"

        if full_key in self._memory_keys:
            self._memory_keys.remove(full_key)
        else:
            # LRU 淘汰
            while len(self._memory_keys) >= self._memory_max_size:
                old_key = self._memory_keys.pop(0)
                cache_name_old, key_old = old_key.split(":", 1)
                self._memory.delete(cache_name_old, key_old)

        self._memory_keys.append(full_key)

    def delete(self, cache_name: str, key: str) -> bool:
        """删除缓存条目"""
        self._memory.delete(cache_name, key)
        full_key = f"{cache_name}:{key}"
        if full_key in self._memory_keys:
            self._memory_keys.remove(full_key)
        return self._disk.delete(cache_name, key)

    def clear(self, cache_name: str) -> int:
        """清空指定缓存区域"""
        self._memory.clear(cache_name)
        self._memory_keys = [
            k for k in self._memory_keys if not k.startswith(f"{cache_name}:")
        ]
        return self._disk.clear(cache_name)


def _validate_key(key: str) -> None:
    """验证缓存键表达式有效"""
    if not key or not key.strip():
        raise ValueError("Cache key expression cannot be empty")


def _build_cache_key(
    key_expr: str | CompiledExpression,
    args: tuple,
    kwargs: dict,
    param_names: list[str],
) -> str:
    """构建缓存键"""
    if isinstance(key_expr, CompiledExpression):
        raw = key_expr.evaluate(args, kwargs, param_names)
    else:
        raw = ExpressionParser.parse(key_expr, args, kwargs, param_names)
    return str(raw)


def _create_cache_provider(
    provider: CacheProviderType,
    cache_dir: Path | None = None,
    max_size_mb: int = 1024,
    memory_max_size: int = 1000,
) -> BaseCache:
    """根据提供方类型创建缓存实例"""
    match provider:
        case CacheProviderType.MEMORY:
            return get_memory_cache()
        case CacheProviderType.DISK:
            return DiskCache(cache_dir=cache_dir, max_size_mb=max_size_mb)
        case CacheProviderType.HYBRID:
            return HybridCache(
                memory_max_size=memory_max_size,
                disk_cache_dir=cache_dir,
                disk_max_size_mb=max_size_mb,
            )


# 全局缓存实例（兼容旧代码）
_cache_instance: BaseCache | None = None


def get_memory_cache() -> BaseCache:
    """获取全局缓存实例（兼容旧代码）

    默认返回 MemoryCache，后续可通过 set_cache_backend() 切换为其他实现。
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = MemoryCache()
    return _cache_instance


def set_cache_backend(backend: BaseCache) -> None:
    """设置全局缓存后端（兼容旧代码）

    用于切换为 RedisCache、DiskCache 等其他实现。

    Args:
        backend: 缓存后端实例
    """
    global _cache_instance
    _cache_instance = backend


def caching(
    cache_name: str,
    *,
    key: str,
    ttl: float | None = None,
    condition: str | None = None,
    provider: CacheProviderType = CacheProviderType.MEMORY,
    cache_dir: Path | None = None,
    max_size_mb: int = 1024,
    memory_max_size: int = 1000,
) -> Callable[[F], F]:
    """缓存装饰器（类似 Spring @Cacheable）

    如果缓存中存在值，直接返回缓存值；否则执行函数并缓存结果。

    Args:
        cache_name: 缓存区域名称
        key: 缓存键表达式（SpEL），默认使用函数名+参数
        ttl: 过期时间（秒），None 表示永不过期
        condition: 条件表达式（SpEL），为真时才缓存
        provider: 缓存提供方类型
        cache_dir: 磁盘缓存目录（DISK/HYBRID 模式使用）
        max_size_mb: 磁盘缓存最大大小（MB）
        memory_max_size: 内存缓存最大条目数（HYBRID 模式使用）

    Examples:
        >>> @caching("feed_meta", key="#feed_id", ttl=300)
        ... async def fetch_feed(self, feed_id: int) -> dict:
        ...     return await expensive_query(feed_id)

        >>> @caching("translations", key="#text+#target_lang", ttl=3600)
        ... async def translate(self, text: str, target_lang: str) -> str:
        ...     return await translator.translate(text, target_lang)

        >>> @caching("media", key="#url", ttl=900, provider=CacheProviderType.DISK)
        ... async def download_media(self, url: str) -> Path:
        ...     return await download(url)
    """
    _validate_key(key)
    cache = _create_cache_provider(provider, cache_dir, max_size_mb, memory_max_size)
    compiled_key = CompiledExpression(key)
    compiled_condition = CompiledExpression(condition) if condition else None

    def decorator(func: F) -> F:
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())

        def _eval_condition(args: tuple, kwargs: dict, result: Any) -> bool:
            if compiled_condition is None:
                return True
            condition_kwargs = {**kwargs, "result": result}
            cond_result = compiled_condition.evaluate(
                args, condition_kwargs, param_names
            )
            return bool(cond_result)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache_key = _build_cache_key(compiled_key, args, kwargs, param_names)

            # 检查缓存
            cached = cache.get(cache_name, cache_key)
            if cached is not None:
                return cached

            # 执行函数
            result = await func(*args, **kwargs)

            if _eval_condition(args, kwargs, result):
                cache.set(cache_name, cache_key, result, ttl)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            cache_key = _build_cache_key(compiled_key, args, kwargs, param_names)

            cached = cache.get(cache_name, cache_key)
            if cached is not None:
                return cached

            result = func(*args, **kwargs)

            if _eval_condition(args, kwargs, result):
                cache.set(cache_name, cache_key, result, ttl)
            return result

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def cacheput(
    cache_name: str,
    *,
    key: str,
    ttl: float | None = None,
    condition: str | None = None,
    provider: CacheProviderType = CacheProviderType.MEMORY,
    cache_dir: Path | None = None,
    max_size_mb: int = 1024,
    memory_max_size: int = 1000,
) -> Callable[[F], F]:
    """缓存更新装饰器（类似 Spring @CachePut）

    始终执行函数，并将结果写入缓存。

    Args:
        cache_name: 缓存区域名称
        key: 缓存键表达式（SpEL）
        ttl: 过期时间（秒）
        condition: 条件表达式（SpEL）
        provider: 缓存提供方类型
        cache_dir: 磁盘缓存目录
        max_size_mb: 磁盘缓存最大大小（MB）
        memory_max_size: 内存缓存最大条目数

    Examples:
        >>> @cacheput("feed_meta", key="#feed_id")
        ... async def update_feed(self, feed_id: int, data: dict) -> dict:
        ...     await db.update(feed_id, data)
        ...     return data
    """
    _validate_key(key)
    cache = _create_cache_provider(provider, cache_dir, max_size_mb, memory_max_size)
    compiled_key = CompiledExpression(key)
    compiled_condition = CompiledExpression(condition) if condition else None

    def decorator(func: F) -> F:
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())

        def _eval_condition(args: tuple, kwargs: dict, result: Any) -> bool:
            if compiled_condition is None:
                return True
            condition_kwargs = {**kwargs, "result": result}
            cond_result = compiled_condition.evaluate(
                args, condition_kwargs, param_names
            )
            return bool(cond_result)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)

            if _eval_condition(args, kwargs, result):
                cache_key = _build_cache_key(compiled_key, args, kwargs, param_names)
                cache.set(cache_name, cache_key, result, ttl)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            result = func(*args, **kwargs)

            if _eval_condition(args, kwargs, result):
                cache_key = _build_cache_key(compiled_key, args, kwargs, param_names)
                cache.set(cache_name, cache_key, result, ttl)
            return result

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def cacheevict(
    cache_name: str,
    *,
    key: str | None = None,
    all_entries: bool = False,
    before_invocation: bool = False,
    provider: CacheProviderType = CacheProviderType.MEMORY,
    cache_dir: Path | None = None,
    max_size_mb: int = 1024,
    memory_max_size: int = 1000,
) -> Callable[[F], F]:
    """缓存清除装饰器（类似 Spring @CacheEvict）

    清除指定缓存条目或整个缓存区域。

    Args:
        cache_name: 缓存区域名称
        key: 缓存键表达式（SpEL），all_entries=False 时必须提供
        all_entries: 是否清除整个缓存区域
        before_invocation: 是否在方法执行前清除
        provider: 缓存提供方类型
        cache_dir: 磁盘缓存目录
        max_size_mb: 磁盘缓存最大大小（MB）
        memory_max_size: 内存缓存最大条目数

    Examples:
        >>> @cacheevict("feed_meta", key="#feed_id")
        ... async def delete_feed(self, feed_id: int) -> None:
        ...     pass

        >>> @cacheevict("translations", all_entries=True)
        ... async def clear_translations(self) -> None:
        ...     pass
    """
    if not all_entries:
        _validate_key(key)
    cache = _create_cache_provider(provider, cache_dir, max_size_mb, memory_max_size)
    compiled_key = CompiledExpression(key) if key else None

    def decorator(func: F) -> F:
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())

        def _do_evict(args: tuple, kwargs: dict) -> None:
            if all_entries:
                cache.clear(cache_name)
            elif compiled_key is not None:
                cache_key = _build_cache_key(compiled_key, args, kwargs, param_names)
                cache.delete(cache_name, cache_key)
            else:
                raise ValueError(
                    "cacheevict requires either 'key' or 'all_entries=True'"
                )

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if before_invocation:
                _do_evict(args, kwargs)
            result = await func(*args, **kwargs)
            if not before_invocation:
                _do_evict(args, kwargs)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if before_invocation:
                _do_evict(args, kwargs)
            result = func(*args, **kwargs)
            if not before_invocation:
                _do_evict(args, kwargs)
            return result

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


__all__ = [
    "BaseCache",
    "CacheProviderType",
    "DiskCache",
    "HybridCache",
    "MemoryCache",
    "cacheevict",
    "cacheput",
    "caching",
    "get_memory_cache",
    "set_cache_backend",
]
