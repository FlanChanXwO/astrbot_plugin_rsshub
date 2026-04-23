#  RSS to AstrBot Plugin
#  基于 RSS-to-Telegram-Bot 项目移植
#  Original: Copyright (C) 2020-2025 Rongrong <i@rong.moe>
#  Ported to AstrBot by AstrBot Team
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.

"""
AstrBot RSS订阅插件
基于 RSS-to-Telegram-Bot 项目移植，适配 AstrBot 多平台消息推送
"""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import parse_qsl

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star

from .api import close_shared_session
from .commands import (
    bind_target,
    export_subscriptions,
    get_plugin_config,
    get_session_defaults,
    import_subscriptions,
    list_subscriptions,
    set_plugin_config,
    set_session_default,
    set_subscription_option,
    set_user_default_option,
    subscribe_feed,
    test_subscription,
    unsubscribe_all_feeds,
    unsubscribe_feed,
)
from .config import (
    SESSION_DEFAULT_KEYS,
    SESSION_DEFAULT_KV_PREFIX,
    SUB_OPTION_CASTERS,
)
from .db import Sub, User, close_db, init_db
from .monitor import Monitor
from .notifier.senders import set_bot_self_id_provider
from .utils.config import PluginConfig
from .utils.ffmpeg_helper import ensure_ffmpeg_ready
from .utils.log_utils import logger
from .utils.rsshub_api import RSSHubRadarAPI, normalize_base_url
from .web import RSSHubWebUI, resolve_webui_config

IMPORT_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
IMPORT_MAX_FILE_SIZE_DISPLAY = f"{IMPORT_MAX_FILE_SIZE_BYTES / 1024 / 1024:g}MB"


class RSSHubPlugin(Star):
    """AstrBot RSS订阅插件主类"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.astrbot_config = config
        self.config: PluginConfig | None = None
        self.monitor: Monitor | None = None
        self._scheduler_task: asyncio.Task | None = None
        self._webui: RSSHubWebUI | None = None
        self._rsshub_radar_api: RSSHubRadarAPI | None = None
        self._rsshub_radar_api_settings: tuple[int, str] | None = None
        self._import_session_lock = asyncio.Lock()
        self._import_sessions: dict[tuple[str, str], float] = {}
        self._import_session_timeout = 300  # 5 分钟超时
        self._unsub_export_retention_seconds = 24 * 60 * 60

    def _select_test_entries(self, entries: list, granularity: str) -> tuple[list, str]:
        """根据测试粒度参数选择要推送的条目。"""
        mode = (granularity or "latest").strip().lower()

        if mode in {"latest", "last"}:
            return [entries[0]], "latest"

        if mode == "all":
            return entries, f"all({len(entries)})"

        # 语义化别名：默认和 count 一样，都是取前 n 个
        if (
            mode.startswith("first:")
            or mode.startswith("head:")
            or mode.startswith("oldest:")
        ):
            count_raw = mode.split(":", 1)[1]
            if not count_raw.isdigit() or int(count_raw) <= 0:
                raise ValueError("粒度数量必须大于 0")
            count = int(count_raw)
            selected = entries[:count]
            return selected, f"first:{len(selected)}"

        if mode.startswith("newest:") or mode.startswith("tail:"):
            count_raw = mode.split(":", 1)[1]
            if not count_raw.isdigit() or int(count_raw) <= 0:
                raise ValueError("粒度数量必须大于 0")
            count = int(count_raw)
            selected = entries[-count:]
            return selected, f"newest:{len(selected)}"

        count_raw = mode.removeprefix("count:") if mode.startswith("count:") else mode
        if count_raw.isdigit():
            count = int(count_raw)
            if count <= 0:
                raise ValueError("粒度数量必须大于 0")
            selected = entries[:count]
            return selected, f"count:{len(selected)}"

        raise ValueError(
            "粒度参数无效。可选: latest / all / <数量> / count:<数量> / first:<数量> / newest:<数量>"
        )

    def _parse_plugin_config_value(self, key: str, value: str):
        """Parse plugin-level config values from command."""
        normalized_key = key.strip().lower()
        raw_value = value.strip()

        if normalized_key in {"default_interval", "minimal_interval", "timeout"}:
            if not raw_value.isdigit() or int(raw_value) <= 0:
                raise ValueError(f"{normalized_key} 需要大于 0 的整数")
            return int(raw_value)

        if normalized_key == "download_image_before_send":
            lowered = raw_value.lower()
            if lowered in {"1", "true", "yes", "on", "enable", "enabled"}:
                return True
            if lowered in {"0", "false", "no", "off", "disable", "disabled"}:
                return False
            raise ValueError("download_image_before_send 仅支持布尔值: true/false")

        if normalized_key == "bootstrap_skip_history":
            lowered = raw_value.lower()
            if lowered in {"1", "true", "yes", "on", "enable", "enabled"}:
                return True
            if lowered in {"0", "false", "no", "off", "disable", "disabled"}:
                return False
            raise ValueError("bootstrap_skip_history 仅支持布尔值: true/false")

        if normalized_key == "debug_payload":
            lowered = raw_value.lower()
            if lowered in {"1", "true", "yes", "on", "enable", "enabled"}:
                return True
            if lowered in {"0", "false", "no", "off", "disable", "disabled"}:
                return False
            raise ValueError("debug_payload 仅支持布尔值: true/false")

        if normalized_key == "proxy":
            return raw_value

        if normalized_key == "rsshub_base_url":
            try:
                return normalize_base_url(raw_value)
            except ValueError as ex:
                raise ValueError(f"rsshub_base_url 非法: {ex}") from ex

        if normalized_key in {"failed_queue_capacity", "failed_queue_max_retries"}:
            if not raw_value.isdigit() or int(raw_value) < 0:
                raise ValueError(f"{normalized_key} 需要大于等于 0 的整数")
            return int(raw_value)

        if normalized_key in {
            "sender_strategy_telegram",
            "sender_strategy_aiocqhttp",
            "sender_strategy_weixin_oc",
            "deduplicate_multi_bot",
            "platform_shared_data_aiocqhttp",
        }:
            lowered = raw_value.lower()
            if lowered in {"1", "true", "yes", "on", "enable", "enabled"}:
                return True
            if lowered in {"0", "false", "no", "off", "disable", "disabled"}:
                return False
            raise ValueError(f"{normalized_key} 仅支持布尔值: true/false")

        raise ValueError(f"不支持的插件配置项: {normalized_key}")

    def _is_platform_shared(self, platform_name: str) -> bool:
        """Check if platform shared data is enabled for the given platform."""
        if self.config and self.config.platform_shared_data:
            return bool(self.config.platform_shared_data.get(platform_name, False))
        return False

    @staticmethod
    def _parse_llm_params_input(params: str) -> dict[str, str]:
        """Parse LLM params input from JSON object or query-string form."""
        raw = (params or "").strip()
        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("params_json 必须是 JSON 对象")
            return {str(k): str(v) for k, v in parsed.items() if str(k).strip()}
        except json.JSONDecodeError:
            return {k: v for k, v in parse_qsl(raw, keep_blank_values=True) if k}

    def _rsshub_api(self) -> RSSHubRadarAPI:
        """Create/reuse API helper with current runtime timeout/proxy config."""
        timeout = self.config.timeout if self.config else 30
        proxy = self.config.proxy if self.config else ""
        settings = (int(timeout), str(proxy))

        if (
            self._rsshub_radar_api is None
            or self._rsshub_radar_api_settings != settings
        ):
            self._rsshub_radar_api = RSSHubRadarAPI(
                timeout=settings[0],
                proxy=settings[1],
            )
            self._rsshub_radar_api_settings = settings

        return self._rsshub_radar_api

    def _parse_target_session(
        self,
        event: AstrMessageEvent,
        target: str,
    ) -> tuple[str | None, str | None]:
        """解析命令目标参数，返回(session, error)。"""
        raw = target.strip()
        if not raw:
            return event.unified_msg_origin, None

        normalized = raw.lower()
        platform_id = event.get_platform_id()

        if normalized in {"here", "current", "this"}:
            return event.unified_msg_origin, None

        if normalized in {"private", "friend", "dm"}:
            sender_id = event.get_sender_id()
            if not sender_id:
                return None, "当前事件无法识别发送者，无法绑定私聊目标"
            return f"{platform_id}:FriendMessage:{sender_id}", None

        if normalized in {"group", "grp"}:
            group_id = event.get_group_id()
            if not group_id:
                return None, "当前不是群聊上下文，无法绑定群聊目标"
            return f"{platform_id}:GroupMessage:{group_id}", None

        if raw.count(":") >= 2:
            return raw, None

        return (
            None,
            "目标参数无效。可选: private/group/current 或完整 session(platform:MessageType:id)",
        )

    def _parse_option_value(self, key: str, value: str):
        """解析命令中的选项值并做基础校验"""
        caster = SUB_OPTION_CASTERS.get(key)
        if caster is None:
            raise ValueError(f"不支持的选项: {key}")
        if caster is str:
            return value.strip()
        try:
            parsed = caster(value)
        except ValueError as ex:
            raise ValueError(f"选项 {key} 需要数字值") from ex
        if key == "interval" and self.config is not None:
            minimal = self.config.minimal_interval
            if parsed < minimal:
                raise ValueError(f"interval 不能小于 minimal_interval ({minimal})")
        return parsed

    async def _get_session_defaults(self, session_id: str) -> dict[str, int | str]:
        raw = await self.get_kv_data(f"{SESSION_DEFAULT_KV_PREFIX}{session_id}", {})
        if not isinstance(raw, dict):
            return {}
        return raw

    async def _set_session_default(self, session_id: str, key: str, value):
        current = await self._get_session_defaults(session_id)
        current[key] = value
        await self.put_kv_data(f"{SESSION_DEFAULT_KV_PREFIX}{session_id}", current)

    async def _apply_session_defaults_to_sub(
        self, event: AstrMessageEvent, sub_id: int
    ):
        session_id = event.unified_msg_origin
        defaults = await self._get_session_defaults(session_id)
        if not defaults:
            return

        update_payload: dict[str, int | str] = {}
        for key, raw_value in defaults.items():
            if key not in SESSION_DEFAULT_KEYS:
                continue
            if key in {"title", "tags"}:
                update_payload[key] = str(raw_value)
            else:
                update_payload[key] = int(raw_value)

        if update_payload:
            await Sub.update_options(sub_id, event.get_sender_id(), **update_payload)

    async def _emit_binding_notice_if_needed(self, event: AstrMessageEvent):
        """如果用户存在推送绑定待处理提醒，则在本次命令先提示一次。"""
        user_id = event.get_sender_id()
        if not user_id:
            return
        if await User.consume_binding_notice(user_id):
            yield event.plain_result(
                "检测到最近一次 RSS 推送失败，可能是订阅目标会话已失效。\n"
                "请使用 /sub_bind <private|group|session> 重新绑定默认推送目标。"
            )

    def _get_bot_self_id(self, platform_id: str) -> str:
        """根据 platform_id 获取对应平台适配器的 bot self_id"""
        if self.context is None:
            return "10000"

        try:
            platform_manager = getattr(self.context, "platform_manager", None)
            if platform_manager is None:
                return "10000"

            platform_insts = getattr(platform_manager, "platform_insts", [])
            for platform in platform_insts:
                meta = platform.meta()
                if meta and meta.id == platform_id:
                    if hasattr(platform, "bot_self_id") and platform.bot_self_id:
                        return str(platform.bot_self_id)
                    if hasattr(platform, "bot") and hasattr(platform.bot, "self_id"):
                        return str(platform.bot.self_id)
                    break
        except Exception as ex:
            logger.debug("获取 bot_self_id 失败: %s", ex)

        return "10000"

    async def initialize(self):
        """插件初始化"""
        logger.info("RSS订阅插件初始化...")

        self.config = PluginConfig.load(
            plugin_name=self.name,
            astrbot_config=self.astrbot_config,
        )
        logger.info(f"RSS插件配置加载完成，数据目录: {self.config.data_dir}")

        if self.config.video_transcode:
            ffmpeg_path = ensure_ffmpeg_ready(auto_install=True)
            if ffmpeg_path:
                logger.info("RSS插件 FFmpeg 已就绪: %s", ffmpeg_path)
            else:
                logger.warning("RSS插件 FFmpeg 未就绪，视频将尝试原始格式发送")

        await init_db(self.config.db_path)
        logger.info("RSS插件数据库初始化完成")

        self.monitor = Monitor(self.config)
        logger.info("RSS监控器初始化完成")

        # 设置 bot_self_id provider
        set_bot_self_id_provider(self._get_bot_self_id)

        await self._start_webui_if_enabled()

        self._start_scheduler_task()
        logger.info("RSS插件定时监控任务已启动")

    async def terminate(self):
        """插件终止"""
        logger.info("RSS订阅插件终止...")

        # 清除 bot_self_id provider
        set_bot_self_id_provider(None)

        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        if self._rsshub_radar_api is not None:
            await self._rsshub_radar_api.close()
        await close_shared_session()

        await self._stop_webui_if_needed()
        await close_db()
        logger.info("RSS插件数据库已关闭")

    def _start_scheduler_task(self):
        """启动定时监控任务"""
        self._scheduler_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        """定时监控循环"""
        while True:
            try:
                await asyncio.sleep(60)
                await self.monitor.run_periodic_task()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"RSS监控执行出错: {e}", exc_info=True)

    async def _start_webui_if_enabled(self) -> None:
        if self.astrbot_config is None:
            return

        webui_cfg = resolve_webui_config(self.astrbot_config)
        if not webui_cfg.enabled:
            return

        self._webui = RSSHubWebUI(self, webui_cfg)
        await self._webui.start()

    async def _stop_webui_if_needed(self) -> None:
        if self._webui is not None:
            await self._webui.stop()
            self._webui = None

    # ===== 命令方法 =====

    @filter.command("sub", alias={"订阅"})
    async def cmd_sub(self, event: AstrMessageEvent, url: str = "", target: str = ""):
        """订阅 RSS 源

        Usage: /sub https://example.com/rss.xml
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        result = await subscribe_feed(
            url=url,
            target=target,
            user_id=event.get_sender_id(),
            platform_name=event.platform_meta.name,
            timeout=self.config.timeout if self.config else 30,
            proxy=self.config.proxy if self.config else "",
            is_platform_shared=self._is_platform_shared(event.platform_meta.name),
            session_defaults=await self._get_session_defaults(event.unified_msg_origin),
            parse_target_fn=lambda t: self._parse_target_session(event, t),
        )

        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("unsub", alias={"取消订阅"})
    async def cmd_unsub(self, event: AstrMessageEvent, sub_id: str = ""):
        """取消订阅

        Usage: /unsub <订阅 ID>
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        result = await unsubscribe_feed(
            sub_id=sub_id,
            user_id=event.get_sender_id(),
            current_session=event.unified_msg_origin,
            is_admin=event.is_admin(),
            platform_name=event.platform_meta.name,
            is_platform_shared=self._is_platform_shared(event.platform_meta.name),
        )

        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("sub_list", alias={"订阅列表"})
    async def cmd_list(
        self,
        event: AstrMessageEvent,
        scope: str = "",
        page: str = "1",
        page_size: str = "5",
    ):
        """列出订阅列表

        Usage:
            /sub_list                          (查看当前会话的订阅)
            /sub_list [page] [page_size]       (平台共享模式下分页查看)
            /sub_list all [page] [page_size]   (管理员查看所有订阅)
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        result = await list_subscriptions(
            user_id=event.get_sender_id(),
            current_session=event.unified_msg_origin,
            platform_name=event.platform_meta.name,
            is_platform_shared=self._is_platform_shared(event.platform_meta.name),
            is_admin=event.is_admin(),
            scope=scope,
            page=page,
            page_size=page_size,
        )

        yield event.plain_result(result.get("message", result.get("error", "未知错误")))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("sub_test", alias={"测试订阅"})
    async def cmd_sub_test(
        self,
        event: AstrMessageEvent,
        sub_id: str = "",
        granularity: str = "latest",
    ):
        """管理员手动触发单个订阅测试推送

        Usage: /sub_test <订阅ID> [latest|all|数量|count:数量|first:数量|newest:数量]
        """
        result = await test_subscription(
            sub_id=sub_id,
            granularity=granularity,
            timeout=self.config.timeout if self.config else 30,
            proxy=self.config.proxy if self.config else "",
            download_image_before_send=(
                self.config.download_image_before_send if self.config else True
            ),
            config=self.config,
        )

        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("unsub_all", alias={"取消全部订阅"})
    async def cmd_unsub_all(self, event: AstrMessageEvent, scope: str = ""):
        """取消当前会话或所有订阅

        Usage: /unsub_all [global]
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        result = await unsubscribe_all_feeds(
            user_id=event.get_sender_id(),
            current_session=event.unified_msg_origin,
            is_admin=event.is_admin(),
            scope=scope,
            unsub_export_retention_seconds=self._unsub_export_retention_seconds,
        )

        if result["success"]:
            if "export_path" in result:
                yield event.plain_result(result["message"])
                yield event.chain_result(
                    [
                        File(
                            name=result["export_filename"],
                            file=str(result["export_path"]),
                        )
                    ]
                )
            else:
                yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("sub_export", alias={"导出订阅"})
    async def cmd_sub_export(self, event: AstrMessageEvent, scope: str = ""):
        """导出订阅到 TOML 文件

        Usage: /sub_export [all]
        """
        result = await export_subscriptions(
            user_id=event.get_sender_id(),
            current_session=event.unified_msg_origin,
            is_admin=event.is_admin(),
            scope=scope,
        )

        if result["success"]:
            yield event.plain_result(result["message"])
            yield event.chain_result(
                [File(name=result["export_filename"], file=str(result["export_path"]))]
            )
            # 清理临时文件
            try:
                if result["export_path"].exists():
                    result["export_path"].unlink()
            except OSError:
                pass
        else:
            yield event.plain_result(result["error"])

    @filter.command("sub_import", alias={"导入订阅"})
    async def cmd_sub_import(self, event: AstrMessageEvent, import_path: str = ""):
        """导入订阅

        Usage: /sub_import [本地文件路径]
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        # 读取导入内容
        content, read_err, should_wait_upload = await self._read_import_toml_content(
            event, import_path
        )

        if content:
            result = await import_subscriptions(
                content=content,
                user_id=event.get_sender_id(),
                session_id=event.unified_msg_origin,
                platform_name=event.platform_meta.name,
                validate_options_fn=lambda options: (
                    self._validate_import_record_options(event, options)
                ),
            )
            yield event.plain_result(
                result.get("message", result.get("error", "未知错误"))
            )
            return

        if read_err:
            yield event.plain_result(read_err)
            return

        if not should_wait_upload:
            yield event.plain_result("未检测到可导入的文件")
            return

        # 设置导入会话，等待用户上传文件
        user_id = str(event.get_sender_id())
        session_key = (user_id, event.unified_msg_origin)
        now = time.monotonic()
        async with self._import_session_lock:
            # 清理超时会话
            timeout_threshold = now - self._import_session_timeout
            expired_keys = [
                sid
                for sid, start_time in self._import_sessions.items()
                if start_time < timeout_threshold
            ]
            for sid in expired_keys:
                del self._import_sessions[sid]
            self._import_sessions[session_key] = now

        yield event.plain_result(
            "请在 5 分钟内发送 TOML 订阅文件。\n"
            "注意：导入将添加新的订阅，重复的订阅会被跳过。\n"
            "超时请重新执行 /sub_import 命令。"
        )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_file_message(self, event: AstrMessageEvent):
        """监听文件消息以处理订阅导入"""
        sender_id = str(event.get_sender_id())
        session_key = (sender_id, event.unified_msg_origin)

        # 检查是否有活跃的导入会话
        async with self._import_session_lock:
            session_start = self._import_sessions.get(session_key)
            if session_start is None:
                return

            # 检查会话是否超时
            now = time.monotonic()
            if now - session_start > self._import_session_timeout:
                del self._import_sessions[session_key]
                return

        has_file = False

        try:
            content, read_err, has_file = await self._read_uploaded_toml_content(
                event,
                max_file_size=IMPORT_MAX_FILE_SIZE_BYTES,
            )
            if not has_file:
                return
            if read_err:
                yield event.plain_result(read_err)
                return
            if not content:
                yield event.plain_result("读取上传文件失败")
                return

            result = await import_subscriptions(
                content=content,
                user_id=event.get_sender_id(),
                session_id=event.unified_msg_origin,
                platform_name=event.platform_meta.name,
                validate_options_fn=lambda options: (
                    self._validate_import_record_options(event, options)
                ),
            )
            yield event.plain_result(
                result.get("message", result.get("error", "未知错误"))
            )

        except OSError as e:
            logger.error(f"导入文件处理失败: {e}")
            yield event.plain_result(f"文件处理失败: {e}")
        finally:
            # 清理导入会话
            if has_file:
                async with self._import_session_lock:
                    self._import_sessions.pop(session_key, None)

    @filter.command("sub_set", alias={"设置订阅"})
    async def cmd_set_sub_option(
        self, event: AstrMessageEvent, sub_id: str = "", key: str = "", value: str = ""
    ):
        """设置订阅选项

        Usage: /sub_set <订阅ID> <选项名> <值>
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        result = await set_subscription_option(
            sub_id=sub_id,
            key=key,
            value=value,
            user_id=event.get_sender_id(),
            parse_option_value_fn=self._parse_option_value,
            parse_target_session_fn=lambda t: self._parse_target_session(event, t),
        )

        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("sub_set_default", alias={"设置默认订阅"})
    async def cmd_set_default_option(
        self, event: AstrMessageEvent, key: str = "", value: str = ""
    ):
        """设置当前用户默认订阅选项

        Usage: /sub_set_default <选项名> <值>
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        result = await set_user_default_option(
            key=key,
            value=value,
            user_id=event.get_sender_id(),
            parse_option_value_fn=self._parse_option_value,
        )

        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("sub_bind", alias={"绑定订阅"})
    async def cmd_sub_bind(self, event: AstrMessageEvent, target: str = ""):
        """绑定当前用户默认推送目标

        Usage: /sub_bind <private|group|session>
        """
        result = await bind_target(
            target=target,
            user_id=event.get_sender_id(),
            parse_target_session_fn=lambda t: self._parse_target_session(event, t),
        )

        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("sub_session_default_set", alias={"设置会话默认"})
    async def cmd_sub_session_default_set(
        self,
        event: AstrMessageEvent,
        key: str = "",
        value: str = "",
    ):
        """设置会话级默认选项

        Usage: /sub_session_default_set <key> <value>
        """
        result = await set_session_default(
            session_id=event.unified_msg_origin,
            key=key,
            value=value,
            session_default_keys=SESSION_DEFAULT_KEYS,
            parse_option_value_fn=self._parse_option_value,
            set_session_defaults_fn=self._set_session_default,
        )

        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("sub_session_default_get", alias={"获取会话默认"})
    async def cmd_sub_session_default_get(self, event: AstrMessageEvent):
        """获取会话级默认选项

        Usage: /sub_session_default_get
        """
        result = await get_session_defaults(
            session_id=event.unified_msg_origin,
            get_session_defaults_fn=self._get_session_defaults,
        )

        yield event.plain_result(result["message"])

    @filter.command("rss_conf", alias={"RSS配置"})
    async def cmd_rss_conf(
        self, event: AstrMessageEvent, key: str = "", value: str = ""
    ):
        """查看或设置插件配置

        Usage: /rss_conf [key] [value]
        """
        if self.config is None:
            yield event.plain_result("插件配置尚未初始化")
            return

        normalized_key = key.strip().lower()

        if not normalized_key:
            yield event.plain_result(get_plugin_config(self.config))
            return

        await set_plugin_config(
            key=key,
            value=value,
            config=self.config,
            parse_plugin_config_value_fn=self._parse_plugin_config_value,
        )
