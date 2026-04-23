"""
RSS-to-AstrBot Async Helper
异步辅助函数模块
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")

# 全局线程池
_thread_pool: ThreadPoolExecutor | None = None


def get_thread_pool() -> ThreadPoolExecutor:
    """获取全局线程池"""
    global _thread_pool
    if _thread_pool is None:
        _thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rsshub_")
    return _thread_pool


async def run_async(
    func: Callable[..., T], *args, prefer_pool: str | None = None, **kwargs
) -> T:
    """
    在线程池中运行同步函数

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
        executor = get_thread_pool()
        return await loop.run_in_executor(
            executor, functools.partial(func, **kwargs), *args
        )

    # 直接在执行器中运行
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


async def run_async_with_timeout(
    func: Callable[..., T], *args, timeout: float = 30.0, **kwargs
) -> T | None:
    """
    在线程池中运行同步函数，带超时

    Args:
        func: 同步函数
        *args: 位置参数
        timeout: 超时时间（秒）
        **kwargs: 关键字参数

    Returns:
        函数返回值，超时返回 None
    """
    try:
        return await asyncio.wait_for(run_async(func, *args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def gather_with_concurrency(*tasks, concurrency: int = 10) -> list:
    """
    并发执行任务，限制并发数

    Args:
        *tasks: 任务列表
        concurrency: 最大并发数

    Returns:
        结果列表
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_task(task):
        async with semaphore:
            return await task

    return await asyncio.gather(*[bounded_task(task) for task in tasks])


async def retry_async(
    func: Callable[..., T],
    *args,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    """
    带重试的异步执行

    Args:
        func: 异步函数
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
                return await run_async(func, *args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                await asyncio.sleep(current_delay)
                current_delay *= backoff
            else:
                raise

    raise last_exception


def async_to_sync(func: Callable[..., T]) -> Callable[..., T]:
    """
    将异步函数转换为同步函数

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
