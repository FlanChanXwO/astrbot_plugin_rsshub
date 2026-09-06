"""Bundle 聊天命令处理器。

这里只解析 GreedyStr 风格的整段参数；归属、成员原子性、模板和积压保护
全部交给 ``BundleCommand``。
"""

from __future__ import annotations

import shlex
from typing import Any

from astrbot.api.event import AstrMessageEvent


def _split_args(args: str) -> list[str]:
    try:
        return shlex.split(str(args or ""))
    except ValueError as exc:
        raise ValueError(f"参数引号不完整: {exc}") from exc


def _event_user_id(event: AstrMessageEvent) -> str:
    return str(event.get_sender_id() or "").strip()


def _current_session(event: AstrMessageEvent) -> str:
    return str(getattr(event, "unified_msg_origin", "") or "").strip()


def _parse_positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是数字") from exc
    if parsed <= 0:
        raise ValueError(f"{label} 必须是正整数")
    return parsed


def _parse_feed_ids(tokens: list[str]) -> list[int]:
    feed_ids: list[int] = []
    for token in tokens:
        for raw_id in token.split(","):
            if not raw_id.strip():
                continue
            feed_ids.append(_parse_positive_int(raw_id.strip(), "Feed ID"))
    return feed_ids


def _append_targets(targets: list[str], raw_value: str) -> None:
    targets.extend(target.strip() for target in str(raw_value or "").split(","))


def _usage() -> str:
    return (
        "用法:\n"
        '/bundle create "名称" <feed_id> <feed_id...> '
        "[--targets target1,target2] [--interval 分钟]\n"
        "/bundle list | show <id> | add <id> <feed_id...>\n"
        "/bundle remove <id> <member_id...> | move <id> <member_id> <position>\n"
        "/bundle set <id> <option> <value> | state <id> on|off\n"
        "/bundle test|retry|discard|delete <id>"
    )


async def handle_bundle_create(
    event: AstrMessageEvent,
    args: str,
    deps: dict,
) -> dict:
    try:
        tokens = _split_args(args)
        if not tokens:
            return {"plain": _usage()}
        name = tokens.pop(0)
        feed_tokens: list[str] = []
        targets: list[str] = []
        interval: int | None = None
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in {"--target", "--targets"}:
                index += 1
                if index >= len(tokens):
                    raise ValueError("--targets 缺少目标会话")
                _append_targets(targets, tokens[index])
            elif token.startswith(("--targets=", "--target=")):
                _append_targets(targets, token.split("=", 1)[1])
            elif token in {"--interval", "-i"}:
                index += 1
                if index >= len(tokens):
                    raise ValueError("--interval 缺少数值")
                interval = _parse_positive_int(tokens[index], "interval")
            elif token.startswith(("--interval=", "interval=")):
                interval = _parse_positive_int(token.split("=", 1)[1], "interval")
            elif token.startswith(("targets=", "target=")):
                _append_targets(targets, token.split("=", 1)[1])
            elif token in {"--feed", "--feeds", "--feed-ids"}:
                index += 1
                if index >= len(tokens):
                    raise ValueError(f"{token} 缺少 Feed ID")
                feed_tokens.append(tokens[index])
            else:
                feed_tokens.append(token)
            index += 1

        feed_ids = _parse_feed_ids(feed_tokens)
        if not targets:
            targets = [_current_session(event)]
        result = await deps["bundle_cmd"].create(
            user_id=_event_user_id(event),
            name=name,
            feed_ids=feed_ids,
            target_sessions=targets,
            interval=interval,
        )
        return {"plain": result.message}
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}\n{_usage()}"}


async def handle_bundle_list(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    try:
        tokens = _split_args(args)
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}"}
    if tokens:
        return {"plain": "list 不接受额外参数，用法: /bundle list"}
    result = await deps["bundle_cmd"].list(user_id=_event_user_id(event))
    if not result.success or not result.data:
        return {"plain": result.message}
    lines = [result.message]
    for bundle in result.data:
        state = "启用" if bundle.state else "停用"
        lines.append(f"- [{bundle.id}] {bundle.name} | {state}")
    return {"plain": "\n".join(lines)}


async def handle_bundle_show(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    try:
        tokens = _split_args(args)
        if len(tokens) != 1:
            return {"plain": "用法: /bundle show <id>"}
        bundle_id = _parse_positive_int(tokens[0], "Bundle ID")
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}"}
    result = await deps["bundle_cmd"].show(
        bundle_id=bundle_id,
        user_id=_event_user_id(event),
    )
    if result.success and isinstance(result.data, dict):
        members = result.data.get("members") or []
        member_text = ", ".join(str(member.feed_id) for member in members) or "无"
        return {"plain": f"{result.message}\n成员 Feed: {member_text}"}
    return {"plain": result.message}


async def handle_bundle_add(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    return await _handle_member_batch(event, args, deps, action="add")


async def handle_bundle_remove(
    event: AstrMessageEvent,
    args: str,
    deps: dict,
) -> dict:
    return await _handle_member_batch(event, args, deps, action="remove")


async def _handle_member_batch(
    event: AstrMessageEvent,
    args: str,
    deps: dict,
    *,
    action: str,
) -> dict:
    try:
        tokens = _split_args(args)
        if len(tokens) < 2:
            return {"plain": f"用法: /bundle {action} <bundle_id> <member_id...>"}
        bundle_id = _parse_positive_int(tokens[0], "Bundle ID")
        member_ids = _parse_feed_ids(tokens[1:])
        if not member_ids:
            raise ValueError("请提供成员 ID")
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}"}
    if action == "add":
        result = await deps["bundle_cmd"].add(
            bundle_id=bundle_id,
            user_id=_event_user_id(event),
            feed_ids=member_ids,
        )
    else:
        result = await deps["bundle_cmd"].remove(
            bundle_id=bundle_id,
            user_id=_event_user_id(event),
            member_ids=member_ids,
        )
    return {"plain": result.message}


async def handle_bundle_move(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    try:
        tokens = _split_args(args)
        if len(tokens) != 3:
            return {"plain": "用法: /bundle move <bundle_id> <member_id> <position>"}
        bundle_id = _parse_positive_int(tokens[0], "Bundle ID")
        member_id = _parse_positive_int(tokens[1], "成员 ID")
        position = int(tokens[2])
        if position < 0:
            raise ValueError("position 不能小于 0")
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}"}
    result = await deps["bundle_cmd"].move(
        bundle_id=bundle_id,
        user_id=_event_user_id(event),
        member_id=member_id,
        position=position,
    )
    return {"plain": result.message}


async def handle_bundle_set(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    try:
        tokens = _split_args(args)
        if len(tokens) < 3:
            return {"plain": "用法: /bundle set <bundle_id> <option> <value>"}
        bundle_id = _parse_positive_int(tokens[0], "Bundle ID")
        option_tokens = tokens[1:]
        options: dict[str, Any] = {}
        if all("=" in token for token in option_tokens):
            for token in option_tokens:
                key, value = token.split("=", 1)
                options[key] = value
        else:
            options[option_tokens[0]] = " ".join(option_tokens[1:])
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}"}
    result = await deps["bundle_cmd"].set(
        bundle_id=bundle_id,
        user_id=_event_user_id(event),
        options=options,
    )
    return {"plain": result.message}


async def handle_bundle_state(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    try:
        tokens = _split_args(args)
        if len(tokens) != 2:
            return {"plain": "用法: /bundle state <bundle_id> on|off"}
        bundle_id = _parse_positive_int(tokens[0], "Bundle ID")
        state = tokens[1].lower()
        if state in {"on", "true", "1", "开启", "启用"}:
            enable = True
        elif state in {"off", "false", "0", "关闭", "停用"}:
            enable = False
        else:
            raise ValueError("状态只支持 on/off")
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}"}
    result = await deps["bundle_cmd"].state(
        bundle_id=bundle_id,
        user_id=_event_user_id(event),
        enable=enable,
    )
    return {"plain": result.message}


async def handle_bundle_test(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    try:
        tokens = _split_args(args)
        if not tokens or len(tokens) > 2:
            return {"plain": "用法: /bundle test <bundle_id> [target_session]"}
        bundle_id = _parse_positive_int(tokens[0], "Bundle ID")
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}"}
    is_admin = bool(event.is_admin())
    result = await deps["bundle_cmd"].test(
        bundle_id=bundle_id,
        user_id=_event_user_id(event),
        is_admin=is_admin,
        target_session=tokens[1] if len(tokens) == 2 else None,
    )
    return {"plain": result.message}


async def _handle_bundle_id_action(
    event: AstrMessageEvent,
    args: str,
    deps: dict,
    *,
    action: str,
) -> dict:
    try:
        tokens = _split_args(args)
        if len(tokens) != 1:
            return {"plain": f"用法: /bundle {action} <bundle_id>"}
        bundle_id = _parse_positive_int(tokens[0], "Bundle ID")
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}"}
    result = await getattr(deps["bundle_cmd"], action)(
        bundle_id=bundle_id,
        user_id=_event_user_id(event),
    )
    return {"plain": result.message}


async def handle_bundle_retry(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    return await _handle_bundle_id_action(event, args, deps, action="retry")


async def handle_bundle_discard(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    return await _handle_bundle_id_action(event, args, deps, action="discard")


async def handle_bundle_delete(event: AstrMessageEvent, args: str, deps: dict) -> dict:
    return await _handle_bundle_id_action(event, args, deps, action="delete")


async def handle_bundle_command(
    event: AstrMessageEvent,
    args: str,
    deps: dict,
) -> dict:
    """按第一个子命令分发，便于非 AstrBot 入口复用和测试。"""
    try:
        tokens = _split_args(args)
    except ValueError as exc:
        return {"plain": f"参数无效: {exc}"}
    if not tokens:
        return {"plain": _usage()}
    action = tokens[0].lower()
    remainder = " ".join(shlex.quote(token) for token in tokens[1:])
    handlers = {
        "create": handle_bundle_create,
        "list": handle_bundle_list,
        "show": handle_bundle_show,
        "add": handle_bundle_add,
        "remove": handle_bundle_remove,
        "move": handle_bundle_move,
        "set": handle_bundle_set,
        "state": handle_bundle_state,
        "test": handle_bundle_test,
        "retry": handle_bundle_retry,
        "discard": handle_bundle_discard,
        "delete": handle_bundle_delete,
    }
    handler = handlers.get(action)
    if handler is None:
        return {"plain": f"未知 Bundle 操作: {action}\n{_usage()}"}
    return await handler(event, remainder, deps)
