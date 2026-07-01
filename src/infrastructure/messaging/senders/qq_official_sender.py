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
    QQ_OFFICIAL_MARKDOWN_MODE_AUTO,
    QQ_OFFICIAL_MARKDOWN_MODE_OPTIONS,
)
from ...pipeline import MessageComponent
from .base_sender import DefaultMessageSender
from .types import MessageContext, SendRequest, SendResult

if TYPE_CHECKING:
    pass


class QQOfficialMessageSender(DefaultMessageSender):
    """QQ 官方 Bot 消息发送器

    特性：
    - 主动推送临时统一纯文本
    - 组件排序由 MessageFormatter 统一
    - 多媒体消息按媒体优先、文本最后拆分发送
    """

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送消息到 QQ 官方 Bot"""
        prepared_media = None
        cleanup_owned = request.prepared_media is None
        try:
            use_markdown = self._use_markdown_for_context(context)
            prepared_media = await self._prepare_effective_media(request, context)
            prepared_media_by_url = {
                pm.original_url: pm for pm in (prepared_media or []) if pm.original_url
            }
            if self._is_original_style(context) and request.layout:
                layout_components = self._layout_to_components(
                    request, prepared_media_by_url=prepared_media_by_url
                )
                layout_components = self._apply_first_send_candidates(
                    layout_components,
                    prepared_media_by_url,
                    platform="qq_official",
                )
                threshold_result = await self._maybe_send_threshold_degrade(
                    request,
                    layout_components,
                    use_markdown=use_markdown,
                )
                if threshold_result is not None:
                    return threshold_result
                if self._single_video_component(layout_components) is not None:
                    return await self._send_single_video_then_fallback(
                        request,
                        layout_components,
                        use_markdown=use_markdown,
                    )
                return await self._send_components_in_order(
                    request.session_id,
                    layout_components,
                    combine_image_text=True,
                    default_text=request.message,
                    use_markdown=use_markdown,
                    prepared_media_by_url=prepared_media_by_url,
                    platform="qq_official",
                )

            components = self._build_components(
                request,
                prepared_media,
                context,
                platform="qq_official",
            )
            components = self._apply_first_send_candidates(
                components,
                prepared_media_by_url,
                platform="qq_official",
            )
            has_media = any(self._is_media_component(item) for item in components)
            if not has_media:
                chain = self._chain_from_components(components)
                if not chain:
                    return SendResult(ok=False, detail="empty_message")
                return await self._send_chain(
                    request.session_id,
                    chain,
                    use_markdown=use_markdown,
                )
            threshold_result = await self._maybe_send_threshold_degrade(
                request,
                components,
                use_markdown=use_markdown,
            )
            if threshold_result is not None:
                return threshold_result
            if self._can_send_single_image_with_text(components):
                chain = self._chain_from_components(components)
                if not chain:
                    return SendResult(ok=False, detail="empty_message")
                result = await self._send_chain(
                    request.session_id,
                    chain,
                    use_markdown=use_markdown,
                )
                if result.ok:
                    return result
                return await self._handle_single_image_text_failure(
                    request,
                    components,
                    first_failure=result,
                    use_markdown=use_markdown,
                    prepared_media_by_url=prepared_media_by_url,
                )
            if self._single_video_component(components) is not None:
                return await self._send_single_video_then_fallback(
                    request,
                    components,
                    use_markdown=use_markdown,
                    prepared_media_by_url=prepared_media_by_url,
                )
            return await self._send_components_media_first(
                request.session_id,
                components,
                default_text=request.message,
                use_markdown=use_markdown,
                prepared_media_by_url=prepared_media_by_url,
                platform="qq_official",
            )
        except Exception as err:
            return SendResult(
                ok=False,
                transient=self._is_transient_network_error(err),
                detail=self._stage_error_detail("qq_official_send", str(err)),
            )
        finally:
            if cleanup_owned:
                self._cleanup_owned_paths(prepared_media)

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
        threshold = self._get_qq_official_media_threshold()
        if threshold <= 0:
            return False
        media_count = sum(1 for item in components if self._is_media_component(item))
        return media_count > threshold

    def _single_video_component(
        self,
        components: list[MessageComponent],
    ) -> MessageComponent | None:
        media_components = [
            item for item in components if self._is_media_component(item)
        ]
        if (
            len(media_components) == 1
            and media_components[0].kind == "media"
            and media_components[0].media_type == "video"
        ):
            return media_components[0]
        return None

    async def _send_single_video_then_fallback(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None = None,
        prepared_media_by_url: dict | None = None,
    ) -> SendResult:
        video_component = self._single_video_component(components)
        if video_component is None:
            return await self._send_components_media_first(
                request.session_id,
                components,
                default_text=request.message,
                use_markdown=use_markdown,
                prepared_media_by_url=prepared_media_by_url,
                platform="qq_official",
            )

        chain = self._component_to_chain(video_component)
        if not chain:
            return SendResult(ok=False, detail="empty_message")

        video_result = await self._send_chain(
            request.session_id,
            chain,
            use_markdown=use_markdown,
        )
        if not video_result.ok:
            return await self._handle_single_video_failure(
                request,
                components,
                video_component=video_component,
                first_failure=video_result,
                use_markdown=use_markdown,
                prepared_media_by_url=prepared_media_by_url,
            )

        failures: list[SendResult] = []
        text = "\n".join(
            item.text for item in components if item.kind == "text" and item.text
        ).strip()
        if text:
            from astrbot.api.message_components import Plain

            text_result = await self._send_chain(
                request.session_id,
                [Plain(text)],
                use_markdown=use_markdown,
            )
            if not text_result.ok:
                failures.append(self._result_with_stage(text_result, "send_text"))
        return self._partial_send_result(failures)

    async def _maybe_send_threshold_degrade(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None = None,
    ) -> SendResult | None:
        if not self._should_degrade_for_media_count(components):
            return None

        strategy = self._get_qq_official_degrade_strategy()
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL:
            return SendResult(
                ok=False,
                transient=False,
                detail=self._stage_error_detail(
                    "degrade_threshold",
                    "qq_official_media_threshold_exceeded",
                ),
            )
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_LINK_ONLY:
            return await self._send_link_only_degrade(
                request,
                components,
                use_markdown=use_markdown,
            )
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK:
            if not self._can_degrade_media_as_files(components):
                return None
            return await self._send_file_then_link_degrade(
                request,
                components,
                use_markdown=use_markdown,
            )
        return None

    async def _handle_single_image_text_failure(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        first_failure: SendResult,
        use_markdown: bool | None = None,
        prepared_media_by_url: dict | None = None,
    ) -> SendResult:
        image_component = next(
            item
            for item in components
            if item.kind == "media" and item.media_type == "image"
        )
        strategy = self._get_qq_official_degrade_strategy()
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL:
            return self._result_with_stage(first_failure, "send_image_text")

        failures = [self._result_with_stage(first_failure, "send_image_text")]
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK:
            fallback = await self._send_component_fallback_candidates(
                request.session_id,
                image_component,
                prepared_media_by_url=prepared_media_by_url,
                platform="qq_official",
                skip_first_file=image_component.file,
                use_markdown=use_markdown,
            )
            failures.extend(fallback.failures)
            if fallback.ok:
                text_result = await self._send_failed_media_links_text(
                    request,
                    components,
                    [],
                    use_markdown=use_markdown,
                )
                if not text_result.ok:
                    failures.append(
                        self._result_with_stage(text_result, "degrade_text")
                    )
                    return self._partial_send_result(failures)
                return SendResult(ok=True)

        text_result = await self._send_failed_media_links_text(
            request,
            components,
            [image_component.original_url],
            use_markdown=use_markdown,
        )
        if not text_result.ok:
            failures.append(self._result_with_stage(text_result, "degrade_text"))
            return self._partial_send_result(failures)
        return SendResult(ok=True)

    async def _handle_single_video_failure(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        video_component: MessageComponent,
        first_failure: SendResult,
        use_markdown: bool | None = None,
        prepared_media_by_url: dict | None = None,
    ) -> SendResult:
        strategy = self._get_qq_official_degrade_strategy()
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL:
            return self._result_with_stage(first_failure, "send_video")

        failures = [self._result_with_stage(first_failure, "send_video")]
        failed_urls: list[str] = []

        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK:
            fallback = await self._send_component_fallback_candidates(
                request.session_id,
                video_component,
                prepared_media_by_url=prepared_media_by_url,
                platform="qq_official",
                skip_first_file=video_component.file,
                use_markdown=use_markdown,
            )
            failures.extend(fallback.failures)
            if fallback.ok:
                text_result = await self._send_failed_media_links_text(
                    request,
                    components,
                    [],
                    use_markdown=use_markdown,
                )
                if not text_result.ok:
                    failures.append(
                        self._result_with_stage(text_result, "degrade_text")
                    )
                    return self._partial_send_result(failures)
                return SendResult(ok=True)

        self._record_failed_url(failed_urls, video_component)
        text_result = await self._send_failed_media_links_text(
            request,
            components,
            failed_urls,
            use_markdown=use_markdown,
        )
        if not text_result.ok:
            failures.append(self._result_with_stage(text_result, "degrade_text"))
            return self._partial_send_result(failures)
        return SendResult(ok=True)

    async def _send_link_only_degrade(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        failed_urls = [
            item.original_url for item in components if self._is_media_component(item)
        ]
        return await self._send_failed_media_links_text(
            request,
            components,
            failed_urls,
            use_markdown=use_markdown,
        )

    async def _send_file_then_link_degrade(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        media_components = [
            item for item in components if self._is_media_component(item)
        ]
        failures: list[SendResult] = []
        failed_urls: list[str] = []

        for component in media_components:
            fallback = await self._send_component_fallback_candidates(
                request.session_id,
                component,
                prepared_media_by_url=None,
                platform="qq_official",
            )
            if not fallback.ok:
                self._record_failed_url(failed_urls, component)
            failures.extend(fallback.failures)

        text_result = await self._send_failed_media_links_text(
            request,
            components,
            failed_urls,
            use_markdown=use_markdown,
        )
        if not text_result.ok:
            failures.append(self._result_with_stage(text_result, "degrade_text"))
            return self._partial_send_result(failures)
        return SendResult(ok=True)

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
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        text = "\n".join(
            item.text for item in components if item.kind == "text" and item.text
        ).strip()
        text = self._append_failed_links(text or request.message, failed_urls)
        if not text:
            return SendResult(ok=False, detail="empty_message")

        from astrbot.api.message_components import Plain

        return await self._send_chain(
            request.session_id,
            [Plain(text)],
            use_markdown=use_markdown,
        )

    @staticmethod
    def _markdown_mode_for_context(context: MessageContext | None) -> str:
        strategy = getattr(context, "sender_strategy", None)
        mode = str(
            getattr(strategy, "markdown_mode", "")
            or (strategy.get("markdown_mode", "") if isinstance(strategy, dict) else "")
            or QQ_OFFICIAL_MARKDOWN_MODE_AUTO
        )
        if mode not in QQ_OFFICIAL_MARKDOWN_MODE_OPTIONS:
            return QQ_OFFICIAL_MARKDOWN_MODE_AUTO
        return mode

    @classmethod
    def _use_markdown_for_context(
        cls,
        context: MessageContext | None,
    ) -> bool | None:
        # Temporary compatibility guard: QQ Official active pushes stay plain text
        # until AstrBot core no longer leaks Markdown syntax in normal payloads.
        return False

    async def _send_media_as_file(
        self,
        session_id: str,
        component: MessageComponent,
    ) -> SendResult:
        file_path = str(component.file or "").strip()
        if not file_path or "://" in file_path:
            return SendResult(
                ok=False,
                detail=self._stage_error_detail(
                    "degrade_file",
                    "degrade_file_unavailable",
                ),
            )

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
