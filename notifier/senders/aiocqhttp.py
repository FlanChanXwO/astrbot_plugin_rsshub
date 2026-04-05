from __future__ import annotations

from astrbot.api.message_components import Node, Nodes, Plain

from .base import MessageSender
from .types import NotifierContext, PreparedMedia, SendResult


class AiocqhttpMessageSender(MessageSender):
    """OneBot sender: pack metadata and media into merged forward nodes."""

    @classmethod
    def _build_node(cls, nickname: str, chain: list):
        return Node(content=chain, name=nickname)

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
        effective_prepared = prepared_media
        if effective_prepared is None and media:
            effective_prepared = await cls.prepare_media(media)

        image_components = []
        tail_components = []
        if effective_prepared:
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

        return await cls._send_chain(session_id, [Nodes(nodes)])
