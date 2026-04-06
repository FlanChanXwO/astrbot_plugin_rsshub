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

import asyncio
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star
from astrbot.core.provider.register import llm_tools
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from .api import close_shared_session
from .db import Feed, Sub, User, close_db, init_db
from .monitor import Monitor
from .notifier import Notifier
from .notifier.senders import set_bot_self_id_provider
from .utils.config import PluginConfig
from .utils.rsshub_api import RSSHubRadarAPI, normalize_base_url
from .utils.subscription_io import (
    parse_subscriptions_toml,
    serialize_subscriptions_to_toml,
)
from .web import RSSHubWebUI, feed_get, resolve_webui_config

SUB_OPTION_CASTERS = {
    "notify": int,
    "send_mode": int,
    "length_limit": int,
    "link_preview": int,
    "display_author": int,
    "display_via": int,
    "display_title": int,
    "display_entry_tags": int,
    "style": int,
    "display_media": int,
    "interval": int,
    "title": str,
    "tags": str,
    "target_session": str,
}

USER_DEFAULT_OPTION_KEYS = {
    "notify",
    "send_mode",
    "length_limit",
    "link_preview",
    "display_author",
    "display_via",
    "display_title",
    "display_entry_tags",
    "style",
    "display_media",
    "interval",
}

PLUGIN_CONFIG_KEYS = {
    "proxy",
    "default_interval",
    "minimal_interval",
    "timeout",
    "download_image_before_send",
    "rsshub_base_url",
}

SESSION_DEFAULT_KV_PREFIX = "session_defaults::"
SESSION_DEFAULT_KEYS = {
    "notify",
    "send_mode",
    "length_limit",
    "link_preview",
    "display_author",
    "display_via",
    "display_title",
    "display_entry_tags",
    "style",
    "display_media",
    "interval",
    "title",
    "tags",
}

IMPORT_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024


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
        # 导入会话状态管理（类似 deerpipe）
        self._import_session_lock = asyncio.Lock()
        self._import_sessions: dict[tuple[str, str], float] = {}
        self._import_session_timeout = 300  # 5分钟超时
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

        if normalized_key == "proxy":
            return raw_value

        if normalized_key == "rsshub_base_url":
            try:
                return normalize_base_url(raw_value)
            except ValueError as ex:
                raise ValueError(f"rsshub_base_url 非法: {ex}") from ex

        raise ValueError(f"不支持的插件配置项: {normalized_key}")

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

    async def initialize(self):
        """插件初始化"""
        logger.info("RSS订阅插件初始化...")

        self.config = PluginConfig.load(
            plugin_name=self.name,
            astrbot_config=self.astrbot_config,
        )
        logger.info(f"RSS插件配置加载完成，数据目录: {self.config.data_dir}")

        await init_db(self.config.db_path)
        logger.info("RSS插件数据库初始化完成")

        self.monitor = Monitor(self.config)
        logger.info("RSS监控器初始化完成")

        # 设置 bot_self_id provider
        set_bot_self_id_provider(self._get_bot_self_id)

        await self._register_llm_tools()

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
        await self._unregister_llm_tools()
        await close_db()
        logger.info("RSS插件数据库已关闭")

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
                    # 尝试获取 bot_self_id 属性
                    if hasattr(platform, "bot_self_id") and platform.bot_self_id:
                        return str(platform.bot_self_id)
                    # 对于 aiocqhttp，尝试从 bot 获取
                    if hasattr(platform, "bot") and hasattr(platform.bot, "self_id"):
                        return str(platform.bot.self_id)
                    break
        except Exception as ex:
            logger.debug("获取 bot_self_id 失败: %s", ex)

        return "10000"

    async def _start_webui_if_enabled(self) -> None:
        if self.astrbot_config is None:
            return

        webui_cfg = resolve_webui_config(self.astrbot_config)
        if not bool(webui_cfg.get("enabled", False)):
            return

        self._webui = RSSHubWebUI(self, webui_cfg)
        await self._webui.start()

    async def _stop_webui_if_needed(self) -> None:
        if self._webui is not None:
            await self._webui.stop()
            self._webui = None

    async def _register_llm_tools(self) -> None:
        """Register LLM tools for rss commands except sub_test."""
        tools = [
            (
                "rss_subscribe",
                self._llm_subscribe,
                [
                    {"name": "url", "type": "string", "description": "RSS URL"},
                    {
                        "name": "target",
                        "type": "string",
                        "description": "Target session alias: private/group/current or full session id",
                    },
                ],
                "Subscribe an RSS feed for current user/session.",
            ),
            (
                "rss_unsubscribe",
                self._llm_unsubscribe,
                [
                    {
                        "name": "sub_id",
                        "type": "string",
                        "description": "Subscription id",
                    }
                ],
                "Unsubscribe by subscription id.",
            ),
            (
                "rss_unsubscribe_all",
                self._llm_unsubscribe_all,
                [],
                "Unsubscribe all feeds for current user.",
            ),
            (
                "rss_list_subscriptions",
                self._llm_list_subscriptions,
                [],
                "List subscriptions for current user.",
            ),
            (
                "rss_set_subscription_option",
                self._llm_set_subscription_option,
                [
                    {
                        "name": "sub_id",
                        "type": "string",
                        "description": "Subscription id",
                    },
                    {"name": "key", "type": "string", "description": "Option key"},
                    {"name": "value", "type": "string", "description": "Option value"},
                ],
                "Set one subscription option.",
            ),
            (
                "rss_set_user_default_option",
                self._llm_set_user_default_option,
                [
                    {"name": "key", "type": "string", "description": "Option key"},
                    {"name": "value", "type": "string", "description": "Option value"},
                ],
                "Set user default option.",
            ),
            (
                "rss_bind_default_target",
                self._llm_bind_target,
                [
                    {
                        "name": "target",
                        "type": "string",
                        "description": "Target session alias or full session",
                    }
                ],
                "Bind user default push target.",
            ),
            (
                "rss_get_plugin_config",
                self._llm_get_plugin_config,
                [
                    {
                        "name": "key",
                        "type": "string",
                        "description": "Optional config key",
                    }
                ],
                "Get plugin runtime config.",
            ),
            (
                "rss_set_plugin_config",
                self._llm_set_plugin_config,
                [
                    {"name": "key", "type": "string", "description": "Config key"},
                    {"name": "value", "type": "string", "description": "Config value"},
                ],
                "Set plugin runtime config.",
            ),
            (
                "rss_set_session_default_option",
                self._llm_set_session_default_option,
                [
                    {
                        "name": "key",
                        "type": "string",
                        "description": "Session default key",
                    },
                    {
                        "name": "value",
                        "type": "string",
                        "description": "Session default value",
                    },
                ],
                "Set session-level default option for new subscriptions in current session.",
            ),
            (
                "rss_get_session_defaults",
                self._llm_get_session_defaults,
                [],
                "Get current session-level default options.",
            ),
            (
                "rsshub_search_routes",
                self._llm_rsshub_search_routes,
                [
                    {
                        "name": "query",
                        "type": "string",
                        "description": "Route search keywords, e.g. bilibili dynamic",
                    },
                    {
                        "name": "top_k",
                        "type": "string",
                        "description": "Optional result limit (1-30), default 8",
                    },
                    {
                        "name": "base_url",
                        "type": "string",
                        "description": "Optional RSSHub base URL override",
                    },
                ],
                "Search RSSHub routes and return concise route summaries.",
            ),
            (
                "rsshub_get_route_schema",
                self._llm_rsshub_get_route_schema,
                [
                    {
                        "name": "uri",
                        "type": "string",
                        "description": "Route URI like /bilibili/user/dynamic/:uid",
                    },
                    {
                        "name": "base_url",
                        "type": "string",
                        "description": "Optional RSSHub base URL override",
                    },
                ],
                "Get one RSSHub route schema with required/optional params.",
            ),
            (
                "rsshub_build_subscribe_url",
                self._llm_rsshub_build_subscribe_url,
                [
                    {
                        "name": "uri",
                        "type": "string",
                        "description": "Route URI path to build final subscription URL",
                    },
                    {
                        "name": "params_json",
                        "type": "string",
                        "description": "Optional JSON object or query-string params",
                    },
                    {
                        "name": "base_url",
                        "type": "string",
                        "description": "Optional RSSHub base URL override",
                    },
                ],
                "Build final RSSHub subscription URL from uri and params.",
            ),
        ]

        for name, handler, args, desc in tools:
            llm_tools.add_func(name=name, func_args=args, desc=desc, handler=handler)
            tool = llm_tools.get_func(name)
            if tool:
                tool.handler_module_path = __name__

    async def _unregister_llm_tools(self) -> None:
        tool_names = [
            "rss_subscribe",
            "rss_unsubscribe",
            "rss_unsubscribe_all",
            "rss_list_subscriptions",
            "rss_set_subscription_option",
            "rss_set_user_default_option",
            "rss_bind_default_target",
            "rss_get_plugin_config",
            "rss_set_plugin_config",
            "rss_set_session_default_option",
            "rss_get_session_defaults",
            "rsshub_search_routes",
            "rsshub_get_route_schema",
            "rsshub_build_subscribe_url",
        ]
        for name in tool_names:
            try:
                llm_tools.remove_func(name)
            except Exception:
                pass

    @staticmethod
    def _collect_tool_text(result) -> str:
        text = getattr(result, "text", None)
        if isinstance(text, str):
            return text
        chain = getattr(result, "chain", None)
        if isinstance(chain, list):
            for component in chain:
                component_text = getattr(component, "text", None)
                if isinstance(component_text, str):
                    return component_text
        return str(result)

    async def _run_command_and_collect(self, command_coro) -> str:
        lines: list[str] = []
        async for result in command_coro:
            lines.append(self._collect_tool_text(result))
        return "\n".join(line for line in lines if line)

    async def _llm_subscribe(
        self, event: AstrMessageEvent, url: str = "", target: str = ""
    ) -> str:
        return await self._run_command_and_collect(self.cmd_sub(event, url, target))

    async def _llm_unsubscribe(self, event: AstrMessageEvent, sub_id: str = "") -> str:
        return await self._run_command_and_collect(self.cmd_unsub(event, sub_id))

    async def _llm_unsubscribe_all(self, event: AstrMessageEvent) -> str:
        return await self._run_command_and_collect(self.cmd_unsub_all(event, "global"))

    async def _llm_list_subscriptions(self, event: AstrMessageEvent) -> str:
        return await self._run_command_and_collect(self.cmd_list(event))

    async def _llm_set_subscription_option(
        self,
        event: AstrMessageEvent,
        sub_id: str = "",
        key: str = "",
        value: str = "",
    ) -> str:
        return await self._run_command_and_collect(
            self.cmd_set_sub_option(event, sub_id, key, value)
        )

    async def _llm_set_user_default_option(
        self,
        event: AstrMessageEvent,
        key: str = "",
        value: str = "",
    ) -> str:
        return await self._run_command_and_collect(
            self.cmd_set_default_option(event, key, value)
        )

    async def _llm_bind_target(self, event: AstrMessageEvent, target: str = "") -> str:
        return await self._run_command_and_collect(self.cmd_sub_bind(event, target))

    async def _llm_get_plugin_config(
        self, event: AstrMessageEvent, key: str = ""
    ) -> str:
        return await self._run_command_and_collect(self.cmd_rss_conf(event, key, ""))

    async def _llm_set_plugin_config(
        self,
        event: AstrMessageEvent,
        key: str = "",
        value: str = "",
    ) -> str:
        return await self._run_command_and_collect(self.cmd_rss_conf(event, key, value))

    async def _llm_set_session_default_option(
        self,
        event: AstrMessageEvent,
        key: str = "",
        value: str = "",
    ) -> str:
        return await self._run_command_and_collect(
            self.cmd_sub_session_default_set(event, key, value)
        )

    async def _llm_get_session_defaults(self, event: AstrMessageEvent) -> str:
        return await self._run_command_and_collect(
            self.cmd_sub_session_default_get(event)
        )

    async def _llm_rsshub_search_routes(
        self,
        event: AstrMessageEvent,
        query: str = "",
        top_k: str = "",
        base_url: str = "",
    ) -> str:
        del event
        if self.config is None:
            return "插件配置尚未初始化"

        try:
            limit = int(top_k) if (top_k or "").strip() else 8
        except ValueError:
            return "top_k 必须是整数"
        limit = max(1, min(limit, 30))

        try:
            resolved_base_url, routes = await self._rsshub_api().search_routes(
                query=query,
                top_k=limit,
                explicit_base_url=base_url,
                default_base_url=self.config.rsshub_base_url,
            )
        except Exception as ex:
            return f"RSSHub 路由检索失败: {ex}"

        return json.dumps(
            {
                "resolved_base_url": resolved_base_url,
                "count": len(routes),
                "routes": routes,
            },
            ensure_ascii=False,
            indent=2,
        )

    async def _llm_rsshub_get_route_schema(
        self,
        event: AstrMessageEvent,
        uri: str = "",
        base_url: str = "",
    ) -> str:
        del event
        if self.config is None:
            return "插件配置尚未初始化"
        if not (uri or "").strip():
            return "请提供 uri，例如 /bilibili/user/dynamic/:uid"

        try:
            resolved_base_url, schema = await self._rsshub_api().get_route_schema(
                uri=uri,
                explicit_base_url=base_url,
                default_base_url=self.config.rsshub_base_url,
            )
        except Exception as ex:
            return f"获取路由参数失败: {ex}"

        if schema is None:
            return json.dumps(
                {
                    "resolved_base_url": resolved_base_url,
                    "found": False,
                    "message": "未找到指定 uri，请先调用 rsshub_search_routes",
                },
                ensure_ascii=False,
                indent=2,
            )

        return json.dumps(
            {
                "resolved_base_url": resolved_base_url,
                "found": True,
                "schema": schema,
            },
            ensure_ascii=False,
            indent=2,
        )

    async def _llm_rsshub_build_subscribe_url(
        self,
        event: AstrMessageEvent,
        uri: str = "",
        params_json: str = "",
        base_url: str = "",
    ) -> str:
        del event
        if self.config is None:
            return "插件配置尚未初始化"
        if not (uri or "").strip():
            return "请提供 uri，例如 /bilibili/user/dynamic/12345"

        try:
            parsed_params = self._parse_llm_params_input(params_json)
            resolved_base_url, subscribe_url = self._rsshub_api().build_subscribe_url(
                uri=uri,
                params=parsed_params,
                explicit_base_url=base_url,
                default_base_url=self.config.rsshub_base_url,
            )
        except Exception as ex:
            return f"构建订阅链接失败: {ex}"

        return json.dumps(
            {
                "resolved_base_url": resolved_base_url,
                "uri": uri,
                "params": parsed_params,
                "subscribe_url": subscribe_url,
            },
            ensure_ascii=False,
            indent=2,
        )

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
            if key == "title" or key == "tags":
                update_payload[key] = str(raw_value)
            else:
                update_payload[key] = int(raw_value)

        if update_payload:
            await Sub.update_options(sub_id, event.get_sender_id(), **update_payload)

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

    async def _cleanup_unsub_export_backups(self, temp_dir: Path) -> None:
        """Best-effort cleanup for old unsub backup files under temp directory."""
        now = time.time()
        cutoff = now - self._unsub_export_retention_seconds

        for path in temp_dir.glob("rsshub_subscriptions_*.toml"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError as ex:
                logger.debug("Skip stale export cleanup for %s: %s", path, ex)

    async def _read_uploaded_toml_content(
        self,
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
                    return None, "导入文件过大，请控制在 5MB 以内", True
                return candidate.read_text(encoding="utf-8-sig"), None, True
            except OSError as ex:
                return None, f"读取上传文件失败: {ex}", True
            finally:
                if file_path:
                    try:
                        os.unlink(file_path)
                    except OSError:
                        pass

        return None, None, has_file_component

    async def _read_import_toml_content(
        self,
        event: AstrMessageEvent,
        import_path: str = "",
    ) -> tuple[str | None, str | None, bool]:
        """Read import TOML content from local path or uploaded file.

        Returns: (content, error, should_wait_upload)
        """
        if import_path.strip():
            if not event.is_admin():
                return (
                    None,
                    "出于安全考虑，仅管理员可使用本地路径导入，请改为上传 TOML 文件。",
                    False,
                )
            if self.config is None:
                return None, "插件配置尚未初始化", False

            path = Path(import_path.strip()).expanduser().resolve()
            allowed_dir = (self.config.data_dir / "imports").resolve()
            allowed_dir.mkdir(parents=True, exist_ok=True)

            try:
                path.relative_to(allowed_dir)
            except ValueError:
                return (
                    None,
                    f"仅允许从导入目录读取文件: {allowed_dir}",
                    False,
                )

            if not path.is_file():
                return None, f"导入文件不存在: {path}", False
            try:
                if path.stat().st_size > IMPORT_MAX_FILE_SIZE_BYTES:
                    return None, "导入文件过大，请控制在 5MB 以内", False
                return path.read_text(encoding="utf-8-sig"), None, False
            except OSError as ex:
                return None, f"读取导入文件失败: {ex}", False

        content, read_err, has_file_component = await self._read_uploaded_toml_content(
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

    def _validate_import_record_options(
        self,
        event: AstrMessageEvent,
        options: dict[str, int | str],
    ) -> tuple[dict[str, int | str], str | None]:
        """Validate and normalize imported subscription options."""
        validated: dict[str, int | str] = {}

        for key, raw_value in options.items():
            if key == "platform_name":
                if isinstance(raw_value, str) and raw_value.strip():
                    validated[key] = raw_value.strip()
                continue

            if key == "target_session":
                if not isinstance(raw_value, str):
                    return {}, "target_session 必须是字符串"
                parsed_target, parse_err = self._parse_target_session(event, raw_value)
                if parse_err:
                    return {}, f"target_session 无效: {parse_err}"
                if parsed_target:
                    validated[key] = parsed_target
                continue

            if key in {"title", "tags"}:
                if not isinstance(raw_value, str):
                    return {}, f"{key} 必须是字符串"
                normalized = raw_value.strip()
                if normalized:
                    validated[key] = normalized
                continue

            if key not in SUB_OPTION_CASTERS:
                continue

            try:
                parsed_value = self._parse_option_value(key, str(raw_value))
            except ValueError as ex:
                return {}, str(ex)
            validated[key] = parsed_value

        return validated, None

    # ===== 命令处理 =====

    @filter.command("sub")
    async def cmd_sub(
        self,
        event: AstrMessageEvent,
        url: str = "",
        target: str = "",
    ):
        """订阅RSS源

        Usage: /sub https://example.com/rss.xml [private|group|current|session]
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        if not url:
            yield event.plain_result("请提供RSS链接，用法: /sub <RSS链接> [目标]")
            return

        if not re.match(r"^https?://", url):
            yield event.plain_result("请提供有效的RSS链接（需以http或https开头）")
            return
        wf = await feed_get(
            url,
            timeout=self.config.timeout if self.config else None,
            proxy=self.config.proxy if self.config else "",
        )
        if wf.error:
            yield event.plain_result(f"订阅失败: {wf.error.error_name}")
            return

        if wf.rss_d is None:
            yield event.plain_result("订阅失败: 无法解析RSS内容")
            return

        title = wf.rss_d.feed.get("title", url)

        user_id = event.get_sender_id()
        user = await User.get_or_create(user_id)

        target_session, target_err = self._parse_target_session(event, target)
        if target_err:
            yield event.plain_result(target_err)
            return

        existing_sub = await Sub.get_by_user_and_link(user_id, url, target_session)
        if existing_sub:
            yield event.plain_result(f"您已经订阅了此源: {existing_sub.feed.title}")
            return

        feed = await Feed.get_or_create(link=url, title=title)
        platform_name = event.platform.name
        sub = await Sub.create(
            user_id=user.id,
            feed_id=feed.id,
            target_session=target_session,
            platform_name=platform_name,
        )

        await self._apply_session_defaults_to_sub(event, sub.id)

        if target_session:
            await User.set_default_target(user.id, target_session)

        yield event.plain_result(
            "订阅成功!\n"
            f"源标题: {title}\n"
            f"订阅ID: {sub.id}\n"
            f"推送目标: {target_session or '未设置'}"
        )

    @filter.command("unsub")
    async def cmd_unsub(self, event: AstrMessageEvent, sub_id: str = ""):
        """取消订阅

        Usage: /unsub <订阅ID>
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        if not sub_id:
            yield event.plain_result("请提供订阅ID，用法: /unsub <订阅ID>")
            return

        try:
            sub_id_int = int(sub_id)
        except ValueError:
            yield event.plain_result("订阅ID必须是数字")
            return

        user_id = event.get_sender_id()

        sub = await Sub.get_by_id_and_user(sub_id_int, user_id)
        if not sub:
            yield event.plain_result("未找到该订阅")
            return

        await Sub.delete(sub)
        yield event.plain_result(f"已取消订阅 (ID: {sub_id_int})")

    @filter.command("sub_list")
    async def cmd_list(self, event: AstrMessageEvent, scope: str = ""):
        """列出订阅列表。

        Usage: /sub_list [all]
        """
        user_id = event.get_sender_id()

        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        subs = await Sub.get_by_user(user_id)
        if not subs:
            yield event.plain_result("您还没有任何订阅")
            return

        show_all_sessions = scope.strip().lower() == "all" and event.is_admin()
        current_session = event.unified_msg_origin

        if show_all_sessions:
            filtered_subs = subs
            lines = ["您的订阅列表（所有会话）:"]
        else:
            filtered_subs = [
                sub
                for sub in subs
                if (sub.target_session or current_session) == current_session
            ]
            if not filtered_subs:
                yield event.plain_result(
                    "当前会话没有订阅。\n"
                    "可使用 /sub 添加订阅；管理员可用 /sub_list all 查看所有会话。"
                )
                return
            lines = ["您的订阅列表（当前会话）:"]

        for idx, sub in enumerate(filtered_subs, 1):
            feed_title = sub.feed.title if sub.feed else "未知"
            feed_link = sub.feed.link if sub.feed else ""
            custom_title = f" ({sub.title})" if sub.title else ""
            lines.append(f"{idx}. [{sub.id}] {feed_title}{custom_title}")
            if show_all_sessions and sub.target_session:
                lines.append(f"    target: {sub.target_session}")
            if feed_link:
                lines.append(f"    {feed_link}")

        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("sub_test")
    async def cmd_sub_test(
        self,
        event: AstrMessageEvent,
        sub_id: str = "",
        granularity: str = "latest",
    ):
        """管理员手动触发单个订阅测试推送

        Usage: /sub_test <订阅ID> [latest|all|数量|count:数量|first:数量|newest:数量]
        """
        if not sub_id:
            yield event.plain_result(
                "请提供订阅ID，用法: /sub_test <订阅ID> "
                "[latest|all|数量|count:数量|first:数量|newest:数量]"
            )
            return

        try:
            sub_id_int = int(sub_id)
        except ValueError:
            yield event.plain_result("订阅ID必须是数字")
            return

        sub = await Sub.get_by_id(sub_id_int)
        if not sub:
            yield event.plain_result("未找到该订阅，或订阅已停用")
            return

        if not sub.feed:
            yield event.plain_result("该订阅缺少 Feed 信息，无法执行测试")
            return

        target_session = sub.target_session
        if not target_session:
            user = sub.user or await User.get_or_create(sub.user_id)
            target_session = user.default_target_session
        if not target_session:
            yield event.plain_result(
                "该订阅尚未绑定推送目标，请先让订阅用户执行 /sub_bind 绑定目标"
            )
            return

        wf = await feed_get(
            sub.feed.link,
            timeout=self.config.timeout if self.config else None,
            proxy=self.config.proxy if self.config else "",
        )
        if wf.error:
            yield event.plain_result(f"测试抓取失败: {wf.error.error_name}")
            return

        if wf.rss_d is None or not wf.rss_d.entries:
            yield event.plain_result("测试抓取成功，但该源暂无可推送条目")
            return

        try:
            selected_entries, mode_label = self._select_test_entries(
                list(wf.rss_d.entries), granularity
            )
        except ValueError as ex:
            yield event.plain_result(str(ex))
            return

        await Notifier(
            feed=sub.feed,
            subs=[sub],
            entries=selected_entries,
            timeout_seconds=self.config.timeout if self.config else 30,
            proxy=self.config.proxy if self.config else "",
            download_media_before_send=(
                self.config.download_image_before_send if self.config else True
            ),
        ).notify_all()

        first_title = selected_entries[0].get("title") or "(无标题)"
        yield event.plain_result(
            f"已触发测试推送: 订阅ID={sub_id_int} -> {target_session}\n"
            f"粒度: {mode_label}，条目数: {len(selected_entries)}\n"
            f"首条: {first_title}"
        )

    @filter.command("unsub_all")
    async def cmd_unsub_all(self, event: AstrMessageEvent, scope: str = ""):
        """取消当前会话或所有订阅

        Usage: /unsub_all [global|yes]
        - 默认只清除当前会话的订阅
        - global / yes: 清除所有会话的订阅（需要管理员权限）
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        user_id = event.get_sender_id()
        current_session = event.unified_msg_origin
        scope_value = scope.strip().lower()
        is_global = scope_value in {"global", "yes"}

        # global 模式需要管理员权限
        if is_global and not event.is_admin():
            yield event.plain_result(
                "清除所有会话订阅需要管理员权限。\n"
                "说明: /unsub_all 默认仅删除当前会话；使用 /unsub_all global(或 yes) 删除所有会话。"
            )
            return

        subscriptions = await Sub.get_by_user(user_id)
        if not subscriptions:
            yield event.plain_result("您当前没有可删除的订阅")
            return

        # 根据范围筛选订阅
        if is_global:
            to_delete = subscriptions
            scope_desc = "所有会话"
        else:
            to_delete = [
                sub
                for sub in subscriptions
                if (sub.target_session or current_session) == current_session
            ]
            scope_desc = "当前会话"

        if not to_delete:
            yield event.plain_result(f"当前{scope_desc}没有订阅")
            return

        # 导出备份
        export_text = serialize_subscriptions_to_toml(
            user_id=str(user_id),
            subscriptions=to_delete,
        )

        temp_dir = Path(get_astrbot_temp_path())
        temp_dir.mkdir(parents=True, exist_ok=True)
        await self._cleanup_unsub_export_backups(temp_dir)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        export_filename = f"rsshub_subscriptions_{user_id}_{timestamp}.toml"
        export_path = temp_dir / export_filename

        try:
            export_path.write_text(export_text, encoding="utf-8")
            yield event.plain_result(
                f"已自动导出{scope_desc}订阅备份，请先保存该文件，再确认删除结果。"
            )
            yield event.chain_result(
                [File(name=export_filename, file=str(export_path))]
            )
        except OSError as ex:
            logger.error("Failed to export subscriptions before unsub_all: %s", ex)
            yield event.plain_result(f"备份导出失败，将继续删除订阅: {ex}")

        # 删除订阅
        deleted_count = 0
        for sub in to_delete:
            await Sub.delete(sub)
            deleted_count += 1

        yield event.plain_result(f"已取消{scope_desc}订阅，共删除 {deleted_count} 条")

    @filter.command("sub_import", alias={"import"})
    async def cmd_sub_import(self, event: AstrMessageEvent, import_path: str = ""):
        """Import subscriptions from TOML file.

        Usage: /sub_import [本地文件路径]
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        # 先尝试直接读取（用户可能直接附带文件或提供路径）
        content, read_err, should_wait_upload = await self._read_import_toml_content(
            event,
            import_path,
        )

        if content:
            # 用户已提供文件，直接处理
            async for result in self._process_import_toml(event, content):
                yield result
            return

        if read_err:
            yield event.plain_result(read_err)
            return

        if not should_wait_upload:
            yield event.plain_result("未检测到可导入的文件")
            return

        # 没有提供文件，设置导入会话状态，等待用户发送文件
        user_id = event.get_sender_id()
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

    async def _process_import_toml(self, event: AstrMessageEvent, content: str):
        """处理 TOML 内容并导入订阅。"""
        payload = parse_subscriptions_toml(content)
        if payload.errors and not payload.records:
            preview = "\n".join(payload.errors[:8])
            yield event.plain_result(f"导入失败，文件校验未通过:\n{preview}")
            return

        user_id = event.get_sender_id()
        # Ensure user exists before creating subscriptions for FK consistency.
        user = await User.get_or_create(user_id)
        imported = 0
        skipped = 0
        failed = 0
        details: list[str] = []
        seen_pairs: set[tuple[str, str]] = set()

        for index, record in enumerate(payload.records, start=1):
            options = dict(record.options)
            validated, option_err = self._validate_import_record_options(event, options)
            if option_err:
                failed += 1
                details.append(f"[{index}] 选项校验失败: {option_err}")
                continue

            target_session = str(
                validated.get("target_session") or event.unified_msg_origin
            )
            pair = (record.link, target_session)
            if pair in seen_pairs:
                skipped += 1
                details.append(f"[{index}] 文件内重复订阅，已跳过: {record.link}")
                continue
            seen_pairs.add(pair)

            exists = await Sub.get_by_user_and_link(
                user_id, record.link, target_session
            )
            if exists:
                skipped += 1
                continue

            feed = await Feed.get_or_create(
                link=record.link,
                title=(record.feed_title or record.link),
            )
            platform_name = str(
                validated.pop("platform_name", "") or event.platform.name
            )
            sub = await Sub.create(
                user_id=user.id,
                feed_id=feed.id,
                target_session=target_session,
                platform_name=platform_name,
            )

            validated.pop("target_session", None)
            if validated:
                updated = await Sub.update_options(sub.id, user_id, **validated)
                if not updated:
                    failed += 1
                    details.append(f"[{index}] 导入后写入选项失败: {record.link}")
                    continue

            imported += 1

        if payload.warnings:
            details.extend([f"警告: {item}" for item in payload.warnings[:3]])
        if payload.errors:
            details.extend([f"错误: {item}" for item in payload.errors[:5]])

        result = (
            f"订阅导入完成\n- 成功导入: {imported}\n- 跳过: {skipped}\n- 失败: {failed}"
        )
        if details:
            result += "\n\n详情:\n" + "\n".join(details[:12])

        yield event.plain_result(result)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_file_message(self, event: AstrMessageEvent):
        """监听文件消息以处理订阅导入.

        当用户发送文件时，自动尝试解析并导入订阅。
        需要满足以下条件才会处理：
        1. 在执行导入命令后5分钟内
        2. 发送者是发起导入命令的用户本人（会话隔离）
        文件大小限制：5MB
        """
        sender_id = event.get_sender_id()
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

            async for result in self._process_import_toml(event, content):
                yield result

        except OSError as e:
            logger.error(f"导入文件处理失败: {e}")
            yield event.plain_result(f"文件处理失败: {e}")
        finally:
            # 仅在本次消息包含文件并触发导入流程时，才清理导入会话
            if has_file:
                async with self._import_session_lock:
                    self._import_sessions.pop(session_key, None)

    @filter.command("sub_set")
    async def cmd_set_sub_option(
        self, event: AstrMessageEvent, sub_id: str = "", key: str = "", value: str = ""
    ):
        """设置单个订阅选项

        Usage: /sub_set <订阅ID> <选项名> <值>
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        if not sub_id or not key or not value:
            yield event.plain_result(
                "用法: /sub_set <订阅ID> <选项名> <值>\n"
                "可用选项: notify/send_mode/length_limit/link_preview/display_author/"
                "display_via/display_title/display_entry_tags/style/display_media/interval/title/tags/target_session"
            )
            return

        try:
            sub_id_int = int(sub_id)
        except ValueError:
            yield event.plain_result("订阅ID必须是数字")
            return

        option_key = key.strip().lower()
        if option_key == "target_session":
            parsed_value, parse_err = self._parse_target_session(event, value)
            if parse_err:
                yield event.plain_result(parse_err)
                return
        else:
            try:
                parsed_value = self._parse_option_value(option_key, value)
            except ValueError as ex:
                yield event.plain_result(str(ex))
                return

        user_id = event.get_sender_id()
        updated = await Sub.update_options(
            sub_id_int, user_id, **{option_key: parsed_value}
        )
        if not updated:
            yield event.plain_result("未找到该订阅，或无权限修改")
            return

        yield event.plain_result(
            f"订阅 [{sub_id_int}] 已更新: {option_key} = {parsed_value}"
        )

    @filter.command("sub_set_default")
    async def cmd_set_default_option(
        self, event: AstrMessageEvent, key: str = "", value: str = ""
    ):
        """设置当前用户默认订阅选项

        Usage: /sub_set_default <选项名> <值>
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        if not key or not value:
            yield event.plain_result(
                "用法: /sub_set_default <选项名> <值>\n"
                "可用选项: notify/send_mode/length_limit/link_preview/display_author/"
                "display_via/display_title/display_entry_tags/style/display_media/interval"
            )
            return

        option_key = key.strip().lower()
        if option_key not in USER_DEFAULT_OPTION_KEYS:
            yield event.plain_result("该选项不支持设置为默认值")
            return

        try:
            parsed_value = self._parse_option_value(option_key, value)
        except ValueError as ex:
            yield event.plain_result(str(ex))
            return

        user_id = event.get_sender_id()
        await User.update_defaults(user_id, **{option_key: parsed_value})
        yield event.plain_result(f"默认选项已更新: {option_key} = {parsed_value}")

    @filter.command("sub_bind")
    async def cmd_sub_bind(self, event: AstrMessageEvent, target: str = ""):
        """绑定当前用户默认推送目标

        Usage: /sub_bind <private|group|session>
        """
        target_session, target_err = self._parse_target_session(event, target)
        if target_err:
            yield event.plain_result(target_err)
            return

        if not target_session:
            yield event.plain_result(
                "请提供目标，用法: /sub_bind <private|group|session>"
            )
            return

        user_id = event.get_sender_id()
        await User.set_default_target(user_id, target_session)
        yield event.plain_result(f"已绑定默认推送目标: {target_session}")

    @filter.command("sub_session_default_set")
    async def cmd_sub_session_default_set(
        self,
        event: AstrMessageEvent,
        key: str = "",
        value: str = "",
    ):
        """Set session-level defaults for new subscriptions in this session.

        Usage: /sub_session_default_set <key> <value>
        """
        if not key or not value:
            yield event.plain_result(
                "用法: /sub_session_default_set <key> <value>\n"
                "可用 key: notify/send_mode/length_limit/link_preview/display_author/"
                "display_via/display_title/display_entry_tags/style/display_media/interval/title/tags"
            )
            return

        normalized_key = key.strip().lower()
        if normalized_key not in SESSION_DEFAULT_KEYS:
            yield event.plain_result("不支持的会话默认配置项")
            return

        try:
            if normalized_key in {"title", "tags"}:
                parsed_value = value.strip()
            else:
                parsed_value = self._parse_option_value(normalized_key, value)
        except ValueError as ex:
            yield event.plain_result(str(ex))
            return

        await self._set_session_default(
            event.unified_msg_origin, normalized_key, parsed_value
        )
        yield event.plain_result(
            f"会话默认配置已更新: {normalized_key} = {parsed_value}"
        )

    @filter.command("sub_session_default_get")
    async def cmd_sub_session_default_get(self, event: AstrMessageEvent):
        """Get session-level defaults in current session.

        Usage: /sub_session_default_get
        """
        defaults = await self._get_session_defaults(event.unified_msg_origin)
        if not defaults:
            yield event.plain_result("当前会话没有设置订阅默认项")
            return

        yield event.plain_result(
            "当前会话订阅默认项:\n" + json.dumps(defaults, ensure_ascii=False, indent=2)
        )

    @filter.command("rss_conf")
    async def cmd_rss_conf(
        self, event: AstrMessageEvent, key: str = "", value: str = ""
    ):
        """查看或设置插件配置。

        Usage: /rss_conf [key] [value]
        """
        if self.config is None:
            yield event.plain_result("插件配置尚未初始化")
            return

        normalized_key = key.strip().lower()

        if not normalized_key:
            yield event.plain_result(
                "当前 RSS 插件配置:\n"
                f"proxy = {self.config.proxy or '(empty)'}\n"
                f"rsshub_base_url = {self.config.rsshub_base_url}\n"
                f"default_interval = {self.config.default_interval}\n"
                f"minimal_interval = {self.config.minimal_interval}\n"
                f"timeout = {self.config.timeout}\n"
                "download_image_before_send = "
                f"{self.config.download_image_before_send}"
            )
            return

        if normalized_key not in PLUGIN_CONFIG_KEYS:
            yield event.plain_result(
                "不支持的配置项。可用项: "
                "proxy/rsshub_base_url/default_interval/minimal_interval/timeout/download_image_before_send"
            )
            return

        if not value.strip():
            yield event.plain_result(
                f"{normalized_key} = {self.config.get(normalized_key)}"
            )
            return

        try:
            parsed_value = self._parse_plugin_config_value(normalized_key, value)
        except ValueError as ex:
            yield event.plain_result(str(ex))
            return

        self.config.set(normalized_key, parsed_value)
        yield event.plain_result(f"插件配置已更新: {normalized_key} = {parsed_value}")

    @filter.command("rsshelp")
    async def cmd_help(self, event: AstrMessageEvent):
        """RSS插件帮助"""
        command_lines = [
            "订阅: /sub <RSS链接> [目标]",
            "取消订阅: /unsub <订阅ID>",
            "取消订阅: /unsub_all [global|yes]  # 默认当前会话，global/yes=所有会话(管理员)",
            "订阅列表: /sub_list [all]",
            "设置订阅选项: /sub_set <订阅ID> <选项> <值>",
            "设置默认选项: /sub_set_default <选项> <值>",
            "设置推送目标: /sub_bind <目标>",
            "会话默认配置: /sub_session_default_set <key> <value>",
            "查看会话默认配置: /sub_session_default_get",
            "插件配置: /rss_conf [key] [value]",
            "导入订阅: /sub_import [本地文件路径]",
        ]
        if event.is_admin():
            command_lines.append(
                "管理员测试推送: /sub_test <订阅ID> [latest|all|数量|count:数量|first:数量|newest:数量]"
            )
        command_lines.append("帮助: /rsshelp")

        help_text = (
            "RSS订阅插件帮助:\n\n"
            + "\n".join(command_lines)
            + "\n\n"
            + "常用选项:\n"
            + "- notify: 0/1\n"
            + "- send_mode: -1(仅链接)/0(自动)/2(直接消息)\n"
            + "- length_limit: 正整数，0表示不限制\n"
            + "- display_title/display_via/display_author: -1~1\n"
            + "- display_media: -1/0\n"
            + "- target_session: private/group/current 或完整 session\n\n"
            + "插件配置项:\n"
            + "- proxy/rsshub_base_url/default_interval/minimal_interval/timeout/download_image_before_send\n\n"
            + "会话级默认配置项:\n"
            + "- notify/send_mode/length_limit/link_preview/display_author/display_via/display_title/display_entry_tags/style/display_media/interval/title/tags\n\n"
            + "目标绑定:\n"
            + "- /sub <RSS链接> [目标]  # 目标可选: private/group/current/session\n"
            + "- /sub_bind <目标>      # 设置当前用户默认推送目标\n\n"
            + "支持的平台: QQ、Telegram、微信、钉钉、Slack、Discord等"
        )
        yield event.plain_result(help_text)
