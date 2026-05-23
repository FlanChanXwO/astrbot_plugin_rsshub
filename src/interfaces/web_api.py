"""RSSHub Plugin Pages Web API

提供基于 AstrBot Plugin Pages bridge 的 HTTP API 处理函数。
所有端点注册为 /astrbot_plugin_rsshub/<endpoint>。
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from quart import Response, jsonify, request

from astrbot.api import AstrBotConfig
from astrbot.api.star import Context

from ..application.commands.batch_activate_cmd import BatchActivateCommand
from ..application.commands.batch_deactivate_cmd import BatchDeactivateCommand
from ..application.commands.batch_unsubscribe_cmd import BatchUnsubscribeCommand
from ..application.commands.export_subscriptions_cmd import (
    ExportSubscriptionsCommand,
)
from ..application.commands.get_user_settings_cmd import GetUserSettingsCommand
from ..application.commands.import_subscriptions_cmd import (
    ImportSubscriptionsCommand,
)
from ..application.commands.set_user_settings_cmd import SetUserSettingsCommand
from ..application.commands.subscribe_feed_cmd import SubscribeFeedCommand
from ..application.commands.test_subscription_cmd import TestSubscriptionCommand
from ..application.commands.unsubscribe_feed_cmd import UnsubscribeFeedCommand
from ..application.commands.update_subscription_cmd import UpdateSubscriptionCommand
from ..application.queries.get_feed_items_query import GetFeedItemsQuery
from ..application.services.feed_polling_service import FeedPollingService
from ..application.services.route_knowledge_service import (
    RouteKnowledgeSyncService,
)
from ..domain.entities.handlers import list_handler_registry
from ..domain.repositories.feed_repository import FeedRepository
from ..domain.repositories.push_history_repository import PushHistoryRepository
from ..domain.repositories.subscription_repository import SubscriptionRepository
from ..domain.repositories.user_repository import UserRepository
from ..infrastructure.config import (
    RsshubPluginConfig,
    build_application_settings,
    set_config,
    validate_interval_value,
)
from ..infrastructure.utils import get_plugin_cache_dir, get_plugin_export_dir

PLUGIN_NAME = "astrbot_plugin_rsshub"
USER_ID_REQUIRED_ERROR = "user_id 不能为空"


class WebApiHandler:
    """Web API 处理函数容器

    持有所有命令/查询引用，提供各端点的 async handler。
    """

    def __init__(
        self,
        subscribe_cmd: SubscribeFeedCommand,
        unsubscribe_cmd: UnsubscribeFeedCommand,
        update_sub_cmd: UpdateSubscriptionCommand,
        batch_activate_cmd: BatchActivateCommand,
        batch_deactivate_cmd: BatchDeactivateCommand,
        batch_unsub_cmd: BatchUnsubscribeCommand,
        export_cmd: ExportSubscriptionsCommand,
        import_cmd: ImportSubscriptionsCommand,
        get_user_settings_cmd: GetUserSettingsCommand,
        set_user_settings_cmd: SetUserSettingsCommand,
        test_sub_cmd: TestSubscriptionCommand,
        get_items_query: GetFeedItemsQuery,
        polling_service: FeedPollingService,
        feed_repo: FeedRepository,
        sub_repo: SubscriptionRepository,
        user_repo: UserRepository,
        push_history_repo: PushHistoryRepository,
        route_knowledge_service: RouteKnowledgeSyncService | None = None,
        config: RsshubPluginConfig | None = None,
        raw_config: AstrBotConfig | None = None,
    ):
        self._sse_clients: list[asyncio.Queue] = []
        self._change_counter: int = 0

        self._subscribe_cmd = subscribe_cmd
        self._unsubscribe_cmd = unsubscribe_cmd
        self._update_sub_cmd = update_sub_cmd
        self._batch_activate_cmd = batch_activate_cmd
        self._batch_deactivate_cmd = batch_deactivate_cmd
        self._batch_unsub_cmd = batch_unsub_cmd
        self._export_cmd = export_cmd
        self._import_cmd = import_cmd
        self._get_user_settings_cmd = get_user_settings_cmd
        self._set_user_settings_cmd = set_user_settings_cmd
        self._test_sub_cmd = test_sub_cmd
        self._get_items_query = get_items_query
        self._polling_service = polling_service
        self._feed_repo = feed_repo
        self._sub_repo = sub_repo
        self._user_repo = user_repo
        self._push_history_repo = push_history_repo
        self._route_knowledge_service = route_knowledge_service
        self._config = config
        self._raw_config = raw_config

    def register_all(self, context: Context) -> None:
        """注册所有 API 端点到 AstrBot"""
        prefix = f"/{PLUGIN_NAME}"

        routes = [
            ("GET", "/events", self.handle_events, "SSE 事件推送"),
            ("GET", "/updates", self.handle_updates, "检查更新"),
            ("GET", "/subscriptions", self.handle_list_subscriptions, "列出所有订阅"),
            ("GET", "/users", self.handle_users, "列出所有用户"),
            ("GET", "/feeds", self.handle_feeds, "列出所有 Feed"),
            ("POST", "/subscribe", self.handle_subscribe, "订阅 RSS"),
            ("POST", "/unsubscribe", self.handle_unsubscribe, "取消订阅"),
            (
                "POST",
                "/subscriptions/update",
                self.handle_update_subscription,
                "更新订阅",
            ),
            ("GET", "/feeds/items", self.handle_feed_items, "获取 Feed 条目"),
            ("POST", "/feeds/refresh", self.handle_refresh_feed, "刷新 Feed"),
            ("GET", "/settings", self.handle_get_settings, "获取用户设置"),
            ("POST", "/settings", self.handle_set_settings, "更新用户设置"),
            (
                "GET",
                "/plugin-settings",
                self.handle_get_plugin_settings,
                "获取插件设置",
            ),
            ("GET", "/handlers", self.handle_handlers, "获取 handler registry"),
            (
                "GET",
                "/handlers/schema",
                self.handle_handlers_schema,
                "获取 handler schema",
            ),
            (
                "POST",
                "/plugin-settings",
                self.handle_set_plugin_settings,
                "更新插件设置",
            ),
            ("POST", "/test-subscription", self.handle_test_subscription, "测试订阅"),
            ("POST", "/test-url", self.handle_test_url, "测试 URL"),
            ("POST", "/batch/activate", self.handle_batch_activate, "批量启用"),
            ("POST", "/batch/deactivate", self.handle_batch_deactivate, "批量禁用"),
            ("POST", "/batch/unsubscribe", self.handle_batch_unsubscribe, "批量取消"),
            ("POST", "/export", self.handle_export, "导出订阅"),
            ("POST", "/import", self.handle_import, "导入订阅"),
            ("GET", "/stats", self.handle_stats, "插件统计"),
            ("GET", "/push-history", self.handle_push_history, "推送历史"),
            (
                "GET",
                "/data-management/overview",
                self.handle_data_management_overview,
                "数据管理概览",
            ),
            (
                "POST",
                "/data-management/cache/clear",
                self.handle_clear_cache,
                "清空缓存",
            ),
            (
                "GET",
                "/data-management/exports",
                self.handle_list_exports,
                "导出文件列表",
            ),
            (
                "GET",
                "/data-management/exports/download",
                self.handle_download_export,
                "下载导出文件",
            ),
            (
                "GET",
                "/data-management/exports/content",
                self.handle_export_content,
                "读取导出文件内容",
            ),
            (
                "POST",
                "/data-management/exports/delete",
                self.handle_delete_export,
                "删除导出文件",
            ),
            (
                "POST",
                "/data-management/exports/clear",
                self.handle_clear_exports,
                "清空导出文件",
            ),
            ("GET", "/route-kb/status", self.handle_route_kb_status, "Routes KB 状态"),
            ("POST", "/route-kb/sync", self.handle_route_kb_sync, "同步 Routes KB"),
            ("GET", "/route-kb/task", self.handle_route_kb_task, "Routes KB 任务"),
            (
                "POST",
                "/push-history/delete",
                self.handle_delete_push_history,
                "删除推送历史",
            ),
            (
                "POST",
                "/push-history/cleanup",
                self.handle_cleanup_push_history,
                "清理推送历史",
            ),
            (
                "POST",
                "/push-history/clear",
                self.handle_clear_push_history,
                "清空推送历史",
            ),
            ("GET", "/users/detail", self.handle_user_details, "用户详情列表"),
            ("POST", "/users/update", self.handle_update_user, "更新用户配置"),
            ("POST", "/users/delete", self.handle_delete_user, "删除用户"),
        ]

        for method, endpoint, handler, desc in routes:
            context.register_web_api(
                f"{prefix}{endpoint}",
                handler,
                [method],
                desc,
            )

    # ─── SSE 事件推送 ─────────────────────────────────────────

    def _bump_counter(self) -> None:
        self._change_counter += 1

    async def _broadcast(self, event_data: dict) -> None:
        """向所有 SSE 客户端广播事件"""
        dead: list[asyncio.Queue] = []
        for q in self._sse_clients:
            try:
                q.put_nowait(event_data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._sse_clients.remove(q)

    async def handle_events(self):
        """SSE 事件流端点"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        self._sse_clients.append(queue)

        async def _stream():
            try:
                yield f"data: {json.dumps({'event': 'connected'})}\n\n"
                while True:
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=30)
                        yield f"data: {json.dumps(data)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                pass
            finally:
                if queue in self._sse_clients:
                    self._sse_clients.remove(queue)

        return Response(
            _stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ─── 更新检查 ─────────────────────────────────────────────

    async def handle_updates(self):
        """轻量更新检查（无认证限制，通过 bridge apiGet 代理调用）"""
        return jsonify({"ok": True, "changed": False, "counter": self._change_counter})

    # ─── RSSHub Routes KB ────────────────────────────────────

    async def handle_route_kb_status(self):
        """获取 RSSHub Routes 知识库同步状态。"""
        if self._route_knowledge_service is None:
            return jsonify({"ok": False, "error": "Routes KB 服务未初始化"})
        status = await self._route_knowledge_service.get_status()
        return jsonify({"ok": True, "status": _dump_dataclass_like(status)})

    async def handle_route_kb_sync(self):
        """启动 RSSHub Routes 知识库同步。"""
        if self._route_knowledge_service is None:
            return jsonify({"ok": False, "error": "Routes KB 服务未初始化"})
        try:
            task = await self._route_knowledge_service.start_sync()
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})
        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "route_kb_sync_started"}))
        return jsonify({"ok": True, "task": _dump_dataclass_like(task)})

    async def handle_route_kb_task(self):
        """获取最近 RSSHub Routes 知识库同步任务。"""
        if self._route_knowledge_service is None:
            return jsonify({"ok": False, "error": "Routes KB 服务未初始化"})
        task = self._route_knowledge_service.get_task_status()
        return jsonify({"ok": True, "task": _dump_dataclass_like(task)})

    # ─── 订阅列表 ─────────────────────────────────────────────

    async def handle_list_subscriptions(self):
        """列出所有订阅（含 Feed 信息）"""
        user_ids = _split_multi_values(request.args.get("user_id", ""))
        feed_ids = _split_multi_int_values(request.args.get("feed_id", ""))
        sub_ids = _split_multi_int_values(request.args.get("sub_id", ""))
        keywords = _split_multi_values(request.args.get("keyword", ""))

        subs = await self._sub_repo.list_for_dashboard(
            user_ids=user_ids or None,
            feed_ids=feed_ids or None,
            sub_ids=sub_ids or None,
            keywords=keywords or None,
        )
        feed_ids = {s.feed_id for s in subs if s.feed_id}
        feeds: dict[int, Any] = {}
        for fid in feed_ids:
            f = await self._feed_repo.get_by_id(fid)
            if f:
                feeds[fid] = f

        items = []
        for s in subs:
            feed = feeds.get(s.feed_id) if s.feed_id else None
            items.append(
                {
                    "id": s.id,
                    "state": s.state,
                    "user_id": s.user_id,
                    "feed_id": s.feed_id,
                    "feed_title": feed.title if feed else "",
                    "feed_link": feed.link if feed else "",
                    "title": s.title,
                    "tags": s.tags,
                    "target_session": s.target_session,
                    "platform_name": s.platform_name,
                    "interval": s.interval,
                    "notify": s.notify,
                    "send_mode": s.send_mode,
                    "handlers_mode": s.handlers_mode,
                    "handlers": s.get_handlers(),
                    "length_limit": s.length_limit,
                    "display_author": s.display_author,
                    "display_via": s.display_via,
                    "display_title": s.display_title,
                    "display_entry_tags": s.display_entry_tags,
                    "style": s.style,
                    "display_media": s.display_media,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
            )

        return jsonify({"ok": True, "items": items, "total": len(items)})

    # ─── 用户列表 ─────────────────────────────────────────────

    async def handle_users(self):
        """列出所有用户及其订阅统计"""
        subs = await self._sub_repo.get_all_active()
        user_map: dict[str, dict] = {}
        for s in subs:
            uid = s.user_id or "unknown"
            if uid not in user_map:
                user_map[uid] = {"user_id": uid, "total": 0, "active": 0}
            user_map[uid]["total"] += 1
            if s.state == 1:
                user_map[uid]["active"] += 1
        return jsonify(
            {"ok": True, "items": list(user_map.values()), "total": len(user_map)}
        )

    async def handle_user_details(self):
        """列出所有用户详情（从 UserRepository）"""
        user_ids = _split_multi_values(request.args.get("user_id", ""))
        keywords = _split_multi_values(request.args.get("keyword", ""))
        users = await self._user_repo.get_all(limit=1000)
        items = []
        for u in users:
            if user_ids and u.id not in user_ids:
                continue
            if keywords:
                haystacks = [
                    str(u.id or ""),
                    str(getattr(u, "default_target_session", "") or ""),
                ]
                if not any(
                    keyword.lower() in haystack.lower()
                    for keyword in keywords
                    for haystack in haystacks
                ):
                    continue
            items.append(
                {
                    "user_id": u.id,
                    "state": u.state,
                    "interval": u.interval,
                    "notify": u.notify,
                    "send_mode": u.send_mode,
                    "handlers": u.get_handlers(),
                    "length_limit": u.length_limit,
                    "display_author": u.display_author,
                    "display_via": u.display_via,
                    "display_title": u.display_title,
                    "display_entry_tags": u.display_entry_tags,
                    "style": u.style,
                    "display_media": u.display_media,
                    "default_target_session": u.default_target_session,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "updated_at": u.updated_at.isoformat() if u.updated_at else None,
                }
            )
        return jsonify({"ok": True, "items": items, "total": len(items)})

    async def handle_update_user(self):
        """更新用户配置"""
        data = await request.get_json()
        if not data:
            return jsonify({"ok": False, "error": "请求体为空"})

        user_id = data.get("user_id", "")
        settings = data.get("settings", {})
        if not user_id:
            return jsonify({"ok": False, "error": "user_id 不能为空"})

        result = await self._set_user_settings_cmd.execute(
            user_id=user_id, settings=settings
        )
        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify({"ok": result.success, "message": result.message})

    async def handle_delete_user(self):
        """删除用户"""
        data = await request.get_json()
        user_ids: list[str] = []
        if data:
            if isinstance(data.get("user_ids"), list):
                user_ids = [
                    str(item).strip() for item in data["user_ids"] if str(item).strip()
                ]
            elif data.get("user_id"):
                user_ids = [str(data.get("user_id", "")).strip()]

        user_ids = list(dict.fromkeys(user_ids))
        if not user_ids:
            return jsonify({"ok": False, "error": "user_id 或 user_ids 不能为空"})

        removed_count = 0
        for user_id in user_ids:
            await self._sub_repo.delete_all_by_user(user_id)
            if await self._user_repo.delete(user_id):
                removed_count += 1

        if removed_count > 0:
            self._bump_counter()
            asyncio.create_task(self._broadcast({"event": "data_changed"}))
            return jsonify(
                {
                    "ok": True,
                    "removed_count": removed_count,
                    "message": f"已删除 {removed_count} 个用户"
                    if len(user_ids) > 1
                    else f"用户 {user_ids[0]} 已删除",
                }
            )
        return jsonify(
            {"ok": False, "error": "用户不存在或删除失败", "removed_count": 0}
        )

    # ─── Feed 列表 ────────────────────────────────────────────

    async def handle_feeds(self):
        """列出所有 Feed 源及其订阅统计"""
        feed_ids = _split_multi_int_values(request.args.get("feed_id", ""))
        keywords = _split_multi_values(request.args.get("keyword", ""))
        feeds = await self._feed_repo.get_all()
        subs = await self._sub_repo.get_all_active()
        sub_counts: dict[int, int] = {}
        for s in subs:
            if s.feed_id:
                sub_counts[s.feed_id] = sub_counts.get(s.feed_id, 0) + 1

        items = []
        for f in feeds:
            if feed_ids and f.id not in feed_ids:
                continue
            if keywords:
                haystacks = [str(f.id or ""), str(f.title or ""), str(f.link or "")]
                if not any(
                    keyword.lower() in haystack.lower()
                    for keyword in keywords
                    for haystack in haystacks
                ):
                    continue
            items.append(
                {
                    "id": f.id,
                    "title": f.title or "",
                    "link": f.link or "",
                    "state": f.state,
                    "last_modified": f.last_modified.isoformat()
                    if f.last_modified
                    else None,
                    "updated_at": f.updated_at.isoformat() if f.updated_at else None,
                    "subscription_count": sub_counts.get(f.id, 0),
                }
            )
        return jsonify({"ok": True, "items": items, "total": len(items)})

    # ─── 订阅管理 ─────────────────────────────────────────────

    @staticmethod
    def _extract_required_user_id(data: dict[str, Any] | None) -> str:
        if not isinstance(data, dict):
            return ""
        user_id = data.get("user_id", "")
        return str(user_id).strip() if user_id is not None else ""

    @staticmethod
    def _user_id_required_response():
        return jsonify({"ok": False, "error": USER_ID_REQUIRED_ERROR})

    async def handle_subscribe(self):
        """订阅 RSS 源"""
        data = await request.get_json()
        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        url = (data or {}).get("url", "").strip()
        if not url:
            return jsonify({"ok": False, "error": "url 不能为空"})

        target_session = (data or {}).get("target_session")
        platform_name = (data or {}).get("platform_name")

        result = await self._subscribe_cmd.execute(
            url=url,
            user_id=user_id,
            target_session=target_session,
            platform_name=platform_name,
        )

        resp = {"ok": result.success, "message": result.message}
        if result.data:
            resp["data"] = (
                {"id": result.data.id} if hasattr(result.data, "id") else result.data
            )
        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify(resp)

    async def handle_unsubscribe(self):
        """取消订阅"""
        data = await request.get_json()
        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        sub_id = (data or {}).get("sub_id", 0)

        if not sub_id:
            return jsonify({"ok": False, "error": "sub_id 不能为空"})

        result = await self._unsubscribe_cmd.execute(
            sub_id=int(sub_id), user_id=user_id
        )
        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify({"ok": result.success, "message": result.message})

    async def handle_update_subscription(self):
        """更新订阅选项"""
        data = await request.get_json()
        if not data:
            return self._user_id_required_response()

        sub_id = data.get("sub_id", 0)
        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        options = data.get("options", {})

        if not sub_id:
            return jsonify({"ok": False, "error": "sub_id 不能为空"})

        result = await self._update_sub_cmd.execute(
            sub_id=int(sub_id),
            user_id=user_id,
            **options,
        )
        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify({"ok": result.success, "message": result.message})

    # ─── Feed 操作 ────────────────────────────────────────────

    async def handle_feed_items(self):
        """获取 Feed 条目"""
        feed_id = request.args.get("feed_id", type=int)
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)

        if not feed_id:
            return jsonify({"ok": False, "error": "feed_id 不能为空"})

        result = await self._get_items_query.execute(
            feed_id=feed_id,
            page=page,
            page_size=page_size,
        )

        items = []
        for item in result.items:
            items.append(
                {
                    "title": item.title,
                    "link": item.link,
                    "summary": item.summary[:300] + "..."
                    if item.summary and len(item.summary) > 300
                    else item.summary,
                    "author": item.author,
                    "published_at": item.published_at.isoformat()
                    if item.published_at
                    else None,
                }
            )

        return jsonify(
            {
                "ok": not result.error,
                "items": items,
                "total": result.total,
                "page": result.page,
                "page_size": result.page_size,
                "error": result.error or "",
            }
        )

    async def handle_refresh_feed(self):
        """手动刷新 Feed"""
        data = await request.get_json()
        feed_ids: list[int] = []
        if data:
            if isinstance(data.get("feed_ids"), list):
                feed_ids = [int(item) for item in data["feed_ids"] if str(item).strip()]
            elif data.get("feed_id"):
                feed_ids = [int(data.get("feed_id", 0))]

        feed_ids = sorted({feed_id for feed_id in feed_ids if feed_id > 0})
        if not feed_ids:
            return jsonify({"ok": False, "error": "feed_id 或 feed_ids 不能为空"})

        try:
            if len(feed_ids) == 1:
                result = await self._polling_service.poll_feed(feed_ids[0])
                self._bump_counter()
                asyncio.create_task(self._broadcast({"event": "data_changed"}))
                return jsonify(
                    {
                        "ok": result.success,
                        "message": result.message,
                        "status": result.status,
                        "feed_id": result.feed_id,
                        "total_entries": result.total_entries,
                        "new_entries": result.new_entries,
                        "dispatched": result.dispatched,
                        "bootstrap_skipped": result.bootstrap_skipped,
                        "error": result.error,
                    }
                )

            results = []
            success_count = 0
            for feed_id in feed_ids:
                result = await self._polling_service.poll_feed(feed_id)
                results.append(
                    {
                        "ok": result.success,
                        "message": result.message,
                        "status": result.status,
                        "feed_id": result.feed_id or feed_id,
                        "total_entries": result.total_entries,
                        "new_entries": result.new_entries,
                        "dispatched": result.dispatched,
                        "bootstrap_skipped": result.bootstrap_skipped,
                        "error": result.error,
                    }
                )
                if result.success:
                    success_count += 1
            self._bump_counter()
            asyncio.create_task(self._broadcast({"event": "data_changed"}))
            return jsonify(
                {
                    "ok": success_count > 0,
                    "message": f"已刷新 {success_count}/{len(feed_ids)} 个 Feed",
                    "results": results,
                    "success_count": success_count,
                }
            )
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ─── 用户设置 ─────────────────────────────────────────────

    async def handle_get_settings(self):
        """获取用户默认设置"""
        user_id = (request.args.get("user_id") or "").strip()
        if not user_id:
            return self._user_id_required_response()

        result = await self._get_user_settings_cmd.execute(user_id=user_id)
        if result.success and result.data:
            return jsonify({"ok": True, "settings": result.data})
        return jsonify({"ok": False, "error": result.message})

    async def handle_set_settings(self):
        """更新用户默认设置"""
        data = await request.get_json()
        if not data:
            return self._user_id_required_response()

        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        settings = data.get("settings", {})

        result = await self._set_user_settings_cmd.execute(
            user_id=user_id, settings=settings
        )
        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify({"ok": result.success, "message": result.message})

    async def handle_get_plugin_settings(self):
        """获取插件级订阅默认值"""
        if self._config is None:
            return jsonify({"ok": False, "error": "插件配置未初始化"})
        settings = build_application_settings(self._config)
        return jsonify(
            {
                "ok": True,
                "subscription_defaults": _dump_dataclass_like(
                    settings.subscription_defaults
                ),
            }
        )

    async def handle_handlers(self):
        """获取 handler registry metadata/schema。"""
        return jsonify({"ok": True, "items": list_handler_registry()})

    async def handle_handlers_schema(self):
        """获取 Plugin Pages 使用的 handler schema。"""
        handlers = list_handler_registry()
        return jsonify({"ok": True, "items": handlers, "handlers": handlers})

    async def handle_set_plugin_settings(self):
        """更新插件级订阅默认值"""
        if self._config is None:
            return jsonify({"ok": False, "error": "插件配置未初始化"})
        if self._raw_config is None or not hasattr(self._raw_config, "save_config"):
            return jsonify({"ok": False, "error": "当前运行环境不支持保存插件配置"})

        data = await request.get_json()
        if not data:
            return jsonify({"ok": False, "error": "请求体为空"})

        subscription_updates = data.get("subscription_defaults") or {}
        if not isinstance(subscription_updates, dict):
            return jsonify({"ok": False, "error": "配置格式无效"})

        try:
            config_dict = self._config.model_dump()
            if subscription_updates:
                if "interval" in subscription_updates:
                    subscription_updates = dict(subscription_updates)
                    subscription_updates["interval"] = validate_interval_value(
                        subscription_updates["interval"],
                        allow_inherit=False,
                        field_name="interval",
                        config=self._config,
                    )
                config_dict["global_config"] = {
                    **config_dict.get("global_config", {}),
                    **subscription_updates,
                }

            updated = RsshubPluginConfig.from_astrbot_config(config_dict)
            updated.save(self._raw_config)
            self._config = updated
            set_config(updated)
            self._bump_counter()
            asyncio.create_task(self._broadcast({"event": "settings_changed"}))
            settings = build_application_settings(updated)
            return jsonify(
                {
                    "ok": True,
                    "message": "插件设置已保存，部分运行时设置需重启插件后完全生效",
                    "subscription_defaults": _dump_dataclass_like(
                        settings.subscription_defaults
                    ),
                }
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": f"保存失败: {exc}"})

    # ─── 测试 ─────────────────────────────────────────────────

    async def handle_test_subscription(self):
        """测试订阅推送"""
        data = await request.get_json()
        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        sub_id = (data or {}).get("sub_id", 0)
        target_session = str((data or {}).get("target_session", "") or "").strip()
        platform_name = str((data or {}).get("platform_name", "") or "").strip()

        if not sub_id:
            return jsonify({"ok": False, "error": "sub_id 不能为空"})

        subscription = await self._sub_repo.get_by_id(int(sub_id))
        if not subscription:
            return jsonify({"ok": False, "error": f"订阅不存在 (ID: {sub_id})"})
        if subscription.user_id != user_id:
            return jsonify({"ok": False, "error": "无权操作此订阅"})

        if not target_session:
            target_session = str(subscription.target_session or "").strip()
        if not platform_name:
            platform_name = str(subscription.platform_name or "").strip()
        if not target_session:
            user = await self._user_repo.get_by_id(user_id)
            target_session = str(getattr(user, "default_target_session", "") or "")
        if not target_session:
            return jsonify({"ok": False, "error": "订阅和用户都未配置推送目标会话"})
        if not platform_name:
            return jsonify({"ok": False, "error": "订阅未配置平台，无法测试推送"})

        result = await self._test_sub_cmd.execute_target(
            target=str(sub_id),
            user_id=user_id,
            target_session=target_session,
            platform_name=platform_name,
        )
        if result.success:
            payload = {"ok": True, "message": result.message}
            if result.data:
                payload["data"] = _dump_dataclass_like(result.data)
            return jsonify(payload)
        return jsonify({"ok": False, "error": result.message})

    async def handle_test_url(self):
        """测试 URL（无需订阅）"""
        data = await request.get_json()
        url = (data or {}).get("url", "").strip()

        if not url:
            return jsonify({"ok": False, "error": "url 不能为空"})

        result = await self._test_sub_cmd.execute_by_url(url=url)
        if result.success and result.data:
            return jsonify(
                {
                    "ok": True,
                    "message": result.message,
                    "data": _dump_dataclass_like(result.data),
                }
            )
        return jsonify({"ok": False, "error": result.message})

    # ─── 批量操作 ─────────────────────────────────────────────

    async def handle_batch_activate(self):
        """批量启用订阅"""
        data = await request.get_json()
        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        sub_ids = (data or {}).get("sub_ids", [])

        if not sub_ids:
            return jsonify({"ok": False, "error": "sub_ids 不能为空"})

        result = await self._batch_activate_cmd.execute(
            sub_ids=sub_ids, user_id=user_id
        )
        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify({"ok": result.success, "message": result.message})

    async def handle_batch_deactivate(self):
        """批量禁用订阅"""
        data = await request.get_json()
        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        sub_ids = (data or {}).get("sub_ids", [])

        if not sub_ids:
            return jsonify({"ok": False, "error": "sub_ids 不能为空"})

        result = await self._batch_deactivate_cmd.execute(
            sub_ids=sub_ids, user_id=user_id
        )
        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify({"ok": result.success, "message": result.message})

    async def handle_batch_unsubscribe(self):
        """批量取消订阅"""
        data = await request.get_json()
        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        sub_ids = (data or {}).get("sub_ids", [])

        if not sub_ids:
            return jsonify({"ok": False, "error": "sub_ids 不能为空"})

        result = await self._batch_unsub_cmd.execute(sub_ids=sub_ids, user_id=user_id)
        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify({"ok": result.success, "message": result.message})

    # ─── 导出 / 统计 ──────────────────────────────────────────

    async def handle_export(self):
        """导出订阅（返回 OPML/TOML 内容）"""
        data = await request.get_json()
        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        result = await self._export_cmd.execute(user_id=user_id)
        if result.success and result.data:
            return jsonify(
                {
                    "ok": True,
                    "message": result.message,
                    "data": {
                        "content": result.data.content,
                        "filename": result.data.filename,
                        "count": result.data.count,
                    },
                }
            )
        return jsonify({"ok": False, "error": result.message})

    async def handle_import(self):
        """导入 TOML 订阅内容"""
        data = await request.get_json()
        user_id = self._extract_required_user_id(data)
        if not user_id:
            return self._user_id_required_response()

        content = (data or {}).get("content", "")
        target_session = (data or {}).get("target_session")
        platform_name = (data or {}).get("platform_name")
        skip_existing = bool((data or {}).get("skip_existing", True))

        if not str(content).strip():
            return jsonify({"ok": False, "error": "content 不能为空"})

        result = await self._import_cmd.execute(
            content=str(content),
            user_id=user_id,
            target_session=target_session,
            platform_name=platform_name,
            skip_existing=skip_existing,
        )
        if result.success:
            self._bump_counter()
            asyncio.create_task(self._broadcast({"event": "data_changed"}))
            payload = {
                "ok": True,
                "message": result.message,
            }
            if result.data:
                payload["data"] = {
                    "total": result.data.total,
                    "success_count": result.data.success_count,
                    "failure_count": result.data.failure_count,
                    "skipped_count": result.data.skipped_count,
                }
            return jsonify(payload)
        return jsonify({"ok": False, "error": result.message})

    async def handle_stats(self):
        """获取插件统计概览"""
        subs = await self._sub_repo.get_all_active()
        all_subs = subs

        total_active = sum(1 for s in all_subs if s.state == 1)
        feed_ids = {s.feed_id for s in all_subs if s.feed_id}
        unique_users = {s.user_id for s in all_subs if s.user_id}

        return jsonify(
            {
                "ok": True,
                "stats": {
                    "total_subscriptions": len(all_subs),
                    "active_subscriptions": total_active,
                    "total_feeds": len(feed_ids),
                    "unique_users": len(unique_users),
                },
            }
        )

    async def handle_data_management_overview(self):
        """获取插件 cache / exports 目录统计。"""
        try:
            cache_dir = _ensure_directory(get_plugin_cache_dir())
            export_dir = _ensure_directory(get_plugin_export_dir())
            cache_summary = _build_directory_summary(
                cache_dir, breakdown_mode="top_level"
            )
            export_summary = _build_directory_summary(
                export_dir, breakdown_mode="extension"
            )
            return jsonify(
                {
                    "ok": True,
                    "cache": cache_summary,
                    "exports": export_summary,
                    "totals": {
                        "cache_bytes": cache_summary["total_size"],
                        "exports_bytes": export_summary["total_size"],
                        "combined_bytes": cache_summary["total_size"]
                        + export_summary["total_size"],
                        "total_size": cache_summary["total_size"]
                        + export_summary["total_size"],
                        "file_count": cache_summary["file_count"]
                        + export_summary["file_count"],
                    },
                }
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    async def handle_clear_cache(self):
        """清空插件缓存目录。"""
        try:
            cache_dir = _ensure_directory(get_plugin_cache_dir())
            removed_count = _clear_directory_contents(cache_dir)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify(
            {
                "ok": True,
                "removed_count": removed_count,
                "message": f"已清理缓存文件 {removed_count} 个",
            }
        )

    async def handle_list_exports(self):
        """列出可下载的导出 TOML 文件。"""
        try:
            export_dir = _ensure_directory(get_plugin_export_dir())
            files = _list_export_files(export_dir)
            breakdown = _build_breakdown(export_dir, mode="extension")
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

        items = []
        total_size = 0
        for export_file in files:
            stat = export_file.stat()
            total_size += stat.st_size
            items.append(
                {
                    "name": export_file.relative_to(export_dir).as_posix(),
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )

        return jsonify(
            {
                "ok": True,
                "items": items,
                "breakdown": breakdown,
                "total_size": total_size,
                "file_count": len(items),
            }
        )

    async def handle_download_export(self):
        """下载单个导出 TOML 文件。"""
        try:
            export_file = _resolve_export_file(
                _ensure_directory(get_plugin_export_dir()),
                request.args.get("name", ""),
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

        filename = export_file.name
        content_disposition = (
            f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
        )
        return Response(
            export_file.read_bytes(),
            content_type="application/toml; charset=utf-8",
            headers={"Content-Disposition": content_disposition},
        )

    async def handle_export_content(self):
        """读取单个导出 TOML 文件文本内容。"""
        try:
            export_file = _resolve_export_file(
                _ensure_directory(get_plugin_export_dir()),
                request.args.get("name", ""),
            )
            content = export_file.read_text(encoding="utf-8")
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

        return jsonify(
            {
                "ok": True,
                "name": export_file.relative_to(
                    _ensure_directory(get_plugin_export_dir())
                ).as_posix(),
                "content": content,
                "size": export_file.stat().st_size,
            }
        )

    async def handle_delete_export(self):
        """删除单个导出 TOML 文件。"""
        data = await request.get_json()
        try:
            export_file = _resolve_export_file(
                _ensure_directory(get_plugin_export_dir()),
                (data or {}).get("name", ""),
            )
            export_file.unlink()
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify({"ok": True, "message": f"已删除导出文件 {export_file.name}"})

    async def handle_clear_exports(self):
        """清空导出目录。"""
        try:
            export_dir = _ensure_directory(get_plugin_export_dir())
            removed_count = _clear_directory_contents(export_dir)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

        self._bump_counter()
        asyncio.create_task(self._broadcast({"event": "data_changed"}))
        return jsonify(
            {
                "ok": True,
                "removed_count": removed_count,
                "message": f"已清理导出文件 {removed_count} 个",
            }
        )

    # ─── 推送历史 ─────────────────────────────────────────────

    async def handle_push_history(self):
        """获取推送历史列表"""
        status = request.args.get("status")
        user_id = request.args.get("user_id")
        target_session = request.args.get("target_session")
        keywords = _split_multi_values(request.args.get("keyword", ""))
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)
        offset = (page - 1) * page_size

        if user_id:
            items = await self._push_history_repo.get_by_user(
                user_id=user_id,
                limit=page_size,
                offset=offset,
                target_session=target_session,
                status=status,
                keywords=keywords or None,
            )
            total = await self._push_history_repo.count_by_user(
                user_id=user_id,
                target_session=target_session,
                status=status,
                keywords=keywords or None,
            )
        else:
            items = await self._push_history_repo.get_all(
                limit=page_size,
                offset=offset,
                status=status,
                keywords=keywords or None,
            )
            total = await self._push_history_repo.count_all(
                status=status,
                keywords=keywords or None,
            )

        data = []
        for h in items:
            data.append(
                {
                    "id": h.id,
                    "sub_id": h.sub_id,
                    "user_id": h.user_id,
                    "feed_id": h.feed_id,
                    "source_type": h.source_type,
                    "source_key": h.source_key,
                    "content": h.content,
                    "raw_xml": h.raw_xml,
                    "media_urls": h.media_urls,
                    "handler_trace": getattr(h, "handler_trace", None),
                    "entry_title": h.entry_title,
                    "entry_link": h.entry_link,
                    "entry_guid": h.entry_guid,
                    "feed_title": h.feed_title,
                    "feed_link": h.feed_link,
                    "platform_name": h.platform_name,
                    "target_session": h.target_session,
                    "status": h.status,
                    "retry_count": h.retry_count,
                    "max_retries": h.max_retries,
                    "fail_reason": h.fail_reason,
                    "created_at": h.created_at.isoformat() if h.created_at else None,
                    "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                    "completed_at": h.completed_at.isoformat()
                    if h.completed_at
                    else None,
                }
            )

        return jsonify(
            {
                "ok": True,
                "items": data,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        )

    async def handle_delete_push_history(self):
        """删除推送历史"""
        data = await request.get_json()
        history_ids = []
        if data:
            if isinstance(data.get("history_ids"), list):
                history_ids = [
                    int(item) for item in data["history_ids"] if str(item).strip()
                ]
            elif data.get("history_id"):
                history_ids = [int(data["history_id"])]

        history_ids = sorted(
            {history_id for history_id in history_ids if history_id > 0}
        )
        if not history_ids:
            return jsonify({"ok": False, "error": "history_id 或 history_ids 不能为空"})

        if len(history_ids) == 1:
            ok = await self._push_history_repo.delete(history_ids[0])
            if ok:
                self._bump_counter()
            return jsonify(
                {
                    "ok": ok,
                    "removed_count": 1 if ok else 0,
                    "message": "已删除" if ok else "记录不存在",
                }
            )

        removed_count = await self._push_history_repo.delete_many(history_ids)
        if removed_count > 0:
            self._bump_counter()
        return jsonify(
            {
                "ok": removed_count > 0,
                "removed_count": removed_count,
                "message": f"已删除 {removed_count} 条记录"
                if removed_count > 0
                else "没有匹配的记录被删除",
            }
        )

    async def handle_cleanup_push_history(self):
        """清理旧推送历史"""
        data = await request.get_json()
        days = data.get("days", 30) if data else 30
        count = await self._push_history_repo.delete_old_records(int(days))
        self._bump_counter()
        return jsonify(
            {
                "ok": True,
                "removed_count": count,
                "message": f"已清理 {count} 条记录",
            }
        )

    async def handle_clear_push_history(self):
        """清空推送历史。"""
        count = await self._push_history_repo.delete_all()
        self._bump_counter()
        return jsonify(
            {
                "ok": True,
                "removed_count": count,
                "message": f"已清空 {count} 条记录",
            }
        )


def _dump_dataclass_like(value: Any) -> dict[str, Any]:
    def _convert(item: Any) -> Any:
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, list):
            return [_convert(part) for part in item]
        if isinstance(item, dict):
            return {key: _convert(part) for key, part in item.items()}
        if isinstance(item, tuple):
            return [_convert(part) for part in item]
        if hasattr(item, "model_dump"):
            return {key: _convert(part) for key, part in item.model_dump().items()}
        if hasattr(item, "__dict__"):
            return {
                key: _convert(part)
                for key, part in vars(item).items()
                if not key.startswith("_")
            }
        return item

    return _convert(value)


def _split_multi_values(raw: str) -> list[str]:
    text = str(raw or "").replace("，", ",")
    values = []
    for chunk in text.replace("\n", ",").split(","):
        value = chunk.strip()
        if value:
            values.append(value)
    return values


def _split_multi_int_values(raw: str) -> list[int]:
    values = []
    for value in _split_multi_values(raw):
        try:
            values.append(int(value))
        except ValueError:
            continue
    return values


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_directory_summary(path: Path, *, breakdown_mode: str) -> dict[str, Any]:
    files = list(_iter_files(path))
    total_size = sum(file.stat().st_size for file in files)
    return {
        "path": str(path),
        "total_size": total_size,
        "file_count": len(files),
        "breakdown": _build_breakdown(path, mode=breakdown_mode),
    }


def _build_breakdown(path: Path, *, mode: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = {}
    for file in _iter_files(path):
        rel = file.relative_to(path)
        if mode == "extension":
            bucket_name = file.suffix.lower() or "(no_ext)"
        else:
            bucket_name = rel.parts[0] if len(rel.parts) > 1 else "root"
        bucket = buckets.setdefault(bucket_name, {"size": 0, "file_count": 0})
        bucket["size"] += file.stat().st_size
        bucket["file_count"] += 1

    return [
        {"name": name, "size": item["size"], "file_count": item["file_count"]}
        for name, item in sorted(
            buckets.items(),
            key=lambda entry: (-entry[1]["size"], entry[0]),
        )
    ]


def _iter_files(path: Path):
    for file in sorted(path.rglob("*")):
        if file.is_file():
            yield file


def _list_export_files(export_dir: Path) -> list[Path]:
    return [file for file in sorted(export_dir.rglob("*.toml")) if file.is_file()]


def _resolve_export_file(export_dir: Path, name: str) -> Path:
    candidate_name = str(name or "").strip()
    if not candidate_name:
        raise ValueError("name 不能为空")

    candidate = (export_dir / candidate_name).resolve()
    try:
        candidate.relative_to(export_dir.resolve())
    except ValueError as exc:
        raise ValueError("非法的导出文件名") from exc

    if candidate.suffix.lower() != ".toml":
        raise ValueError("仅支持下载 TOML 导出文件")
    if not candidate.is_file():
        raise FileNotFoundError("导出文件不存在")
    return candidate


def _clear_directory_contents(path: Path) -> int:
    removed_count = 0
    for entry in sorted(path.iterdir(), key=lambda item: item.name):
        if entry.is_dir():
            removed_count += sum(1 for _ in _iter_files(entry))
            shutil.rmtree(entry)
        elif entry.is_file():
            entry.unlink()
            removed_count += 1
    return removed_count
