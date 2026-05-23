"""管理员命令处理器（纯函数）"""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent


async def handle_test_sub(event: AstrMessageEvent, sub_id: int, deps: dict) -> dict:
    """测试订阅推送"""
    args = sub_id.strip() if isinstance(sub_id, str) else str(sub_id).strip()
    if not args:
        return {"plain": "请提供目标\n用法: /sub_test <ID|URL>"}

    parts = [p.strip() for p in args.split() if p.strip()]
    if len(parts) != 1:
        return {"plain": "sub_test 不支持额外参数\n用法: /sub_test <ID|URL>"}
    target = parts[0]

    user_id = event.get_sender_id()
    result = await deps["test_sub_cmd"].execute_target(
        target=target,
        user_id=user_id,
        target_session=event.unified_msg_origin,
        platform_name=event.get_platform_name(),
        event=event,
    )
    return {"plain": result.message}
