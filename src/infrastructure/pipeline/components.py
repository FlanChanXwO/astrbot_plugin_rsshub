"""Platform-neutral message components and ordering rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ...domain.entities.content_types import is_generated_media_url

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
    fallback_text: str = ""


class MessageComponentSorter:
    """Build and sort platform-neutral message components."""

    def build_components(
        self,
        prepared_media: list[PreparedMedia] | None,
        text: str,
        failed_urls: list[str] | None,
        platform: str = "",
    ) -> list[MessageComponent]:
        failed = self._collect_failed_urls(prepared_media, failed_urls)
        components = self._build_media_components(prepared_media)
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
    ) -> list[MessageComponent]:
        components: list[MessageComponent] = []
        if not prepared_media:
            return components
        from ..utils.media_dispatch import MediaDispatchResolver

        for item in prepared_media:
            if item.download_failed:
                continue
            if not item.local_path and not item.original_url:
                continue
            dispatch = MediaDispatchResolver.resolve_prepared(item)
            if not dispatch.media_type:
                continue
            components.append(
                MessageComponent(
                    kind=dispatch.component_kind,
                    media_type=dispatch.media_type,
                    file=dispatch.file,
                    original_url=dispatch.original_url,
                    name=dispatch.name,
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
                if (
                    item.download_failed
                    and item.original_url not in failed
                    and not item.generated
                    and not is_generated_media_url(item.original_url)
                ):
                    failed.append(item.original_url)
        return failed
