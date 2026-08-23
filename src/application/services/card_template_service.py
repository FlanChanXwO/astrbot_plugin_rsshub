"""卡片模板管理应用服务。"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from ...domain.exceptions import DomainException
from ..ports.card_templates import (
    CardTemplateArchiveDownloader,
    CardTemplateReferenceLookup,
    CardTemplateRepository,
)


class CardTemplateInUseError(DomainException):
    """模板仍被 Subscription 或 Bundle 引用。"""

    def __init__(self, template_id: str) -> None:
        self.template_id = template_id
        super().__init__(
            message=f"模板 {template_id} 正在被引用，不能删除",
            code="CARD_TEMPLATE_IN_USE",
        )


class UnsupportedCardTemplateUrlError(DomainException):
    """模板下载 URL 不是有效 HTTP(S) 地址。"""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(
            message=f"模板下载只支持有效的 HTTP(S) URL: {url}",
            code="CARD_TEMPLATE_URL_UNSUPPORTED",
        )


class InsecureCardTemplateDownloadError(DomainException):
    """HTTP 下载尚未得到显式确认。"""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(
            message=f"HTTP 模板下载需要显式确认: {url}",
            code="CARD_TEMPLATE_HTTP_CONFIRMATION_REQUIRED",
        )


class CardTemplateManagementService:
    """在删除文件前执行跨 owner 引用保护。"""

    def __init__(
        self,
        repository: CardTemplateRepository,
        reference_lookup: CardTemplateReferenceLookup,
    ) -> None:
        self._repository = repository
        self._reference_lookup = reference_lookup

    async def delete_template(self, template_id: str) -> bool:
        """删除未被引用的模板。"""
        if await self._reference_lookup.is_template_in_use(template_id):
            raise CardTemplateInUseError(template_id)
        return await asyncio.to_thread(self._repository.delete, template_id)


class CardTemplateDownloadService:
    """从外部 URL 下载模板 ZIP 并交给安全仓储安装。"""

    def __init__(
        self,
        repository: CardTemplateRepository,
        downloader: CardTemplateArchiveDownloader,
    ) -> None:
        self._repository = repository
        self._downloader = downloader

    async def install_from_url(
        self,
        url: str,
        *,
        allow_insecure_http: bool,
    ) -> Any:
        """下载并安装一个模板包。"""
        normalized_url = str(url or "").strip()
        parsed = urlparse(normalized_url)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname:
            raise UnsupportedCardTemplateUrlError(url)
        if scheme == "http" and not allow_insecure_http:
            raise InsecureCardTemplateDownloadError(url)
        archive_data = await self._downloader.download(normalized_url)
        # ZIP 校验和文件切换是同步磁盘 I/O，不能阻塞 AstrBot 的事件循环。
        return await asyncio.to_thread(self._repository.install_archive, archive_data)
