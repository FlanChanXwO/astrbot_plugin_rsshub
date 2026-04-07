from __future__ import annotations

from astrbot.api import logger
from astrbot.api.message_components import Node, Nodes, Plain

from .base import MessageSender
from .types import NotifierContext, PreparedMedia, SendResult


class AiocqhttpMessageSender(MessageSender):
    """OneBot sender: pack metadata and media into merged forward nodes."""

    @classmethod
    def _build_node(cls, nickname: str, chain: list):
        return Node(content=chain, name=nickname)

    @classmethod
    def _prefer_url_media_for_forward(
        cls,
        prepared_media: list[PreparedMedia],
    ) -> list[PreparedMedia]:
        """Use URL media for OneBot forward to avoid cross-runtime local-path ENOENT."""
        normalized: list[PreparedMedia] = []
        for item in prepared_media:
            if item.download_failed:
                normalized.append(item)
                continue
            normalized.append(
                PreparedMedia(
                    media_type=item.media_type,
                    original_url=item.original_url,
                    local_path=None,
                    download_failed=False,
                )
            )
        return normalized

    @classmethod
    async def send_to_user(
        cls,
        session_id: str,
        message: str,
        media: list[tuple[str, str]] | None = None,
        prepared_media: list[PreparedMedia] | None = None,
        context: NotifierContext | None = None,
    ) -> SendResult:
        """发送消息到用户。

        Args:
            session_id: 目标会话ID
            message: 消息内容
            media: 媒体列表
            prepared_media: 预处理的媒体
            context: 通知上下文，包含频道元信息和运行时信息
        """
        logger.debug(
            "Aiocqhttp sender strategy: merged-forward nodes, session=%s, has_media=%s, prepared_media=%s",
            session_id,
            bool(media),
            bool(prepared_media),
        )
        effective_prepared: list[PreparedMedia] | None = prepared_media
        try:
            if effective_prepared is None and media:
                effective_prepared = await cls.prepare_media(media)

            image_components = []
            tail_components = []
            if effective_prepared:
                effective_prepared = cls._prefer_url_media_for_forward(
                    effective_prepared
                )
                for item in effective_prepared:
                    logger.debug(
                        "Aiocqhttp media resolved: type=%s, source=url, session=%s, failed=%s",
                        item.media_type,
                        session_id,
                        item.download_failed,
                    )
                (
                    image_components,
                    tail_components,
                    failed_media_urls,
                ) = await cls._build_media_components(effective_prepared)
                message = cls._append_failed_media_links(message, failed_media_urls)

            # 从 context 获取 nickname
            if context:
                nickname = context.channel.title if context.channel.title else "RSSHub"
            else:
                nickname = "RSSHub"
            nodes = []

            header_chain = [Plain(message)] if message else [Plain("RSS update")]
            nodes.append(cls._build_node(nickname, header_chain))

            for component in image_components:
                nodes.append(cls._build_node(nickname, [component]))

            for component in tail_components:
                nodes.append(cls._build_node(nickname, [component]))

            if not nodes:
                return SendResult(ok=False, detail="empty_message")

            logger.debug(
                "Aiocqhttp sender node summary: session=%s, header=1, images=%s, tail=%s, total_nodes=%s",
                session_id,
                len(image_components),
                len(tail_components),
                len(nodes),
            )
            return await cls._send_chain(session_id, [Nodes(nodes)])
        except Exception as err:
            err_text = str(err)
            logger.warning(
                "Aiocqhttp merged-forward send failed: session=%s, err=%s",
                session_id,
                err,
            )

            # Keep merged-forward mode even in fallback: convert media to links in text.
            fallback_urls: list[str] = []
            if media:
                fallback_urls.extend([url for _, url in media if url])
            fallback_text = cls._append_failed_media_links(message, fallback_urls)

            if context:
                nickname = context.channel.title if context.channel.title else "RSSHub"
            else:
                nickname = "RSSHub"

            logger.warning(
                "Aiocqhttp falling back to text-only merged nodes: session=%s, prev_err=%s",
                session_id,
                err_text,
            )

            merged_text = fallback_text or "RSS update"
            fallback_nodes = [cls._build_node(nickname, [Plain(merged_text)])]

            try:
                fallback_result = await cls._send_chain(
                    session_id, [Nodes(fallback_nodes)]
                )
                if fallback_result.ok:
                    return SendResult(
                        ok=True,
                        transient=False,
                        detail="merged_forward_failed_text_nodes_fallback",
                    )
                return fallback_result
            except Exception as fallback_ex:
                return SendResult(
                    ok=False,
                    transient=cls._is_transient_network_error(fallback_ex),
                    detail=str(fallback_ex),
                )
