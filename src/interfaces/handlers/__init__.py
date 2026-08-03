"""命令处理器模块（纯函数）"""

from .admin import handle_test_sub
from .batch import (
    handle_batch_activate,
    handle_batch_deactivate,
    handle_unsub_all,
)
from .config import (
    handle_sub_get_session,
    handle_sub_get_user,
    handle_sub_profile_get,
    handle_sub_profile_set,
    handle_sub_set,
    handle_sub_set_session,
    handle_sub_set_user,
)
from .data import handle_export, handle_import
from .route_knowledge import (
    handle_rsshub_kb_init,
    handle_rsshub_kb_status,
    handle_rsshub_kb_sync,
    handle_rsshub_kb_task,
)
from .subscription import (
    handle_rss_stop,
    handle_sub,
    handle_sub_list,
    handle_sub_state,
    handle_sub_status,
    handle_unsub,
)

__all__ = [
    "handle_batch_activate",
    "handle_batch_deactivate",
    "handle_export",
    "handle_import",
    "handle_rss_stop",
    "handle_rsshub_kb_init",
    "handle_rsshub_kb_status",
    "handle_rsshub_kb_sync",
    "handle_rsshub_kb_task",
    "handle_sub",
    "handle_sub_get_session",
    "handle_sub_get_user",
    "handle_sub_list",
    "handle_sub_profile_get",
    "handle_sub_profile_set",
    "handle_sub_set",
    "handle_sub_set_session",
    "handle_sub_set_user",
    "handle_sub_state",
    "handle_sub_status",
    "handle_test_sub",
    "handle_unsub",
    "handle_unsub_all",
]
