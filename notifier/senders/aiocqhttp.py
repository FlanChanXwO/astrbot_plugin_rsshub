from __future__ import annotations

from astrbot.api.message_components import Image, Node, Nodes, Plain

from ...utils.log_utils import logger
from .base import MessageSender
from .types import NotifierContext, PreparedMedia, SendResult


class AiocqhttpMessageSender(MessageSender):
    """OneBot sender: pack metadata and media into merged forward nodes."""

    @classmethod
    def _build_node(cls, nickname: str, chain: list):
        processed_chain = []
        for component in chain:
            if isinstance(component, Image):
                processed_chain.append(component)
            else:
                processed_chain.append(component)
        return Node(content=processed_chain, name=nickname)

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
            "Aiocqhttp sender strategy: merged-forward nodes (local-preferred), "
            "session=%s, has_media=%s, prepared_media=%s",
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
                for item in effective_prepared:
                    source = "local_path" if item.local_path is not None else "url"
                    logger.debug(
                        "Aiocqhttp media resolved: type=%s, source=%s, "
                        "session=%s, failed=%s",
                        item.media_type,
                        source,
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

            # QQ 合并转发消息渲染顺序是反的：后添加的节点显示在最上面
            # 所以要让媒体在上面、文字在下面，需要先添加文本，后添加媒体

            # 1. 先添加文字内容（会显示在最下面）
            header_chain = [Plain(message)] if message else [Plain("RSS update")]
            nodes.append(cls._build_node(nickname, header_chain))

            # 2. 后添加媒体组件（会显示在最上面）
            media_nodes = []
            # 使用 _build_node 方法构建媒体节点
            for item in effective_prepared:
                # 确保 file 参数是字符串类型（Image 组件要求 str，不是 Path）
                file_path = item.local_path
                if file_path is not None:
                    file_path = str(file_path)
                file_url = item.original_url or ""
                image_file = file_path or file_url

                if item.media_type == "image":
                    media_nodes.append(cls._build_node(nickname, [Image(file=image_file)]))
                elif item.media_type == "video":
                    # 视频也使用 Image 组件展示缩略图或链接
                    media_nodes.append(cls._build_node(nickname, [Image(file=image_file)]))

            # 添加所有媒体节点（在上面）
            nodes.extend(media_nodes)

            if not nodes:
                return SendResult(ok=False, detail="empty_message")

            logger.debug(
                "Aiocqhttp sender node summary: session=%s, text=1, media=%s, "
                "total_nodes=%s (QQ renders last node on top)",
                session_id,
                len(media_nodes),
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

            fallback_urls: list[str] = []
            if media:
                fallback_urls.extend([url for _, url in media if url])
            fallback_text = cls._append_failed_media_links(message, fallback_urls)

            if context:
                nickname = context.channel.title if context.channel.title else "RSSHub"
            else:
                nickname = "RSSHub"

            logger.warning(
                "Aiocqhttp falling back to text-only merged nodes: "
                "session=%s, prev_err=%s",
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
