# RSS-to-AstrBot Database Module
# 基于 RSS-to-Telegram-Bot 移植，使用 SQLModel 替代 tortoise-orm

from .migrations import ensure_schema_compat
from .models import (
    Feed,
    MigrationRecord,
    PushHistory,
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
    "PushHistory",
    "MigrationRecord",
    "TranslationCache",
    "ensure_schema_compat",
    "init_db",
    "close_db",
    "get_session",
]
