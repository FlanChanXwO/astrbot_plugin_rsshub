"""Feed 解析输出模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Enclosure(BaseModel):
    """附件信息。"""

    url: str = Field(..., description="附件URL")
    length: int = Field(default=0, description="文件大小")
    type: str = Field(default="", description="MIME类型")


class EntryParsed(BaseModel):
    """解析后的 Feed 条目。"""

    id: str = Field(default="", description="条目稳定标识")
    title: str = Field(default="", description="标题")
    link: str = Field(default="", description="链接")
    author: str | None = Field(default="", description="作者")
    content: str | None = Field(default="", description="正文内容")
    summary: str | None = Field(default="", description="摘要")
    guid: str = Field(default="", description="全局唯一标识")
    entry_id: str = Field(default="", description="条目ID")
    raw_xml: str = Field(default="", description="原始或合成 item/entry XML")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    enclosures: list[Enclosure] = Field(default_factory=list, description="附件列表")
    published: datetime | None = Field(default=None, description="发布时间")
    updated: datetime | None = Field(default=None, description="更新时间")

    def to_dict(self) -> dict[str, Any]:
        """转换为普通字典，保留历史测试依赖的字段名。"""
        return self.model_dump()

    def text_content(self) -> str:
        """获取用于搜索/格式化的条目文本内容。"""
        parts = [
            self.title or "",
            self.content or self.summary or "",
        ]
        return "\n".join(part for part in parts if part)
