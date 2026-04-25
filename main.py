"""
AstrBot RSS订阅插件
基于 RSS-to-Telegram-Bot 项目移植，适配 AstrBot 多平台消息推送
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star

from .api import RSSHubRadarAPI, close_shared_session
from .commands import (
    IMPORT_MAX_FILE_SIZE_BYTES,
    batch_activate_subs,
    batch_deactivate_subs,
    batch_subscribe_feeds,
    batch_unsubscribe_feeds,
    export_subscriptions,
    get_session,
    get_user_option,
    import_subscriptions,
    list_subscriptions,
    read_import_toml_content,
    read_uploaded_toml_content,
    set_session,
    set_subscription_option,
    set_user_option,
    subscribe_feed,
    test_subscription,
    unsubscribe_all_feeds,
    unsubscribe_feed,
)
from .config import (
    SESSION_DEFAULT_KEYS,
    SESSION_DEFAULT_KV_PREFIX,
    SUB_OPTION_CASTERS,
    RuntimeConfig,
    cfg,
)
from .db import Sub, User, close_db, init_db
from .monitor import Monitor
from .notifier.senders import set_bot_self_id_provider
from .utils.ffmpeg_helper import FFmpegTool
from .utils.log_utils import logger
from .web import RSSHubWebUI, resolve_webui_config


class RSSHubPlugin(Star):
    """AstrBot RSS订阅插件主类"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.astrbot_config = config
        self.config: RuntimeConfig | None = None
        self.monitor: Monitor | None = None
        self._scheduler_task: asyncio.Task | None = None
        self._webui: RSSHubWebUI | None = None
        self._rsshub_radar_api: RSSHubRadarAPI | None = None
        self._rsshub_radar_api_settings: tuple[int, str] | None = None
        self._import_session_lock = asyncio.Lock()
        self._import_sessions: dict[tuple[str, str], float] = {}
        self._import_session_timeout = 300  # 5 分钟超时
        self._unsub_export_retention_seconds = 24 * 60 * 60

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
        """解析命令目标参数，返回 (session, error)。

        支持的参数：
        - 空/不传：使用当前会话
        - current/here/this：显式使用当前会话
        - 完整 session 格式：platform:MessageType:id（用于跨平台推送）
        """
        raw = target.strip()
        if not raw:
            return event.unified_msg_origin, None

        normalized = raw.lower()

        if normalized in {"here", "current", "this"}:
            return event.unified_msg_origin, None

        # 支持完整的 session 格式：platform:MessageType:id
        if raw.count(":") >= 2:
            return raw, None

        return (
            None,
            "目标参数无效。可选：current/here/this 或完整 session 格式 (platform:MessageType:id)",
        )

    @staticmethod
    def _parse_option_value(key: str, value: str):
        """解析命令中的选项值并做基础校验"""
        from .utils.config_parsers import parse_bool_value

        caster = SUB_OPTION_CASTERS.get(key)
        if caster is None:
            raise ValueError(f"不支持的选项: {key}")
        if caster is str:
            return value.strip()

        # 尝试解析为布尔值（支持 true/false/yes/no/1/0 等）
        try:
            return parse_bool_value(value)
        except ValueError:
            pass  # 不是布尔值，继续尝试数字

        try:
            parsed = caster(value)
        except ValueError as ex:
            raise ValueError(f"选项 {key} 需要数字值或布尔值") from ex
        if key == "interval" and cfg is not None:
            minimal = cfg.minimal_interval
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
                "请检查订阅配置或重新订阅。"
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
                    return {}, f"target_session 无效：{parse_err}"
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

    def _get_bot_self_id(self, platform_id: str) -> str:
        """根据 platform_id 获取对应平台适配器的 bot self_id

        Raises:
            RuntimeError: 当无法获取有效的 bot_self_id 时抛出异常
        """
        for platform in self.context.platform_manager.platform_insts:
            meta = platform.meta()
            if meta and meta.id == platform_id:
                if platform.bot_self_id:
                    return str(platform.bot_self_id)
                if platform.bot.self_id:
                    return str(platform.bot.self_id)
                raise RuntimeError(
                    f"平台 {platform_id} 的 bot_self_id 不可用，"
                    "请检查平台适配器配置是否正确"
                )

        raise RuntimeError(
            f"未找到平台 {platform_id} 的适配器实例，请检查平台配置是否正确"
        )

    async def initialize(self):
        """插件初始化"""
        logger.info("RSS 订阅插件初始化...")

        self.config = RuntimeConfig(
            plugin_name=self.name,
            astrbot_config=dict(self.astrbot_config) if self.astrbot_config else None,
        )

        # 初始化 ConfigProxy 单例
        await cfg.init(self.config)
        logger.info(f"RSS 插件配置加载完成，数据目录：{self.config.data_dir}")

        if cfg.ffmpeg.video_transcode:
            ffmpeg_path = FFmpegTool.ensure_ffmpeg_ready(auto_install=True)
            if ffmpeg_path:
                logger.info("RSS插件 FFmpeg 已就绪: %s", ffmpeg_path)
            else:
                logger.warning("RSS插件 FFmpeg 未就绪，视频将尝试原始格式发送")

        await init_db(cfg.db_path)
        logger.info("RSS插件数据库初始化完成")

        self.monitor = Monitor()
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

    @filter.command("sub_state", alias={"订阅状态"})
    async def cmd_sub_state(self, event: AstrMessageEvent, sub_id: str = ""):
        """订阅状态管理命令

        Usage:
            /sub_state <订阅ID> on      # 启用推送
            /sub_state <订阅ID> off     # 禁用推送
        """
        if not sub_id:
            yield event.plain_result(
                "用法: /sub_state <订阅ID> on/off\n"
                "支持: on/off, true/false, yes/no, y/n, 1/0, 开启/关闭"
            )
            return
        # 解析 sub_id 和 state
        parts = sub_id.split()
        if len(parts) >= 2:
            actual_sub_id = parts[0]
            state = parts[1].lower()
        else:
            yield event.plain_result(
                "用法: /sub_state <订阅ID> on/off\n示例: /sub_state 123 on"
            )
            return

        if state in ("on", "true", "yes", "y", "1", "开启"):
            enable = True
        elif state in ("off", "false", "no", "n", "0", "关闭"):
            enable = False
        else:
            yield event.plain_result(
                f"不支持的状态值: {state}\n"
                "请使用: on/off, true/false, yes/no, y/n, 1/0, 开启/关闭"
            )
            return

        try:
            sub_id_int = int(actual_sub_id)
        except ValueError:
            yield event.plain_result("订阅 ID 必须是数字")
            return

        from sqlmodel import select

        from .db import Sub, get_session

        async with get_session() as session:
            stmt = select(Sub).where(
                Sub.id == sub_id_int, Sub.user_id == event.get_sender_id()
            )
            result = await session.execute(stmt)
            sub = result.scalar_one_or_none()

            if not sub:
                yield event.plain_result("未找到该订阅或无权限")
                return

            sub.state = 1 if enable else 0
            session.add(sub)
            await session.commit()

            action = "启用" if enable else "禁用"
            yield event.plain_result(f"已{action}订阅 (ID: {sub_id_int}) 的推送")

    @filter.command("sub", alias={"订阅"})
    async def cmd_sub(self, event: AstrMessageEvent, urls: str = "", target: str = ""):
        """订阅 RSS 源

        Usage:
            /sub https://example.com/rss.xml
            /sub https://rss1.xml https://rss2.xml https://rss3.xml
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        # 解析URL（支持空格分隔的多个URL）
        url_list = [u.strip() for u in urls.split() if u.strip()]

        # 过滤有效的 RSS URL（以 http 或 https 开头）
        valid_urls = [u for u in url_list if u.startswith(("http://", "https://"))]

        if not valid_urls:
            yield event.plain_result(
                "请提供至少一个有效的 RSS 链接（需以 http 或 https 开头）\n"
                "使用 /sub_state \u003cID\u003e on/off 控制订阅推送启停"
            )
            return

        # 单个链接使用原有方式
        if len(valid_urls) == 1:
            result = await subscribe_feed(
                url=valid_urls[0],
                target=target,
                user_id=event.get_sender_id(),
                platform_name=event.platform_meta.name,
                timeout=cfg.timeout if cfg else 30,
                proxy=cfg.proxy if cfg else "",
                session_defaults=await self._get_session_defaults(
                    event.unified_msg_origin
                ),
                parse_target_fn=lambda t: self._parse_target_session(event, t),
            )
            if result["success"]:
                yield event.plain_result(result["message"])
            else:
                yield event.plain_result(result["error"])
        else:
            # 多个链接使用批量订阅
            result = await batch_subscribe_feeds(
                urls=valid_urls,
                target=target,
                user_id=event.get_sender_id(),
                platform_name=event.platform_meta.name,
                timeout=cfg.timeout if cfg else 30,
                proxy=cfg.proxy if cfg else "",
                session_defaults=await self._get_session_defaults(
                    event.unified_msg_origin
                ),
                parse_target_fn=lambda t: self._parse_target_session(event, t),
            )

            # 构建批量结果消息
            messages = []
            if result.get("successful"):
                messages.append(f"✅ 成功订阅 {len(result['successful'])} 个源：")
                for item in result["successful"]:
                    messages.append(
                        f"  • {item.get('title', '未知')} (ID: {item.get('sub_id', 0)})"
                    )

            if result.get("failed"):
                messages.append(f"\n❌ 失败 {len(result['failed'])} 个：")
                for item in result["failed"]:
                    messages.append(
                        f"  • {item.get('url', '未知')} - {item.get('reason', '未知错误')}"
                    )

            if messages:
                yield event.plain_result("\n".join(messages))

    @filter.command("unsub", alias={"取消订阅"})
    async def cmd_unsub(self, event: AstrMessageEvent, targets: str = ""):
        """取消订阅

        Usage:
            /unsub <订阅 ID>
            /unsub 1 2 3 4
            /unsub https://example.com/rss.xml
            /unsub https://rss1.xml https://rss2.xml
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        # 解析目标（支持空格分隔的多个值）
        target_list = [t.strip() for t in targets.split() if t.strip()]

        if not target_list:
            yield event.plain_result("请提供至少一个订阅 ID 或 URL")
            return

        # 单个目标使用原有方式
        if len(target_list) == 1:
            target = target_list[0]
            # 判断是 ID 还是 URL
            if target.isdigit():
                result = await unsubscribe_feed(
                    sub_id=target,
                    user_id=event.get_sender_id(),
                    current_session=event.unified_msg_origin,
                    is_admin=event.is_admin(),
                    platform_name=event.platform_meta.name,
                )
            else:
                # 按 URL 取消
                result = await batch_unsubscribe_feeds(
                    targets=[target],
                    user_id=event.get_sender_id(),
                    current_session=event.unified_msg_origin,
                    is_admin=event.is_admin(),
                    platform_name=event.platform_meta.name,
                )

            if result["success"]:
                yield event.plain_result(result["message"])
            else:
                yield event.plain_result(result["error"])
        else:
            # 多个目标使用批量取消
            result = await batch_unsubscribe_feeds(
                targets=target_list,
                user_id=event.get_sender_id(),
                current_session=event.unified_msg_origin,
                is_admin=event.is_admin(),
                platform_name=event.platform_meta.name,
            )

            # 构建批量结果消息
            messages = []
            if result.get("successful_count", 0) > 0:
                messages.append(f"✅ 成功取消 {result['successful_count']} 个订阅")

            if result.get("failed"):
                messages.append(f"\n❌ 失败 {len(result['failed'])} 个：")
                for item in result["failed"]:
                    messages.append(
                        f"  • {item.get('target', '未知')} - {item.get('reason', '未知错误')}"
                    )

            if messages:
                yield event.plain_result("\n".join(messages))

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
        target: str = "",
        start: str = "1",
        end: str = "",
    ):
        """管理员手动触发测试推送

        支持通过订阅ID或URL进行测试推送。

        Usage:
            /sub_test <订阅ID> [起始编号] [结束编号]
            /sub_test <URL> [起始编号] [结束编号]

        示例:
            /sub_test 5              # 测试订阅ID=5，推送条目1（最新）
            /sub_test 5 1 3          # 测试订阅ID=5，推送条目1,2,3
            /sub_test https://xxx 2  # 测试URL，只推送条目2
            /sub_test https://xxx 1 5 # 测试URL，推送条目1-5

        说明:
            - 条目编号从1开始，1表示最新发布的条目
            - 只提供1个编号：推送该编号的单个条目
            - 提供2个编号：推送从起始到结束的所有条目
        """
        if not target:
            yield event.plain_result(
                "请提供订阅ID或RSS链接\n"
                "用法: /sub_test <订阅ID或URL> [起始编号] [结束编号]\n"
                "示例: /sub_test 5 1 3  # 推送订阅ID=5的条目1-3"
            )
            return

        # 解析条目编号
        try:
            start_index = int(start) if start else 1
        except ValueError:
            yield event.plain_result("起始条目编号必须是数字")
            return

        end_index: int | None = None
        if end:
            try:
                end_index = int(end)
            except ValueError:
                yield event.plain_result("结束条目编号必须是数字")
                return

        result = await test_subscription(
            target=target,
            start_index=start_index,
            end_index=end_index,
            target_session=event.unified_msg_origin,
            platform_name=event.platform_meta.name,
            user_id=event.get_sender_id(),
            timeout=cfg.timeout if cfg else 30,
            proxy=cfg.proxy if cfg else "",
            download_media_before_send=(
                cfg.download_media_before_send if cfg else True
            ),
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
        content, read_err, should_wait_upload = await read_import_toml_content(
            event,
            import_path,
            cfg.local_imports_dir if cfg else Path("."),
            event.is_admin(),
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
            content, read_err, has_file = await read_uploaded_toml_content(
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

    @filter.command("sub_set_user", alias={"设置用户"})
    async def cmd_sub_set_user(
        self, event: AstrMessageEvent, key: str = "", value: str = ""
    ):
        """设置当前用户配置选项

        Usage: /sub_set_user <选项名> <值>

        布尔值支持: true/false, yes/no, y/n, 1/0, on/off, enable/disable
        """
        async for notice in self._emit_binding_notice_if_needed(event):
            yield notice

        if not key or not value:
            # 显示帮助信息
            result = await get_user_option(
                key=None,
                user_id=event.get_sender_id(),
            )
            yield event.plain_result(result["message"])
            return

        result = await set_user_option(
            key=key,
            value=value,
            user_id=event.get_sender_id(),
            parse_option_value_fn=self._parse_option_value,
        )

        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("sub_get_user", alias={"获取用户"})
    async def cmd_sub_get_user(self, event: AstrMessageEvent, key: str = ""):
        """获取当前用户配置选项

        Usage:
            /sub_get_user           # 获取所有配置
            /sub_get_user <选项名>   # 获取指定配置
        """
        result = await get_user_option(
            key=key if key else None,
            user_id=event.get_sender_id(),
        )
        yield event.plain_result(result["message"])

    @filter.command("sub_set_session", alias={"设置会话"})
    async def cmd_sub_set_session(
        self,
        event: AstrMessageEvent,
        key: str = "",
        value: str = "",
    ):
        """设置会话级默认选项

        Usage: /sub_set_session <key> <value>
        """
        if not key or not value:
            # 显示帮助信息
            result = await get_session(
                session_id=event.unified_msg_origin,
                key=None,
                get_session_defaults_fn=self._get_session_defaults,
            )
            yield event.plain_result(result["message"])
            return

        result = await set_session(
            session_id=event.unified_msg_origin,
            key=key,
            value=value,
            parse_option_value_fn=self._parse_option_value,
            set_session_defaults_fn=self._set_session_default,
        )

        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["error"])

    @filter.command("sub_get_session", alias={"获取会话"})
    async def cmd_sub_get_session(self, event: AstrMessageEvent, key: str = ""):
        """获取会话级默认选项

        Usage:
            /sub_get_session          # 获取所有
            /sub_get_session <key>    # 获取指定选项
        """
        result = await get_session(
            session_id=event.unified_msg_origin,
            key=key if key else None,
            get_session_defaults_fn=self._get_session_defaults,
        )
        yield event.plain_result(result["message"])

    @filter.command("activate_subs", alias={"enable_subs", "启用全部订阅"})
    async def cmd_activate_subs(self, event: AstrMessageEvent):
        """启用当前会话中的所有订阅

        Usage: /activate_subs
        """
        result = await batch_activate_subs(
            user_id=event.get_sender_id(),
            current_session=event.unified_msg_origin,
        )
        yield event.plain_result(result["message"])

    @filter.command("deactivate_subs", alias={"disable_subs", "禁用全部订阅"})
    async def cmd_deactivate_subs(self, event: AstrMessageEvent):
        """禁用当前会话中的所有订阅

        Usage: /deactivate_subs
        """
        result = await batch_deactivate_subs(
            user_id=event.get_sender_id(),
            current_session=event.unified_msg_origin,
        )
        yield event.plain_result(result["message"])
