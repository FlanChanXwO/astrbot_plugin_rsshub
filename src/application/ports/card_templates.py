"""卡片模板管理所需的边界端口。"""

from __future__ import annotations

from typing import Any, Protocol


class CardTemplateRepository(Protocol):
    """模板文件仓储的应用层视图。"""

    def install_archive(self, archive_data: bytes) -> Any:
        """校验并安装一个 ZIP 模板包。"""
        ...

    def delete(self, template_id: str) -> bool:
        """删除可删除模板；不存在时返回 False。"""
        ...


class CardTemplateArchiveDownloader(Protocol):
    """外部模板归档下载边界。"""

    async def download(self, url: str) -> bytes:
        """下载 URL 并返回完整归档字节。"""
        ...


class CardTemplateReferenceLookup(Protocol):
    """查询 Subscription/Bundle 是否仍引用模板。"""

    async def is_template_in_use(self, template_id: str) -> bool:
        """模板存在任何活动引用时返回 True。"""
        ...
