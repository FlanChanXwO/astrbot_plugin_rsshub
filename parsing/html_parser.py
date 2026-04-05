"""
RSS-to-AstrBot HTML Parser
基于 RSS-to-Telegram-Bot 移植的 HTML 解析模块
适配 AstrBot 跨平台消息格式
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag


@dataclass
class TextContent:
    """文本内容节点"""

    text: str

    def get_plain(self) -> str:
        return self.text


@dataclass
class LinkContent:
    """链接内容节点"""

    text: str
    url: str

    def get_plain(self) -> str:
        return self.text


@dataclass
class ImageContent:
    """图片内容节点"""

    url: str
    alt: str = ""

    def get_plain(self) -> str:
        # 图片将通过消息组件发送，纯文本里仅保留可读 alt（如果有）
        return (self.alt or "").strip()


@dataclass
class VideoContent:
    """视频内容节点"""

    url: str

    def get_plain(self) -> str:
        return "[视频]"


@dataclass
class AudioContent:
    """音频内容节点"""

    url: str

    def get_plain(self) -> str:
        return "[音频]"


@dataclass
class FileContent:
    """文件内容节点"""

    url: str
    name: str = ""

    def get_plain(self) -> str:
        return f"[文件: {self.name}]" if self.name else "[文件]"


@dataclass
class MentionContent:
    """提及内容节点（仅组件能力，不承担触发逻辑）"""

    target: str
    name: str = ""

    def get_plain(self) -> str:
        return f"@{self.name}" if self.name else "@"


@dataclass
class HtmlNode:
    """HTML节点"""

    children: list[
        HtmlNode
        | TextContent
        | LinkContent
        | ImageContent
        | VideoContent
        | AudioContent
        | FileContent
        | MentionContent
    ] = field(default_factory=list)

    def get_plain(self) -> str:
        return "".join(child.get_plain() for child in self.children)


@dataclass
class ParsedResult:
    """解析结果"""

    html_tree: HtmlNode
    media: list[ImageContent | VideoContent | AudioContent | FileContent] = field(
        default_factory=list
    )
    links: list[str] = field(default_factory=list)
    mentions: list[MentionContent] = field(default_factory=list)


class HTMLParser:
    """
    HTML 解析器

    将 HTML 内容解析为结构化数据，适配 AstrBot 消息格式
    """

    # 分隔符
    SEPARATORS = (
        "\n",
        "。",
        ". ",
        "？",
        "? ",
        "！",
        "! ",
        "：",
        ": ",
        "；",
        "; ",
        "，",
        ", ",
        "\t",
        " ",
    )

    def __init__(self, html: str, feed_link: str | None = None):
        """
        初始化解析器

        Args:
            html: HTML 内容
            feed_link: feed 链接（用于解析相对 URL）
        """
        self.html = html
        self.feed_link = feed_link
        self.soup: BeautifulSoup | None = None
        self.media: list[ImageContent | VideoContent | AudioContent | FileContent] = []
        self.links: list[str] = []
        self.mentions: list[MentionContent] = []
        self._parse_count = 0
        self._seen_links: set[str] = set()
        self._seen_media: set[str] = set()
        self._seen_mentions: set[str] = set()

    async def parse(self) -> ParsedResult:
        """
        解析 HTML 内容

        Returns:
            ParsedResult 对象
        """
        # 使用 BeautifulSoup 解析
        self.soup = await self._run_async(BeautifulSoup, self.html, "lxml")

        # 解析内容
        children = await self._parse_children(self.soup)

        return ParsedResult(
            html_tree=HtmlNode(children=children),
            media=self.media,
            links=self.links,
            mentions=self.mentions,
        )

    async def _run_async(self, func, *args, **kwargs):
        """异步执行同步函数"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def _parse_children(self, element) -> list:
        """解析子元素"""
        self._parse_count += 1
        if self._parse_count % 64 == 0:
            await asyncio.sleep(0)  # 让出控制权

        result = []

        if isinstance(element, Iterator):
            for child in element:
                parsed = await self._parse_element(child)
                if parsed:
                    if isinstance(parsed, list):
                        result.extend(parsed)
                    else:
                        result.append(parsed)
            return result

        if isinstance(element, NavigableString):
            text = str(element).strip()
            if text:
                return [TextContent(text=text)]
            return []

        if not isinstance(element, Tag):
            return []

        tag = element.name
        if tag in ("script", "style", "noscript"):
            return []

        # 处理各种标签
        parsed = await self._parse_tag(element)
        if parsed:
            if isinstance(parsed, list):
                result.extend(parsed)
            else:
                result.append(parsed)

        return result

    async def _parse_element(self, element):
        """统一入口，便于 children 迭代时处理单元素"""
        parsed = await self._parse_children(element)
        if not parsed:
            return None
        if len(parsed) == 1:
            return parsed[0]
        return parsed

    async def _parse_tag(
        self, tag: Tag
    ) -> (
        list
        | TextContent
        | LinkContent
        | ImageContent
        | VideoContent
        | AudioContent
        | FileContent
        | MentionContent
        | None
    ):
        """解析单个标签"""
        tag_name = tag.name

        # At 组件标签，保留组件支持，不用于触发策略
        if tag_name in ("at", "mention"):
            target = (
                tag.get("qq")
                or tag.get("id")
                or tag.get("uid")
                or tag.get("target")
                or ""
            )
            name = tag.get("name") or tag.get_text().strip()
            mention = MentionContent(target=str(target).strip(), name=name)
            if mention.target:
                self._append_mention(mention)
            return mention

        # 图片
        if tag_name == "img":
            src = self._choose_image_src(tag)
            if src:
                url = self._resolve_url(src)
                alt = tag.get("alt", "")
                # 表情图片用 alt 替代，避免噪音媒体
                if (
                    alt
                    and len(alt) <= 3
                    and not url.lower().endswith((".gif", ".webm", ".mp4", ".m4v"))
                ):
                    return TextContent(text=alt)
                img = ImageContent(url=url, alt=alt)
                self._append_media(img)
                return img
            return None

        # 视频
        if tag_name == "video":
            sources = self._get_multi_src(tag)
            if sources:
                video = VideoContent(url=sources[0])
                self._append_media(video)
                return video
            return None

        # 音频
        if tag_name == "audio":
            sources = self._get_multi_src(tag)
            if sources:
                audio = AudioContent(url=sources[0])
                self._append_media(audio)
                return audio
            return None

        # 链接
        if tag_name == "a":
            href = tag.get("href", "")
            text = tag.get_text().strip()
            if not href:
                return TextContent(text=text)
            if href.startswith("javascript"):
                return TextContent(text=text)
            url = self._resolve_url(href)
            if url.startswith("http"):
                if url not in self._seen_links:
                    self._seen_links.add(url)
                    self.links.append(url)
                if self._is_file_link(tag, url):
                    file_item = FileContent(url=url, name=text)
                    self._append_media(file_item)
                    return file_item
                return LinkContent(text=text or url, url=url)
            return TextContent(text=f"{text} ({href})" if text else href)

        # 段落
        if tag_name in ("p", "section"):
            children = await self._parse_children(tag.children)
            if children:
                return children + [TextContent(text="\n\n")]
            return None

        # 换行
        if tag_name == "br":
            return TextContent(text="\n")

        # 标题
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            children = await self._parse_children(tag.children)
            if children:
                return [TextContent(text="\n")] + children + [TextContent(text="\n\n")]
            return None

        # 列表
        if tag_name in ("ul", "menu", "dir"):
            return await self._parse_children(tag.children)
        if tag_name == "ol":
            return await self._parse_ordered_list(tag)
        if tag_name == "li":
            children = await self._parse_children(tag.children)
            if children:
                return [TextContent(text="• ")] + children + [TextContent(text="\n")]
            return None

        # 分隔
        if tag_name == "hr":
            return TextContent(text="\n---\n")

        # 引用
        if tag_name == "blockquote":
            children = await self._parse_children(tag.children)
            if children:
                return [TextContent(text="\n> ")] + children + [TextContent(text="\n")]
            return None

        if tag_name == "q":
            children = await self._parse_children(tag.children)
            if children:
                return [TextContent(text="“")] + children + [TextContent(text="”")]
            return None

        # 文本样式（markdown 轻量保留语义）
        if tag_name in ("b", "strong"):
            text = tag.get_text().strip()
            return TextContent(text=f"**{text}**") if text else None

        if tag_name in ("i", "em"):
            text = tag.get_text().strip()
            return TextContent(text=f"*{text}*") if text else None

        if tag_name in ("u", "ins"):
            text = tag.get_text().strip()
            return TextContent(text=f"__{text}__") if text else None

        # 代码
        if tag_name == "code":
            text = tag.get_text()
            return TextContent(text=f"`{text}`")

        if tag_name == "pre":
            text = tag.get_text()
            return TextContent(text=f"\n```\n{text}\n```\n")

        if tag_name == "iframe":
            src = tag.get("src", "")
            if src:
                url = self._resolve_url(src)
                return TextContent(text=f"\n[嵌入内容: {url}]\n")
            return None

        # 表格（简化处理）
        if tag_name == "table":
            return await self._parse_table(tag)

        # 其他标签，递归处理子元素
        return await self._parse_children(tag.children)

    async def _parse_ordered_list(self, ordered_list: Tag) -> list[TextContent]:
        """解析有序列表"""
        result: list[TextContent] = []
        index = 1
        for li in ordered_list.find_all("li", recursive=False):
            children = await self._parse_children(li.children)
            if children:
                result.append(TextContent(text=f"{index}. "))
                result.extend(children)
                result.append(TextContent(text="\n"))
                index += 1
        return result

    async def _parse_table(self, table: Tag) -> list[TextContent] | None:
        """将表格简化为按行文本，避免完全丢失信息"""
        rows = table.find_all("tr")
        if not rows:
            return None

        result: list[TextContent] = [TextContent(text="\n")]
        for row in rows:
            cols = row.find_all(("th", "td"))
            values: list[str] = []
            for col in cols:
                parsed = await self._parse_children(col.children)
                plain = "".join(item.get_plain() for item in parsed).strip()
                if plain:
                    values.append(plain)
            if values:
                result.append(TextContent(text=" | ".join(values)))
                result.append(TextContent(text="\n"))

        if len(result) <= 1:
            return None
        result.append(TextContent(text="\n"))
        return result

    def _append_media(
        self, media: ImageContent | VideoContent | AudioContent | FileContent
    ) -> None:
        """按 URL 去重收集媒体"""
        if media.url not in self._seen_media:
            self._seen_media.add(media.url)
            self.media.append(media)

    def _append_mention(self, mention: MentionContent) -> None:
        """按 target 去重收集提及组件"""
        if mention.target and mention.target not in self._seen_mentions:
            self._seen_mentions.add(mention.target)
            self.mentions.append(mention)

    @staticmethod
    def _is_file_link(tag: Tag, url: str) -> bool:
        """识别文件链接，避免将普通页面链接误判为文件。"""
        if tag.has_attr("download"):
            return True
        path = (urlparse(url).path or "").lower()
        file_exts = (
            ".zip",
            ".rar",
            ".7z",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".txt",
            ".csv",
            ".epub",
            ".mobi",
            ".apk",
            ".exe",
            ".msi",
            ".dmg",
            ".mp3",
            ".wav",
            ".ogg",
            ".flac",
            ".mp4",
            ".mkv",
            ".mov",
            ".avi",
        )
        return path.endswith(file_exts)

    def _choose_image_src(self, tag: Tag) -> str:
        """优先从 srcset 选择最优图片源"""
        srcset = tag.get("srcset", "")
        if srcset:
            best_url = ""
            best_score = -1.0
            for part in srcset.split(","):
                token = part.strip().split()
                if not token:
                    continue
                url = token[0]
                score = 1.0
                if len(token) > 1:
                    size = token[1]
                    if size.endswith("w"):
                        try:
                            score = float(size[:-1])
                        except ValueError:
                            score = 1.0
                    elif size.endswith("x"):
                        try:
                            score = float(size[:-1]) * 1000.0
                        except ValueError:
                            score = 1.0
                if score > best_score:
                    best_score = score
                    best_url = url
            if best_url:
                return best_url

        # 一些 RSS/站点会使用 lazy-load 字段承载真实图片地址
        for key in (
            "src",
            "data-src",
            "data-original",
            "data-lazy-src",
            "data-url",
            "data-fallback-src",
        ):
            value = tag.get(key, "")
            if value:
                return value
        return ""

    def _get_multi_src(self, tag: Tag) -> list[str]:
        """获取 media 标签中的多来源 URL"""
        urls: list[str] = []
        src = tag.get("src", "")
        if src:
            urls.append(self._resolve_url(src))

        for source in tag.find_all("source"):
            source_src = source.get("src", "")
            if source_src:
                urls.append(self._resolve_url(source_src))

        # 保留顺序去重
        deduped: list[str] = []
        seen: set[str] = set()
        for item in urls:
            if item and item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    def _resolve_url(self, url: str) -> str:
        """解析相对 URL"""
        if not url:
            return ""
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("//"):
            return f"https:{url}"
        if self.feed_link:
            return urljoin(self.feed_link, url)
        return url

    def get_plain_text(self) -> str:
        """
        获取纯文本内容

        Returns:
            纯文本字符串
        """
        if not self.soup:
            return ""

        # 移除脚本和样式
        for element in self.soup(["script", "style", "noscript"]):
            element.decompose()

        # 获取文本
        text = self.soup.get_text()

        # 清理空白
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk)

        return text


async def parse_html(html: str, feed_link: str | None = None) -> ParsedResult:
    """
    解析 HTML 内容

    Args:
        html: HTML 内容
        feed_link: feed 链接

    Returns:
        ParsedResult 对象
    """
    parser = HTMLParser(html, feed_link)
    return await parser.parse()
