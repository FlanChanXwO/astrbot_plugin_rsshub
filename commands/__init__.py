"""Commands package.

RSSHub 插件命令模块，提供纯逻辑函数供 main.py 调用。
所有函数返回数据，不涉及 yield 操作。
"""

from .config_cmd import get_plugin_config, set_plugin_config, set_user_default_option
from .failed_queue_cmd import get_failed_queue_status
from .help_cmd import get_help_text
from .session_cmd import get_session_defaults, set_session_default
from .subscription_cmd import (
    bind_target,
    export_subscriptions,
    import_subscriptions,
    list_subscriptions,
    set_subscription_option,
    subscribe_feed,
    test_subscription,
    unsubscribe_all_feeds,
    unsubscribe_feed,
)

__all__ = [
    # 订阅相关
    "subscribe_feed",
    "unsubscribe_feed",
    "list_subscriptions",
    "test_subscription",
    "unsubscribe_all_feeds",
    "export_subscriptions",
    "import_subscriptions",
    "set_subscription_option",
    "bind_target",
    # 配置相关
    "get_plugin_config",
    "set_plugin_config",
    "set_user_default_option",
    # 失败队列
    "get_failed_queue_status",
    # 会话默认
    "set_session_default",
    "get_session_defaults",
    # 帮助
    "get_help_text",
]
