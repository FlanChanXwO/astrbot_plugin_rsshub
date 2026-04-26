"""订阅相关命令逻辑"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from astrbot.api.message_components import File
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from ..api import feed_get
from ..config import cfg
from ..db import Feed, Sub, User
from ..utils.command_helpers import (
    ImportApplyResult,
    apply_import_payload,
    build_subscriptions_export_text,
    delete_subscriptions,
    select_subscriptions_for_scope,
)
from ..utils.subscription_io import parse_subscriptions_toml
from .types import (
    BatchSubscribeResult,
    BatchUnsubscribeResult,
    CommandResult,
    ExportSubscriptionsResult,
    ImportSubscriptionsResult,
    ListSubscriptionsResult,
    SetSubscriptionOptionResult,
    SubscribeResult,
    UnsubscribeAllResult,
)

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent


async def subscribe_feed(
    *,
    url: str,
    target: str,
    user_id: str,
    platform_name: str,
    timeout: int,
    proxy: str,
    session_defaults: dict[str, int | str],
    parse_target_fn: Callable[[str], tuple[str | None, str | None]],
) -> SubscribeResult:
    """订阅 RSS 源"""
    if not url:
        return {"success": False, "error": "请提供 RSS 链接，用法：/sub <RSS 链接>"}

    if not re.match(r"^https?://", url):
        return {
            "success": False,
            "error": "请提供有效的 RSS 链接（需以 http 或 https 开头）",
        }

    wf = await feed_get(url, timeout=timeout, proxy=proxy)
    if wf.error:
        return {"success": False, "error": f"订阅失败：{wf.error.error_name}"}

    if wf.rss_d is None:
        return {"success": False, "error": "订阅失败：无法解析 RSS 内容"}

    title = wf.rss_d.feed.get("title", url)
    user = await User.get_or_create(user_id)

    # 解析目标会话
    target_session, target_err = parse_target_fn(target)
    if target_err:
        return {"success": False, "error": target_err}

    # 检查重复订阅
    existing_sub = await Sub.get_by_user_and_link(user_id, url, target_session)
    if existing_sub:
        return {
            "success": False,
            "error": f"您已经订阅了此源：{existing_sub.feed.title}",
        }

    feed = await Feed.get_or_create(link=url, title=title)

    sub = await Sub.create(
        user_id=user.id,
        feed_id=feed.id,
        target_session=target_session,
        platform_name=platform_name,
    )

    # 应用会话默认设置
    if session_defaults:
        update_payload = {}
        for key, raw_value in session_defaults.items():
            if key in {"title", "tags"}:
                update_payload[key] = str(raw_value)
            else:
                try:
                    update_payload[key] = int(raw_value)
                except (ValueError, TypeError):
                    pass
        if update_payload:
            await Sub.update_options(sub.id, user.id, **update_payload)

    # 设置用户默认目标
    if target_session:
        await User.set_default_target(user.id, target_session)

    return {
        "success": True,
        "message": (
            f"订阅成功!\n"
            f"源标题：{title}\n"
            f"订阅 ID: {sub.id}\n"
            f"推送目标：{target_session or '未设置'}"
        ),
        "sub_id": sub.id,
    }


async def unsubscribe_feed(
    *,
    sub_id: str,
    user_id: str,
    current_session: str,
    is_admin: bool,
    platform_name: str,
) -> SubscribeResult:
    """取消订阅"""
    if not sub_id:
        return {"success": False, "error": "请提供订阅 ID，用法：/unsub <订阅 ID>"}

    try:
        sub_id_int = int(sub_id)
    except ValueError:
        return {"success": False, "error": "订阅 ID 必须是数字"}

    sub = await Sub.get_by_id(sub_id_int)
    if not sub:
        return {"success": False, "error": "未找到该订阅"}

    if not is_admin:
        is_owner = sub.user_id == user_id
        is_current_session = bool(sub.target_session) and (
            sub.target_session == current_session
        )

        if not (is_owner or is_current_session):
            return {"success": False, "error": "无权限删除该订阅"}

    # 构建取消订阅的详细信息（简约列表格式）
    feed_title = sub.feed.title if sub.feed else "未知"
    feed_link = sub.feed.link if sub.feed else ""
    custom_title = f" ({sub.title})" if sub.title else ""

    await Sub.delete(sub)

    lines = [
        "已取消的订阅列表（当前会话）:",
        "共 1 个订阅",
        f"1. [{sub_id_int}] ✗ {feed_title}{custom_title}",
    ]
    if feed_link:
        lines.append(f"    {feed_link}")

    return {"success": True, "message": "\n".join(lines)}


async def unsubscribe_feed_by_url(
    *,
    url: str,
    user_id: str,
    current_session: str,
    is_admin: bool,
    platform_name: str,
) -> CommandResult:
    """根据 URL 取消当前会话的订阅（精确匹配）"""
    # 验证 URL 格式
    if not re.match(r"^https?://", url):
        return {"success": False, "error": f"无效的 URL: {url}"}

    # 查找订阅
    sub = await Sub.get_by_user_and_link(user_id, url, current_session)

    if not sub:
        return {
            "success": False,
            "error": f"当前会话未找到此订阅: {url}",
        }

    # 权限检查
    if not is_admin:
        is_owner = sub.user_id == user_id
        is_current_session = bool(sub.target_session) and (
            sub.target_session == current_session
        )

        if not (is_owner or is_current_session):
            return {"success": False, "error": f"无权限取消订阅: {url}"}

    # 构建取消订阅的详细信息（简约列表格式）
    feed_title = sub.feed.title if sub.feed else "未知"
    feed_link = sub.feed.link if sub.feed else url
    custom_title = f" ({sub.title})" if sub.title else ""
    sub_id = sub.id

    await Sub.delete(sub)

    lines = [
        "已取消的订阅列表（当前会话）:",
        "共 1 个订阅",
        f"1. [{sub_id}] ✗ {feed_title}{custom_title}",
    ]
    if feed_link:
        lines.append(f"    {feed_link}")

    return {"success": True, "message": "\n".join(lines)}


async def batch_subscribe_feeds(
    *,
    urls: list[str],
    target: str,
    user_id: str,
    platform_name: str,
    timeout: int,
    proxy: str,
    session_defaults: dict[str, int | str],
    parse_target_fn: Callable[[str], tuple[str | None, str | None]],
) -> BatchSubscribeResult:
    """批量订阅多个 RSS 源"""
    if not urls:
        return {
            "success": False,
            "error": "请提供至少一个 RSS 链接",
            "successful": [],
            "failed": [],
        }

    successful: list[dict[str, object]] = []
    failed: list[dict[str, str]] = []

    for url in urls:
        result = await subscribe_feed(
            url=url,
            target=target,
            user_id=user_id,
            platform_name=platform_name,
            timeout=timeout,
            proxy=proxy,
            session_defaults=session_defaults,
            parse_target_fn=parse_target_fn,
        )

        if result["success"]:
            successful.append(
                {
                    "sub_id": result.get("sub_id", 0),
                    "title": result.get("sub_title", url),
                    "url": url,
                }
            )
        else:
            failed.append({"url": url, "reason": result.get("error", "未知错误")})

    success_count = len(successful)
    fail_count = len(failed)

    if success_count == 0:
        return {
            "success": False,
            "error": f"所有 {fail_count} 个订阅均失败",
            "successful": successful,
            "failed": failed,
        }

    return {
        "success": True,
        "message": f"批量订阅完成：成功 {success_count} 个，失败 {fail_count} 个",
        "successful": successful,
        "failed": failed,
    }


async def batch_unsubscribe_feeds(
    *,
    targets: list[str],
    user_id: str,
    current_session: str,
    is_admin: bool,
    platform_name: str,
) -> BatchUnsubscribeResult:
    """批量取消订阅（支持 ID 列表或 URL 列表）"""
    if not targets:
        return {
            "success": False,
            "error": "请提供至少一个订阅 ID 或 URL",
            "successful_count": 0,
            "failed": [],
        }

    successful_count = 0
    failed: list[dict[str, str]] = []

    for target in targets:
        target = target.strip()
        if not target:
            continue

        # 判断是 ID 还是 URL
        is_id = target.isdigit()

        if is_id:
            # 按 ID 取消
            result = await unsubscribe_feed(
                sub_id=target,
                user_id=user_id,
                current_session=current_session,
                is_admin=is_admin,
                platform_name=platform_name,
            )
        else:
            # 按 URL 取消
            result = await unsubscribe_feed_by_url(
                url=target,
                user_id=user_id,
                current_session=current_session,
                is_admin=is_admin,
                platform_name=platform_name,
            )

        if result["success"]:
            successful_count += 1
        else:
            failed.append({"target": target, "reason": result.get("error", "未知错误")})

    total = len(targets)
    fail_count = len(failed)

    if successful_count == 0:
        return {
            "success": False,
            "error": f"所有 {total} 个取消操作均失败",
            "successful_count": 0,
            "failed": failed,
        }

    return {
        "success": True,
        "message": f"批量取消完成：成功 {successful_count} 个，失败 {fail_count} 个",
        "successful_count": successful_count,
        "failed": failed,
    }


async def list_subscriptions(
    *,
    user_id: str,
    current_session: str,
    platform_name: str,
    is_admin: bool,
    scope: str,
    page: str,
    page_size: str,
) -> ListSubscriptionsResult:
    """列出订阅"""
    scope_value = scope.strip().lower()
    show_all_sessions = scope_value == "all" and is_admin

    list_offset = 0
    total_count = 0
    page_int = 1
    page_size_int = 5

    if show_all_sessions:
        try:
            page_int = max(1, int(page.strip() or "1"))
            page_size_int = int(page_size.strip() or "5")
        except ValueError:
            return {"success": False, "error": "分页参数无效"}

        page_size_int = max(1, min(page_size_int, 100))
        list_offset = (page_int - 1) * page_size_int

    if show_all_sessions:
        subs, total_count = await Sub.get_all_active_paged(
            page=page_int, page_size=page_size_int
        )
        total_pages = max(1, (total_count + page_size_int - 1) // page_size_int)
        lines = [
            "订阅列表（全局，所有平台/会话）:",
            f"页码: {page_int}/{total_pages}  每页: {page_size_int}  总数: {total_count}",
        ]
    else:
        subs = await Sub.get_by_user(user_id)
        lines = ["您的订阅列表（当前会话）:"]

    if not subs:
        if show_all_sessions:
            return {"success": True, "message": "当前没有任何订阅"}
        return {"success": True, "message": "您还没有任何订阅"}

    if not show_all_sessions:
        subs = [
            sub
            for sub in subs
            if (sub.target_session or current_session) == current_session
        ]
        # 统计会话状态
        total_count = len(subs)
        active_count = sum(1 for sub in subs if sub.state == 1)
        inactive_count = total_count - active_count

        if not subs:
            return {
                "success": True,
                "message": (
                    "当前会话没有订阅。\n"
                    "可使用 /sub 添加订阅；管理员可用 /sub_list all 查看所有会话。"
                ),
            }

        lines.append(
            f"共 {total_count} 个订阅 | 启用: {active_count} | 禁用: {inactive_count}"
        )

    for idx, sub in enumerate(subs, list_offset + 1):
        feed_title = sub.feed.title if sub.feed else "未知"
        feed_link = sub.feed.link if sub.feed else ""
        custom_title = f" ({sub.title})" if sub.title else ""
        state_icon = "✓" if sub.state == 1 else "✗"
        lines.append(f"{idx}. [{sub.id}] {state_icon} {feed_title}{custom_title}")
        if show_all_sessions:
            lines.append(f"    user: {sub.user_id}")
            lines.append(f"    platform: {sub.platform_name or '(unknown)'}'")
            lines.append(f"    target: {sub.target_session or '(未绑定)'}'")
            lines.append(f"    state: {'启用' if sub.state == 1 else '禁用'}")
        if feed_link:
            lines.append(f"    {feed_link}")

    has_more = False
    if show_all_sessions and page_int < total_pages:
        has_more = True

    return {"success": True, "message": "\n".join(lines), "has_more": has_more}


async def test_subscription(
    *,
    target: str,
    start_index: int,
    end_index: int | None,
    target_session: str,
    platform_name: str,
    user_id: str,
    timeout: int,
    proxy: str,
    download_media_before_send: bool,
) -> CommandResult:
    """管理员测试推送

    支持通过订阅ID或URL进行测试推送。
    - 订阅ID: 使用订阅的配置
    - URL: 使用全局配置创建临时订阅

    Args:
        target: 订阅ID或RSS URL
        start_index: 起始条目编号（从1开始，1=最新）
        end_index: 结束条目编号（可选，None表示只推送起始条目）
        target_session: 推送目标会话
        platform_name: 平台类型名（如 aiocqhttp, telegram 等）
        user_id: 用户ID
        timeout: 请求超时时间
        proxy: 代理设置
        download_media_before_send: 是否在发送前下载媒体

    Returns:
        {"success": bool, "message": str, "error": str}
    """
    if not target:
        return {"success": False, "error": "请提供订阅ID或RSS链接"}

    # 判断目标是订阅ID还是URL
    is_url = target.startswith(("http://", "https://"))

    feed_link: str
    feed_title: str
    sub: Sub | None = None

    if is_url:
        # URL模式：使用全局配置
        feed_link = target
        feed_title = "测试订阅"
    else:
        # 订阅ID模式：查询数据库
        try:
            sub_id_int = int(target)
        except ValueError:
            return {"success": False, "error": "订阅ID必须是数字，或提供有效的RSS链接"}

        sub = await Sub.get_by_id(sub_id_int)
        if not sub:
            return {"success": False, "error": f"未找到订阅ID={target}"}
        if not sub.feed:
            return {"success": False, "error": "该订阅缺少Feed信息"}

        feed_link = sub.feed.link
        feed_title = sub.feed.title

    # 抓取Feed
    wf = await feed_get(feed_link, timeout=timeout, proxy=proxy)
    if wf.error:
        # 构建详细错误信息
        error_parts = [f"测试抓取失败: {wf.error.error_name}", f"URL: {feed_link}"]
        if wf.error.status:
            error_parts.append(f"状态码: {wf.error.status}")
        if wf.error.base_error:
            error_parts.append(f"详情: {wf.error.base_error}")
        return {"success": False, "error": " | ".join(error_parts)}

    if wf.rss_d is None or not wf.rss_d.entries:
        return {"success": True, "message": "测试抓取成功，但该源暂无可推送条目"}

    # 准备Feed和Sub对象
    entries = list(wf.rss_d.entries)
    total_entries = len(entries)

    # 创建临时Feed对象
    from ..db import Feed

    feed = Feed(
        link=feed_link,
        title=wf.rss_d.feed.get("title", feed_title),
        entry_hashes=[],
    )

    if is_url:
        # URL模式：创建临时Sub对象，使用全局配置
        # 使用传入的 platform_name（平台类型名，如 aiocqhttp, telegram 等）
        # 注意：不要从 target_session 提取，因为那是适配器ID（如 default），不是平台类型名
        # 使用 to_db_values() 获取转换后的整数值
        db_values = cfg.global_config.to_db_values()

        sub = Sub(
            id=0,  # 临时ID
            state=1,
            user_id=user_id,
            feed_id=0,
            target_session=target_session,
            platform_name=platform_name,
            use_sub_config=True,
            interval=db_values["interval"],
            notify=db_values["notify"],
            send_mode=db_values["send_mode"],
            length_limit=db_values["length_limit"],
            link_preview=db_values["link_preview"],
            display_author=db_values["display_author"],
            display_via=db_values["display_via"],
            display_title=db_values["display_title"],
            display_entry_tags=db_values["display_entry_tags"],
            style=db_values["style"],
            display_media=db_values["display_media"],
            translate=db_values["translate"],
            translate_target_lang=db_values["translate_target_lang"],
        )
        target_desc = f"URL={feed_link}"
    else:
        target_desc = f"订阅ID={target}"

    # 验证条目编号范围
    if start_index < 1:
        return {"success": False, "error": "起始条目编号必须大于等于1"}

    if start_index > total_entries:
        return {
            "success": False,
            "error": f"起始条目编号超出范围（最大{total_entries}）",
        }

    # 确定结束编号
    actual_end = end_index if end_index is not None else start_index
    if actual_end > total_entries:
        actual_end = total_entries

    if actual_end < start_index:
        return {"success": False, "error": "结束条目编号不能小于起始编号"}

    # 选择条目（编号1 = 索引0）
    selected = entries[start_index - 1 : actual_end]

    # 发送通知
    from ..notifier import Notifier

    notifier = Notifier(
        feed=feed,
        subs=[sub],
        entries=selected,
        timeout_seconds=timeout,
        proxy=proxy,
        download_media_before_send=download_media_before_send,
    )
    try:
        await notifier.notify_all()
    finally:
        await notifier.close()

    # 构建结果消息
    if len(selected) == 1:
        entry_desc = f"条目{start_index}"
    else:
        entry_desc = f"条目{start_index}-{actual_end}（共{len(selected)}条）"

    first_title = selected[0].get("title") or "(无标题)"
    return {
        "success": True,
        "message": (
            f"✅ 测试推送成功\n"
            f"目标: {target_desc}\n"
            f"推送: {entry_desc} -> {target_session}\n"
            f"首条: {first_title[:50]}..."
        ),
    }


async def unsubscribe_all_feeds(
    *,
    user_id: str,
    current_session: str,
    is_admin: bool,
    scope: str,
    unsub_export_retention_seconds: int,
) -> UnsubscribeAllResult:
    """取消所有订阅

    Returns:
        {"success": bool, "message": str, "error": str, "export_path": Path}
    """
    scope_value = scope.strip().lower()

    if scope_value and scope_value != "global":
        return {"success": False, "error": "参数无效。用法: /unsub_all [global]"}

    is_global = scope_value == "global"

    if is_global and not is_admin:
        return {"success": False, "error": "清除所有会话订阅需要管理员权限"}

    subscriptions = await Sub.get_by_user(user_id)
    if not subscriptions:
        return {"success": False, "error": "您当前没有可删除的订阅"}

    # 筛选订阅
    to_delete, scope_desc = select_subscriptions_for_scope(
        subscriptions,
        current_session=current_session,
        is_global=is_global,
    )

    if not to_delete:
        return {"success": False, "error": f"当前{scope_desc}没有订阅"}

    # 导出备份
    export_text = build_subscriptions_export_text(
        user_id=str(user_id),
        subscriptions=to_delete,
    )

    temp_dir = Path(get_astrbot_temp_path())
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 清理旧备份
    now = datetime.now(UTC).timestamp()
    cutoff = now - unsub_export_retention_seconds
    for path in temp_dir.glob("rsshub_subscriptions_*.toml"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            pass

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    export_filename = f"rsshub_subscriptions_{user_id}_{timestamp}.toml"
    export_path = temp_dir / export_filename

    try:
        export_path.write_text(export_text, encoding="utf-8")
    except OSError as ex:
        return {"success": False, "error": f"备份导出失败: {ex}"}

    # 删除订阅
    deleted_count = await delete_subscriptions(to_delete)

    return {
        "success": True,
        "message": f"已取消{scope_desc}订阅，共删除 {deleted_count} 条",
        "export_path": export_path,
        "export_filename": export_filename,
    }


async def export_subscriptions(
    *,
    user_id: str,
    current_session: str,
    is_admin: bool,
    scope: str,
) -> ExportSubscriptionsResult:
    """导出订阅

    Returns:
        {"success": bool, "message": str, "error": str, "export_path": Path}
    """
    scope_value = scope.strip().lower()

    if scope_value and scope_value != "all":
        return {"success": False, "error": "参数无效。用法: /sub_export [all]"}

    is_global = scope_value == "all"

    if is_global and not is_admin:
        return {"success": False, "error": "导出所有订阅需要管理员权限"}

    if is_global:
        subs = await Sub.get_all_active()
        if not subs:
            return {"success": False, "error": "当前没有任何订阅"}
        export_text = build_subscriptions_export_text(
            user_id="global",
            subscriptions=subs,
        )
        import uuid

        short_id = uuid.uuid4().hex[:8]
        filename = f"rsshub_export_global_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{short_id}.toml"
    else:
        subs = await Sub.get_by_user(user_id)
        if not subs:
            return {"success": False, "error": "您当前没有可导出的订阅"}
        filtered_subs = [
            sub
            for sub in subs
            if (sub.target_session or current_session) == current_session
        ]
        if not filtered_subs:
            return {"success": False, "error": "当前会话没有可导出的订阅"}
        export_text = build_subscriptions_export_text(
            user_id=str(user_id),
            subscriptions=filtered_subs,
        )
        import uuid

        short_id = uuid.uuid4().hex[:8]
        filename = f"rsshub_export_{user_id}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{short_id}.toml"

    temp_dir = Path(get_astrbot_temp_path())
    temp_dir.mkdir(parents=True, exist_ok=True)
    export_path = temp_dir / filename

    try:
        export_path.write_text(export_text, encoding="utf-8")
        return {
            "success": True,
            "message": f"订阅导出完成，共 {len(subs if is_global else filtered_subs)} 条",
            "export_path": export_path,
            "export_filename": filename,
        }
    except OSError as ex:
        return {"success": False, "error": f"导出失败: {ex}"}


async def import_subscriptions(
    *,
    content: str,
    user_id: str,
    session_id: str,
    platform_name: str,
    validate_options_fn: callable,
) -> ImportSubscriptionsResult:
    """导入订阅

    Returns:
        {"success": bool, "message": str, "imported": int, "skipped": int, "failed": int}
    """
    payload = parse_subscriptions_toml(content)
    if payload.errors and not payload.records:
        preview = "\n".join(payload.errors[:8])
        return {"success": False, "error": f"导入失败，文件校验未通过:\n{preview}"}

    user = await User.get_or_create(user_id)

    result_stats: ImportApplyResult = await apply_import_payload(
        payload=payload,
        user_id=user_id,
        user_db_id=user.id,
        current_session=session_id,
        default_platform_name=platform_name,
        validate_options=validate_options_fn,
    )

    details = list(result_stats.details)
    if payload.warnings:
        details.extend([f"警告: {item}" for item in payload.warnings[:3]])
    if payload.errors:
        details.extend([f"错误: {item}" for item in payload.errors[:5]])

    message = (
        f"订阅导入完成\n"
        f"- 成功导入: {result_stats.imported}\n"
        f"- 跳过: {result_stats.skipped}\n"
        f"- 失败: {result_stats.failed}"
    )
    if details:
        message += "\n\n详情:\n" + "\n".join(details[:12])

    return {
        "success": True,
        "message": message,
        "imported": result_stats.imported,
        "skipped": result_stats.skipped,
        "failed": result_stats.failed,
    }


async def set_subscription_option(
    *,
    sub_id: str,
    key: str,
    value: str,
    user_id: str,
    parse_option_value_fn: Callable[[str, str], int | str],
    parse_target_session_fn: Callable[[str], tuple[str | None, str | None]],
) -> SetSubscriptionOptionResult:
    """设置订阅选项

    Returns:
        {"success": bool, "message": str, "error": str}
    """
    if not sub_id or not key or not value:
        return {
            "success": False,
            "error": (
                "用法: /sub_set <订阅ID> <选项名> <值>\n"
                "可用选项: notify/send_mode/length_limit/link_preview/display_author/"
                "display_via/display_title/display_entry_tags/style/display_media/"
                "interval/title/tags/target_session"
            ),
        }

    try:
        sub_id_int = int(sub_id)
    except ValueError:
        return {"success": False, "error": "订阅 ID 必须是数字"}

    option_key = key.strip().lower()

    if option_key == "target_session":
        parsed_value, parse_err = parse_target_session_fn(value)
        if parse_err:
            return {"success": False, "error": parse_err}
    else:
        try:
            parsed_value = parse_option_value_fn(option_key, value)
        except ValueError as ex:
            return {"success": False, "error": str(ex)}

    # 获取订阅信息（旧值和 feed 标题）
    sub_info = await Sub.get_by_id(sub_id_int)
    if not sub_info:
        return {"success": False, "error": "未找到该订阅，或无权限修改"}

    old_value = getattr(sub_info, option_key, None)
    feed_title = sub_info.feed.title if sub_info.feed else "未知"

    # 更新订阅
    updated = await Sub.update_options(
        sub_id_int, user_id, **{option_key: parsed_value}
    )
    if not updated:
        return {"success": False, "error": "更新失败"}

    # 格式化显示值（布尔值显示为中文）
    def fmt(val):
        if val is None:
            return "未设置"
        if isinstance(val, bool) or val in (0, 1, -100):
            val_map = {0: "禁用", 1: "启用", -100: "继承"}
            return val_map.get(val, str(val))
        return str(val)

    return {
        "success": True,
        "message": f"订阅 [{sub_id_int}] {feed_title}\n{option_key}: {fmt(old_value)} → {fmt(parsed_value)}",
    }


async def batch_activate_subs(
    *,
    user_id: str,
    current_session: str,
) -> CommandResult:
    """激活当前会话中的所有订阅

    Args:
        user_id: 用户ID
        current_session: 当前会话ID

    Returns:
        命令结果
    """
    from sqlalchemy.orm import selectinload
    from sqlmodel import or_, select

    from ..db import Sub, get_session

    async with get_session() as session:
        # 查询当前会话中该用户的所有订阅（当前禁用的），预加载 feed
        # 处理 target_session 为 NULL 的情况（NULL 视为当前会话）
        stmt = (
            select(Sub)
            .options(selectinload(Sub.feed))
            .where(
                Sub.user_id == user_id,
                or_(
                    Sub.target_session == current_session,
                    Sub.target_session.is_(None),
                ),
                Sub.state == 0,
            )
        )
        result = await session.execute(stmt)
        subs = list(result.scalars().all())

        if not subs:
            return {
                "success": True,
                "message": "当前会话没有需要启用的订阅",
            }

        # 激活所有订阅
        activated_count = 0
        sub_titles = []
        for sub in subs:
            sub.state = 1
            session.add(sub)
            activated_count += 1
            title = sub.feed.title if sub.feed else f"订阅 {sub.id}"
            sub_titles.append(f"  • {title}")

        await session.commit()

        message_lines = [
            f"已启用当前会话的 {activated_count} 个订阅：",
            *sub_titles,
            "\n当前会话订阅已全部启用",
        ]

        return {
            "success": True,
            "message": "\n".join(message_lines),
        }


async def batch_deactivate_subs(
    *,
    user_id: str,
    current_session: str,
) -> CommandResult:
    """停用当前会话中的所有订阅

    Args:
        user_id: 用户ID
        current_session: 当前会话ID

    Returns:
        命令结果
    """
    from sqlalchemy.orm import selectinload
    from sqlmodel import or_, select

    from ..db import Sub, get_session

    async with get_session() as session:
        # 查询当前会话中该用户的所有订阅（当前启用的），预加载 feed
        # 处理 target_session 为 NULL 的情况（NULL 视为当前会话）
        stmt = (
            select(Sub)
            .options(selectinload(Sub.feed))
            .where(
                Sub.user_id == user_id,
                or_(
                    Sub.target_session == current_session,
                    Sub.target_session.is_(None),
                ),
                Sub.state == 1,
            )
        )
        result = await session.execute(stmt)
        subs = list(result.scalars().all())

        if not subs:
            return {
                "success": True,
                "message": "当前会话没有需要禁用的订阅",
            }

        # 停用所有订阅
        deactivated_count = 0
        for sub in subs:
            sub.state = 0
            session.add(sub)
            deactivated_count += 1

        await session.commit()

        return {
            "success": True,
            "message": (
                f"已禁用当前会话的 {deactivated_count} 个订阅\n\n"
                "当前会话订阅已全部禁用，不再推送更新\n"
                "使用 /activate_subs 可随时重新启用"
            ),
        }


# Import file reading constants
IMPORT_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
IMPORT_MAX_FILE_SIZE_DISPLAY = f"{IMPORT_MAX_FILE_SIZE_BYTES / 1024 / 1024:g}MB"


async def read_uploaded_toml_content(
    event: AstrMessageEvent,
    *,
    max_file_size: int,
) -> tuple[str | None, str | None, bool]:
    """Read TOML content from uploaded file components.

    Returns: (content, error, has_file_component)
    """
    has_file_component = False
    file_messages = event.get_messages()
    for component in file_messages:
        if not isinstance(component, File):
            continue

        has_file_component = True
        file_path = ""
        try:
            file_path = await component.get_file()
            if not file_path:
                continue
            candidate = Path(file_path)
            if not candidate.is_file():
                continue
            if candidate.stat().st_size > max_file_size:
                return (
                    None,
                    f"导入文件过大，请控制在 {IMPORT_MAX_FILE_SIZE_DISPLAY} 以内",
                    True,
                )
            return candidate.read_text(encoding="utf-8-sig"), None, True
        except OSError as ex:
            return None, f"读取上传文件失败：{ex}", True
        finally:
            if file_path:
                try:
                    os.unlink(file_path)
                except OSError:
                    pass

    return None, None, has_file_component


async def read_import_toml_content(
    event: AstrMessageEvent,
    import_path: str,
    local_imports_dir: Path,
    is_admin: bool,
) -> tuple[str | None, str | None, bool]:
    """Read import TOML content from local path or uploaded file.

    Args:
        event: AstrMessageEvent
        import_path: Local file path (admin only)
        local_imports_dir: Allowed directory for local imports
        is_admin: Whether the user is admin

    Returns: (content, error, should_wait_upload)
    """
    if import_path.strip():
        if not is_admin:
            return (
                None,
                "出于安全考虑，仅管理员可使用本地路径导入，请改为上传 TOML 文件。",
                False,
            )

        path = Path(import_path.strip()).expanduser().resolve()
        allowed_dir = local_imports_dir.resolve()
        allowed_dir.mkdir(parents=True, exist_ok=True)

        try:
            path.relative_to(allowed_dir)
        except ValueError:
            return (
                None,
                f"仅允许从导入目录读取文件：{allowed_dir}",
                False,
            )

        if not path.is_file():
            return None, f"导入文件不存在：{path}", False
        try:
            if path.stat().st_size > IMPORT_MAX_FILE_SIZE_BYTES:
                return (
                    None,
                    f"导入文件过大，请控制在 {IMPORT_MAX_FILE_SIZE_DISPLAY} 以内",
                    False,
                )
            return path.read_text(encoding="utf-8-sig"), None, False
        except OSError as ex:
            return None, f"读取导入文件失败：{ex}", False

    content, read_err, has_file_component = await read_uploaded_toml_content(
        event,
        max_file_size=IMPORT_MAX_FILE_SIZE_BYTES,
    )
    if content:
        return content, None, False
    if read_err:
        return None, read_err, False
    if has_file_component:
        return None, "读取上传文件失败", False

    return None, None, True
