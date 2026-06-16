"""RSSHub 插件入口"""

from __future__ import annotations

import time

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File, Image
from astrbot.api.star import Context, Star

from .bootstrap import PluginDeps, PluginRuntime, create_plugin_runtime
from .src.application.commands import HelpImageCommand
from .src.application.commands.import_subscriptions_cmd import (
    IMPORT_UPLOAD_WAIT_SECONDS,
)
from .src.application.llmtools import LLM_TOOL_NAMES, build_llm_tools
from .src.application.services.session_push_queue import SessionPushQueue
from .src.infrastructure.config import ApplicationSettings
from .src.infrastructure.schedule import RSSScheduler
from .src.infrastructure.utils import get_logger
from .src.interfaces import WebApiHandler
from .src.interfaces import handlers as _h

logger = get_logger()


class RSSHubPlugin(Star):
    """RSS订阅推送插件"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self._config = config
        self._scheduler: RSSScheduler | None = None
        self._db_initialized = False
        self._web_api: WebApiHandler | None = None
        self._deps: PluginDeps = {}
        self._app_settings: ApplicationSettings | None = None
        self._push_job_queue = SessionPushQueue()
        self._notification_dispatcher = None
        self._runtime: PluginRuntime | None = None
        self._registered_llm_tools: list[str] = []
        self._pending_imports: dict[str, float] = {}

    async def initialize(self):
        try:
            runtime = await create_plugin_runtime(
                self.context,
                self._config,
                push_job_queue=self._push_job_queue,
            )
            self._runtime = runtime
            self._scheduler = runtime.scheduler
            self._db_initialized = runtime.db_initialized
            self._web_api = runtime.web_api
            self._deps = runtime.deps
            self._app_settings = runtime.app_settings
            self._push_job_queue = runtime.push_job_queue
            self._notification_dispatcher = runtime.notification_dispatcher
            self.context.add_llm_tools(
                *build_llm_tools(
                    deps=self._deps,
                    plugin_context=self,
                )
            )
            self._bind_llm_tool_origin()
            self._registered_llm_tools = list(LLM_TOOL_NAMES)
        except Exception as e:
            logger.exception("RSSHub 插件初始化失败: %s", e)

    async def terminate(self):
        logger.info("正在停止 RSSHub 插件...")
        self._unregister_llm_tools()
        if self._runtime:
            await self._runtime.stop()
        else:
            await self._push_job_queue.stop_all()
        logger.info("RSSHub 插件已停止")

    def _unregister_llm_tools(self) -> None:
        if not self._registered_llm_tools:
            return
        for tool_name in self._registered_llm_tools:
            try:
                self.context.unregister_llm_tool(tool_name)
            except Exception:
                try:
                    self.context.get_llm_tool_manager().remove_func(tool_name)
                except Exception:
                    logger.warning("卸载 LLM 工具失败: %s", tool_name)
        self._registered_llm_tools = []

    def _bind_llm_tool_origin(self) -> None:
        """Rebind tool module path to this plugin so dashboard shows plugin origin."""
        manager = self.context.get_llm_tool_manager()
        plugin_module = self.__class__.__module__
        for tool in getattr(manager, "func_list", []):
            if tool.name in LLM_TOOL_NAMES:
                tool.handler_module_path = plugin_module

    # ── 命令方法（装饰器留在插件入口类，委托到纯函数） ───────────────────────

    @filter.command("sub", alias={"订阅"})
    async def sub_feed(self, event: AstrMessageEvent, args: str = ""):
        """订阅 RSS 源。

        用法:
        - /sub <url1> [url2 ...]
        示例:
        - /sub https://rsshub.app/bilibili/user/dynamic/123456
        """
        result = await _h.handle_sub(event, str(args), self._deps)
        if result.get("chain"):
            yield event.chain_result(result["chain"])
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("unsub", alias={"取消订阅"})
    async def unsub_feed(self, event: AstrMessageEvent, args: str = ""):
        """取消订阅（支持 ID/URL 批量）。

        用法:
        - /unsub <ID/URL ...>
        示例:
        - /unsub 12 15
        - /unsub https://rss.atri.rodeo/twitter/home
        """
        result = await _h.handle_unsub(event, str(args), self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("sub_list", alias={"订阅列表"})
    async def sub_list(self, event: AstrMessageEvent, args: str = ""):
        """查看当前会话订阅列表（分页）。

        用法:
        - /sub_list [page] [page_size]
        示例:
        - /sub_list
        - /sub_list 2 10
        """
        result = await _h.handle_sub_list(event, str(args), self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("sub_stop", alias={"rss_stop", "停止RSS", "停止推送"})
    async def stop_rss_job(self, event: AstrMessageEvent, args: str = ""):
        """停止当前会话推送任务。

        用法:
        - /sub_stop
        - /sub_stop <job_id|feed_id|all>
        示例:
        - /sub_stop rss-000123
        - /sub_stop 42
        - /sub_stop all
        """
        result = _h.handle_rss_stop(event, self._push_job_queue, str(args))
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("sub_status", alias={"推送状态", "任务状态"})
    async def sub_status(self, event: AstrMessageEvent):
        """查看当前会话推送任务状态（running + queued）。"""
        result = _h.handle_sub_status(event, self._push_job_queue)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("sub_state", alias={"订阅状态"})
    async def sub_state(self, event: AstrMessageEvent, sub_id_str: str = ""):
        """切换订阅启用状态。

        用法:
        - /sub_state <sub_id> on|off
        示例:
        - /sub_state 12 off
        """
        result = await _h.handle_sub_state(event, sub_id_str, self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command_group("sub_profile", alias={"订阅配置"})
    def sub_profile_group(self):
        """订阅/用户配置命令组。"""
        pass

    @sub_profile_group.command("set", alias={"设置"})
    async def sub_profile_set(self, event: AstrMessageEvent, args: str = ""):
        """设置订阅或用户配置。

        用法:
        - /sub_profile set sub <sub_id> <option> <value>
        - /sub_profile set user <key> <value>
        """
        result = await _h.handle_sub_profile_set(event, str(args), self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @sub_profile_group.command("get", alias={"获取"})
    async def sub_profile_get(self, event: AstrMessageEvent, args: str = ""):
        """查询用户配置。

        用法:
        - /sub_profile get user [key]
        """
        result = await _h.handle_sub_profile_get(event, str(args), self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command_group("sub_session", alias={"会话设置"})
    def sub_session_group(self):
        """会话默认配置命令组。"""
        pass

    @sub_session_group.command("set", alias={"设置"})
    async def sub_set_session(
        self, event: AstrMessageEvent, key: str = "", value: str = ""
    ):
        """设置当前会话默认配置。

        用法:
        - /sub_session set <key> <value>
        """
        result = await _h.handle_sub_set_session(event, key, value, self._deps, self)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @sub_session_group.command("get", alias={"获取"})
    async def sub_get_session(self, event: AstrMessageEvent, key: str = ""):
        """查看当前会话默认配置。

        用法:
        - /sub_session get [key]
        """
        result = await _h.handle_sub_get_session(event, key, self._deps, self)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("activate_subs", alias={"enable_subs", "启用全部订阅"})
    async def batch_activate(self, event: AstrMessageEvent, sub_ids: str = ""):
        """批量启用订阅。

        用法:
        - /activate_subs
        - /activate_subs 1,2,3
        """
        result = await _h.handle_batch_activate(event, sub_ids, self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("deactivate_subs", alias={"disable_subs", "禁用全部订阅"})
    async def batch_deactivate(self, event: AstrMessageEvent, sub_ids: str = ""):
        """批量禁用订阅。

        用法:
        - /deactivate_subs
        - /deactivate_subs 1,2,3
        """
        result = await _h.handle_batch_deactivate(event, sub_ids, self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("unsub_all", alias={"取消全部订阅"})
    async def unsub_all(self, event: AstrMessageEvent, scope: str = ""):
        """取消全部订阅（当前会话或全局）。

        用法:
        - /unsub_all
        - /unsub_all global  (管理员)
        """
        result = await _h.handle_unsub_all(event, scope, self._deps)
        if result.get("chain"):
            yield event.chain_result(result["chain"])
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("sub_export", alias={"导出订阅"})
    async def export_subs(self, event: AstrMessageEvent, scope: str = ""):
        """导出订阅为 TOML。

        用法:
        - /sub_export
        - /sub_export all  (管理员)
        """
        result = await _h.handle_export(event, str(scope), self._deps)
        if result.get("chain"):
            yield event.chain_result(result["chain"])
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.command("sub_import", alias={"导入订阅"})
    async def import_subs(self, event: AstrMessageEvent, args: str = ""):
        """导入订阅。

        用法:
        - /sub_import <toml文件路径>
        - /sub_import <toml内容>
        - /sub_import  (进入上传等待)
        """
        result = await _h.handle_import(event, str(args), self._deps)
        if result.get("wait_import"):
            self._prune_pending_imports()
            self._pending_imports[self._import_wait_key(event)] = (
                time.time() + IMPORT_UPLOAD_WAIT_SECONDS
            )
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def import_upload_listener(self, event: AstrMessageEvent):
        """处理 /sub_import 空参数后的文件上传。"""
        self._prune_pending_imports()
        key = self._import_wait_key(event)
        expire_ts = self._pending_imports.get(key)
        if not expire_ts:
            return
        if expire_ts < time.time():
            self._pending_imports.pop(key, None)
            return

        file_component = self._find_uploaded_file(event)
        if file_component is None:
            return

        self._pending_imports.pop(key, None)
        try:
            file_path = await file_component.get_file()
            if not file_path:
                yield event.plain_result("导入失败: 未能获取上传文件")
                return
            result = await _h.handle_import(event, file_path, self._deps)
        except Exception as ex:
            logger.warning("订阅导入上传文件处理失败: %s", ex, exc_info=True)
            yield event.plain_result(f"导入失败: {ex}")
            return

        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @staticmethod
    def _import_wait_key(event: AstrMessageEvent) -> str:
        return f"{event.unified_msg_origin}:{event.get_sender_id()}"

    def _prune_pending_imports(self) -> None:
        now = time.time()
        expired_keys = [
            key for key, expire_ts in self._pending_imports.items() if expire_ts < now
        ]
        for key in expired_keys:
            self._pending_imports.pop(key, None)

    @staticmethod
    def _find_uploaded_file(event: AstrMessageEvent) -> File | None:
        message = getattr(getattr(event, "message_obj", None), "message", None) or []
        for component in message:
            try:
                if isinstance(component, File):
                    return component
            except TypeError:
                pass
            component_type = component.__class__.__name__.lower()
            if component_type == "file" or hasattr(component, "get_file"):
                return component
        return None

    @filter.command("rsshelp", alias={"RSS帮助", "rss帮助"})
    async def rsshelp(self, event: AstrMessageEvent):
        """查看 RSSHub 命令帮助图片。"""
        help_image_path = HelpImageCommand().execute(self.context)
        if help_image_path.exists():
            yield event.chain_result([Image(file=str(help_image_path.resolve()))])
            return
        yield event.plain_result("没有找到帮助图片")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("rsshub_kb_init", alias={"rss知识库初始化", "RSS知识库初始化"})
    async def rsshub_kb_init(self, event: AstrMessageEvent):
        """初始化 RSSHub Routes 知识库。"""
        result = await _h.handle_rsshub_kb_init(self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("rsshub_kb_sync", alias={"rss知识库同步", "RSS知识库同步"})
    async def rsshub_kb_sync(self, event: AstrMessageEvent):
        """启动 RSSHub Routes 知识库同步任务。"""
        result = await _h.handle_rsshub_kb_sync(self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command(
        "rsshub_kb_status", alias={"rss知识库同步状态", "RSS知识库同步状态"}
    )
    async def rsshub_kb_status(self, event: AstrMessageEvent):
        """查看 RSSHub Routes 知识库状态。"""
        result = await _h.handle_rsshub_kb_status(self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command(
        "rsshub_kb_task", alias={"rss知识库近期同步任务", "RSS知识库近期同步任务"}
    )
    async def rsshub_kb_task(self, event: AstrMessageEvent):
        """查看最近 RSSHub Routes 知识库同步任务。"""
        result = _h.handle_rsshub_kb_task(self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("sub_test", alias={"测试订阅"})
    async def test_sub(self, event: AstrMessageEvent, args: str = ""):
        """管理员测试推送。

        用法:
        - /sub_test <ID|URL>
        示例:
        - /sub_test 5
        """
        result = await _h.handle_test_sub(event, str(args), self._deps)
        if result.get("plain"):
            yield event.plain_result(result["plain"])
