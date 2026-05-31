"""Telegram 消息发送器

针对 Telegram 平台的特定优化。
组件排序由 MessageFormatter 统一处理，此处只负责发送。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ...config import get_config_manager
from ...pipeline import MessageFormatter
from ...utils import get_logger
from .base_sender import DefaultMessageSender
from .telegraph_client import TelegraphClient
from .types import MessageContext, SendRequest, SendResult

if TYPE_CHECKING:
    pass

logger = get_logger()


class TelegramMessageSender(DefaultMessageSender):
    """Telegram 平台消息发送器

    特性：
    - 媒体优先展示（caption = text）
    - 组件排序由 MessageFormatter 统一（platform="telegram"）
    """

    @staticmethod
    def _strategy_value(strategy, key: str, default=None):
        if strategy is None:
            return default
        if isinstance(strategy, dict):
            return strategy.get(key, default)
        return getattr(strategy, key, default)

    @staticmethod
    def _strategy_from_templates(sender_strategies, template_key: str):
        templates = (
            sender_strategies.get("platform_strategies")
            if isinstance(sender_strategies, dict)
            else getattr(sender_strategies, "platform_strategies", None)
        )
        if not isinstance(templates, list):
            return None
        return next(
            (
                item
                for item in templates
                if isinstance(item, dict) and item.get("__template_key") == template_key
            ),
            None,
        )

    @classmethod
    def _get_timeout_seconds(cls) -> int:
        """Telegram 可能需要更长的超时"""
        return max(1, int(getattr(cls, "_timeout_seconds", 60)))

    @staticmethod
    def _normalize_planned_media(prepared_media):
        if not prepared_media:
            return prepared_media
        from ..media_send_planner import MediaSendPlanner

        normalized = []
        changed = False
        for item in prepared_media:
            if item.download_failed:
                normalized.append(item)
                continue

            candidates = MediaSendPlanner.candidates_for(item, platform="telegram")
            first = next(
                (candidate for candidate in candidates if candidate.action != "link"),
                None,
            )
            if first is None or not first.file:
                normalized.append(item)
                continue

            if first.action == "media":
                planned_path = Path(first.file) if "://" not in first.file else None
                if first.media_type == item.media_type and (
                    planned_path is None or planned_path == item.local_path
                ):
                    normalized.append(item)
                    continue
                normalized.append(item)
                if planned_path is not None:
                    normalized[-1] = type(item)(
                        media_type=first.media_type,
                        original_url=item.original_url,
                        local_path=planned_path,
                        download_failed=item.download_failed,
                        detected_mime=item.detected_mime,
                        detected_suffix=planned_path.suffix.lower(),
                        detection_source=item.detection_source,
                        variants=list(item.variants),
                    )
                    changed = True
                continue

            normalized.append(
                type(item)(
                    media_type="file",
                    original_url=item.original_url,
                    local_path=Path(first.file),
                    download_failed=item.download_failed,
                    detected_mime=item.detected_mime,
                    detected_suffix=Path(first.file).suffix.lower(),
                    detection_source=item.detection_source,
                    variants=list(item.variants),
                )
            )
            changed = True
        return normalized if changed else prepared_media

    @classmethod
    def _should_use_telegraph(
        cls,
        context: MessageContext | None,
        prepared_media,
    ) -> tuple[bool, str, str]:
        if context is None or context.send_mode != 0:
            return False, "", ""

        strategy = getattr(context, "sender_strategy", None)
        if strategy is None:
            try:
                config = get_config_manager()
                sender_strategies = getattr(config, "sender_strategies", None)
                strategy = cls._strategy_from_templates(
                    sender_strategies, "telegram_strategy"
                )
                if strategy is None:
                    strategy = (
                        sender_strategies.get("telegram")
                        if isinstance(sender_strategies, dict)
                        else getattr(
                            sender_strategies,
                            "telegram_settings",
                            getattr(sender_strategies, "telegram", None),
                        )
                    )
            except Exception:
                strategy = None

        enabled = bool(cls._strategy_value(strategy, "enable_telegraph", False))
        token = str(cls._strategy_value(strategy, "telegraph_token", "") or "").strip()
        proxy = cls._normalize_telegraph_proxy(
            cls._strategy_value(strategy, "telegraph_proxy", "")
        )
        if not enabled or not token:
            return False, "", ""

        unique_urls = MessageFormatter.collect_original_urls(prepared_media)
        return len(unique_urls) > 1, token, proxy

    @staticmethod
    def _normalize_telegraph_proxy(value) -> str:
        """归一化 Telegraph 代理：裸 host:port 按 http:// 处理；留空即直连。

        策略可能来自原始配置模板（未归一化）或已解析的设置对象（已归一化），
        此规则幂等，重复应用安全。
        """
        proxy = str(value or "").strip()
        if not proxy:
            return ""
        if "://" not in proxy:
            return f"http://{proxy}"
        return proxy

    async def _send_via_telegraph(
        self,
        *,
        session_id: str,
        request: SendRequest,
        context: MessageContext | None,
        prepared_media,
        token: str,
        proxy: str = "",
    ) -> SendResult:
        media_urls = MessageFormatter.collect_original_urls(prepared_media)
        client = TelegraphClient(
            access_token=token,
            timeout_seconds=self._get_timeout_seconds(),
            proxy=proxy,
        )
        page_title = (
            str(getattr(context, "entry_title", "") or "").strip() if context else ""
        )
        if not page_title:
            page_title = (
                context.channel.title if context and context.channel.title else "RSSHub"
            )
        page_url = await client.create_media_page(
            title=page_title,
            content=request.message,
            media_urls=media_urls,
            channel=context.channel if context else None,
        )
        message = self._build_telegraph_message(
            request.message,
            page_url,
            context=context,
        )
        return await self._send_chain(
            session_id,
            self._formatter.build_chain(
                prepared_media=None,
                text=message,
                failed_urls=[],
                platform="telegram",
            ),
        )

    @staticmethod
    def _build_telegraph_message(
        content: str,
        page_url: str,
        *,
        context: MessageContext | None,
    ) -> str:
        text = str(content or "").strip()
        if page_url and page_url not in text:
            text = f"{text}\n\n{page_url}" if text else page_url
        return text

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """发送消息到 Telegram 用户

        平台标记为 telegram，由 MessageFormatter 选择 Telegram 专属链式顺序。
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
            effective_prepared = self._normalize_planned_media(effective_prepared)

            failed_urls: list[str] = []
            if effective_prepared:
                failed_urls = self._collect_failed_urls(effective_prepared)

            use_telegraph, telegraph_token, telegraph_proxy = (
                self._should_use_telegraph(
                    context,
                    effective_prepared,
                )
            )
            if use_telegraph:
                try:
                    return await self._send_via_telegraph(
                        session_id=session_id,
                        request=request,
                        context=context,
                        prepared_media=effective_prepared,
                        token=telegraph_token,
                        proxy=telegraph_proxy,
                    )
                except Exception as err:
                    logger.warning(
                        "Telegram Telegraph fallback to native send: session=%s, error=%s",
                        session_id,
                        err,
                    )

            chain = self._formatter.build_chain(
                prepared_media=effective_prepared,
                text=self._message_with_unavailable_generated_fallbacks(
                    request,
                    effective_prepared,
                ),
                failed_urls=failed_urls,
                platform="telegram",
            )

            if not chain:
                return SendResult(ok=False, detail="empty_message")

            result = await self._send_chain(session_id, chain)
            if result.ok:
                return result
            return await self._retry_text_with_generated_fallbacks(
                request,
                result,
            )

        except Exception as err:
            logger.error(
                "Telegram send failed: session=%s, error=%s", request.session_id, err
            )
            return SendResult(
                ok=False,
                transient=self._is_transient_network_error(err),
                detail=self._normalize_error_detail(str(err)),
            )
