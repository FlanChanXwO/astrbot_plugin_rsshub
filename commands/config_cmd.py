"""配置相关命令逻辑"""

from collections.abc import Callable

from ..utils.config_parsers import field_loader, parse_bool_value
from .types import CommandResult


async def set_user_option(
    *,
    key: str,
    value: str,
    user_id: str,
    parse_option_value_fn: Callable[[str, str], int | str],
) -> CommandResult:
    """设置用户配置选项

    Args:
        key: 配置项名称
        value: 配置值
        user_id: 用户ID
        parse_option_value_fn: 选项值解析函数

    Returns:
        命令结果
    """
    from ..db import User

    if not key or not value:
        return {
            "success": False,
            "error": (
                "用法: /sub_set_user <选项名> <值>\n使用 /sub_get_user 查看可用选项"
            ),
        }

    option_key = key.strip().lower()

    # 特殊处理 use_user_config 布尔字段
    if option_key == "use_user_config":
        try:
            parsed_value = parse_bool_value(value)
        except ValueError as ex:
            return {"success": False, "error": str(ex)}
    else:
        # 获取字段定义以验证
        field_def = field_loader.get_user_field(option_key)
        if field_def is None:
            return {"success": False, "error": f"未知选项: {option_key}"}

        # 解析选项值
        try:
            parsed_value = parse_option_value_fn(option_key, value)
        except ValueError as ex:
            return {"success": False, "error": str(ex)}

    # 获取当前用户以显示旧值
    user = await User.get_or_create(user_id)
    old_value = getattr(user, option_key, None)

    # 更新用户配置
    await User.update_defaults(user_id, **{option_key: parsed_value})

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
        "message": f"用户配置已更新:\n{option_key}: {fmt(old_value)} → {fmt(parsed_value)}",
    }


async def get_user_option(
    *,
    key: str | None,
    user_id: str,
) -> CommandResult:
    """获取用户配置选项

    Args:
        key: 配置项名称（None 表示获取所有）
        user_id: 用户ID

    Returns:
        命令结果
    """
    from ..db import User

    user = await User.get_or_create(user_id)

    if key:
        # 获取单个配置项
        option_key = key.strip().lower()
        field_def = field_loader.get_user_field(option_key)

        if field_def is None:
            return {"success": False, "error": f"未知选项: {option_key}"}

        current_value = getattr(user, option_key, None)
        info = field_loader.format_field_info(option_key, field_def, current_value)

        # 添加设置说明
        info += f"\n\n使用 /sub_set_user {option_key} <值> 修改配置"
        if option_key == "use_user_config":
            info += "\n注意: 设置为 true 后将使用用户独立配置，不再继承全局配置"

        return {"success": True, "message": info}
    else:
        # 获取所有配置项
        all_fields = field_loader.get_all_user_fields()
        lines = [f"用户配置 (使用独立配置: {user.use_user_config})\n"]

        for field_name, field_def in all_fields.items():
            current_value = getattr(user, field_name, None)
            lines.append(
                f"{field_name} = {current_value if current_value is not None else field_def.get('default', 'null')}"
            )
            lines.append(f"  {field_def.get('description', '')}")

        lines.append("\n使用 /sub_get_user <选项名> 查看详细信息")
        lines.append("使用 /sub_set_user <选项名> <值> 修改配置")

        return {"success": True, "message": "\n".join(lines)}
