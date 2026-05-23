"""导入导出命令处理器（纯函数）"""

from __future__ import annotations

from pathlib import Path

from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import File

from ...infrastructure.utils import get_plugin_export_dir
from ...shared.constants import ONEBOT_PLATFORMS

_INLINE_EXPORT_LIMIT = 5000


async def handle_export(event: AstrMessageEvent, scope: str, deps: dict) -> dict:
    """导出订阅为 TOML"""
    user_id = event.get_sender_id()
    is_admin = event.is_admin()
    scope_value = (scope or "").strip().lower()

    if scope_value and scope_value != "all":
        return {
            "plain": "参数无效。用法: /sub_export [all]\n不带参数表示导出当前会话；all 表示导出所有订阅（管理员）。"
        }

    result = await deps["export_cmd"].execute(
        user_id=user_id,
        is_admin=is_admin,
        scope=scope_value,
        current_session=event.unified_msg_origin,
    )

    if result.data and result.data.content:
        temp_dir = _get_export_dir()
        filename = result.data.filename
        file_path = temp_dir / filename
        file_path.write_text(result.data.content, encoding="utf-8")

        platform = _get_platform_name(event)
        if platform in ONEBOT_PLATFORMS and not _has_callback_file_service():
            return {
                "plain": _build_inline_export_message(
                    result.message,
                    result.data.content,
                    file_path,
                )
            }

        return {
            "chain": [File(name=filename, file=str(file_path.resolve()))],
            "plain": result.message,
        }
    return {"plain": result.message}


async def handle_import(event: AstrMessageEvent, content: str, deps: dict) -> dict:
    """从 TOML 导入订阅"""
    args = (content or "").strip()

    if not args:
        return {
            "plain": "请在 5 分钟内上传 TOML 订阅文件，或使用 /sub_import <文件路径>",
            "wait_import": True,
        }

    if "\n" in args or "[[subscriptions]]" in args:
        toml_content = args
    else:
        path = Path(args)
        if not path.exists() or not path.is_file():
            return {"plain": f"导入失败: 文件不存在 {args}"}
        toml_content = path.read_text(encoding="utf-8")

    user_id = event.get_sender_id()
    target_session = event.unified_msg_origin
    platform_name = event.get_platform_name()
    result = await deps["import_cmd"].execute(
        content=toml_content,
        user_id=user_id,
        target_session=target_session,
        platform_name=platform_name,
    )
    return {"plain": result.message}


def _get_export_dir() -> Path:
    """Use plugin data dir for export files to avoid /tmp cleanup races."""
    export_dir = get_plugin_export_dir()
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def _get_platform_name(event: AstrMessageEvent) -> str:
    try:
        return str(event.get_platform_name() or "").strip().lower()
    except Exception:
        return ""


def _build_inline_export_message(message: str, content: str, file_path: Path) -> str:
    """Fallback for OneBot when callback file service is unavailable."""
    tip = (
        "检测到 OneBot 平台且未配置 callback_api_base，"
        "已回退为内联 TOML。若需直接发送文件，请在 AstrBot 配置 callback_api_base。"
    )
    if len(content) <= _INLINE_EXPORT_LIMIT:
        return (
            f"{message}\n{tip}\n\n```toml\n{content}\n```\n\n"
            f"导出文件已保存到宿主机: {file_path.resolve()}"
        )
    snippet = content[:_INLINE_EXPORT_LIMIT]
    return (
        f"{message}\n{tip}\n\n导出内容较长，以下仅展示前 {_INLINE_EXPORT_LIMIT} 字符:\n"
        f"```toml\n{snippet}\n```\n\n完整导出文件已保存到宿主机: {file_path.resolve()}"
    )


def _has_callback_file_service() -> bool:
    try:
        from astrbot.core import astrbot_config

        callback_api_base = str(astrbot_config.get("callback_api_base", "")).strip()
        return bool(callback_api_base)
    except Exception:
        return False
