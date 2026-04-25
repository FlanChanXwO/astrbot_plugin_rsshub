"""帮助命令逻辑"""


def get_help_text(is_admin: bool) -> str:
    """获取帮助文本

    Returns:
        帮助文本字符串
    """
    command_lines = [
        "订阅: /sub <RSS 链接>",
        "取消订阅: /unsub <订阅 ID>",
        "取消全部订阅: /unsub_all [global]  # 默认当前会话，global=所有会话 (管理员)",
        "订阅列表: /sub_list [all [page] [page_size]]",
        "导出订阅: /sub_export [all]  # 默认当前会话，all=所有订阅 (管理员)",
        "导入订阅: /sub_import [本地文件路径]",
        "设置订阅选项: /sub_set <订阅 ID> <选项> <值>",
        "设置默认选项: /sub_set_default <选项> <值>",
        "会话默认配置: /sub_session_default_set <key> <value>",
        "查看会话默认配置: /sub_session_default_get",
        "插件配置: /rss_conf [key] [value]",
        "失败队列: /sub_failed_queue  # 查看当前失败队列状态",
    ]

    if is_admin:
        command_lines.append(
            "管理员测试推送: /sub_test <订阅ID或URL> [起始编号] [结束编号]"
        )
        command_lines.append("  示例: /sub_test 5 1 3    # 测试订阅ID=5，推送条目1-3")
        command_lines.append("  示例: /sub_test https://xxx 1  # 测试URL，推送条目1")

    command_lines.append("帮助: /rsshelp")

    return (
        "RSS 订阅插件帮助:\n\n"
        + "\n".join(command_lines)
        + "\n\n"
        + "常用选项:\n"
        + "- notify: 0/1\n"
        + "- send_mode: -1(仅链接)/0(自动)/2(直接消息)\n"
        + "- length_limit: 正整数，0 表示不限制\n"
        + "- display_title/display_via/display_author: -1~1\n"
        + "- display_media: -1/0\n"
        + "插件配置项:\n"
        + "- proxy/rsshub_base_url/default_interval/minimal_interval/timeout/"
        + "download_media_before_send/download_media_timeout/"
        + "bootstrap_skip_history/ffmpeg_video_transcode/"
        + "failed_queue_capacity/failed_queue_max_retries\n"
        + "- sender_strategy_telegram/sender_strategy_aiocqhttp/"
        + "sender_strategy_weixin_oc: 平台发送策略开关\n"
        + "- deduplicate_multi_bot: 单会话多 BOT 去重（默认 true）\n"
        + "- platform_shared_data_aiocqhttp: aiocqhttp 平台共享数据源"
        + "（默认 false）\n\n"
        + "会话级默认配置项:\n"
        + "- notify/send_mode/length_limit/link_preview/\n"
        + "display_author/display_via/display_title/display_entry_tags/\n"
        + "style/display_media/interval/title/tags\n\n"
        + "目标绑定:\n"
        + "- /sub <RSS 链接>  # 自动推送到当前会话\n\n"
        + "支持的平台：QQ、Telegram、微信、钉钉、Slack、Discord 等"
    )
