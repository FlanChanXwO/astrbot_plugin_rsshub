"""领域层

包含业务实体、值对象、领域事件和领域异常。
"""

from ..shared.constants import INHERIT_VALUE
from .entities.bundle import Bundle
from .entities.bundle_feed import BundleFeed
from .entities.card_template import CardTemplateMetadata
from .entities.feed import Feed
from .entities.push_history import PushHistory
from .entities.subscription import Subscription
from .entities.user import User
from .exceptions import (
    ConfigurationError,
    DomainException,
    FeedNotFoundError,
    PermissionDeniedError,
    RateLimitError,
    RSSFetchError,
    SubscriptionNotFoundError,
    UserNotFoundError,
    ValidationError,
    WebError,
)
from .repositories.feed_repository import FeedRepository
from .repositories.push_history_repository import PushHistoryRepository
from .repositories.subscription_repository import SubscriptionRepository
from .repositories.user_repository import UserRepository

__all__ = [
    "INHERIT_VALUE",
    "Bundle",
    "BundleFeed",
    "CardTemplateMetadata",
    "ConfigurationError",
    "DomainException",
    "Feed",
    "FeedNotFoundError",
    "FeedRepository",
    "PermissionDeniedError",
    "PushHistory",
    "PushHistoryRepository",
    "RSSFetchError",
    "RateLimitError",
    "Subscription",
    "SubscriptionNotFoundError",
    "SubscriptionRepository",
    "User",
    "UserNotFoundError",
    "UserRepository",
    "ValidationError",
    "WebError",
]
