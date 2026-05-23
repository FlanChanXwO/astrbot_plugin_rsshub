"""Message sender port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...domain.entities.content_types import LayoutFragment


@dataclass(frozen=True)
class MessageContext:
    """Runtime context for a message send."""

    channel_title: str = ""
    channel_link: str = ""
    entry_title: str = ""
    entry_link: str = ""
    platform_name: str = ""
    send_mode: int | None = None
    style: int = 0
    sender_strategy: Any = None


@dataclass(frozen=True)
class SendRequest:
    """Request to send one message to one session."""

    session_id: str
    message: str = ""
    media: list[tuple[str, str]] | None = None
    layout: list[LayoutFragment] | None = None


@dataclass(frozen=True)
class SendResult:
    """Result returned by a message sender."""

    ok: bool = False
    needs_rebind: bool = False
    transient: bool = False
    detail: str = ""
    http_status: int | None = None


class MessageSender(Protocol):
    """Message sender implementation."""

    async def send_to_user(
        self,
        request: SendRequest,
        context: MessageContext | None = None,
    ) -> SendResult:
        """Send a message to the target session."""
        ...


class MessageSenderProvider(Protocol):
    """Resolve a sender for a platform."""

    def get(self, platform_name: str | None) -> MessageSender:
        """Return the sender adapter for a platform."""
        ...
