"""QQ OneBot 消息发送器

针对 QQ OneBot 协议的特定优化。
支持合并转发节点（Nodes）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astrbot.api.message_components import Node, Nodes, Plain

from ...utils import get_logger
from .base_sender import DefaultMessageSender
from .types import MessageContext, SendRequest, SendResult

if TYPE_CHECKING:
    pass

logger = get_logger()


class OneBotMessageSender(DefaultMessageSender):
    """QQ OneBot 平台消息发送器

    特性：
    - 合并转发节点（Nodes）：文字 + 图片/视频/音频/文件各自一个节点
    - 经典合并转发失败时回退为纯文本 Nodes；原始顺序排版不走合并转发
    """

    @staticmethod
    def _strategy_value(strategy, key: str, default=None):
        if strategy is None:
            return default
        if isinstance(strategy, dict):
            return strategy.get(key, default)
        return getattr(strategy, key, default)

    @classmethod
    def _prefer_local_video(cls, context: MessageContext | None) -> bool:
        strategy = getattr(context, "sender_strategy", None) if context else None
        return bool(cls._strategy_value(strategy, "prefer_local_video", False))

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送合并转发消息到 QQ OneBot 用户

        经典策略下每条消息/媒体各自一个 Node；失败后回退为纯文本 Nodes。
        """
        try:
            session_id = request.session_id
            timeout = self._get_timeout_seconds()
            proxy = self._get_proxy()

            effective_prepared = request.prepared_media
            if effective_prepared is None and request.media:
                effective_prepared = await self.prepare_media(
                    request.media, timeout=timeout, proxy=proxy
                )

            if self._is_original_style(context) and request.layout:
                return await self._send_components_in_order(
                    session_id,
                    self._layout_to_components(request),
                    combine_image_text=True,
                    default_text=request.message,
                )

            nickname = (
                context.channel.title if context and context.channel.title else "RSSHub"
            )

            from astrbot.api.message_components import File, Image, Record, Video

            components = self._formatter.build_components(
                prepared_media=effective_prepared,
                text=request.message,
                failed_urls=[],
                platform="onebot",
                prefer_local_video=self._prefer_local_video(context),
            )

            nodes: list[Node] = []
            for component in components:
                node_content: list | None = None
                if component.kind == "text":
                    node_content = [Plain(component.text or "RSS update")]
                elif component.kind == "media":
                    match component.media_type:
                        case "image":
                            node_content = [Image(file=component.file)]
                        case "video":
                            node_content = [Video(file=component.file)]
                elif component.kind == "tail":
                    match component.media_type:
                        case "audio":
                            node_content = [Record(file=component.file, text="audio")]
                        case "file":
                            node_content = [
                                File(
                                    name=component.name or "attachment",
                                    file=component.file,
                                    url=component.original_url,
                                )
                            ]
                if node_content:
                    nodes.append(Node(content=node_content, name=nickname))

            if not nodes and request.message:
                nodes.append(Node(content=[Plain(request.message)], name=nickname))

            if not nodes:
                return SendResult(ok=False, detail="empty_message")

            result = await self._send_chain(session_id, [Nodes(nodes)])
            if not result.ok:
                logger.warning(
                    "OneBot merged-forward send failed, fallback to text-only: "
                    "session=%s, detail=%s",
                    session_id,
                    result.detail,
                )
                failed_urls = self._formatter.collect_original_urls(
                    effective_prepared or []
                )
                fallback_text = self._append_failed_links(
                    request.message or "RSS update",
                    failed_urls,
                )
                fallback_nodes = [
                    Node(content=[Plain(fallback_text or "RSS update")], name=nickname)
                ]
                return await self._send_chain(session_id, [Nodes(fallback_nodes)])
            return result

        except Exception as err:
            logger.error(
                "OneBot merged-forward send exception: session=%s, err=%s",
                request.session_id,
                err,
                exc_info=True,
            )
            return SendResult(
                ok=False,
                transient=self._is_transient_network_error(err),
                detail=self._normalize_error_detail(str(err)),
            )
