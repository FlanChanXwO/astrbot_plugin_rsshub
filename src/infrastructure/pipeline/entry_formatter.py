"""RSS entry text cleaning and formatting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...application.services.html_parser import HTMLParser


@dataclass(frozen=True)
class EffectivePushOptions:
    """Resolved push options for one subscription/user target."""

    notify: bool = True
    length_limit: int = 0
    display_author: int = 0
    display_via: int = 0
    display_title: int = 0
    display_entry_tags: bool = False
    style: int = 0
    display_media: bool = True


@dataclass(frozen=True)
class EntryFormatInput:
    """Normalized RSS entry data used by the text formatter."""

    title: str = ""
    content: str = ""
    summary: str = ""
    link: str = ""
    author: str = ""
    feed_title: str = ""
    feed_link: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


class EntryTextFormatter:
    """Format cleaned entry text according to effective push options."""

    async def format_entry(
        self,
        entry: EntryFormatInput,
        options: EffectivePushOptions | None = None,
    ) -> str:
        options = options or EffectivePushOptions()
        body = await self.clean_text(entry.content or entry.summary or "")
        title = await self.clean_text(entry.title)
        author = await self.clean_text(entry.author)
        feed_title = await self.clean_text(entry.feed_title)
        feed_link = str(entry.feed_link or "").strip()
        link = str(entry.link or "").strip()

        if options.display_title != -1:
            body = self._remove_repeated_title(body, title)
        if options.length_limit > 0 and body:
            body = self._truncate(body, options.length_limit)

        lines: list[str] = []
        if options.display_title != -1 and title:
            lines.append(title)
        if body:
            lines.append(body)
        if options.display_entry_tags and entry.tags:
            tags = " ".join(
                f"#{tag.strip().lstrip('#')}" for tag in entry.tags if tag.strip()
            )
            if tags:
                lines.append(tags)

        content = "\n\n".join(part for part in lines if part)
        via_suffix = self._build_via_suffix(
            link=link,
            feed_title=feed_title,
            feed_link=feed_link,
            author=author,
            options=options,
        )
        if via_suffix:
            return f"{content}\n\n{via_suffix}" if content else via_suffix
        return content

    @staticmethod
    async def clean_text(value: str) -> str:
        parsed = await HTMLParser(value or "").parse()
        text = parsed.html_tree.get_plain()
        text = remove_media_placeholders(text)
        return normalize_plain_text(text)

    @staticmethod
    def _remove_repeated_title(body: str, title: str) -> str:
        if not body or not title:
            return body
        stripped = body.strip()
        normalized_title = title.strip()
        if stripped == normalized_title:
            return ""
        if normalize_plain_text(stripped).replace("\n", " ") == normalize_plain_text(
            normalized_title
        ).replace("\n", " "):
            return ""
        if stripped.startswith(normalized_title + "\n"):
            return stripped[len(normalized_title) :].strip()
        return body

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if limit <= 0 or len(text) <= limit:
            return text
        if limit <= 3:
            return text[:limit]
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _build_via_suffix(
        *,
        link: str,
        feed_title: str,
        feed_link: str,
        author: str,
        options: EffectivePushOptions,
    ) -> str:
        if options.display_via == -2:
            return ""

        source = feed_title or feed_link
        if options.display_via == -1:
            source = ""

        parts: list[str] = []
        if link and source:
            parts.append(f"via {link} | {source}")
        elif link:
            parts.append(f"via {link}")
        elif source:
            parts.append(source)

        if options.display_author != -1 and author:
            if parts:
                parts[-1] += f" (author: {author})"
            else:
                parts.append(f"author: {author}")

        return " ".join(parts)


def normalize_plain_text(value: str) -> str:
    """Normalize whitespace without flattening meaningful line breaks."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_media_placeholders(value: str) -> str:
    text = re.sub(r"(?m)^\s*\[(视频|音频)\]\s*$\n?", "", value or "")
    text = re.sub(r"[ \t]*(\[视频\]|\[音频\])[ \t]*", " ", text)
    return text
