"""帮助命令逻辑"""

HELP_TEXT = """\
RSS 订阅插件帮助

━━━━━━━━━━━━━━━━━━━━━━
📋 订阅管理
━━━━━━━━━━━━━━━━━━━━━━
/sub <RSS链接>              订阅 RSS 源
/unsub <订阅ID>             取消订阅
/unsub_all [global]         取消全部订阅（global=所有会话，仅管理员）
/sub_list [all [page] [size]]  查看订阅列表

━━━━━━━━━━━━━━━━━━━━━━
⚙️ 订阅设置
━━━━━━━━━━━━━━━━━━━━━━
/sub_set <ID> <选项> <值>   设置指定订阅选项
/sub_state <ID> <on|off>    快速启停订阅推送

━━━━━━━━━━━━━━━━━━━━━━
💾 导入导出
━━━━━━━━━━━━━━━━━━━━━━
/sub_export [all]            导出订阅
/sub_import [文件路径]      导入订阅

━━━━━━━━━━━━━━━━━━━━━━
🛠️ 用户与会话
━━━━━━━━━━━━━━━━━━━━━━
/sub_set_user <选项> <值>    设置当前用户配置
/sub_get_user [选项]         查看用户配置
/sub_set_session <key> <val> 设置当前会话默认配置
/sub_get_session [key]       查看会话配置

━━━━━━━━━━━━━━━━━━━━━━
🧪 管理员命令
━━━━━━━━━━━━━━━━━━━━━━
/sub_test <ID或URL> [start] [end]  测试推送指定订阅

━━━━━━━━━━━━━━━━━━━━━━
💡 常用选项说明
━━━━━━━━━━━━━━━━━━━━━━
• notify           是否推送通知 (0/1)
• send_mode        发送模式：-1=仅链接, 0=自动, 2=直接消息
• length_limit     正文长度限制 (0=不限制)
• display_title    是否显示标题 (-1=不显示, 0=自动, 1=显示)
• display_media    是否显示媒体 (-1=不显示, 0=按配置)
• interval         检查间隔（秒）
• translate        是否开启翻译 (true/false)
• translate_target_lang  翻译目标语言 (zh-CN/zh-TW/en/ja)

━━━━━━━━━━━━━━━━━━━━━━
❓ 其他帮助
━━━━━━━━━━━━━━━━━━━━━━
/rsshelp                    显示此帮助信息
"""


def get_help_text(is_admin: bool) -> str:
    """获取帮助文本

    Args:
        is_admin: 是否为管理员

    Returns:
        帮助文本字符串
    """
    text = HELP_TEXT

    if is_admin:
        admin_tip = "\n\n👑 管理员提示：你可以使用所有命令，包括测试推送和跨会话操作。"
        text += admin_tip

    return text
