"""会话默认设置相关命令逻辑"""

from collections.abc import Awaitable, Callable

from ..utils.config_parsers import field_loader
from .types import CommandResult


async def set_session(
    *,
    session_id: str,
    key: str,
    value: str,
    parse_option_value_fn: Callable[[str, str], int | str],
    set_session_defaults_fn: Callable[[str, str, int | str], Awaitable[None]],
) -> CommandResult:
    """设置会话默认选项

    Args:
        session_id: 会话ID
        key: 配置项名称
        value: 配置值
        parse_option_value_fn: 选项值解析函数
        set_session_defaults_fn: 设置会话默认值的函数

    Returns:
        命令结果
    """
    if not key or not value:
        return {
            "success": False,
            "error": (
                "用法: /sub_set_session <选项名> <值>\n"
                "使用 /sub_get_session 查看可用选项"
            ),
        }

    normalized_key = key.strip().lower()

    # 获取字段定义以验证
    field_def = field_loader.get_session_field(normalized_key)
    if field_def is None:
        return {"success": False, "error": f"未知选项: {normalized_key}"}

    try:
        if normalized_key in {"title", "tags"}:
            parsed_value = value.strip()
        else:
            parsed_value = parse_option_value_fn(normalized_key, value)
    except ValueError as ex:
        return {"success": False, "error": str(ex)}

    await set_session_defaults_fn(session_id, normalized_key, parsed_value)
    return {
        "success": True,
        "message": f"会话默认配置已更新: {normalized_key} = {parsed_value}",
    }


async def get_session(
    *,
    session_id: str,
    key: str | None,
    get_session_defaults_fn: Callable[[str], dict],
) -> CommandResult:
    """获取会话默认选项

    Args:
        session_id: 会话ID
        key: 配置项名称（None 表示获取所有）
        get_session_defaults_fn: 获取会话默认值的函数

    Returns:
        命令结果
    """
    defaults = await get_session_defaults_fn(session_id)

    if key:
        # 获取单个配置项
        option_key = key.strip().lower()
        field_def = field_loader.get_session_field(option_key)

        if field_def is None:
            return {"success": False, "error": f"未知选项: {option_key}"}

        current_value = defaults.get(option_key)
        info = field_loader.format_field_info(option_key, field_def, current_value)

        # 添加设置说明
        info += f"\n\n使用 /sub_set_session {option_key} <值> 修改配置"

        return {"success": True, "message": info}
    else:
        # 获取所有配置项
        all_fields = field_loader.get_all_session_fields()
        lines = ["会话默认配置\n"]

        for field_name, field_def in all_fields.items():
            current_value = defaults.get(field_name)
            default_label = (
                current_value
                if current_value is not None
                else field_def.get("default", "null")
            )
            lines.append(f"{field_name} = {default_label}")
            lines.append(f"  {field_def.get('description', '')}")

        if not defaults:
            lines.append("\n当前会话未设置任何默认值")
            lines.append("新订阅将继承用户/全局配置")

        lines.append("\n使用 /sub_get_session <选项名> 查看详细信息")
        lines.append("使用 /sub_set_session <选项名> <值> 修改配置")

        return {"success": True, "message": "\n".join(lines)}
