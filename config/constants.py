"""RSSHub Plugin Constants

集中管理插件常量，便于维护和类型检查。
"""

# 订阅选项类型映射
SUB_OPTION_CASTERS: dict[str, type] = {
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
    "use_sub_config": int,
    "translate": int,
    "translate_target_lang": str,
}

# 用户默认选项键集合
USER_DEFAULT_OPTION_KEYS: set[str] = {
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

# 插件配置键集合
PLUGIN_CONFIG_KEYS: set[str] = {
    "proxy",
    "default_interval",
    "minimal_interval",
    "timeout",
    "download_media_before_send",
    "download_media_timeout",
    "ffmpeg_video_transcode",
    "ffmpeg_video_transcode_timeout",
    "ffmpeg_gif_transcode",
    "ffmpeg_gif_transcode_timeout",
    "history_entry_limit",
    "video_transcode",
    "video_transcode_timeout",
    "gif_transcode",
    "gif_transcode_timeout",
    "rsshub_base_url",
    "failed_queue_capacity",
    "failed_queue_max_retries",
    "sender_strategy_telegram",
    "sender_strategy_aiocqhttp",
    "sender_strategy_weixin_oc",
    "deduplicate_multi_bot",
    "bootstrap_skip_history",
    "debug_payload",
}

# 会话默认前缀
SESSION_DEFAULT_KV_PREFIX: str = "session_defaults::"

# 会话默认键集合
SESSION_DEFAULT_KEYS: set[str] = {
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
