"""内容类型领域实体

定义消息内容的结构化类型。
"""

from __future__ import annotations

from abc import ABC
from urllib.parse import urlparse

from pydantic import BaseModel, Field

GENERATED_MEDIA_SCHEME = "rsshub-generated"
GENERATED_MEDIA_TABLE_KIND = "table"


def build_generated_media_url(kind: str, digest: str) -> str:
    """构造本地生成媒体的稳定标识，不承诺它是远程 URL。"""
    normalized_kind = str(kind or "").strip().lower()
    normalized_digest = str(digest or "").strip().lower()
    return f"{GENERATED_MEDIA_SCHEME}://{normalized_kind}/{normalized_digest}"


def parse_generated_media_url(value: str) -> tuple[str, str] | None:
    """解析本地生成媒体标识，返回 kind 与内容 hash。"""
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != GENERATED_MEDIA_SCHEME:
        return None
    kind = parsed.netloc.strip().lower()
    digest = parsed.path.strip("/").lower()
    if not kind or not digest:
        return None
    return kind, digest


def is_generated_media_url(value: str) -> bool:
    """判断字符串是否为插件本地生成媒体标识。"""
    return parse_generated_media_url(value) is not None


class ContentNode(BaseModel, ABC):
    """内容节点基类"""

    def get_plain(self) -> str:
        """获取纯文本表示"""
        raise NotImplementedError


class TextContent(ContentNode):
    """文本内容节点"""

    text: str = Field(..., description="文本内容")

    def get_plain(self) -> str:
        return self.text


class LinkContent(ContentNode):
    """链接内容节点"""

    text: str = Field(default="", description="链接文本")
    url: str = Field(..., description="链接URL")

    def get_plain(self) -> str:
        return self.text


class ImageContent(ContentNode):
    """图片内容节点"""

    url: str = Field(..., description="图片URL")
    alt: str = Field(default="", description="替代文本")

    def get_plain(self) -> str:
        return (self.alt or "").strip()


class GeneratedImageContent(ContentNode):
    """插件本地生成的图片内容节点。"""

    source_id: str = Field(..., description="本地生成媒体稳定标识")
    cache_path: str = Field(..., description="本地缓存文件路径")
    alt: str = Field(default="[表格已转为图片]", description="替代文本")
    fallback_text: str = Field(default="", description="生成图片不可用时的文本降级")

    @property
    def url(self) -> str:
        return self.source_id

    def get_plain(self) -> str:
        return (self.alt or "").strip()


class VideoContent(ContentNode):
    """视频内容节点"""

    url: str = Field(..., description="视频URL")

    def get_plain(self) -> str:
        return "[视频]"


class AudioContent(ContentNode):
    """音频内容节点"""

    url: str = Field(..., description="音频URL")

    def get_plain(self) -> str:
        return "[音频]"


class FileContent(ContentNode):
    """文件内容节点"""

    url: str = Field(..., description="文件URL")
    name: str = Field(default="", description="文件名")

    def get_plain(self) -> str:
        return f"[文件: {self.name}]" if self.name else "[文件]"


class MentionContent(ContentNode):
    """提及内容节点"""

    target: str = Field(..., description="提及目标")
    name: str = Field(default="", description="提及名称")

    def get_plain(self) -> str:
        return f"@{self.name}" if self.name else "@"


# 内容节点联合类型
ContentNodeType = (
    TextContent
    | LinkContent
    | ImageContent
    | GeneratedImageContent
    | VideoContent
    | AudioContent
    | FileContent
    | MentionContent
)


class HtmlNode(BaseModel):
    """HTML节点"""

    children: list[ContentNodeType | HtmlNode] = Field(default_factory=list)

    def get_plain(self) -> str:
        return "".join(child.get_plain() for child in self.children)


class LayoutFragment(BaseModel):
    """A send-layout fragment preserving parsed content order."""

    kind: str = Field(..., description="text/image/video/audio/file")
    text: str = Field(default="", description="Text content")
    media_type: str = Field(default="", description="Media type")
    url: str = Field(default="", description="Media URL")
    local_path: str = Field(default="", description="Generated local media path")
    name: str = Field(default="", description="File name")
    fallback_text: str = Field(default="", description="Media send failure fallback")


class ParsedResult(BaseModel):
    """HTML解析结果"""

    html_tree: HtmlNode = Field(..., description="解析后的HTML树")
    media: list[
        ImageContent | GeneratedImageContent | VideoContent | AudioContent | FileContent
    ] = Field(default_factory=list, description="媒体列表")
    layout: list[LayoutFragment] = Field(
        default_factory=list, description="按解析顺序生成的推送布局片段"
    )
    links: list[str] = Field(default_factory=list, description="链接列表")
    mentions: list[MentionContent] = Field(default_factory=list, description="提及列表")
