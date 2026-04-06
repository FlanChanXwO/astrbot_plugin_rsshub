"""Helpers for command-layer unsubscribe/import flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..db import Feed, Sub
from .subscription_io import SubscriptionImportPayload, serialize_subscriptions_to_toml


@dataclass(slots=True)
class ImportApplyResult:
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    details: list[str] = field(default_factory=list)


def select_subscriptions_for_scope(
    subscriptions: list,
    *,
    current_session: str,
    is_global: bool,
) -> tuple[list, str]:
    """Select subscriptions to delete and return localized scope label."""
    if is_global:
        return subscriptions, "所有会话"

    selected = [
        sub
        for sub in subscriptions
        if (sub.target_session or current_session) == current_session
    ]
    return selected, "当前会话"


def build_subscriptions_export_text(*, user_id: str, subscriptions: list) -> str:
    """Serialize subscriptions to TOML text for backup exports."""
    return serialize_subscriptions_to_toml(user_id=user_id, subscriptions=subscriptions)


async def delete_subscriptions(subscriptions: list) -> int:
    """Delete subscriptions and return deleted count."""
    deleted_count = 0
    for sub in subscriptions:
        await Sub.delete(sub)
        deleted_count += 1
    return deleted_count


async def apply_import_payload(
    *,
    payload: SubscriptionImportPayload,
    user_id: int,
    user_db_id: int,
    current_session: str,
    default_platform_name: str,
    validate_options: Callable[
        [dict[str, int | str]], tuple[dict[str, int | str], str | None]
    ],
) -> ImportApplyResult:
    """Apply parsed TOML payload into DB and return import statistics."""
    result = ImportApplyResult()
    seen_pairs: set[tuple[str, str]] = set()

    for index, record in enumerate(payload.records, start=1):
        options = dict(record.options)
        validated, option_err = validate_options(options)
        if option_err:
            result.failed += 1
            result.details.append(f"[{index}] 选项校验失败: {option_err}")
            continue

        target_session = str(validated.get("target_session") or current_session)
        pair = (record.link, target_session)
        if pair in seen_pairs:
            result.skipped += 1
            result.details.append(f"[{index}] 文件内重复订阅，已跳过: {record.link}")
            continue
        seen_pairs.add(pair)

        exists = await Sub.get_by_user_and_link(user_id, record.link, target_session)
        if exists:
            result.skipped += 1
            continue

        feed = await Feed.get_or_create(
            link=record.link,
            title=(record.feed_title or record.link),
        )
        platform_name = str(validated.pop("platform_name", "") or default_platform_name)
        sub = await Sub.create(
            user_id=user_db_id,
            feed_id=feed.id,
            target_session=target_session,
            platform_name=platform_name,
        )

        validated.pop("target_session", None)
        if validated:
            updated = await Sub.update_options(sub.id, user_id, **validated)
            if not updated:
                result.failed += 1
                result.details.append(f"[{index}] 导入后写入选项失败: {record.link}")
                continue

        result.imported += 1

    return result
