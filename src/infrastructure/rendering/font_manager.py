"""表格渲染字体的运行时下载与校验。

插件不再内置 CJK 字体，改为在启用表格转图功能时按需下载到持久化数据目录。
下载使用 SHA256 + 大小双重校验，避免截断或损坏文件被误用。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from ..fetcher.http import HttpFetcher
from ..utils.logger import get_logger
from ..utils.paths import get_plugin_data_dir

logger = get_logger()

TABLE_FONT_URL = (
    "https://cdn.jsdelivr.net/gh/googlefonts/noto-cjk@main"
    "/Sans/Variable/OTF/Subset/NotoSansSC-VF.otf"
)
TABLE_FONT_SHA256 = "d13ed01ec8aa45d6178999b648e96fb92150683e9f8e2a581f2acf208dcbe44b"
TABLE_FONT_SIZE = 15054748
TABLE_FONT_FILENAME = "NotoSansSC-subset.otf"
_FONT_DATA_PART = "fonts"
_DOWNLOAD_TIMEOUT_FLOOR = 120

_download_lock = asyncio.Lock()

# 已校验字体路径缓存：避免渲染路径每张表都重跑 SHA256 全量校验阻塞事件循环。
# 校验/写入通过 _verify_lock 串行化，保证检查与写缓存原子。
_cached_verified_font: Path | None = None
_verify_lock = asyncio.Lock()

# 启动时配置的下载参数；按需门控与后台预取共用，避免在渲染路径再次穿透业务层取代理。
_download_configured = False
_configured_proxy = ""
_configured_timeout = 300
_prefetch_task: asyncio.Task[Path | None] | None = None


def configure_table_font_download(http_proxy: str = "", timeout: int = 300) -> None:
    """记录字体下载使用的代理与超时（启动装配时调用一次）。

    配置后，按需门控 :func:`ensure_table_font_runtime` 才会在字体缺失时触发下载；
    未配置时（如单元测试）门控只读取已落盘字体，绝不发起网络请求。
    """
    global _download_configured, _configured_proxy, _configured_timeout
    _download_configured = True
    _configured_proxy = http_proxy or ""
    _configured_timeout = int(timeout or 300)


def prefetch_table_font() -> None:
    """在后台异步预取字体，不阻塞插件启动（幂等）。

    需先调用 :func:`configure_table_font_download`。字体已就绪或已有进行中的
    预取任务时直接返回。异常在任务内兜底，不会向调用方逃逸。
    """
    global _prefetch_task
    if _prefetch_task is not None and not _prefetch_task.done():
        return
    if _verify_font(get_runtime_font_path()):
        return

    async def _run() -> Path | None:
        try:
            return await ensure_table_font(_configured_proxy, _configured_timeout)
        except Exception as ex:  # 防御：兜底未知异常，避免后台任务静默崩溃
            logger.warning(
                "表格字体后台预取异常: err_type=%s, err=%s", type(ex).__name__, ex
            )
            return None

    _prefetch_task = asyncio.create_task(_run())


async def ensure_table_font_runtime() -> Path | None:
    """渲染路径的按需门控：返回已就绪字体，必要且已配置时才下载。

    首次命中缓存后直接返回缓存路径，避免每张表都重跑全量 SHA256 校验阻塞事件
    循环。复用启动时配置的代理/超时。未配置下载（如测试环境）且字体未落盘时返回
    None，调用方据此回退纯文本，绝不触发网络下载。
    """
    if _cached_verified_font is not None:
        return _cached_verified_font

    target = get_runtime_font_path()
    async with _verify_lock:
        # 双检：可能在等锁期间已被其他协程校验/下载完成。
        if _cached_verified_font is not None:
            return _cached_verified_font
        if _verify_font(target):
            return _set_verified_font(target)
        if not _download_configured:
            return None

    # 下载在锁外进行（ensure_table_font 自带 _download_lock），成功后写缓存。
    downloaded = await ensure_table_font(_configured_proxy, _configured_timeout)
    if downloaded is not None:
        return _set_verified_font(downloaded)
    return None


def _set_verified_font(path: Path) -> Path:
    """记录已校验字体路径到缓存并返回。"""
    global _cached_verified_font
    _cached_verified_font = path
    return path


def get_runtime_font_dir() -> Path:
    """返回运行时字体的持久化目录（不在 cache 下，避免 GC 清理）。"""
    return get_plugin_data_dir(_FONT_DATA_PART)


def get_runtime_font_path() -> Path:
    """返回运行时字体文件的目标路径。"""
    return get_runtime_font_dir() / TABLE_FONT_FILENAME


def _verify_font(path: Path) -> bool:
    """校验字体文件大小与 SHA256，防止截断或损坏文件。"""
    try:
        if not path.is_file() or path.stat().st_size != TABLE_FONT_SIZE:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest() == TABLE_FONT_SHA256
    except OSError as ex:
        logger.debug("字体校验读取失败: path=%s, err=%s", path, ex)
        return False


async def ensure_table_font(http_proxy: str = "", timeout: int = 300) -> Path | None:
    """确保运行时字体可用，必要时下载并校验。

    Args:
        http_proxy: 可选代理地址（用于访问字体 CDN）
        timeout: 下载超时（秒）

    Returns:
        校验通过的字体路径；下载或校验失败时返回 None（由调用方降级处理）。
    """
    target = get_runtime_font_path()
    if _verify_font(target):
        return _set_verified_font(target)

    async with _download_lock:
        # 双检：可能在等锁期间已被其他协程下载完成
        if _verify_font(target):
            return _set_verified_font(target)
        result = await _download_and_verify(target, http_proxy, timeout)
        return _set_verified_font(result) if result is not None else None


async def _download_and_verify(
    target: Path,
    http_proxy: str,
    timeout: int,
) -> Path | None:
    effective_timeout = max(_DOWNLOAD_TIMEOUT_FLOOR, int(timeout or 0))
    fetcher = HttpFetcher(timeout=effective_timeout, proxy=http_proxy)
    try:
        logger.info("开始下载表格字体: url=%s", TABLE_FONT_URL)
        result = await fetcher.fetch(TABLE_FONT_URL, verbose=False)
    except Exception as ex:  # 防御：fetch 内部已捕获，此处兜底未知异常
        logger.warning("表格字体下载异常: err_type=%s, err=%s", type(ex).__name__, ex)
        return None
    finally:
        await fetcher.close()

    if result.error is not None or result.status != 200 or not result.content:
        logger.warning(
            "表格字体下载失败: status=%s, error=%s",
            result.status,
            result.error,
        )
        return None

    content = result.content
    if len(content) != TABLE_FONT_SIZE:
        logger.warning(
            "表格字体大小不符: expected=%s, got=%s",
            TABLE_FONT_SIZE,
            len(content),
        )
        return None
    if hashlib.sha256(content).hexdigest() != TABLE_FONT_SHA256:
        logger.warning("表格字体 SHA256 校验失败，丢弃下载内容")
        return None

    return _atomic_write(target, content)


def _atomic_write(target: Path, content: bytes) -> Path | None:
    """唯一临时文件 + 原子 rename 落盘，避免并发或半截文件污染。"""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as ex:
        logger.warning("创建字体目录失败: dir=%s, err=%s", target.parent, ex)
        return None

    tmp_path = target.with_name(
        f".{target.stem}.{os.getpid()}.{uuid4().hex}.tmp{target.suffix}"
    )
    try:
        tmp_path.write_bytes(content)
        tmp_path.replace(target)
        logger.info("表格字体已就绪: path=%s", target)
        return target
    except OSError as ex:
        logger.warning("写入字体文件失败: path=%s, err=%s", target, ex)
        return None
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError as ex:
            logger.debug("字体临时文件清理失败: path=%s, err=%s", tmp_path, ex)
