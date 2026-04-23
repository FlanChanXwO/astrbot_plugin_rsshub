"""订阅相关命令逻辑

所有函数返回字典格式：
- success: bool
- message: str
- data: any (可选)
- error: str (失败时)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from ..api import feed_get
from ..db import Feed, Sub, User
from ..utils.command_helpers import (
    ImportApplyResult,
    apply_import_payload,
    build_subscriptions_export_text,
    delete_subscriptions,
    select_subscriptions_for_scope,
)
from ..utils.subscription_io import parse_subscriptions_toml


async def subscribe_feed(
    *,
    url: str,
    target: str,
    user_id: str,
    platform_name: str,
    timeout: int,
    proxy: str,
    is_platform_shared: bool,
    session_defaults: dict,
    parse_target_fn: Callable[[str], tuple[str | None, str | None]],
) -> dict:
    """订阅 RSS 源

    Returns:
        {"success": bool, "message": str, "error": str, "sub_id": int}
    """
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
    if is_platform_shared:
        existing_sub = await Sub.get_by_platform_and_link(
            platform_name, url, target_session
        )
        if existing_sub:
            return {
                "success": False,
                "error": f"该源已在平台共享订阅中存在：{existing_sub.feed.title}",
            }
    else:
        existing_sub = await Sub.get_by_user_and_link(user_id, url, target_session)
        if existing_sub:
            return {
                "success": False,
                "error": f"您已经订阅了此源：{existing_sub.feed.title}",
            }

    feed = await Feed.get_or_create(link=url, title=title)

    # 预填充 entry_hashes
    if not feed.entry_hashes and wf.rss_d and wf.rss_d.entries:
        try:
            new_groups = []
            for entry in wf.rss_d.entries:
                # 简化处理：使用 entry id 或 link 作为 hash
                entry_id = entry.get("id") or entry.get("link") or str(entry)
                new_groups.append([entry_id])
            if new_groups:
                feed.entry_hashes = [
                    item for sublist in new_groups for item in sublist
                ][:100]
                from ..db import get_session

                async with get_session() as session:
                    db_feed = await session.get(Feed, feed.id)
                    if db_feed:
                        db_feed.entry_hashes = feed.entry_hashes
                        session.add(db_feed)
                        await session.commit()
        except Exception:
            pass  # 预填充失败不影响订阅

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
    is_platform_shared: bool,
) -> dict:
    """取消订阅

    Returns:
        {"success": bool, "message": str, "error": str}
    """
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
        is_same_platform = is_platform_shared and sub.platform_name == platform_name

        if not (is_owner or is_current_session or is_same_platform):
            return {"success": False, "error": "无权限删除该订阅"}

    await Sub.delete(sub)
    return {"success": True, "message": f"已取消订阅 (ID: {sub_id_int})"}


async def list_subscriptions(
    *,
    user_id: str,
    current_session: str,
    platform_name: str,
    is_platform_shared: bool,
    is_admin: bool,
    scope: str,
    page: str,
    page_size: str,
) -> dict:
    """列出订阅

    Returns:
        {"success": bool, "message": str, "error": str, "has_more": bool}
    """
    scope_value = scope.strip().lower()
    show_all_sessions = scope_value == "all" and is_admin

    list_offset = 0
    total_count = 0
    page_int = 1
    page_size_int = 5

    if show_all_sessions or is_platform_shared:
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
    elif is_platform_shared:
        subs, total_count = await Sub.get_by_platform_paged(
            platform_name, page=page_int, page_size=page_size_int
        )
        total_pages = max(1, (total_count + page_size_int - 1) // page_size_int)
        lines = [
            f"订阅列表（平台共享模式 - {platform_name}）:",
            f"页码: {page_int}/{total_pages}  每页: {page_size_int}  总数: {total_count}",
        ]
    else:
        subs = await Sub.get_by_user(user_id)
        lines = ["您的订阅列表（当前会话）:"]

    if not subs:
        if show_all_sessions:
            return {"success": True, "message": "当前没有任何订阅"}
        return {"success": True, "message": "您还没有任何订阅"}

    if not show_all_sessions and not is_platform_shared:
        subs = [
            sub
            for sub in subs
            if (sub.target_session or current_session) == current_session
        ]
        if not subs:
            return {
                "success": True,
                "message": (
                    "当前会话没有订阅。\n"
                    "可使用 /sub 添加订阅；管理员可用 /sub_list all 查看所有会话。"
                ),
            }

    for idx, sub in enumerate(subs, list_offset + 1):
        feed_title = sub.feed.title if sub.feed else "未知"
        feed_link = sub.feed.link if sub.feed else ""
        custom_title = f" ({sub.title})" if sub.title else ""
        lines.append(f"{idx}. [{sub.id}] {feed_title}{custom_title}")
        if show_all_sessions or is_platform_shared:
            lines.append(f"    user: {sub.user_id}")
            lines.append(f"    platform: {sub.platform_name or '(unknown)'}'")
            lines.append(f"    target: {sub.target_session or '(未绑定)'}'")
        if feed_link:
            lines.append(f"    {feed_link}")

    has_more = False
    if (show_all_sessions or is_platform_shared) and page_int < total_pages:
        has_more = True

    return {"success": True, "message": "\n".join(lines), "has_more": has_more}


async def test_subscription(
    *,
    sub_id: str,
    granularity: str,
    timeout: int,
    proxy: str,
    download_image_before_send: bool,
    config: object,
) -> dict:
    """管理员测试推送

    Returns:
        {"success": bool, "message": str, "error": str}
    """
    if not sub_id:
        return {"success": False, "error": "请提供订阅 ID"}

    try:
        sub_id_int = int(sub_id)
    except ValueError:
        return {"success": False, "error": "订阅 ID 必须是数字"}

    sub = await Sub.get_by_id(sub_id_int)
    if not sub:
        return {"success": False, "error": "未找到该订阅"}

    if not sub.feed:
        return {"success": False, "error": "该订阅缺少 Feed 信息"}

    target_session = sub.target_session
    if not target_session:
        user = sub.user or await User.get_or_create(sub.user_id)
        target_session = user.default_target_session
    if not target_session:
        return {"success": False, "error": "该订阅尚未绑定推送目标"}

    wf = await feed_get(sub.feed.link, timeout=timeout, proxy=proxy)
    if wf.error:
        return {"success": False, "error": f"测试抓取失败: {wf.error.error_name}"}

    if wf.rss_d is None or not wf.rss_d.entries:
        return {"success": True, "message": "测试抓取成功，但该源暂无可推送条目"}

    # 选择条目
    entries = list(wf.rss_d.entries)
    mode = (granularity or "latest").strip().lower()

    if mode in {"latest", "last"}:
        selected = [entries[0]]
        mode_label = "latest"
    elif mode == "all":
        selected = entries
        mode_label = f"all({len(entries)})"
    elif mode.startswith("count:") or mode.isdigit():
        count_raw = mode.removeprefix("count:") if mode.startswith("count:") else mode
        try:
            count = int(count_raw)
            if count <= 0:
                raise ValueError
            selected = entries[:count]
            mode_label = f"count:{len(selected)}"
        except ValueError:
            return {"success": False, "error": "数量参数无效"}
    else:
        return {
            "success": False,
            "error": "粒度参数无效。可选: latest / all / <数量> / count:<数量>",
        }

    # 发送通知
    from ..notifier import Notifier

    await Notifier(
        feed=sub.feed,
        subs=[sub],
        entries=selected,
        timeout_seconds=timeout,
        proxy=proxy,
        download_media_before_send=download_image_before_send,
        config=config,
    ).notify_all()

    first_title = selected[0].get("title") or "(无标题)"
    return {
        "success": True,
        "message": (
            f"已触发测试推送: 订阅ID={sub_id_int} -> {target_session}\n"
            f"粒度: {mode_label}，条目数: {len(selected)}\n"
            f"首条: {first_title}"
        ),
    }


async def unsubscribe_all_feeds(
    *,
    user_id: str,
    current_session: str,
    is_admin: bool,
    scope: str,
    unsub_export_retention_seconds: int,
) -> dict:
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
) -> dict:
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
) -> dict:
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
) -> dict:
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

    updated = await Sub.update_options(
        sub_id_int, user_id, **{option_key: parsed_value}
    )
    if not updated:
        return {"success": False, "error": "未找到该订阅，或无权限修改"}

    return {
        "success": True,
        "message": f"订阅 [{sub_id_int}] 已更新: {option_key} = {parsed_value}",
    }


async def bind_target(
    *,
    target: str,
    user_id: str,
    parse_target_session_fn: callable,
) -> dict:
    """绑定推送目标

    Returns:
        {"success": bool, "message": str, "error": str}
    """
    target_session, target_err = parse_target_session_fn(target)
    if target_err:
        return {"success": False, "error": target_err}

    if not target_session:
        return {
            "success": False,
            "error": "请提供目标，用法: /sub_bind <private|group|session>",
        }

    await User.set_default_target(user_id, target_session)
    return {"success": True, "message": f"已绑定默认推送目标: {target_session}"}
