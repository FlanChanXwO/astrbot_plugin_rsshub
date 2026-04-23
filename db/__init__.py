# RSS-to-AstrBot Database Module
# 基于 RSS-to-Telegram-Bot 移植，使用 SQLModel 替代 tortoise-orm

from .migrations import ensure_schema_compat
from .models import (
    FailedNotification,
    Feed,
    MonitorSchedule,
    Option,
    Sub,
    TranslationCache,
    User,
    close_db,
    get_session,
    init_db,
)

__all__ = [
    "Feed",
    "Sub",
    "User",
    "Option",
    "MonitorSchedule",
    "FailedNotification",
    "TranslationCache",
    "ensure_schema_compat",
    "init_db",
    "close_db",
    "get_session",
]
