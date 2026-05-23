"""Platform-neutral message components and ordering rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from ..messaging.senders.types import PreparedMedia

MessageComponentKind = Literal["text", "media", "tail", "failed_url"]
MediaComponentType = Literal["image", "video", "audio", "file"]


@dataclass(frozen=True)
class MessageComponent:
    """A platform-neutral unit before sender-specific conversion."""

    kind: MessageComponentKind
    text: str = ""
    media_type: MediaComponentType | str = ""
    file: str = ""
    original_url: str = ""
    name: str = ""


class MessageComponentSorter:
    """Build and sort platform-neutral message components."""

    def build_components(
        self,
        prepared_media: list[PreparedMedia] | None,
        text: str,
        failed_urls: list[str] | None,
        platform: str = "",
        *,
        prefer_local_video: bool = True,
    ) -> list[MessageComponent]:
        failed = self._collect_failed_urls(prepared_media, failed_urls)
        components = self._build_media_components(
            prepared_media,
            prefer_local_video=prefer_local_video,
        )
        final_text = self.append_failed_links(text, failed)
        if final_text:
            components.append(MessageComponent(kind="text", text=final_text))
        return self.sort_components(components, platform=platform)

    def sort_components(
        self,
        components: list[MessageComponent],
        platform: str = "",
    ) -> list[MessageComponent]:
        """Return components in send-ready order for the target platform."""
        media_order = {
            "image": 0,
            "video": 1,
            "audio": 2,
            "file": 3,
        }

        onebot_like = platform in {"onebot", "onebot11", "onebotv11", "aiocqhttp"}

        def order(component: MessageComponent) -> tuple[int, int]:
            if component.kind == "media":
                return (media_order.get(component.media_type, 99), 0)
            if component.kind == "tail" and onebot_like:
                return (media_order.get(component.media_type, 99), 0)
            if component.kind == "text":
                return (100, 0)
            if component.kind == "tail":
                return (200, 0)
            return (300, 0)

        return sorted(components, key=order)

    @staticmethod
    def append_failed_links(text: str, failed_urls: list[str]) -> str:
        """Append failed media URLs to the message body."""
        if not failed_urls:
            return text
        unique: list[str] = []
        seen: set[str] = set()
        for url in failed_urls:
            if url and url not in seen:
                unique.append(url)
                seen.add(url)
        if not unique:
            return text
        lines = [text] if text else []
        lines.append("媒体原始链接:")
        lines.extend(unique)
        return "\n".join(lines)

    def _build_media_components(
        self,
        prepared_media: list[PreparedMedia] | None,
        *,
        prefer_local_video: bool,
    ) -> list[MessageComponent]:
        components: list[MessageComponent] = []
        if not prepared_media:
            return components
        for item in prepared_media:
            if item.download_failed:
                continue
            if not item.local_path and not item.original_url:
                continue
            path = self._resolve_media_path(item, prefer_local_video=prefer_local_video)
            if item.media_type == "audio":
                components.append(
                    MessageComponent(
                        kind="tail",
                        media_type="audio",
                        file=path,
                        original_url=item.original_url,
                    )
                )
                continue
            if item.media_type == "file":
                components.append(
                    MessageComponent(
                        kind="tail",
                        media_type="file",
                        file=path,
                        original_url=item.original_url,
                        name=self._filename_from_url(item.original_url),
                    )
                )
                continue
            components.append(
                MessageComponent(
                    kind="media",
                    media_type=item.media_type,
                    file=path,
                    original_url=item.original_url,
                )
            )
        return components

    @staticmethod
    def _collect_failed_urls(
        prepared_media: list[PreparedMedia] | None,
        failed_urls: list[str] | None,
    ) -> list[str]:
        failed = list(failed_urls or [])
        if prepared_media:
            for item in prepared_media:
                if item.download_failed and item.original_url not in failed:
                    failed.append(item.original_url)
        return failed

    @staticmethod
    def _resolve_media_path(
        item: PreparedMedia,
        *,
        prefer_local_video: bool,
    ) -> str:
        if item.media_type == "video" and not prefer_local_video:
            return item.original_url
        return str(item.local_path) if item.local_path else item.original_url

    @staticmethod
    def _filename_from_url(url: str) -> str:
        return unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "attachment"
