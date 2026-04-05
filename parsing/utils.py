"""
RSS-to-AstrBot Parsing Utils
RSS内容解析工具
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Enclosure:
    """附件"""

    url: str
    length: int = 0
    type: str = ""


@dataclass
class EntryParsed:
    """解析后的条目"""

    title: str = ""
    link: str = ""
    author: str = ""
    content: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    enclosures: list[Enclosure] = field(default_factory=list)
    published: datetime | None = None
    updated: datetime | None = None


async def parse_entry(entry, feed_link: str = None) -> EntryParsed:
    """
    解析RSS条目

    Args:
        entry: feedparser条目对象
        feed_link: feed链接（用于解析相对链接）

    Returns:
        EntryParsed对象
    """
    result = EntryParsed()

    # 基本信息
    result.title = _get_text(entry.get("title", ""))
    result.link = _get_link(entry, feed_link)
    result.author = _get_text(entry.get("author", ""))

    # 内容
    content = entry.get("content", [])
    if content:
        # 取第一个内容，保留原始 HTML 供后续组件解析
        result.content = content[0].get("value", "")

    summary = entry.get("summary") or entry.get("description")
    if summary:
        # 保留原始 HTML；纯文本提取留给格式化阶段
        result.summary = str(summary)

    # 如果没有 content，使用 summary（同样保留 HTML）
    if not result.content:
        result.content = result.summary

    # 标签
    tags = entry.get("tags", [])
    result.tags = [tag.get("term", "") for tag in tags if tag.get("term")]

    # 附件
    enclosures = entry.get("enclosures", [])
    result.enclosures = [
        Enclosure(
            url=e.get("href", ""),
            length=int(e.get("length", 0)),
            type=e.get("type", ""),
        )
        for e in enclosures
        if e.get("href")
    ]

    # 时间
    if entry.get("published_parsed"):
        try:
            result.published = datetime(*entry.published_parsed[:6])
        except Exception:
            pass
    if entry.get("updated_parsed"):
        try:
            result.updated = datetime(*entry.updated_parsed[:6])
        except Exception:
            pass

    return result


def _get_text(html: str) -> str:
    """
    从HTML中提取纯文本

    简单实现，去除HTML标签
    """
    import re

    # 移除HTML标签
    text = re.sub(r"<[^>]+>", "", html)
    # 解码HTML实体
    import html

    text = html.unescape(text)
    return text.strip()


def _get_link(entry, feed_link: str = None) -> str:
    """获取条目链接"""
    # 尝试多种方式获取链接
    link = entry.get("link") or entry.get("guid")

    if link and not link.startswith("http"):
        # 相对链接，需要补全
        if feed_link:
            from urllib.parse import urljoin

            link = urljoin(feed_link, link)

    return link or ""
