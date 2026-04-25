"""Commands return types.

TypedDict definitions for command return values to provide type-safe access.
"""

from __future__ import annotations

from typing import TypedDict, TypeVar


class CommandResult(TypedDict, total=False):
    """Base command result type."""

    success: bool
    message: str
    error: str


class SubscribeResult(CommandResult):
    """Subscribe command result."""

    sub_id: int


class ListSubscriptionsResult(CommandResult):
    """List subscriptions command result."""

    has_more: bool


class UnsubscribeAllResult(CommandResult):
    """Unsubscribe all command result."""

    export_path: str
    export_filename: str


class ExportSubscriptionsResult(CommandResult):
    """Export subscriptions command result."""

    export_path: str
    export_filename: str


class ImportSubscriptionsResult(CommandResult):
    """Import subscriptions command result."""

    imported: int
    skipped: int
    failed: int


class GetSessionDefaultsResult(CommandResult):
    """Get session defaults command result."""

    defaults: dict[str, int | str]


class CommandResultT(CommandResult, total=False):
    """Generic command result type variable."""

    data: object


class SetSessionDefaultResult(CommandResult):
    """Set session default command result."""


class SetPluginConfigResult(CommandResult):
    """Set plugin config command result."""


class SetUserDefaultOptionResult(CommandResult):
    """Set user default option command result."""


class SetSubscriptionOptionResult(CommandResult):
    """Set subscription option command result."""


class TestSubscriptionResult(CommandResult):
    """Test subscription command result."""


class BatchSubscribeResult(CommandResult):
    """Batch subscribe command result."""

    successful: list[dict[str, object]]  # 成功的订阅信息列表 [{sub_id, title, url}]
    failed: list[dict[str, str]]  # 失败的信息列表 [{url, reason}]


class BatchUnsubscribeResult(CommandResult):
    """Batch unsubscribe command result."""

    successful_count: int
    failed: list[dict[str, str]]  # 失败的信息列表 [{target, reason}]


T = TypeVar("T", bound=CommandResult)
