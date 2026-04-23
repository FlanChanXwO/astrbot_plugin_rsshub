"""配置相关命令逻辑"""

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..utils.config import PluginConfig


def get_plugin_config(config: "PluginConfig") -> str:
    """获取插件配置文本

    Returns:
        配置信息字符串
    """
    strategies = config.sender_strategies if config else {}
    shared_data = config.platform_shared_data if config else {}

    return (
        "当前 RSS 插件配置:\n"
        f"proxy = {config.proxy or '(empty)'}\n"
        f"rsshub_base_url = {config.rsshub_base_url}\n"
        f"default_interval = {config.default_interval}\n"
        f"minimal_interval = {config.minimal_interval}\n"
        f"timeout = {config.timeout}\n"
        f"failed_queue_capacity = {config.failed_queue_capacity}\n"
        f"failed_queue_max_retries = {config.failed_queue_max_retries}\n"
        f"deduplicate_multi_bot = {config.deduplicate_multi_bot}\n"
        f"bootstrap_skip_history = {config.bootstrap_skip_history}\n"
        f"debug_payload = {config.debug_payload}\n"
        f"history_entry_limit = {config.history_entry_limit}\n"
        f"download_image_before_send = {config.download_image_before_send}\n"
        "ffmpeg:\n"
        f"  video_transcode = {config.ffmpeg.get('video_transcode', False)}\n"
        f"  video_transcode_timeout = {config.ffmpeg.get('video_transcode_timeout', 120)}\n"
        f"  gif_transcode = {config.ffmpeg.get('gif_transcode', False)}\n"
        f"  gif_transcode_timeout = {config.ffmpeg.get('gif_transcode_timeout', 60)}\n"
        "sender_strategies:\n"
        f"  telegram = {strategies.get('telegram', True)}\n"
        f"  aiocqhttp = {strategies.get('aiocqhttp', True)}\n"
        f"  weixin_oc = {strategies.get('weixin_oc', True)}\n"
        "platform_shared_data:\n"
        f"  aiocqhttp = {shared_data.get('aiocqhttp', False)}"
    )


def get_single_config(key: str, config: "PluginConfig") -> str:
    """获取单个配置项"""
    value = config.get(key)
    return f"{key} = {value}"


async def set_plugin_config(
    *,
    key: str,
    value: str,
    config: "PluginConfig",
    parse_plugin_config_value_fn: Callable[[str, str], int | str | bool],
) -> dict:
    """设置插件配置

    Returns:
        {"success": bool, "message": str, "error": str}
    """
    from ..config import PLUGIN_CONFIG_KEYS

    normalized_key = key.strip().lower()

    if normalized_key not in PLUGIN_CONFIG_KEYS:
        return {
            "success": False,
            "error": (
                "不支持的配置项。可用项: "
                "proxy/rsshub_base_url/default_interval/minimal_interval/timeout/"
                "download_image_before_send/bootstrap_skip_history/"
                "history_entry_limit/"
                "ffmpeg_video_transcode/ffmpeg_video_transcode_timeout/"
                "ffmpeg_gif_transcode/ffmpeg_gif_transcode_timeout/"
                "failed_queue_capacity/failed_queue_max_retries/"
                "debug_payload/"
                "sender_strategy_telegram/sender_strategy_aiocqhttp/"
                "sender_strategy_weixin_oc/"
                "deduplicate_multi_bot/platform_shared_data_aiocqhttp"
            ),
        }

    if not value.strip():
        return {"success": True, "message": get_single_config(normalized_key, config)}

    try:
        parsed_value = parse_plugin_config_value_fn(normalized_key, value)
    except ValueError as ex:
        return {"success": False, "error": str(ex)}

    config.set(normalized_key, parsed_value)
    return {
        "success": True,
        "message": f"插件配置已更新: {normalized_key} = {parsed_value}",
    }


async def set_user_default_option(
    *,
    key: str,
    value: str,
    user_id: str,
    parse_option_value_fn: Callable[[str, str], int | str],
) -> dict:
    """设置用户默认选项

    Returns:
        {"success": bool, "message": str, "error": str}
    """
    from ..config import USER_DEFAULT_OPTION_KEYS
    from ..db import User

    if not key or not value:
        return {
            "success": False,
            "error": (
                "用法: /sub_set_default <选项名> <值>\n"
                "可用选项: notify/send_mode/length_limit/link_preview/display_author/"
                "display_via/display_title/display_entry_tags/style/display_media/interval"
            ),
        }

    option_key = key.strip().lower()
    if option_key not in USER_DEFAULT_OPTION_KEYS:
        return {"success": False, "error": "该选项不支持设置为默认值"}

    try:
        parsed_value = parse_option_value_fn(option_key, value)
    except ValueError as ex:
        return {"success": False, "error": str(ex)}

    await User.update_defaults(user_id, **{option_key: parsed_value})
    return {
        "success": True,
        "message": f"默认选项已更新: {option_key} = {parsed_value}",
    }
