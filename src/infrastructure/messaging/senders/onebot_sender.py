"""QQ OneBot 消息发送器

针对 QQ OneBot 协议的特定优化。
支持合并转发节点（Nodes）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from astrbot.api.message_components import Node, Nodes, Plain

from ...utils import get_logger
from ..napcat_stream import upload_file_stream
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
    def _napcat_stream_mode(cls, context: MessageContext | None) -> str:
        """获取 NapCat stream 模式配置

        Returns:
            "disabled", "fallback", 或 "always"
        """
        strategy = getattr(context, "sender_strategy", None) if context else None
        value = cls._strategy_value(strategy, "napcat_stream_mode", None)
        if value is None:
            return cls._get_onebot_napcat_stream_mode_default()
        return str(value)

    @classmethod
    def _get_onebot_napcat_stream_mode_default(cls) -> str:
        """获取 OneBot NapCat stream 模式的默认值"""
        from ....shared.constants import ONEBOT_NAPCAT_STREAM_MODE_DEFAULT

        return str(
            getattr(
                cls,
                "_onebot_napcat_stream_mode_default",
                ONEBOT_NAPCAT_STREAM_MODE_DEFAULT,
            )
        )

    @classmethod
    def _resolve_bot_client(cls, context: MessageContext | None) -> Any | None:
        """解析可用于 NapCat stream 的 bot 客户端

        优先使用消息事件携带的 bot（命令响应场景），
        否则通过全局 provider 按平台名解析（主动推送场景）。
        """
        event = getattr(context, "event", None) if context else None
        if event is not None:
            bot = getattr(event, "bot", None) or getattr(event, "_bot", None)
            if bot is not None:
                return bot

        from .types import get_bot_client

        platform_name = getattr(context, "platform_name", "") if context else ""
        return get_bot_client(platform_name or "")

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送合并转发消息到 QQ OneBot 用户

        经典策略下每条消息/媒体各自一个 Node；失败后回退为纯文本 Nodes。
        """
        effective_prepared = None
        cleanup_owned = request.prepared_media is None
        try:
            session_id = request.session_id
            timeout = self._get_timeout_seconds()
            proxy = self._get_proxy()

            effective_prepared = request.prepared_media
            if effective_prepared is None and request.media:
                effective_prepared = await self.prepare_media(
                    request.media, timeout=timeout, proxy=proxy
                )
            effective_prepared = self._apply_generated_layout_local_paths(
                request,
                effective_prepared,
                mark_owned=cleanup_owned,
            )
            prepared_media_by_url = {
                pm.original_url: pm
                for pm in (effective_prepared or [])
                if pm.original_url
            }

            napcat_mode = self._napcat_stream_mode(context)

            if self._is_original_style(context) and request.layout:
                return await self._send_components_in_order(
                    session_id,
                    self._layout_to_components(
                        request, prepared_media_by_url=prepared_media_by_url
                    ),
                    combine_image_text=True,
                    default_text=request.message,
                    prepared_media_by_url=prepared_media_by_url,
                    platform="onebot",
                )

            nickname = (
                context.channel.title if context and context.channel.title else "RSSHub"
            )

            from astrbot.api.message_components import File, Image, Record, Video

            components = self._build_components(
                request,
                effective_prepared,
                context,
                failed_urls=[],
                platform="onebot",
            )
            components = self._apply_first_send_candidates(
                components,
                prepared_media_by_url,
                platform="onebot",
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

            bot_client = self._resolve_bot_client(context)

            # NapCat stream mode: always
            if napcat_mode == "always" and bot_client is not None:
                nodes = await self._stream_upload_nodes(bot_client, nodes)

            result = await self._send_chain(session_id, [Nodes(nodes)])

            # NapCat stream mode: fallback
            if (
                not result.ok
                and napcat_mode == "fallback"
                and bot_client is not None
                and self._has_local_video_nodes(nodes)
            ):
                logger.warning(
                    "OneBot send failed, trying NapCat stream fallback: session=%s",
                    session_id,
                )
                streamed_nodes = await self._stream_upload_nodes(bot_client, nodes)
                result = await self._send_chain(session_id, [Nodes(streamed_nodes)])

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
                fallback_message = (
                    self._message_with_all_generated_fallbacks(request) or "RSS update"
                )
                fallback_text = self._append_failed_links(
                    fallback_message,
                    failed_urls,
                )
                fallback_nodes = [
                    Node(
                        content=[Plain(fallback_text or "RSS update")],
                        name=nickname,
                    )
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
        finally:
            if cleanup_owned:
                self._cleanup_owned_paths(effective_prepared)

    async def _stream_upload_nodes(
        self, bot_client: Any, nodes: list[Node]
    ) -> list[Node]:
        """通过 NapCat Stream 上传节点中的本地视频文件

        Args:
            bot_client: 支持 call_action 的 bot 客户端
            nodes: 原始节点列表

        Returns:
            处理后的节点列表（本地视频文件路径替换为上传后的路径）
        """
        from astrbot.api.message_components import Video

        streamed_nodes: list[Node] = []
        for node in nodes:
            if not node.content:
                streamed_nodes.append(node)
                continue

            streamed_content = []
            for comp in node.content:
                if not isinstance(comp, Video):
                    streamed_content.append(comp)
                    continue

                local_path = self._extract_local_video_path(comp)
                if not local_path:
                    streamed_content.append(comp)
                    continue

                uploaded_path = await upload_file_stream(bot_client, local_path)
                if uploaded_path:
                    logger.info(
                        "[napcat_stream] 视频上传成功: local=%s, remote=%s",
                        local_path,
                        uploaded_path,
                    )
                    streamed_content.append(Video(file=uploaded_path))
                else:
                    logger.warning(
                        "[napcat_stream] 视频上传失败，保留原路径: local=%s",
                        local_path,
                    )
                    streamed_content.append(comp)

            streamed_nodes.append(
                Node(content=streamed_content, name=node.name, uin=node.uin)
            )

        return streamed_nodes

    def _has_local_video_nodes(self, nodes: list[Node]) -> bool:
        """检查节点列表中是否包含本地视频文件"""
        from astrbot.api.message_components import Video

        for node in nodes:
            if not node.content:
                continue
            for comp in node.content:
                if isinstance(comp, Video) and self._extract_local_video_path(comp):
                    return True
        return False

    @staticmethod
    def _extract_local_video_path(video_comp) -> Path | None:
        """从 Video 组件中提取本地文件路径

        Args:
            video_comp: Video 组件

        Returns:
            本地文件路径，如果不是本地文件则返回 None
        """
        file_value = getattr(video_comp, "file", None)
        if not isinstance(file_value, str) or not file_value:
            return None

        # 处理 file:/// 协议
        if file_value.startswith("file:///"):
            path = Path(file_value[8:])
        elif file_value.startswith("http://") or file_value.startswith("https://"):
            # 跳过 HTTP URL
            return None
        else:
            path = Path(file_value)

        return path if path.exists() and path.is_file() else None
