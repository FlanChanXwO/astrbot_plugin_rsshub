"""持久化层包

提供数据库连接、ORM 模型和仓库实现。
"""

from .database import DatabaseManager, RSSHubBaseModel, get_database
from .delivery_repository_impl import (
    DeliveryRepositoryImpl,
    get_delivery_repository,
)
from .feed_repository_impl import FeedRepositoryImpl, get_feed_repository
from .models import (
    EFFECTIVE_OPTION_KEYS,
    INHERIT_VALUE,
    BundleFeedORM,
    BundleORM,
    DeliveryBatchORM,
    DeliveryInboxItemORM,
    FeedORM,
    MigrationRecordORM,
    PushHistoryORM,
    SubORM,
    UserORM,
)
from .push_history_repository_impl import (
    PushHistoryRepositoryImpl,
    get_push_history_repository,
)
from .subscription_repository_impl import (
    SubscriptionRepositoryImpl,
    get_subscription_repository,
)
from .user_repository_impl import UserRepositoryImpl, get_user_repository

__all__ = [
    "EFFECTIVE_OPTION_KEYS",
    "INHERIT_VALUE",
    "BundleFeedORM",
    "BundleORM",
    # Database
    "DatabaseManager",
    "DeliveryBatchORM",
    "DeliveryInboxItemORM",
    "DeliveryRepositoryImpl",
    # ORM Models
    "FeedORM",
    # Repositories
    "FeedRepositoryImpl",
    "MigrationRecordORM",
    "PushHistoryORM",
    "PushHistoryRepositoryImpl",
    "RSSHubBaseModel",
    "SubORM",
    "SubscriptionRepositoryImpl",
    "UserORM",
    "UserRepositoryImpl",
    "get_database",
    "get_delivery_repository",
    "get_feed_repository",
    "get_push_history_repository",
    "get_subscription_repository",
    "get_user_repository",
]
