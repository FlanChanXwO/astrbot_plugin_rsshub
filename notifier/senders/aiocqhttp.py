from __future__ import annotations

from astrbot.api import logger
from astrbot.api.message_components import Node, Nodes, Plain

from .base import MessageSender
from .media_downloader import get_or_download_media_to_cache
from .types import NotifierContext, PreparedMedia, SendResult


class AiocqhttpMessageSender(MessageSender):
    """OneBot sender: pack metadata and media into merged forward nodes."""

    @classmethod
    def _build_node(cls, nickname: str, chain: list):
        return Node(content=chain, name=nickname)

    @classmethod
    async def _ensure_local_media_for_forward(
        cls,
        prepared_media: list[PreparedMedia],
    ) -> list[PreparedMedia]:
        """Ensure video/audio are local files for better OneBot forward compatibility."""
        normalized: list[PreparedMedia] = []
        for item in prepared_media:
            if item.download_failed or item.local_path is not None:
                normalized.append(item)
                continue
            if item.media_type not in {"video", "audio"}:
                normalized.append(item)
                continue

            try:
                local_path = await get_or_download_media_to_cache(
                    url=item.original_url,
                    timeout_seconds=cls._get_timeout_seconds(),
                    proxy=cls._get_proxy(),
                )
                normalized.append(
                    PreparedMedia(
                        media_type=item.media_type,
                        original_url=item.original_url,
                        local_path=local_path,
                        download_failed=False,
                    )
                )
            except Exception as ex:
                logger.warning(
                    "Force local media for OneBot forward failed: type=%s, url=%s, err=%s",
                    item.media_type,
                    item.original_url,
                    ex,
                )
                normalized.append(
                    PreparedMedia(
                        media_type=item.media_type,
                        original_url=item.original_url,
                        local_path=None,
                        download_failed=True,
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
                effective_prepared = await cls._ensure_local_media_for_forward(
                    effective_prepared
                )
                for item in effective_prepared:
                    if item.local_path is None:
                        logger.debug(
                            "Aiocqhttp media resolved: type=%s, source=url, session=%s, failed=%s",
                            item.media_type,
                            session_id,
                            item.download_failed,
                        )
                        continue

                    exists = item.local_path.exists()
                    size = 0
                    if exists:
                        try:
                            size = item.local_path.stat().st_size
                        except OSError:
                            size = 0
                    logger.debug(
                        "Aiocqhttp media resolved: type=%s, source=local_path, session=%s, exists=%s, size=%s, failed=%s",
                        item.media_type,
                        session_id,
                        exists,
                        size,
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

            # Always retry merged-forward once with URL sources when media exists.
            if effective_prepared:
                if context:
                    nickname = (
                        context.channel.title if context.channel.title else "RSSHub"
                    )
                else:
                    nickname = "RSSHub"

                url_prepared = [
                    PreparedMedia(
                        media_type=item.media_type,
                        original_url=item.original_url,
                        local_path=None,
                        download_failed=item.download_failed,
                    )
                    for item in effective_prepared
                ]

                try:
                    (
                        url_image_components,
                        url_tail_components,
                        url_failed_media_urls,
                    ) = await cls._build_media_components(url_prepared)
                    retry_message = cls._append_failed_media_links(
                        message,
                        url_failed_media_urls,
                    )

                    retry_nodes = [
                        cls._build_node(
                            nickname,
                            [Plain(retry_message)]
                            if retry_message
                            else [Plain("RSS update")],
                        )
                    ]
                    for component in url_image_components:
                        retry_nodes.append(cls._build_node(nickname, [component]))
                    for component in url_tail_components:
                        retry_nodes.append(cls._build_node(nickname, [component]))

                    logger.warning(
                        "Aiocqhttp merged-forward retry with URL media: session=%s, prev_err=%s, images=%s, tail=%s",
                        session_id,
                        err_text,
                        len(url_image_components),
                        len(url_tail_components),
                    )
                    retry_result = await cls._send_chain(session_id, [Nodes(retry_nodes)])
                    if retry_result.ok:
                        return SendResult(
                            ok=True,
                            transient=False,
                            detail="merged_forward_retry_with_url",
                        )
                except Exception as retry_ex:
                    logger.warning(
                        "Aiocqhttp URL-media merged-forward retry failed: session=%s, err=%s",
                        session_id,
                        retry_ex,
                    )

            logger.warning(
                "Aiocqhttp falling back to text-only merged nodes: session=%s, prev_err=%s",
                session_id,
                err_text,
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
