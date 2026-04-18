"""
RSS-to-AstrBot Post Formatter
RSS内容格式化器，用于生成推送消息
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .html_parser import (
    AudioContent,
    FileContent,
    ImageContent,
    MentionContent,
    VideoContent,
    parse_html,
)


@dataclass
class Media:
    """媒体对象"""

    url: str
    type: str = "image"  # image, video, audio
    width: int = 0
    height: int = 0


@dataclass
class Mention:
    """提及对象"""

    target: str
    name: str = ""


class PostFormatter:
    """RSS内容格式化基类。"""

    def __init__(
        self,
        html: str,
        title: str | None = None,
        feed_title: str | None = None,
        link: str | None = None,
        author: str | None = None,
        tags: list[str] | None = None,
        feed_link: str | None = None,
        enclosures: list | None = None,
    ):
        self.html = html or ""
        self.title = title
        self.feed_title = feed_title
        self.link = link
        self.author = author
        self.tags = tags or []
        self.feed_link = feed_link
        self.enclosures = enclosures or []
        self.media: list[Media] = []
        self.mentions: list[Mention] = []

        self._parse_enclosures()

    def _parse_enclosures(self):
        for enc in self.enclosures:
            if not hasattr(enc, "url"):
                continue
            enc_type = getattr(enc, "type", "") or ""
            media_type = (
                "image"
                if enc_type.startswith("image")
                else "video"
                if enc_type.startswith("video")
                else "audio"
                if enc_type.startswith("audio")
                else "file"
            )
            self.media.append(Media(url=enc.url, type=media_type))

    def _append_media(self, url: str, media_type: str) -> None:
        if not url:
            return
        if any(m.url == url for m in self.media):
            return
        self.media.append(Media(url=url, type=media_type))

    def _append_mention(self, mention: MentionContent) -> None:
        target = (mention.target or "").strip()
        if not target:
            return
        if any(m.target == target for m in self.mentions):
            return
        self.mentions.append(Mention(target=target, name=mention.name or ""))

    @staticmethod
    def _strip_media_placeholders(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"\[图片(?::[^]]*)?]", "", text)
        text = re.sub(r"\[(视频|音频|文件(?::[^]]*)?)]", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _build_via_line(
        self,
        *,
        entry_link: str,
        display_via: int,
        display_author: int,
    ) -> str:
        raise NotImplementedError

    async def get_formatted_post(
        self,
        sub_title: str | None = None,
        tags: list[str] | None = None,
        send_mode: int = 0,
        length_limit: int = 0,
        link_preview: int = 0,
        display_author: int = 0,
        display_via: int = 0,
        display_title: int = 0,
        display_entry_tags: int = -1,
        style: int = 0,
        display_media: int = 0,
    ) -> tuple[str, bool, bool] | None:
        parsed = await parse_html(self.html, self.feed_link)
        content = self._strip_media_placeholders(parsed.html_tree.get_plain())

        for parsed_media_item in parsed.media:
            if isinstance(parsed_media_item, ImageContent):
                self._append_media(parsed_media_item.url, "image")
            elif isinstance(parsed_media_item, VideoContent):
                self._append_media(parsed_media_item.url, "video")
            elif isinstance(parsed_media_item, AudioContent):
                self._append_media(parsed_media_item.url, "audio")
            elif isinstance(parsed_media_item, FileContent):
                self._append_media(parsed_media_item.url, "file")

        for mention in parsed.mentions:
            self._append_mention(mention)

        if send_mode == -1 and self.link:
            return self.link, False, True

        parts: list[str] = []

        if (
            display_title >= 0
            and self.title
            and (display_title == 1 or (display_title == 0 and self.title))
        ):
            parts.append(f"{self.title}\n")

        if display_entry_tags >= 0 and tags:
            tag_str = " ".join(f"#{tag}" for tag in tags if tag)
            if tag_str:
                parts.append(f"{tag_str}\n")

        if content:
            if length_limit > 0 and len(content) > length_limit:
                content = content[:length_limit].rstrip() + "..."
            if parts:
                parts.append("\n")
            parts.append(content)

        entry_link = self.link if self.link else ""
        via_line = self._build_via_line(
            entry_link=entry_link,
            display_via=display_via,
            display_author=display_author,
        )

        if via_line:
            if parts:
                parts.append("\n\n")
            parts.append(via_line)
        elif entry_link:
            if parts:
                parts.append("\n\n")
            parts.append(entry_link)

        result = ""
        for part in parts:
            result += part
        result = result.strip()
        if not result:
            return None

        need_media = display_media >= 0 and any(
            media_item.type in ("image", "video", "audio", "file")
            for media_item in self.media
        )
        need_link_preview = self.link is not None and link_preview >= 0

        return result, need_media, need_link_preview


class SimplePostFormatter(PostFormatter):
    """默认纯文本 formatter。"""

    def _build_via_line(
        self,
        *,
        entry_link: str,
        display_via: int,
        display_author: int,
    ) -> str:
        via_line = ""
        if display_via > -2 and entry_link:
            via_line = f"via {entry_link}"
            if self.feed_title:
                via_line += f" | {self.feed_title}"
            if display_author >= 0 and self.author:
                via_line += f" (author: {self.author})"
        elif display_author >= 0 and self.author:
            via_line = f"author: {self.author}"
        return via_line


class MarkdownPostFormatter(PostFormatter):
    """适用于支持 markdown 的平台。"""

    def _build_via_line(
        self,
        *,
        entry_link: str,
        display_via: int,
        display_author: int,
    ) -> str:
        title = (self.feed_title or "via").strip() or "via"

        if display_via > -2 and entry_link:
            via_line = f"via [{title}]({entry_link})"
            if display_author >= 0 and self.author:
                via_line += f" | author: {self.author}"
            return via_line

        if display_author >= 0 and self.author:
            return f"author: {self.author}"

        return ""
