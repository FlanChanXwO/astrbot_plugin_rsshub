from __future__ import annotations

from astrbot.api import logger
from astrbot.api.message_components import Plain

from .base import MessageSender
from .types import NotifierContext, PreparedMedia, SendResult


class WeixinOCMessageSender(MessageSender):
    """Weixin personal sender: send one message component per request."""

    @classmethod
    async def _send_components_sequentially(
        cls,
        session_id: str,
        components: list,
    ) -> SendResult:
        for component in components:
            result = await cls._send_chain(session_id, [component])
            if not result.ok:
                return result
        return SendResult(ok=True)

    @classmethod
    async def send_to_user(
        cls,
        session_id: str,
        message: str,
        media: list[tuple[str, str]] | None = None,
        prepared_media: list[PreparedMedia] | None = None,
        context: NotifierContext | None = None,
    ) -> SendResult:
        logger.debug(
            "WeixinOC sender strategy: sequential single-component send, session=%s, has_media=%s, prepared_media=%s",
            session_id,
            bool(media),
            bool(prepared_media),
        )

        try:
            effective_prepared = prepared_media
            if effective_prepared is None and media:
                effective_prepared = await cls.prepare_media(media)

            image_components = []
            tail_components = []
            failed_media_urls: list[str] = []

            if effective_prepared:
                (
                    image_components,
                    tail_components,
                    failed_media_urls,
                ) = await cls._build_media_components(effective_prepared)

            message = cls._append_failed_media_links(message, failed_media_urls)

            if image_components:
                media_result = await cls._send_components_sequentially(
                    session_id,
                    image_components,
                )
                if not media_result.ok:
                    logger.warning(
                        "WeixinOC image/video send failed: session=%s, detail=%s",
                        session_id,
                        media_result.detail,
                    )
                    return media_result

            if tail_components:
                tail_result = await cls._send_components_sequentially(
                    session_id,
                    tail_components,
                )
                if not tail_result.ok:
                    logger.warning(
                        "WeixinOC tail media send failed: session=%s, detail=%s",
                        session_id,
                        tail_result.detail,
                    )
                    return tail_result

            if message:
                return await cls._send_chain(session_id, [Plain(message)])

            if image_components or tail_components:
                return SendResult(ok=True)

            return SendResult(ok=False, detail="empty_message")

        except Exception as err:
            logger.warning(
                "WeixinOC send failed: session=%s, err_type=%s, err=%r",
                session_id,
                type(err).__name__,
                err,
                exc_info=True,
            )
            fallback_text = cls._append_failed_media_links(
                message,
                [url for _, url in media] if media else [],
            )
            try:
                if fallback_text:
                    fallback_result = await cls._send_chain(
                        session_id,
                        [Plain(fallback_text)],
                    )
                    if fallback_result.ok:
                        return SendResult(
                            ok=True,
                            transient=False,
                            detail="weixin_oc_failed_text_fallback",
                        )
                    return fallback_result
            except Exception as fallback_ex:
                return SendResult(
                    ok=False,
                    transient=cls._is_transient_network_error(fallback_ex),
                    detail=str(fallback_ex),
                )

            return SendResult(
                ok=False,
                transient=cls._is_transient_network_error(err),
                detail=str(err),
            )
