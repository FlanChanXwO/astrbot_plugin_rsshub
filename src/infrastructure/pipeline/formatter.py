"""消息格式化器

统一各平台消息组件（图片/文字/音频/文件）的排序规则。
senders 只管发送，排序逻辑全部集中在 Formatter 中。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain.entities.content_types import is_generated_media_url

if TYPE_CHECKING:
    from ..messaging.senders.types import PreparedMedia

from .components import MessageComponent, MessageComponentSorter


class MessageChainFormatter:
    """消息链格式化器

    根据平台特性将预处理后的媒体和文本组合为最终消息链。
    排序规则统一在此管理，senders 只调用 build_chain() 后发送。
    """

    _sorter: MessageComponentSorter = MessageComponentSorter()

    def build_components(
        self,
        prepared_media: list[PreparedMedia] | None,
        text: str,
        failed_urls: list[str],
        platform: str = "",
    ) -> list[MessageComponent]:
        """
        构建平台无关消息组件。
        """
        return self._sorter.build_components(
            prepared_media=prepared_media,
            text=text,
            failed_urls=failed_urls,
            platform=platform,
        )

    def build_chain(
        self,
        prepared_media: list[PreparedMedia] | None,
        text: str,
        failed_urls: list[str],
        platform: str = "",
    ) -> list:
        """
        构建最终消息链

        Args:
            prepared_media: 预处理后的媒体列表
            text: 文本内容
            failed_urls: 下载失败的媒体 URL 列表（可为空，内部会从 prepared_media 补充）
            platform: 平台名称（onebot/telegram/qidian/...）

        Returns:
            已排好序的消息链 list，可直接传入 MessageChain
        """
        if platform == "telegram":
            return self._build_telegram_chain(prepared_media, text, failed_urls)
        components = self.build_components(prepared_media, text, failed_urls, platform)
        return self._components_to_chain(components)

    @staticmethod
    def collect_original_urls(
        prepared_media: list[PreparedMedia] | None,
    ) -> list[str]:
        """Collect all original media URLs in first-seen order."""
        if not prepared_media:
            return []
        urls: list[str] = []
        seen: set[str] = set()
        for item in prepared_media:
            url = str(item.original_url or "").strip()
            if is_generated_media_url(url):
                continue
            if url and url not in seen:
                urls.append(url)
                seen.add(url)
        return urls

    # ------------------------------------------------------------------
    # 通用顺序：images → Plain → tails
    # ------------------------------------------------------------------

    def _components_to_chain(self, components: list[MessageComponent]) -> list:
        """Convert platform-neutral components to AstrBot message components."""
        from astrbot.api.message_components import File, Image, Plain, Record, Video

        chain: list = []
        for component in components:
            if component.kind == "text" and component.text:
                chain.append(Plain(component.text))
            elif component.kind == "media":
                match component.media_type:
                    case "image":
                        chain.append(Image(file=component.file))
                    case "video":
                        chain.append(Video(file=component.file))
            elif component.kind == "tail":
                match component.media_type:
                    case "audio":
                        chain.append(Record(file=component.file, text="audio"))
                    case "file":
                        chain.append(
                            File(
                                name=component.name or "attachment",
                                file=component.file,
                                url=component.original_url,
                            )
                        )
        return chain

    def _build_default_chain(
        self,
        prepared_media: list[PreparedMedia] | None,
        text: str,
        failed_urls: list[str],
    ) -> list:
        """通用消息链顺序：images → Plain → tails"""
        components = self.build_components(prepared_media, text, failed_urls)
        return self._components_to_chain(components)

    # ------------------------------------------------------------------
    # Telegram：media → caption（含失败链接）→ tails
    # ------------------------------------------------------------------

    def _build_telegram_chain(
        self,
        prepared_media: list[PreparedMedia] | None,
        text: str,
        failed_urls: list[str],
    ) -> list:
        """Telegram 消息链：media → Plain(caption) → tails"""
        from astrbot.api.message_components import Plain

        chain: list = []
        components = self.build_components(
            prepared_media,
            text,
            failed_urls,
            platform="telegram",
        )
        has_media = False

        for component in components:
            if component.kind == "media":
                has_media = True
                chain.extend(self._components_to_chain([component]))

        text_components = [
            component for component in components if component.kind == "text"
        ]
        tail_components = [
            component for component in components if component.kind == "tail"
        ]

        if has_media:
            for component in text_components:
                if component.text:
                    chain.append(Plain(component.text))
        else:
            chain.extend(self._components_to_chain(text_components))

        chain.extend(self._components_to_chain(tail_components))
        return chain

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _append_failed_links(text: str, failed_urls: list[str]) -> str:
        """将下载失败的媒体链接追加到文本末尾"""
        return MessageComponentSorter.append_failed_links(text, failed_urls)


# 兼容旧导入名；新代码优先使用 MessageChainFormatter。
MessageFormatter = MessageChainFormatter
