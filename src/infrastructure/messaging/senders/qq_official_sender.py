"""QQ 官方 Bot 消息发送器

针对 QQ 官方 Bot 的特定优化。
组件排序由 MessageFormatter 统一处理，此处只负责发送。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ....shared.constants import (
    QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL,
    QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK,
    QQ_OFFICIAL_DEGRADE_STRATEGY_LINK_ONLY,
)
from ...pipeline import MessageComponent
from .base_sender import DefaultMessageSender
from .types import MessageContext, SendRequest, SendResult

if TYPE_CHECKING:
    pass


class QQOfficialMessageSender(DefaultMessageSender):
    """QQ 官方 Bot 消息发送器

    特性：
    - 支持 Markdown 消息
    - 组件排序由 MessageFormatter 统一
    - 多媒体消息按媒体优先、文本最后拆分发送
    """

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送消息到 QQ 官方 Bot"""
        try:
            prepared_media = await self._prepare_effective_media(request, context)
            if self._is_original_style(context) and request.layout:
                prepared_media_by_url = {
                    pm.original_url: pm
                    for pm in (prepared_media or [])
                    if pm.original_url
                }
                layout_components = self._layout_to_components(
                    request, prepared_media_by_url=prepared_media_by_url
                )
                threshold_result = await self._maybe_send_threshold_degrade(
                    request,
                    layout_components,
                )
                if threshold_result is not None:
                    return threshold_result
                return await self._send_components_in_order(
                    request.session_id,
                    layout_components,
                    combine_image_text=True,
                    default_text=request.message,
                )

            components = self._build_components(
                request,
                prepared_media,
                context,
                platform="qq_official",
            )
            has_media = any(self._is_media_component(item) for item in components)
            if not has_media:
                return await super().send_to_user(request, context)
            threshold_result = await self._maybe_send_threshold_degrade(
                request,
                components,
            )
            if threshold_result is not None:
                return threshold_result
            if self._can_send_single_image_with_text(components):
                chain = self._chain_from_components(components)
                if not chain:
                    return SendResult(ok=False, detail="empty_message")
                result = await self._send_chain(request.session_id, chain)
                if result.ok:
                    return result
                return await self._handle_single_image_text_failure(
                    request,
                    components,
                    first_failure=result,
                )
            return await self._send_components_media_first(
                request.session_id,
                components,
                default_text=request.message,
            )
        except Exception as err:
            return SendResult(
                ok=False,
                transient=self._is_transient_network_error(err),
                detail=self._normalize_error_detail(str(err)),
            )

    @staticmethod
    def _can_send_single_image_with_text(components) -> bool:
        media = [item for item in components if item.kind == "media"]
        tails = [item for item in components if item.kind == "tail"]
        texts = [item for item in components if item.kind == "text" and item.text]
        return (
            len(media) == 1
            and media[0].media_type == "image"
            and not tails
            and len(texts) == 1
        )

    def _should_degrade_for_media_count(
        self,
        components: list[MessageComponent],
    ) -> bool:
        if any(
            item.kind == "media" and item.media_type == "video" for item in components
        ):
            return True
        threshold = self._get_qq_official_media_threshold()
        if threshold <= 0:
            return False
        media_count = sum(1 for item in components if self._is_media_component(item))
        return media_count > threshold

    async def _maybe_send_threshold_degrade(
        self,
        request: SendRequest,
        components: list[MessageComponent],
    ) -> SendResult | None:
        if not self._should_degrade_for_media_count(components):
            return None

        strategy = self._get_qq_official_degrade_strategy()
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL:
            return SendResult(
                ok=False,
                transient=False,
                detail="qq_official_media_threshold_exceeded",
            )
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_LINK_ONLY:
            return await self._send_link_only_degrade(request, components)
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK:
            if not self._can_degrade_media_as_files(components):
                return None
            return await self._send_file_then_link_degrade(request, components)
        return None

    async def _handle_single_image_text_failure(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        first_failure: SendResult,
    ) -> SendResult:
        image_component = next(
            item
            for item in components
            if item.kind == "media" and item.media_type == "image"
        )
        strategy = self._get_qq_official_degrade_strategy()
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL:
            return first_failure

        failures = [first_failure]
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK:
            file_result = await self._send_media_as_file(
                request.session_id,
                image_component,
            )
            if file_result.ok:
                text_result = await self._send_failed_media_links_text(
                    request,
                    components,
                    [],
                )
                if not text_result.ok:
                    failures.append(text_result)
                return self._partial_send_result(failures)
            failures.append(file_result)

        text_result = await self._send_failed_media_links_text(
            request,
            components,
            [image_component.original_url],
        )
        if not text_result.ok:
            failures.append(text_result)
        return self._partial_send_result(failures)

    async def _send_link_only_degrade(
        self,
        request: SendRequest,
        components: list[MessageComponent],
    ) -> SendResult:
        failed_urls = [
            item.original_url for item in components if self._is_media_component(item)
        ]
        return await self._send_failed_media_links_text(
            request, components, failed_urls
        )

    async def _send_file_then_link_degrade(
        self,
        request: SendRequest,
        components: list[MessageComponent],
    ) -> SendResult:
        media_components = [
            item for item in components if self._is_media_component(item)
        ]
        failures: list[SendResult] = []
        failed_urls: list[str] = []

        for component in media_components:
            file_result = await self._send_media_as_file(request.session_id, component)
            if not file_result.ok:
                self._record_failed_url(failed_urls, component)
                failures.append(file_result)

        text_result = await self._send_failed_media_links_text(
            request,
            components,
            failed_urls,
        )
        if not text_result.ok:
            failures.append(text_result)
        return self._partial_send_result(failures)

    @staticmethod
    def _can_degrade_media_as_files(components: list[MessageComponent]) -> bool:
        media_components = [
            item
            for item in components
            if item.kind in {"media", "tail"} and item.original_url
        ]
        if not media_components:
            return False
        return all(item.file and "://" not in item.file for item in media_components)

    async def _send_failed_media_links_text(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        failed_urls: list[str],
    ) -> SendResult:
        text = "\n".join(
            item.text for item in components if item.kind == "text" and item.text
        ).strip()
        text = self._append_failed_links(text or request.message, failed_urls)
        if not text:
            return SendResult(ok=False, detail="empty_message")

        from astrbot.api.message_components import Plain

        return await self._send_chain(request.session_id, [Plain(text)])

    async def _send_media_as_file(
        self,
        session_id: str,
        component: MessageComponent,
    ) -> SendResult:
        file_path = str(component.file or "").strip()
        if not file_path or "://" in file_path:
            return SendResult(ok=False, detail="degrade_file_unavailable")

        from astrbot.api.message_components import File

        name = component.name or Path(file_path).name or "attachment"
        return await self._send_chain(
            session_id,
            [
                File(
                    name=name,
                    file=file_path,
                    url=component.original_url,
                )
            ],
        )
