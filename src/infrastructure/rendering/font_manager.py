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
        return target

    async with _download_lock:
        # 双检：可能在等锁期间已被其他协程下载完成
        if _verify_font(target):
            return target
        return await _download_and_verify(target, http_proxy, timeout)


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
