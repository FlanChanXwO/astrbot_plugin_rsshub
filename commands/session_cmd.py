"""会话默认设置相关命令逻辑"""

import json
from collections.abc import Callable


async def set_session_default(
    *,
    session_id: str,
    key: str,
    value: str,
    session_default_keys: set,
    parse_option_value_fn: Callable[[str, str], int | str],
    set_session_defaults_fn: Callable[[str, str, int | str], None],
) -> dict:
    """设置会话默认选项

    Returns:
        {"success": bool, "message": str, "error": str}
    """
    if not key or not value:
        return {
            "success": False,
            "error": (
                "用法: /sub_session_default_set <key> <value>\n"
                "可用 key: notify/send_mode/length_limit/link_preview/display_author/"
                "display_via/display_title/display_entry_tags/style/display_media/"
                "interval/title/tags"
            ),
        }

    normalized_key = key.strip().lower()
    if normalized_key not in session_default_keys:
        return {"success": False, "error": "不支持的会话默认配置项"}

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


async def get_session_defaults(
    *,
    session_id: str,
    get_session_defaults_fn: Callable[[str], dict],
) -> dict:
    """获取会话默认选项

    Returns:
        {"success": bool, "message": str, "defaults": dict}
    """
    defaults = await get_session_defaults_fn(session_id)
    if not defaults:
        return {
            "success": True,
            "message": "当前会话没有设置订阅默认项",
            "defaults": {},
        }

    return {
        "success": True,
        "message": "当前会话订阅默认项:\n"
        + json.dumps(defaults, ensure_ascii=False, indent=2),
        "defaults": defaults,
    }
