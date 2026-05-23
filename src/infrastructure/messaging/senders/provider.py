"""Infrastructure adapter for the application message sender port."""

from __future__ import annotations

from ....application.ports import (
    MessageContext,
    MessageSender,
    SendRequest,
    SendResult,
)
from ....infrastructure.config import SenderStrategySettings
from ...utils import get_logger
from .factory import get_sender_for_platform
from .types import ChannelInfo
from .types import MessageContext as InfraMessageContext
from .types import SendRequest as InfraSendRequest

logger = get_logger()


class InfrastructureMessageSenderAdapter:
    """Adapter from application send requests to concrete infrastructure senders."""

    def __init__(self, sender, *, sender_strategy=None) -> None:
        self._sender = sender
        self._sender_strategy = sender_strategy

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        infra_context = InfraMessageContext(
            channel=ChannelInfo(
                title=context.channel_title if context else "",
                link=context.channel_link if context else "",
            ),
            entry_title=context.entry_title if context else "",
            entry_link=context.entry_link if context else "",
            platform_name=context.platform_name if context else "",
            send_mode=context.send_mode if context else None,
            style=context.style if context else 0,
            sender_strategy=(
                getattr(context, "sender_strategy", None)
                if context and getattr(context, "sender_strategy", None) is not None
                else self._sender_strategy
            ),
        )
        result = await self._sender.send_to_user(
            InfraSendRequest(
                session_id=request.session_id,
                message=request.message,
                media=request.media,
                layout=request.layout,
            ),
            context=infra_context,
        )
        return SendResult(
            ok=result.ok,
            needs_rebind=result.needs_rebind,
            transient=result.transient,
            detail=result.detail,
            http_status=result.http_status,
        )


class InfrastructureMessageSenderProvider:
    """Resolve message senders using infrastructure sender implementations."""

    def __init__(
        self,
        sender_strategies: SenderStrategySettings | None = None,
    ) -> None:
        self._sender_strategies = sender_strategies

    def get(self, platform_name: str | None) -> MessageSender:
        sender_strategy = _resolve_platform_strategy(
            platform_name,
            self._sender_strategies,
        )
        sender_class = get_sender_for_platform(
            platform_name,
            sender_strategies=self._sender_strategies,
        )
        logger.debug(
            "Resolved sender for platform '%s': %s",
            platform_name,
            sender_class.__name__,
        )
        return InfrastructureMessageSenderAdapter(
            sender_class(),
            sender_strategy=sender_strategy,
        )


def _resolve_platform_strategy(
    platform_name: str | None,
    sender_strategies: SenderStrategySettings | None,
):
    if sender_strategies is None or not platform_name:
        return None
    normalized = platform_name.strip().lower()
    if normalized in {"telegram", "tg"}:
        return sender_strategies.telegram_settings
    if normalized in {"aiocqhttp", "onebot", "onebot11", "onebotv11"}:
        return sender_strategies.aiocqhttp_settings
    return None
