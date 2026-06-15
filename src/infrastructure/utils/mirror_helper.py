"""共享镜像测速工具。

为 FFmpeg 捆绑下载、知识库同步等场景提供统一的 GitHub 镜像前缀映射和自动测速。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable

import aiohttp

from .logger import get_logger

logger = get_logger()

# GitHub 镜像前缀映射。
# mirror_prefix + 原始 GitHub URL = 完整下载链接。
# "default" 表示直连（无前缀）。
MIRROR_PREFIXES: dict[str, str] = {
    "default": "",
    "ghfast": "https://ghfast.top/",
    "ghproxy": "https://ghproxy.com/",
    "mirror_ghproxy": "https://mirror.ghproxy.com/",
    "gh_proxy": "https://gh-proxy.com/",
}


async def speed_test_mirrors(
    target_url: str,
    *,
    proxy: str = "",
    probe_timeout: int = 5,
    extra_candidates: Iterable[tuple[str, str]] = (),
) -> str:
    """并发 HEAD 测速所有镜像 + 直连 + 调用方注入的额外候选，返回响应最快的完整 URL。

    Args:
        target_url: 原始 GitHub URL（如 https://github.com/.../file.tar.gz）
        proxy: 可选 HTTP 代理
        probe_timeout: 每个候选探测超时（秒）
        extra_candidates: 额外候选 (label, full_url) 列表，与内置 mirror/直连一并测速

    Returns:
        响应最快的镜像 URL，全部失败时回退到原始 URL
    """
    # 构建候选列表
    candidates: list[tuple[str, str]] = []  # (label, full_url)
    for name, prefix in MIRROR_PREFIXES.items():
        if name == "default" or not prefix:
            continue
        candidates.append((name, prefix + target_url))
    candidates.append(("direct", target_url))
    for label, url in extra_candidates:
        if not url:
            continue
        candidates.append((label, url))

    mirror_names = ", ".join(label for label, _ in candidates)
    logger.info("镜像测速开始: 候选 = [%s]", mirror_names)

    async def _probe(
        session: aiohttp.ClientSession, label: str, url: str
    ) -> tuple[str, str, float]:
        """返回 (label, url, elapsed)。失败时 url 为空。"""
        try:
            start = time.monotonic()
            async with session.head(
                url,
                timeout=aiohttp.ClientTimeout(total=probe_timeout),
                allow_redirects=True,
                proxy=proxy or None,
            ) as resp:
                elapsed = time.monotonic() - start
                if resp.status < 400:
                    logger.debug("镜像测速: %s = %.2fs", label, elapsed)
                    return label, url, elapsed
                logger.debug("镜像测速: %s = HTTP %d", label, resp.status)
                return label, "", float("inf")
        except Exception as ex:
            logger.debug(
                "镜像测速: %s = 不可达 (err_type=%s, err=%s)",
                label,
                type(ex).__name__,
                ex,
            )
            return label, "", float("inf")

    # 共享一个 session + connector，所有候选并发探测，省连接 / SSL 握手开销
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            *[_probe(session, label, url) for label, url in candidates]
        )

    # 选最快
    best_label = ""
    best_url = ""
    best_time = float("inf")
    for label, url, elapsed in results:
        if url and elapsed < best_time:
            best_label = label
            best_url = url
            best_time = elapsed

    if best_url:
        logger.info("镜像测速完成: 选中 %s (%.2fs)", best_label, best_time)
        return best_url

    # 全部失败，回退直连
    logger.warning("镜像测速全部失败，回退直连")
    return target_url
