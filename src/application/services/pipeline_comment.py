"""AI 评论管道注入（ai_comment 管道模式）。

v2.6.0 起 ai_comment 默认不再由插件直连 ``provider.text_chat`` 生成评论，
而是构造一条合成消息注入 AstrBot 消息管道：像与 bot 对话一样，让管道触发
其他插件过滤器、加载人格、注入 livingmemory 记忆、开启消息交互，并由管道
把生成的评论回复到订阅目标会话。

本模块只负责「注入」：把 ai_comment 的触发载荷变成一条合成消息事件提交到
AstrBot 事件队列（复用官方 StarTools.create_message / create_event API）。
评论正文在管道里异步生成，不回流到插件；注入失败时由调用方（dispatcher）
自动回退到直连模式，避免评论静默丢失。

v2.6.1 修复（对照首次真实推送日志 log.md）：

1. 图片本地化：不再把原始 URL 交给 AstrBot 核心下载（核心不带插件代理，
   pbs.twimg.com 等直连不可达的 CDN 会卡住管道 2 分钟以上且模型看不到图），
   注入前用插件自己的 ``media_downloader``（带代理/反代，与转发卡片同链路）
   把图片落到本地，``Image.fromFileSystem`` 传本地路径；单张失败短超时快速
   跳过，绝不阻塞管道。
2. 合成消息标记：``message_str`` 首行带 ``SYNTHETIC_MESSAGE_TAG``，
   ``raw_message`` 携带结构化标记（source/kind/tag），人格与第三方插件
   （好感度、语料采集等）可据此识别并过滤 RSS 推送消息，避免污染用户数据。
3. 可追踪：注入消息携带 ``rsshub-comment-`` 前缀的 ``message_id``，
   可凭该 ID 在 AstrBot 核心日志中追踪评论链路成败（StarTools 公共 API
   不提供管道内结果回流，追踪标记是目前能做到的最小可观测手段）。
4. 空 ``bot_self_id``：群聊注入依赖 ``At(self_id)`` 唤醒，self_id 为空时
   直接回退直连，不再构造 ``At("")`` 导致评论静默不发。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    from astrbot.api.platform import MessageMember  # type: ignore[import-not-found]
    from astrbot.core.message.components import At, Image, Plain  # type: ignore[import-not-found]
    from astrbot.core.platform.message_session import MessageSession  # type: ignore[import-not-found]
    from astrbot.core.platform.message_type import MessageType  # type: ignore[import-not-found]
    from astrbot.core.star.star_tools import StarTools  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - lightweight test fallback

    class MessageType(Enum):  # type: ignore[no-redef]
        GROUP_MESSAGE = "GroupMessage"
        FRIEND_MESSAGE = "FriendMessage"
        OTHER_MESSAGE = "OtherMessage"

    class MessageMember:  # type: ignore[no-redef]
        def __init__(self, user_id: str, nickname: str | None = None) -> None:
            self.user_id = user_id
            self.nickname = nickname

    class At:  # type: ignore[no-redef]
        def __init__(self, qq: int | str, name: str | None = "") -> None:
            self.qq = qq
            self.name = name

    class Plain:  # type: ignore[no-redef]
        def __init__(self, text: str) -> None:
            self.text = text

    class Image:  # type: ignore[no-redef]
        def __init__(
            self,
            file: str | None,
            url: str | None = None,
            path: str | None = None,
        ) -> None:
            self.file = file
            self.url = url
            self.path = path

        @staticmethod
        def fromURL(url: str) -> "Image":
            if url.startswith("http://") or url.startswith("https://"):
                return Image(file=url)
            raise Exception("not a valid url")

        @staticmethod
        def fromFileSystem(path: str) -> "Image":
            file_path = Path(path).resolve(strict=False)
            return Image(file=file_path.as_uri(), path=str(file_path))

    class MessageSession:  # type: ignore[no-redef]
        def __init__(
            self,
            platform_id: str,
            message_type: MessageType,
            session_id: str,
        ) -> None:
            self.platform_id = platform_id
            self.platform_name = platform_id
            self.message_type = message_type
            self.session_id = session_id

        @staticmethod
        def from_str(session_str: str) -> "MessageSession":
            platform_id, message_type, session_id = session_str.split(":", 2)
            return MessageSession(platform_id, MessageType(message_type), session_id)

    class StarTools:  # type: ignore[no-redef]
        _context: Any = None

        @classmethod
        async def create_message(cls, **kwargs: Any) -> Any:
            raise RuntimeError("StarTools not initialized")

        @classmethod
        async def create_event(
            cls,
            abm: Any,
            platform: str = "aiocqhttp",
            is_wake: bool = True,
        ) -> None:
            raise RuntimeError("StarTools not initialized")


from ...domain.entities.handlers import DEFAULT_AI_COMMENT_PROMPT
from ...infrastructure.utils import detect_media_hint, get_logger

if TYPE_CHECKING:  # 避免与 content_handlers / notification_dispatcher 循环导入
    from .content_handlers import EntryContentContext
    from .notification_dispatcher import SendTarget

logger = get_logger()

#: 管道模式拼进合成消息的图片数量上限（与直连模式读图 cap 一致）。
_MAX_COMMENT_IMAGES = 3
#: 合成消息里条目正文截断长度，避免把超长 RSS 正文整体灌进会话。
_MAX_COMMENT_BODY_CHARS = 2000
#: 管道模式图片本地化下载超时（秒）——失败快速跳过，绝不阻塞管道。
_COMMENT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 45
#: 注入消息的 message_id 前缀：凭该 ID 可在 AstrBot 核心日志追踪评论链路。
_COMMENT_MESSAGE_ID_PREFIX = "rsshub-comment-"

#: 合成消息标记：写进 message_str 首行与 raw_message。
#: 人格模型可借此理解「这是一条 RSS 推送」；第三方插件（好感度、语料采集、
#: 情绪追踪等）可以把该关键词加入各自的过滤/黑名单，避免把推送当成真实
#: 群成员发言（v2.6.0 首次推送日志中订阅者好感度被 +1 即此类污染）。
SYNTHETIC_MESSAGE_TAG = "【RSS订阅推送】"


@dataclass(frozen=True, slots=True)
class AiCommentTrigger:
    """ai_comment 管道模式的评论触发载荷。

    由 handler 链的 ai_comment 步构造（不调 LLM、不读图、不生成正文），
    仅当主推送转发成功后由 ``PipelineCommentRouter`` 把载荷注入 AstrBot
    消息管道；entry/config 同时供直连回退复用（见 dispatcher）。
    """

    entry: Any  # EntryContentContext：改写前的原始条目
    prompt: str  # 评论口吻配置（空则管道内用默认口吻）
    with_media: bool  # 是否把条目图片作为原生图片组件拼进合成消息
    config: dict[str, Any]  # 完整 handler config（直连回退复用）


class PipelineCommentRouter:
    """把 ai_comment 触发载荷注入 AstrBot 消息管道。

    通过 AstrBot 官方合成事件 API（``StarTools.create_message`` +
    ``StarTools.create_event``）构造并提交一条合成消息事件：群里带
    ``At(self_id)`` 唤醒，私聊自动唤醒；图片先用插件 ``media_downloader``
    （带代理/反代）落到本地再以 ``Image.fromFileSystem`` 注入，避免核心
    直连不可达 CDN；``message_str`` 首行携带合成消息标记、``raw_message``
    携带结构化标记、``message_id`` 带 ``rsshub-comment-`` 前缀。管道随后
    像处理真实群消息一样处理它：插件过滤器、人格、livingmemory 记忆、
    消息交互、LLM 回复与平台发送全链路生效。
    """

    def __init__(self, context: Any | None = None) -> None:
        # context 为 AstrBot Context；注入本身走 StarTools（启动时已初始化），
        # 保留该参数便于调用方统一传入与后续扩展。
        self._context = context

    async def inject(self, target: SendTarget, trigger: AiCommentTrigger) -> dict:
        """把 trigger 注入到 target 会话。

        Args:
            target: 订阅推送目标（``SendTarget``）。
            trigger: ai_comment 触发载荷。

        Returns:
            ``{"ok": bool, "fallback": bool, "error": str, "message_id": str}``。
            ``fallback=True`` 表示调用方应回退到直连模式生成并发送评论
            （目标会话不可解析 / 群目标缺 bot_self_id / 平台未连接 /
            StarTools 未就绪 / 注入异常），避免评论静默丢失。
            注入成功时 ``message_id`` 为带 ``rsshub-comment-`` 前缀的追踪 ID
            （可凭其在 AstrBot 核心日志中检索评论链路）。
        """
        try:
            session = MessageSession.from_str(str(target.target_session or ""))
        except Exception:
            logger.warning(
                "ai_comment 管道注入失败：目标会话无法解析 %r",
                getattr(target, "target_session", None),
            )
            return {
                "ok": False,
                "fallback": True,
                "error": "unparseable session",
                "message_id": "",
            }

        is_group = session.message_type == MessageType.GROUP_MESSAGE
        self_id = str(target.bot_self_id or "")
        if is_group and not self_id:
            # 群聊注入依赖 At(self_id) 唤醒（WakingCheckStage）；self_id 为空
            # 时构造 At("") 大概率过不了唤醒检查，评论会静默不发——直接回退直连。
            logger.warning(
                "ai_comment 管道注入失败：群目标缺少 bot_self_id（订阅 %s），回退直连",
                getattr(target, "sub_id", None),
            )
            return {
                "ok": False,
                "fallback": True,
                "error": "missing bot_self_id",
                "message_id": "",
            }

        components: list[Any] = []
        if is_group:
            # 群里需要 @ 到 bot 才唤醒（WakingCheckStage）；私聊自动唤醒。
            components.append(At(qq=self_id))
        requested_images = 0
        injected_images = 0
        if trigger.with_media:
            # 图片本地化：下载成功的才注入（失败的不挂组件，message_str 也不
            # 声称有图，避免「写着有图、实际无图」导致模型幻觉编造图片内容）。
            image_urls = self._collect_image_urls(trigger.entry)
            local_paths = await self._download_comment_images(image_urls)
            requested_images = len(image_urls)
            injected_images = len(local_paths)
            for local_path in local_paths:
                components.append(Image.fromFileSystem(str(local_path)))
        # 在图片结果确定之后再拼 message_str：附带的图片说明与实际注入的
        # Image 组件数严格一致（文本模型兜底时也不会对图片内容产生幻觉）。
        message_str = self._build_message_str(trigger, injected_images=injected_images)
        components.insert(1 if is_group else 0, Plain(message_str))

        message_id = f"{_COMMENT_MESSAGE_ID_PREFIX}{uuid.uuid4().hex[:12]}"
        sender = MessageMember(
            user_id=str(target.user_id or ""),
            nickname=str(getattr(trigger.entry, "feed_title", None) or "") or None,
        )
        try:
            abm = await StarTools.create_message(
                type=session.message_type.value,
                self_id=self_id,
                session_id=session.session_id,
                sender=sender,
                message=components,
                message_str=message_str,
                message_id=message_id,
                # 结构化标记：第三方插件检查 raw_message 即可识别合成消息。
                raw_message={
                    "source": "astrbot_plugin_rsshub",
                    "kind": "ai_comment",
                    "tag": SYNTHETIC_MESSAGE_TAG,
                    "message_id": message_id,
                },
                group_id=session.session_id if is_group else "",
            )
            await StarTools.create_event(abm, platform=session.platform_id, is_wake=True)
        except Exception as exc:
            logger.warning(
                "ai_comment 管道注入失败（平台/StarTools 未就绪）：%s",
                exc,
            )
            return {
                "ok": False,
                "fallback": True,
                "error": str(exc) or "inject failed",
                "message_id": "",
            }
        logger.info(
            "ai_comment 已注入 AstrBot 消息管道: message_id=%s, images=%d/%d"
            "（评论由管道异步生成，可凭 message_id 在核心日志追踪成败）",
            message_id,
            injected_images,
            requested_images,
        )
        return {
            "ok": True,
            "fallback": False,
            "error": "",
            "message_id": message_id,
        }

    def _build_message_str(
        self, trigger: AiCommentTrigger, *, injected_images: int = 0
    ) -> str:
        """把条目正文 + 评论指令拼成管道收到的 message_str。

        首行固定带 ``SYNTHETIC_MESSAGE_TAG``：人格模型借此获得上下文，
        第三方插件（好感度/语料采集/情绪追踪）可把该关键词加入过滤名单，
        避免把 RSS 推送当成真实群成员发言。评论指令缺省用默认口吻
        （与直连模式同源），保证管道模式即使没配 prompt 也能让 bot
        说一句符合预期的评论。

        ``injected_images`` 为实际注入的 Image 组件数：>0 时追加一行与
        组件严格一致的图片提示（供不支持视觉的兜底模型了解上下文而不
        幻觉编造图片内容）；为 0 时不提及图片。
        """
        entry = trigger.entry
        lines: list[str] = [SYNTHETIC_MESSAGE_TAG]
        title = str(getattr(entry, "title", None) or "").strip()
        author = str(getattr(entry, "author", None) or "").strip()
        feed_title = str(getattr(entry, "feed_title", None) or "").strip()
        link = str(getattr(entry, "link", None) or "").strip()
        if title:
            lines.append(f"标题：{title}")
        if author:
            lines.append(f"作者：{author}")
        if feed_title:
            lines.append(f"来源：{feed_title}")
        if link:
            lines.append(f"链接：{link}")
        body = str(getattr(entry, "content", None) or "").strip()
        if not body:
            body = str(getattr(entry, "summary", None) or "").strip()
        if body:
            if len(body) > _MAX_COMMENT_BODY_CHARS:
                body = body[:_MAX_COMMENT_BODY_CHARS].rstrip() + "…"
            lines.append("")
            lines.append(body)
        if injected_images > 0:
            lines.append(f"（本条消息附带 {injected_images} 张条目图片）")
        instruction = str(trigger.prompt or "").strip() or DEFAULT_AI_COMMENT_PROMPT
        return "\n".join(lines) + f"\n\n请评论上面这条推送。要求：{instruction}"

    def _collect_image_urls(self, entry: Any) -> list[str]:
        """收集条目图片 URL：media_items 显式 image + media_urls 推断 image。

        仅 http(s)，去重，最多 ``_MAX_COMMENT_IMAGES`` 张——与直连模式
        ``_collect_comment_image_urls`` 同源，保证两种模式对图片的选取一致。
        """
        collected: list[str] = []
        seen: set[str] = set()

        def append(url: Any) -> None:
            url = str(url or "").strip()
            if not url or url in seen:
                return
            if not (url.startswith("http://") or url.startswith("https://")):
                return
            seen.add(url)
            collected.append(url)

        media_items = tuple(getattr(entry, "media_items", ()) or ())
        for media_type, media_url in media_items:
            if str(media_type or "").strip().lower() == "image":
                append(media_url)
        media_urls = tuple(getattr(entry, "media_urls", ()) or ())
        for media_url in media_urls:
            try:
                detection = detect_media_hint(url=str(media_url or ""))
            except Exception:
                detection = None
            if detection is not None and detection.media_type == "image":
                append(media_url)
        return collected[:_MAX_COMMENT_IMAGES]

    async def _download_comment_images(self, urls: list[str]) -> list[Path]:
        """用插件自带 ``media_downloader``（带代理/反代）把图片落到本地。

        v2.6.0 曾把原始 URL 通过 ``Image.fromURL`` 交给 AstrBot 核心下载，
        而核心下载不带插件代理配置——容器内直连 pbs.twimg.com 等 CDN 不可达
        时，管道空转 2 分钟以上且模型最终看不到图。此处与转发卡片图片走同一条
        下载链路（``DefaultMessageSender`` 运行时配置的 proxy / 图片反代 /
        媒体反代），失败单张快速跳过（短超时 + wait_for 硬上限），不阻塞管道。
        """
        if not urls:
            return []
        try:
            from ...infrastructure.media import MediaDownloader
        except Exception as exc:  # pragma: no cover - astrbot 环境异常兜底
            logger.warning("ai_comment 无法加载 media_downloader，跳过图片: %s", exc)
            return []

        downloader = MediaDownloader()
        proxy, image_relay_base_url, media_relay_base_url = (
            self._media_download_options()
        )
        timeout_seconds = _COMMENT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS

        async def _fetch(url: str) -> Path | None:
            try:
                return Path(
                    await asyncio.wait_for(
                        downloader.get_or_download(
                            url=url,
                            timeout_seconds=timeout_seconds,
                            proxy=proxy,
                            media_type="image",
                            image_relay_base_url=image_relay_base_url,
                            media_relay_base_url=media_relay_base_url,
                        ),
                        timeout=timeout_seconds + 5,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "ai_comment 管道图片下载失败，跳过该图: %s (%s)", url, exc
                )
                return None

        results = await asyncio.gather(*(_fetch(url) for url in urls))
        local_paths = [path for path in results if path is not None]
        if len(local_paths) < len(urls):
            logger.info(
                "ai_comment 管道图片：%d/%d 张下载成功，失败图片不注入"
                "（避免 [图片] 占位与实际内容不符）",
                len(local_paths),
                len(urls),
            )
        return local_paths

    @staticmethod
    def _media_download_options() -> tuple[str, str, str]:
        """复用发送器运行时配置的代理与反代（与转发卡片图片同链路）。

        Returns:
            ``(proxy, image_relay_base_url, media_relay_base_url)``；
            发送器配置不可用（如 astrbot 未安装的测试环境）时全空串。
        """
        try:
            from ...infrastructure.messaging.senders.base_sender import (
                DefaultMessageSender,
            )

            return (
                DefaultMessageSender._get_proxy(),
                DefaultMessageSender._get_image_relay_base_url(),
                DefaultMessageSender._get_media_relay_base_url(),
            )
        except Exception:  # pragma: no cover - 测试环境无 astrbot
            return ("", "", "")
