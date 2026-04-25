"""Commands package.

RSSHub 插件命令模块，提供纯逻辑函数供 main.py 调用。
所有函数返回数据，不涉及 yield 操作。
"""

from .config_cmd import get_user_option, set_user_option
from .help_cmd import get_help_text
from .session_cmd import get_session, set_session
from .subscription_cmd import (
    IMPORT_MAX_FILE_SIZE_BYTES,
    IMPORT_MAX_FILE_SIZE_DISPLAY,
    batch_activate_subs,
    batch_deactivate_subs,
    batch_subscribe_feeds,
    batch_unsubscribe_feeds,
    export_subscriptions,
    import_subscriptions,
    list_subscriptions,
    read_import_toml_content,
    read_uploaded_toml_content,
    set_subscription_option,
    subscribe_feed,
    test_subscription,
    unsubscribe_all_feeds,
    unsubscribe_feed,
    unsubscribe_feed_by_url,
)
from .types import (
    BatchSubscribeResult,
    BatchUnsubscribeResult,
    CommandResult,
    ExportSubscriptionsResult,
    ImportSubscriptionsResult,
    ListSubscriptionsResult,
    SetSubscriptionOptionResult,
    SubscribeResult,
    UnsubscribeAllResult,
)

__all__ = [
    # 订阅相关
    "subscribe_feed",
    "unsubscribe_feed",
    "unsubscribe_feed_by_url",
    "batch_subscribe_feeds",
    "batch_unsubscribe_feeds",
    "batch_activate_subs",
    "batch_deactivate_subs",
    "list_subscriptions",
    "test_subscription",
    "unsubscribe_all_feeds",
    "export_subscriptions",
    "import_subscriptions",
    "set_subscription_option",
    # 导入导出文件读取
    "read_import_toml_content",
    "read_uploaded_toml_content",
    "IMPORT_MAX_FILE_SIZE_BYTES",
    "IMPORT_MAX_FILE_SIZE_DISPLAY",
    # 配置相关
    "set_user_option",
    "get_user_option",
    # 会话默认
    "set_session",
    "get_session",
    # 帮助
    "get_help_text",
    # 类型
    "CommandResult",
    "ExportSubscriptionsResult",
    "ImportSubscriptionsResult",
    "ListSubscriptionsResult",
    "SetSubscriptionOptionResult",
    "SubscribeResult",
    "UnsubscribeAllResult",
    "BatchSubscribeResult",
    "BatchUnsubscribeResult",
]
