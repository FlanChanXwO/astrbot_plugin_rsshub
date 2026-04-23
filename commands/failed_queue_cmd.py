"""失败队列相关命令逻辑"""

from ..db import FailedNotification, Sub


async def get_failed_queue_status(
    *,
    max_retries: int,
    user_id: str,
    failed_queue_capacity: int,
    is_admin: bool,
) -> dict:
    """获取失败队列状态

    Returns:
        {"success": bool, "message": str}
    """
    stats = await FailedNotification.get_stats(max_retries=max_retries)

    # 获取用户的待重试通知数
    user_subs = await Sub.get_by_user(user_id)
    user_sub_ids = [s.id for s in user_subs if s.id]

    failed_counts_by_sub = await FailedNotification.get_count_by_sub_ids(user_sub_ids)
    user_pending = sum(failed_counts_by_sub.values())

    lines = [
        "失败队列状态:",
        f"总待重试: {stats['pending']} 条",
        f"总已耗尽: {stats['exhausted']} 条",
        f"您的待重试: {user_pending} 条",
        "",
        "说明: 推送失败时，消息会进入失败队列等待重试。",
        f"队列容量: {failed_queue_capacity} 条/订阅",
    ]

    if is_admin:
        lines.extend(
            [
                "",
                "管理员: 每分钟监控任务会自动尝试重试失败队列中的消息。",
            ]
        )

    return {"success": True, "message": "\n".join(lines)}
