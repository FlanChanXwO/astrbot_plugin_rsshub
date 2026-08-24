"""Bundle 管理应用用例。

聊天命令、Web API 和后续 LLM tool 都应复用这里的归属、成员、模板与
可靠投递保护规则；入口层只负责把用户输入解析成方法参数。
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Sequence
from typing import Any

from ...domain.entities.bundle import Bundle
from ...domain.entities.handlers import parse_handlers_input
from ...domain.exceptions import DomainException
from ...domain.repositories.delivery_repository import (
    DeliveryDeletionBlockedError,
)
from ...infrastructure.config import validate_interval_value
from ..dto.result_dto import CommandResult
from ..services.card_template_policy import validate_card_template_selection

_BOOLEAN_TRUE_VALUES = {"1", "true", "yes", "on", "开启", "打开"}
_BOOLEAN_FALSE_VALUES = {"0", "false", "no", "off", "关闭", "停用"}

_FORMATTING_OPTIONS = {
    "notify",
    "send_mode",
    "length_limit",
    "display_author",
    "display_via",
    "display_title",
    "display_entry_tags",
    "style",
    "display_media",
}
_BOOLEAN_OPTIONS = {"send_card", "card_send_original_content"}
_SUPPORTED_OPTIONS = {
    "name",
    "target_sessions",
    "targets",
    "interval",
    "handlers",
    "template_id",
    *_FORMATTING_OPTIONS,
    *_BOOLEAN_OPTIONS,
}


def _as_bool(value: object, option: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in _BOOLEAN_TRUE_VALUES:
        return True
    if normalized in _BOOLEAN_FALSE_VALUES:
        return False
    raise ValueError(f"{option} 只支持 true / false")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class BundleCommand:
    """Bundle 的创建、配置、成员和可靠投递管理用例。"""

    def __init__(
        self,
        *,
        bundle_repository: Any,
        feed_repository: Any,
        user_repository: Any | None = None,
        delivery_repository: Any | None = None,
        template_repository: Any | None = None,
        polling_service: Any | None = None,
        bundle_batch_delivery_service: Any | None = None,
        default_interval: int = 10,
    ) -> None:
        self._bundle_repository = bundle_repository
        self._feed_repository = feed_repository
        self._user_repository = user_repository
        self._delivery_repository = delivery_repository
        self._template_repository = template_repository
        self._polling_service = polling_service
        self._bundle_batch_delivery_service = bundle_batch_delivery_service
        self._default_interval = default_interval

    async def create(
        self,
        *,
        user_id: str,
        name: str,
        feed_ids: Sequence[int],
        target_sessions: Sequence[str],
        interval: int | None = None,
    ) -> CommandResult:
        """以停用状态创建 Bundle，并原子写入全部成员。"""
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return CommandResult(success=False, message="用户 ID 不能为空")

        normalized_name = str(name or "").strip()
        if not normalized_name:
            return CommandResult(success=False, message="Bundle 名称不能为空")

        try:
            normalized_feed_ids = self._normalize_feed_ids(feed_ids)
            if len(normalized_feed_ids) < 2:
                return CommandResult(
                    success=False,
                    message="创建 Bundle 至少需要两个不同 Feed",
                )
            normalized_targets = self._normalize_targets(target_sessions)
            normalized_interval = validate_interval_value(
                self._default_interval if interval is None else interval,
                allow_inherit=False,
                field_name="interval",
            )
        except ValueError as exc:
            return CommandResult(success=False, message=str(exc))

        if await self._name_conflict(normalized_user_id, normalized_name):
            return CommandResult(
                success=False,
                message=f"Bundle 名称已存在: {normalized_name}",
            )

        missing = await self._missing_feed_ids(normalized_feed_ids)
        if missing:
            return CommandResult(
                success=False,
                message=f"Feed 不存在: {', '.join(map(str, missing))}",
            )

        if self._user_repository is not None:
            await _maybe_await(self._user_repository.get_or_create(normalized_user_id))

        bundle = Bundle(
            user_id=normalized_user_id,
            name=normalized_name,
            target_sessions=normalized_targets,
            interval=normalized_interval,
            state=0,
        )
        saved = None
        try:
            saved = await _maybe_await(self._bundle_repository.save(bundle))
            if saved is None or saved.id is None:
                return CommandResult(
                    success=False, message="Bundle 创建失败：未返回 ID"
                )
            await _maybe_await(
                self._bundle_repository.replace_members(saved.id, normalized_feed_ids)
            )
        except (ValueError, DeliveryDeletionBlockedError) as exc:
            cleanup_message = ""
            if saved is not None and saved.id is not None:
                try:
                    deleted = await _maybe_await(
                        self._bundle_repository.delete(saved.id)
                    )
                    if deleted is False:
                        cleanup_message = "；创建失败后的 Bundle 清理未确认"
                except (ValueError, DeliveryDeletionBlockedError) as cleanup_exc:
                    cleanup_message = f"；创建失败后的 Bundle 清理失败: {cleanup_exc}"
            return CommandResult(
                success=False,
                message=f"{exc}{cleanup_message}",
            )

        return CommandResult(
            success=True,
            message=f"已创建 Bundle「{saved.name}」(ID: {saved.id})",
            data=saved,
        )

    async def list(self, *, user_id: str) -> CommandResult:
        """列出当前用户拥有的 Bundle。"""
        bundles = await _maybe_await(self._bundle_repository.get_by_user(user_id))
        bundles = list(bundles or [])
        if not bundles:
            return CommandResult(success=True, message="暂无聚合订阅", data=[])
        return CommandResult(
            success=True,
            message=f"共有 {len(bundles)} 个聚合订阅",
            data=bundles,
        )

    async def show(self, *, bundle_id: int, user_id: str) -> CommandResult:
        """查看一个归属于当前用户的 Bundle 及其有序成员。"""
        owned = await self._owned(bundle_id, user_id)
        if isinstance(owned, CommandResult):
            return owned
        members = await _maybe_await(self._bundle_repository.list_members(bundle_id))
        members = list(members or [])
        return CommandResult(
            success=True,
            message=(
                f"Bundle「{owned.name}」(ID: {owned.id})："
                f"{len(members)} 个 Feed，状态={'启用' if owned.state else '停用'}"
            ),
            data={"bundle": owned, "members": members},
        )

    async def add(
        self,
        *,
        bundle_id: int,
        user_id: str,
        feed_ids: Sequence[int],
    ) -> CommandResult:
        """一次性添加多个成员，任何 Feed 无效都不写入。"""
        owned = await self._owned(bundle_id, user_id)
        if isinstance(owned, CommandResult):
            return owned
        try:
            additions = self._normalize_feed_ids(feed_ids, deduplicate=False)
        except ValueError as exc:
            return CommandResult(success=False, message=str(exc))
        if not additions:
            return CommandResult(success=False, message="请提供至少一个 Feed ID")

        members = list(
            await _maybe_await(self._bundle_repository.list_members(bundle_id)) or []
        )
        current_ids = [member.feed_id for member in members]
        duplicated = [feed_id for feed_id in additions if feed_id in current_ids]
        if duplicated:
            return CommandResult(
                success=False,
                message=f"Bundle 成员 Feed 不能重复: {duplicated}",
            )
        missing = await self._missing_feed_ids(additions)
        if missing:
            return CommandResult(
                success=False,
                message=f"Feed 不存在: {', '.join(map(str, missing))}",
            )

        desired = [*current_ids, *additions]
        try:
            updated_members = await _maybe_await(
                self._bundle_repository.replace_members(bundle_id, desired)
            )
        except (ValueError, DeliveryDeletionBlockedError) as exc:
            return CommandResult(success=False, message=str(exc))
        return CommandResult(
            success=True,
            message=f"已添加 {len(additions)} 个 Bundle 成员",
            data=updated_members,
        )

    async def remove(
        self,
        *,
        bundle_id: int,
        user_id: str,
        member_ids: Sequence[int] | int,
    ) -> CommandResult:
        """一次性移除多个成员，并让仓储在同一事务内执行删除保护。"""
        owned = await self._owned(bundle_id, user_id)
        if isinstance(owned, CommandResult):
            return owned
        try:
            targets = self._normalize_feed_ids(member_ids, deduplicate=True)
        except ValueError as exc:
            return CommandResult(success=False, message=str(exc))
        if not targets:
            return CommandResult(success=False, message="请提供至少一个成员 ID")

        members = list(
            await _maybe_await(self._bundle_repository.list_members(bundle_id)) or []
        )
        by_member_id = {
            member.id: member for member in members if member.id is not None
        }
        by_feed_id = {member.feed_id: member for member in members}
        resolved = []
        for target in targets:
            member = by_member_id.get(target) or by_feed_id.get(target)
            if member is None:
                return CommandResult(
                    success=False,
                    message=f"Bundle 成员不存在: {target}",
                )
            if member not in resolved:
                resolved.append(member)

        removed_ids = {member.id for member in resolved}
        desired = [member.feed_id for member in members if member.id not in removed_ids]
        try:
            updated_members = await _maybe_await(
                self._bundle_repository.replace_members(bundle_id, desired)
            )
        except (ValueError, DeliveryDeletionBlockedError) as exc:
            return CommandResult(success=False, message=str(exc))
        return CommandResult(
            success=True,
            message=f"已移除 {len(resolved)} 个 Bundle 成员",
            data=updated_members,
        )

    async def move(
        self,
        *,
        bundle_id: int,
        user_id: str,
        member_id: int,
        position: int,
    ) -> CommandResult:
        """移动一个成员到指定的 0-based position。"""
        owned = await self._owned(bundle_id, user_id)
        if isinstance(owned, CommandResult):
            return owned
        if position < 0:
            return CommandResult(success=False, message="position 不能小于 0")
        members = list(
            await _maybe_await(self._bundle_repository.list_members(bundle_id)) or []
        )
        selected = next(
            (
                member
                for member in members
                if member.id == member_id or member.feed_id == member_id
            ),
            None,
        )
        if selected is None or selected.id is None:
            return CommandResult(
                success=False, message=f"Bundle 成员不存在: {member_id}"
            )
        if position >= len(members):
            return CommandResult(success=False, message="position 超出范围")
        try:
            ordered = await _maybe_await(
                self._bundle_repository.move_member(selected.id, position)
            )
        except (ValueError, DeliveryDeletionBlockedError) as exc:
            return CommandResult(success=False, message=str(exc))
        return CommandResult(
            success=True, message="已调整 Bundle 成员顺序", data=ordered
        )

    async def set_option(
        self,
        *,
        bundle_id: int,
        user_id: str,
        option: str,
        value: Any,
    ) -> CommandResult:
        """更新一个 Bundle 配置选项。"""
        return await self.set(
            bundle_id=bundle_id,
            user_id=user_id,
            options={option: value},
        )

    async def set(
        self,
        *,
        bundle_id: int,
        user_id: str,
        options: dict[str, Any],
    ) -> CommandResult:
        """统一更新 Bundle 配置，先完成全量校验再持久化。"""
        owned = await self._owned(bundle_id, user_id)
        if isinstance(owned, CommandResult):
            return owned
        try:
            updates = self._normalize_options(options)
            candidate = owned.model_copy(update=updates)
            # model_copy(update=...) 不会重新跑 Pydantic 校验，显式复核实体边界。
            candidate = Bundle.model_validate(candidate.model_dump(by_alias=True))
        except (DomainException, TypeError, ValueError) as exc:
            return CommandResult(success=False, message=str(exc))

        if "name" in updates and await self._name_conflict(
            owned.user_id,
            candidate.name,
            exclude_id=bundle_id,
        ):
            return CommandResult(
                success=False,
                message=f"Bundle 名称已存在: {candidate.name}",
            )

        if owned.send_card and not candidate.send_card:
            if self._delivery_repository is None:
                return CommandResult(
                    success=False,
                    message="可靠投递仓储未初始化，不能关闭卡片",
                )
            try:
                await _maybe_await(
                    self._delivery_repository.ensure_owner_deletable(
                        self._delivery_owner(bundle_id)
                    )
                )
            except DeliveryDeletionBlockedError as exc:
                return CommandResult(success=False, message=str(exc))

        members = list(
            await _maybe_await(self._bundle_repository.list_members(bundle_id)) or []
        )
        template_error = await self._validate_template(candidate, members)
        if template_error is not None:
            return CommandResult(success=False, message=template_error)
        try:
            saved = await _maybe_await(self._bundle_repository.save(candidate))
        except (ValueError, DeliveryDeletionBlockedError) as exc:
            return CommandResult(success=False, message=str(exc))
        return CommandResult(
            success=True,
            message=f"已更新 Bundle 配置 (ID: {bundle_id})",
            data=saved,
        )

    async def state(
        self,
        *,
        bundle_id: int,
        user_id: str,
        enable: bool,
    ) -> CommandResult:
        """启用或停用 Bundle，并在启用时校验全部运行前置条件。"""
        owned = await self._owned(bundle_id, user_id)
        if isinstance(owned, CommandResult):
            return owned
        members = list(
            await _maybe_await(self._bundle_repository.list_members(bundle_id)) or []
        )
        if enable and len({member.feed_id for member in members}) < 2:
            return CommandResult(
                success=False,
                message="启用 Bundle 至少需要两个不同 Feed",
            )
        if enable and not owned.target_sessions:
            return CommandResult(
                success=False, message="启用 Bundle 至少需要一个目标会话"
            )

        candidate = owned.model_copy(
            update={
                "state": 1 if enable else 0,
                "next_check_time": None,
            }
        )
        template_error = await self._validate_template(candidate, members)
        if template_error is not None:
            return CommandResult(success=False, message=template_error)
        try:
            saved = await _maybe_await(self._bundle_repository.save(candidate))
        except (ValueError, DeliveryDeletionBlockedError) as exc:
            return CommandResult(success=False, message=str(exc))
        action = "启用" if enable else "停用"
        return CommandResult(
            success=True,
            message=f"已{action} Bundle (ID: {bundle_id})",
            data=saved,
        )

    async def test(
        self,
        *,
        bundle_id: int,
        user_id: str,
        is_admin: bool,
        target_session: str | None = None,
    ) -> CommandResult:
        """管理员只读测试：抓取成员但不写水位、inbox、batch 或 history。"""
        if not is_admin:
            return CommandResult(success=False, message="仅管理员可以测试 Bundle")
        bundle = await _maybe_await(self._bundle_repository.get_by_id(bundle_id))
        if bundle is None:
            return CommandResult(
                success=False, message=f"Bundle 不存在 (ID: {bundle_id})"
            )
        if target_session and target_session not in bundle.target_sessions:
            return CommandResult(success=False, message="目标会话不属于该 Bundle")
        if self._polling_service is None:
            return CommandResult(success=False, message="Bundle 测试服务未初始化")

        members = list(
            await _maybe_await(self._bundle_repository.list_members(bundle_id)) or []
        )
        if not members:
            return CommandResult(success=False, message="Bundle 没有成员")

        summaries: list[dict[str, Any]] = []
        failures = 0
        for member in members:
            feed = await _maybe_await(self._feed_repository.get_by_id(member.feed_id))
            if feed is None:
                failures += 1
                summaries.append(
                    {
                        "feed_id": member.feed_id,
                        "success": False,
                        "error": "Feed 不存在",
                    }
                )
                continue
            try:
                read_result = await _maybe_await(
                    self._polling_service.fetch_feed_entries(feed.link)
                )
            except Exception as exc:  # noqa: BLE001 - 每个成员独立报告抓取异常
                failures += 1
                summaries.append(
                    {"feed_id": feed.id, "success": False, "error": str(exc)}
                )
                continue
            success = bool(getattr(read_result, "success", False))
            if not success:
                failures += 1
            summaries.append(
                {
                    "feed_id": feed.id,
                    "success": success,
                    "entry_count": len(getattr(read_result, "entries", []) or []),
                    "error": str(
                        getattr(read_result, "error", None)
                        or getattr(read_result, "message", "")
                        or ""
                    ),
                }
            )

        success_count = len(summaries) - failures
        return CommandResult(
            success=failures == 0,
            message=(
                f"Bundle 测试完成：{success_count}/{len(summaries)} 个 Feed 成功"
                if failures == 0
                else f"Bundle 测试失败：{success_count}/{len(summaries)} 个 Feed 成功"
            ),
            data=summaries,
        )

    async def retry(self, *, bundle_id: int, user_id: str) -> CommandResult:
        """人工重试当前 Bundle 未完成输出。"""
        owned = await self._owned(bundle_id, user_id)
        if isinstance(owned, CommandResult):
            return owned
        if self._bundle_batch_delivery_service is None:
            return CommandResult(success=False, message="Bundle 投递服务未初始化")
        try:
            result = await _maybe_await(
                self._bundle_batch_delivery_service.retry(bundle_id)
            )
        except (ValueError, RuntimeError, DeliveryDeletionBlockedError) as exc:
            return CommandResult(success=False, message=str(exc))
        if getattr(result, "batch_id", None) is None:
            return CommandResult(success=False, message="没有可重试的 Bundle 积压")
        return CommandResult(
            success=True,
            message=f"已触发 Bundle 重试 (batch_id: {result.batch_id})",
            data=result,
        )

    async def discard(self, *, bundle_id: int, user_id: str) -> CommandResult:
        """显式丢弃当前 Bundle 批次，并消费该批已认领输入。"""
        owned = await self._owned(bundle_id, user_id)
        if isinstance(owned, CommandResult):
            return owned
        if self._bundle_batch_delivery_service is None:
            return CommandResult(success=False, message="Bundle 投递服务未初始化")
        try:
            result = await _maybe_await(
                self._bundle_batch_delivery_service.discard(bundle_id)
            )
        except (ValueError, RuntimeError, DeliveryDeletionBlockedError) as exc:
            return CommandResult(success=False, message=str(exc))
        if result is None:
            return CommandResult(
                success=False, message="没有可丢弃的未确认 Bundle 批次"
            )
        return CommandResult(
            success=True, message=f"已丢弃 Bundle 批次 (ID: {bundle_id})", data=result
        )

    async def delete(self, *, bundle_id: int, user_id: str) -> CommandResult:
        """删除 Bundle；未解决 inbox 或批次由仓储原子阻止。"""
        owned = await self._owned(bundle_id, user_id)
        if isinstance(owned, CommandResult):
            return owned
        try:
            deleted = await _maybe_await(self._bundle_repository.delete(bundle_id))
        except DeliveryDeletionBlockedError as exc:
            return CommandResult(
                success=False,
                message=f"Bundle 有未解决投递，不能删除: {exc}",
            )
        if not deleted:
            return CommandResult(
                success=False, message=f"Bundle 删除失败 (ID: {bundle_id})"
            )
        return CommandResult(success=True, message=f"已删除 Bundle (ID: {bundle_id})")

    async def _owned(self, bundle_id: int, user_id: str) -> Bundle | CommandResult:
        if bundle_id <= 0:
            return CommandResult(success=False, message="Bundle ID 必须是正整数")
        bundle = await _maybe_await(self._bundle_repository.get_by_id(bundle_id))
        if bundle is None:
            return CommandResult(
                success=False, message=f"Bundle 不存在 (ID: {bundle_id})"
            )
        if bundle.user_id != user_id:
            return CommandResult(success=False, message="无权操作此 Bundle")
        return bundle

    @staticmethod
    def _normalize_feed_ids(
        feed_ids: Sequence[int] | int,
        *,
        deduplicate: bool = True,
    ) -> list[int]:
        raw_ids = [feed_ids] if isinstance(feed_ids, int) else list(feed_ids or [])
        normalized: list[int] = []
        seen: set[int] = set()
        for raw_id in raw_ids:
            try:
                feed_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("Feed ID 必须是数字") from exc
            if feed_id <= 0:
                raise ValueError("Feed ID 必须是正整数")
            if feed_id in seen:
                if not deduplicate:
                    raise ValueError(f"Feed ID 不能重复: {feed_id}")
                continue
            seen.add(feed_id)
            normalized.append(feed_id)
        return normalized

    @staticmethod
    def _normalize_targets(target_sessions: Sequence[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_target in target_sessions or []:
            target = str(raw_target or "").strip()
            if not target:
                raise ValueError("目标会话不能为空")
            if target not in seen:
                normalized.append(target)
                seen.add(target)
        if not normalized:
            raise ValueError("Bundle 至少需要一个目标会话")
        return normalized

    async def _missing_feed_ids(self, feed_ids: Sequence[int]) -> list[int]:
        _feeds, missing = await self._load_feeds(feed_ids)
        return missing

    async def _name_conflict(
        self,
        user_id: str,
        name: str,
        *,
        exclude_id: int | None = None,
    ) -> bool:
        existing = await _maybe_await(self._bundle_repository.get_by_user(user_id))
        return any(
            bundle.name == name and bundle.id != exclude_id
            for bundle in (existing or [])
        )

    async def _load_feeds(
        self,
        feed_ids: Sequence[int],
    ) -> tuple[list[Any], list[int]]:
        """批量读取 Feed，并按请求顺序返回，供全量校验复用。"""
        getter = getattr(self._feed_repository, "get_by_ids", None)
        if getter is not None and callable(getter):
            feeds = list(await _maybe_await(getter(list(feed_ids))) or [])
            by_id = {
                int(feed.id): feed
                for feed in feeds
                if getattr(feed, "id", None) is not None
            }
            ordered = [by_id[feed_id] for feed_id in feed_ids if feed_id in by_id]
            missing = [feed_id for feed_id in feed_ids if feed_id not in by_id]
            return ordered, missing

        ordered = []
        missing = []
        for feed_id in feed_ids:
            feed = await _maybe_await(self._feed_repository.get_by_id(feed_id))
            if feed is None:
                missing.append(feed_id)
            else:
                ordered.append(feed)
        return ordered, missing

    def _normalize_options(self, options: dict[str, Any]) -> dict[str, Any]:
        if not options:
            raise ValueError("请提供要更新的配置项")
        updates: dict[str, Any] = {}
        for raw_option, raw_value in options.items():
            option = str(raw_option or "").strip().lower()
            if option not in _SUPPORTED_OPTIONS:
                raise ValueError(f"不支持的 Bundle 配置项: {option}")
            if option in _BOOLEAN_OPTIONS:
                updates[option] = _as_bool(raw_value, option)
            elif option == "interval":
                updates[option] = validate_interval_value(
                    raw_value,
                    allow_inherit=False,
                    field_name="interval",
                )
            elif option in _FORMATTING_OPTIONS:
                try:
                    updates[option] = int(raw_value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{option} 需要数字值") from exc
            elif option == "name":
                value = str(raw_value or "").strip()
                if not value:
                    raise ValueError("Bundle 名称不能为空")
                updates[option] = value
            elif option in {"target_sessions", "targets"}:
                if isinstance(raw_value, str):
                    raw_targets = raw_value.split(",")
                else:
                    raw_targets = list(raw_value or [])
                updates["target_sessions"] = self._normalize_targets(raw_targets)
            elif option == "handlers":
                updates["handlers"] = parse_handlers_input(raw_value)
            elif option == "template_id":
                normalized = str(raw_value or "").strip()
                updates[option] = normalized or None
        return updates

    async def _validate_template(
        self,
        bundle: Bundle,
        members: Sequence[Any],
    ) -> str | None:
        if not bundle.send_card:
            return None
        if self._template_repository is None:
            return "卡片模板配置无效: 模板仓储未初始化"
        feed_ids = [member.feed_id for member in members]
        feeds, missing = await self._load_feeds(feed_ids)
        if missing:
            return f"卡片模板配置无效: Feed 不存在: {missing}"
        feed_urls = [str(feed.link) for feed in (feeds or [])]
        if len(feed_urls) != len(feed_ids):
            return "卡片模板配置无效: Bundle 成员 Feed 不完整"
        try:
            package = await self._template_get(bundle.template_id)
        except (DomainException, ValueError) as exc:
            return f"卡片模板配置无效: {exc}"
        metadata = getattr(package, "metadata", None) if package is not None else None
        try:
            validate_card_template_selection(
                owner=bundle,
                template=metadata,
                feed_urls=feed_urls,
            )
        except (DomainException, ValueError) as exc:
            return f"卡片模板配置无效: {exc}"
        return None

    async def _template_get(self, template_id: str | None) -> Any:
        if not template_id:
            return None
        getter = getattr(self._template_repository, "get", None)
        if getter is None:
            return None
        result = await asyncio.to_thread(getter, template_id)
        return await _maybe_await(result)

    @staticmethod
    def _delivery_owner(bundle_id: int):
        from ...domain.entities.delivery import DeliveryOwner

        return DeliveryOwner(owner_type="bundle", owner_id=bundle_id)


BundleManagementCommand = BundleCommand
