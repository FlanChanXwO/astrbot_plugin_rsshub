"""微信 Official Account 消息发送器。

微信官方号不可靠支持图文组件同发，因此媒体必须逐条发送，文本最后发送。
"""

from __future__ import annotations

from .base_sender import DefaultMessageSender
from .types import MessageContext, SendRequest, SendResult


class WeixinOCMessageSender(DefaultMessageSender):
    """微信 Official Account 专用发送器。"""

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """按媒体逐条、文本最后的顺序发送。"""
        prepared_media = None
        cleanup_owned = request.prepared_media is None
        try:
            prepared_media = await self._prepare_effective_media(request, context)
            if self._is_original_style(context) and request.layout:
                prepared_media_by_url = {
                    pm.original_url: pm
                    for pm in (prepared_media or [])
                    if pm.original_url
                }
                return await self._send_components_in_order(
                    request.session_id,
                    self._layout_to_components(
                        request, prepared_media_by_url=prepared_media_by_url
                    ),
                    combine_image_text=False,
                    default_text=request.message,
                )

            components = self._build_components(
                request,
                prepared_media,
                context,
                platform="weixin_oc",
            )
            has_media = any(self._is_media_component(item) for item in components)
            if not has_media:
                return await super().send_to_user(request, context)
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
        finally:
            if cleanup_owned:
                self._cleanup_owned_paths(prepared_media)
