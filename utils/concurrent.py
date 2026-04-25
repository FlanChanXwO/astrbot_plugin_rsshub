"""并发控制工具模块

提供 AsyncTool 静态方法类和装饰器，用于异步执行控制。

使用示例:
    # 静态方法方式（用于同步函数转异步）
    result = await AsyncTool.run(sync_func, arg1, arg2)
    results = await AsyncTool.gather(task1, task2, concurrency=5)

    # 装饰器方式（仅用于异步函数）
    @retry(max_retries=3)
    async def fetch_data():
        pass

    @timeout(5.0)
    async def api_call():
        pass

    @semaphore(limit=10)
    async def limited_request():
        pass

    # 组合装饰器（从下到上执行）
    @retry(max_retries=3)
    @timeout(5.0)
    async def robust_api_call():
        pass

注意:
    装饰器仅支持异步函数，同步函数使用会抛出 TypeError
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")


# =============================================================================
# AsyncTool 静态方法类
# =============================================================================


class AsyncTool:
    """异步工具类，提供异步执行相关功能"""

    _thread_pool: ThreadPoolExecutor | None = None

    @staticmethod
    def get_thread_pool() -> ThreadPoolExecutor:
        """获取全局线程池（单例）

        Returns:
            ThreadPoolExecutor 实例
        """
        if AsyncTool._thread_pool is None:
            AsyncTool._thread_pool = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="rsshub_"
            )
        return AsyncTool._thread_pool

    @staticmethod
    async def run(
        func: Callable[..., T], *args, prefer_pool: str | None = None, **kwargs
    ) -> T:
        """在线程池中运行同步函数

        Args:
            func: 同步函数
            *args: 位置参数
            prefer_pool: 首选池类型 ('thread' 或 None)
            **kwargs: 关键字参数

        Returns:
            函数返回值
        """
        loop = asyncio.get_event_loop()

        if prefer_pool == "thread":
            executor = AsyncTool.get_thread_pool()
            return await loop.run_in_executor(
                executor, functools.partial(func, **kwargs), *args
            )

        # 直接在执行器中运行
        return await loop.run_in_executor(
            None, functools.partial(func, *args, **kwargs)
        )

    @staticmethod
    async def run_with_timeout(
        func: Callable[..., T], *args, timeout: float = 30.0, **kwargs
    ) -> T | None:
        """在线程池中运行同步函数，带超时

        Args:
            func: 同步函数
            *args: 位置参数
            timeout: 超时时间（秒）
            **kwargs: 关键字参数

        Returns:
            函数返回值，超时返回 None
        """
        try:
            return await asyncio.wait_for(
                AsyncTool.run(func, *args, **kwargs), timeout=timeout
            )
        except asyncio.TimeoutError:
            return None

    @staticmethod
    async def gather(*tasks, concurrency: int = 10) -> list:
        """并发执行任务，限制并发数

        Args:
            *tasks: 任务列表（协程或可等待对象）
            concurrency: 最大并发数

        Returns:
            结果列表
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded_task(task):
            async with semaphore:
                return await task

        return await asyncio.gather(*[bounded_task(task) for task in tasks])

    @staticmethod
    async def retry(
        func: Callable[..., T],
        *args,
        max_retries: int = 3,
        delay: float = 1.0,
        backoff: float = 2.0,
        exceptions: tuple = (Exception,),
        **kwargs,
    ) -> T:
        """带重试的异步执行

        Args:
            func: 异步函数或同步函数
            *args: 位置参数
            max_retries: 最大重试次数
            delay: 初始延迟
            backoff: 延迟增长倍数
            exceptions: 触发重试的异常类型
            **kwargs: 关键字参数

        Returns:
            函数返回值

        Raises:
            最后一次尝试的异常
        """
        last_exception = None
        current_delay = delay

        for attempt in range(max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return await AsyncTool.run(func, *args, **kwargs)
            except exceptions as e:
                last_exception = e
                if attempt < max_retries:
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
                else:
                    raise

        raise last_exception

    @staticmethod
    def to_sync(func: Callable[..., T]) -> Callable[..., T]:
        """将异步函数转换为同步函数

        Args:
            func: 异步函数

        Returns:
            同步包装函数
        """

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None:
                # 已有事件循环，创建新任务
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, func(*args, **kwargs))
                    return future.result()
            else:
                # 没有事件循环，直接运行
                return asyncio.run(func(*args, **kwargs))

        return wrapper


# =============================================================================
# 装饰器（仅用于异步函数）
# =============================================================================


def _ensure_async(func: Callable, decorator_name: str) -> None:
    """确保函数是异步函数，否则抛出 TypeError"""
    if not asyncio.iscoroutinefunction(func):
        raise TypeError(
            f"@{decorator_name} can only be used with async functions, "
            f"got {type(func).__name__}"
        )


def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """为异步函数添加重试功能

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟（秒）
        backoff: 延迟增长倍数
        exceptions: 触发重试的异常类型

    Returns:
        装饰器函数

    Raises:
        TypeError: 用于非异步函数时

    Example:
        @retry(max_retries=3, delay=1.0)
        async def fetch_data():
            return await http_get(url)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        _ensure_async(func, "retry")

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        raise

            raise last_exception

        return wrapper

    return decorator


def timeout(seconds: float):
    """为异步函数添加超时限制

    Args:
        seconds: 超时时间（秒）

    Returns:
        装饰器函数

    Raises:
        TypeError: 用于非异步函数时
        asyncio.TimeoutError: 超时时

    Example:
        @timeout(5.0)
        async def api_call():
            return await fetch_data()
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        _ensure_async(func, "timeout")

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)

        return wrapper

    return decorator


def semaphore(limit: int = 10):
    """限制异步函数并发数

    Args:
        limit: 最大并发数

    Returns:
        装饰器函数

    Raises:
        TypeError: 用于非异步函数时

    Example:
        @semaphore(limit=10)
        async def limited_request():
            return await fetch_data()
    """
    sem = asyncio.Semaphore(limit)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        _ensure_async(func, "semaphore")

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            async with sem:
                return await func(*args, **kwargs)

        return wrapper

    return decorator
