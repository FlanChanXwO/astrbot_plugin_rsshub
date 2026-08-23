"""卡片模板归档的 HTTP 下载边界。"""

from __future__ import annotations

import asyncio
from ssl import SSLError

import aiohttp

from ...domain.exceptions import DomainException


class CardTemplateDownloadError(DomainException):
    """模板归档下载失败。"""

    def __init__(self, url: str, message: str, code: str) -> None:
        self.url = url
        super().__init__(message=message, code=code)


class CardTemplateHttpStatusError(CardTemplateDownloadError):
    """模板下载服务返回非成功 HTTP 状态。"""

    def __init__(self, url: str, status: int, reason: str = "") -> None:
        self.status = status
        self.reason = reason
        caption = f"{status} {reason}".strip()
        super().__init__(
            url=url,
            message=f"模板下载 HTTP 状态错误: {caption} ({url})",
            code="CARD_TEMPLATE_DOWNLOAD_HTTP_ERROR",
        )


class CardTemplateNetworkError(CardTemplateDownloadError):
    """模板下载发生网络或传输错误。"""

    def __init__(self, url: str, cause: Exception) -> None:
        self.cause = cause
        super().__init__(
            url=url,
            message=f"模板下载网络错误: {url}: {cause}",
            code="CARD_TEMPLATE_DOWNLOAD_NETWORK_ERROR",
        )


class AiohttpCardTemplateArchiveDownloader:
    """使用 aiohttp 完整下载模板 ZIP，不施加额外内容或时间限制。"""

    async def download(self, url: str) -> bytes:
        timeout = aiohttp.ClientTimeout(total=None)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 不自动跟随重定向，避免已确认的 HTTPS URL 静默降级到 HTTP。
                async with session.get(url, allow_redirects=False) as response:
                    if response.status != 200:
                        raise CardTemplateHttpStatusError(
                            url,
                            response.status,
                            response.reason or "",
                        )
                    return await response.read()
        except CardTemplateDownloadError:
            raise
        except asyncio.CancelledError:
            raise
        except (
            aiohttp.ClientError,
            SSLError,
            OSError,
            ConnectionError,
            TimeoutError,
        ) as exc:
            raise CardTemplateNetworkError(url, exc) from exc
