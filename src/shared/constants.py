"""Shared enums, constants and compatibility aliases."""

from __future__ import annotations

from enum import Enum, IntEnum

INHERIT_VALUE = -100


class UserState(IntEnum):
    BANNED = -1
    USER = 1


class EntityState(IntEnum):
    DISABLED = 0
    ENABLED = 1


class NotifyState(IntEnum):
    DISABLED = 0
    ENABLED = 1


class SendMode(IntEnum):
    LINK_ONLY = -1
    AUTO = 0
    DIRECT = 1


class DisplayToggle(IntEnum):
    DISABLED = -1
    AUTO = 0
    FORCED = 1


class DisplayVia(IntEnum):
    FULLY_DISABLED = -2
    LINK_ONLY = -1
    AUTO = 0
    FORCED = 1


class StyleMode(IntEnum):
    AUTO = 0
    RSSRT = 1
    ORIGINAL = 2


class SourceType(str, Enum):
    FEED = "feed"
    AGENT = "agent"


class PushStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    STOPPED = "stopped"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class PlatformName(str, Enum):
    TELEGRAM = "telegram"
    ONEBOT = "aiocqhttp"
    QQ_OFFICIAL = "qq_official"
    WEIXIN_OC = "weixin_oc"


class PlatformAlias(str, Enum):
    TELEGRAM_SHORT = "tg"
    ONEBOT = "onebot"
    ONEBOT11 = "onebot11"
    ONEBOTV11 = "onebotv11"
    QQOFFICIAL = "qqofficial"
    QQ = "qq"
    WECHAT = "wechat"
    WEIXIN = "weixin"


class PlatformStrategyTemplate(str, Enum):
    TELEGRAM = "telegram_strategy"
    ONEBOT = "onebot_strategy"
    QQ_OFFICIAL = "qq_official_strategy"


class HandlerStatus(IntEnum):
    INHERIT = -100
    DISABLED = 0
    ENABLED = 1


class HandlerType(str, Enum):
    BUILTIN = "builtin"
    EXTERNAL = "external"


class HandlerFieldType(str, Enum):
    STRING = "string"
    TEXT = "text"
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    SELECT = "select"
    LIST_STRING = "list[string]"
    JSON = "json"


class HandlerTraceStatus(str, Enum):
    OK = "ok"
    DISABLED = "disabled"
    SKIPPED = "skipped"
    ERROR = "error"


class AiFilterInputScope(str, Enum):
    TEXT = "text"
    RAW_XML = "raw_xml"
    BOTH = "both"


class AiTransformScope(str, Enum):
    PLAINTEXT = "plaintext"
    XML = "xml"


USER_STATE_BANNED = int(UserState.BANNED)
USER_STATE_USER = int(UserState.USER)
USER_STATES = {int(item) for item in UserState}

STATE_DISABLED = int(EntityState.DISABLED)
STATE_ENABLED = int(EntityState.ENABLED)
ENTITY_STATES = {int(item) for item in EntityState}

NOTIFY_DISABLED = int(NotifyState.DISABLED)
NOTIFY_ENABLED = int(NotifyState.ENABLED)
NOTIFY_STATES = {int(item) for item in NotifyState}

SEND_MODE_LINK_ONLY = int(SendMode.LINK_ONLY)
SEND_MODE_AUTO = int(SendMode.AUTO)
SEND_MODE_DIRECT = int(SendMode.DIRECT)
SEND_MODES = {int(item) for item in SendMode}

DISPLAY_DISABLED = int(DisplayToggle.DISABLED)
DISPLAY_AUTO = int(DisplayToggle.AUTO)
DISPLAY_FORCED = int(DisplayToggle.FORCED)

DISPLAY_VIA_FULLY_DISABLED = int(DisplayVia.FULLY_DISABLED)
DISPLAY_VIA_LINK_ONLY = int(DisplayVia.LINK_ONLY)
DISPLAY_VIA_AUTO = int(DisplayVia.AUTO)
DISPLAY_VIA_FORCED = int(DisplayVia.FORCED)

STYLE_AUTO = int(StyleMode.AUTO)
STYLE_RSSRT = int(StyleMode.RSSRT)
STYLE_ORIGINAL = int(StyleMode.ORIGINAL)
STYLE_RSSTT = STYLE_AUTO
STYLE_FLOWERSS = STYLE_AUTO
STYLE_VALUES = {int(item) for item in StyleMode}

SOURCE_TYPE_FEED = SourceType.FEED.value
SOURCE_TYPE_AGENT = SourceType.AGENT.value
SOURCE_TYPES = {item.value for item in SourceType}

PUSH_STATUS_PENDING = PushStatus.PENDING.value
PUSH_STATUS_SUCCESS = PushStatus.SUCCESS.value
PUSH_STATUS_FAILED = PushStatus.FAILED.value
PUSH_STATUS_STOPPED = PushStatus.STOPPED.value
PUSH_STATUS_SKIPPED = PushStatus.SKIPPED.value
PUSH_STATUS_RETRYING = PushStatus.RETRYING.value
PUSH_STATUSES = {item.value for item in PushStatus}

PLATFORM_TELEGRAM = PlatformName.TELEGRAM.value
PLATFORM_TELEGRAM_ALIAS = PlatformAlias.TELEGRAM_SHORT.value
PLATFORM_ONEBOT = PlatformName.ONEBOT.value
PLATFORM_ONEBOT_ALIASES = (
    PlatformAlias.ONEBOT.value,
    PlatformAlias.ONEBOT11.value,
    PlatformAlias.ONEBOTV11.value,
)
PLATFORM_QQ_OFFICIAL = PlatformName.QQ_OFFICIAL.value
PLATFORM_QQ_OFFICIAL_ALIASES = (
    PlatformAlias.QQOFFICIAL.value,
    PlatformAlias.QQ.value,
)
PLATFORM_WEIXIN_OC = PlatformName.WEIXIN_OC.value
PLATFORM_WEIXIN_ALIASES = (
    PlatformAlias.WECHAT.value,
    PlatformAlias.WEIXIN.value,
)

PLATFORM_STRATEGY_TEMPLATE_TELEGRAM = PlatformStrategyTemplate.TELEGRAM.value
PLATFORM_STRATEGY_TEMPLATE_ONEBOT = PlatformStrategyTemplate.ONEBOT.value
PLATFORM_STRATEGY_TEMPLATE_QQ_OFFICIAL = PlatformStrategyTemplate.QQ_OFFICIAL.value

TELEGRAM_PHOTO_MAX_BYTES = 10 * 1024 * 1024
TELEGRAM_ANIMATION_MAX_BYTES = 50 * 1024 * 1024
TELEGRAM_VIDEO_MAX_BYTES = 50 * 1024 * 1024
TELEGRAM_DOCUMENT_MAX_BYTES = 50 * 1024 * 1024

ONEBOT_NAPCAT_STREAM_MODE_DEFAULT = "fallback"
ONEBOT_VIDEO_MAX_BYTES = 100 * 1024 * 1024

QQ_OFFICIAL_MEDIA_THRESHOLD_DEFAULT = 0
QQ_OFFICIAL_IMAGE_MAX_BYTES = 20 * 1024 * 1024
QQ_OFFICIAL_GIF_MAX_BYTES = 10 * 1024 * 1024
QQ_OFFICIAL_VIDEO_MAX_BYTES = 100 * 1024 * 1024
QQ_OFFICIAL_DEGRADE_STRATEGY_LINK_ONLY = "link_only"
QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK = "file_then_link"
QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL = "fail"
QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT = QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK
QQ_OFFICIAL_DEGRADE_STRATEGY_OPTIONS = (
    QQ_OFFICIAL_DEGRADE_STRATEGY_LINK_ONLY,
    QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK,
    QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL,
)
QQ_OFFICIAL_MARKDOWN_MODE_AUTO = "auto"
QQ_OFFICIAL_MARKDOWN_MODE_FORCE = "force"
QQ_OFFICIAL_MARKDOWN_MODE_PLAIN = "plain"
QQ_OFFICIAL_MARKDOWN_MODE_DEFAULT = QQ_OFFICIAL_MARKDOWN_MODE_AUTO
QQ_OFFICIAL_MARKDOWN_MODE_OPTIONS = (
    QQ_OFFICIAL_MARKDOWN_MODE_AUTO,
    QQ_OFFICIAL_MARKDOWN_MODE_FORCE,
    QQ_OFFICIAL_MARKDOWN_MODE_PLAIN,
)

ALL_SUPPORTED_PLATFORMS = (
    PlatformName.TELEGRAM.value,
    PlatformName.ONEBOT.value,
    PlatformName.QQ_OFFICIAL.value,
    PlatformName.WEIXIN_OC.value,
)

SENDER_STRATEGY_ENABLED_PLATFORMS = (
    PlatformName.TELEGRAM.value,
    PlatformName.ONEBOT.value,
    PlatformName.QQ_OFFICIAL.value,
)

PLATFORM_STRATEGY_TEMPLATE_KEYS: dict[str, str] = {
    PlatformName.TELEGRAM.value: PlatformStrategyTemplate.TELEGRAM.value,
    PlatformName.ONEBOT.value: PlatformStrategyTemplate.ONEBOT.value,
    PlatformName.QQ_OFFICIAL.value: PlatformStrategyTemplate.QQ_OFFICIAL.value,
}

PLATFORM_ALIASES: dict[str, tuple[str, ...]] = {
    PlatformName.TELEGRAM.value: (PlatformAlias.TELEGRAM_SHORT.value,),
    PlatformName.ONEBOT.value: PLATFORM_ONEBOT_ALIASES,
    PlatformName.QQ_OFFICIAL.value: PLATFORM_QQ_OFFICIAL_ALIASES,
    PlatformName.WEIXIN_OC.value: PLATFORM_WEIXIN_ALIASES,
}

ONEBOT_PLATFORMS = {PlatformName.ONEBOT.value, *PLATFORM_ONEBOT_ALIASES}
TELEGRAM_PLATFORMS = {
    PlatformName.TELEGRAM.value,
    PlatformAlias.TELEGRAM_SHORT.value,
}
QQ_OFFICIAL_PLATFORMS = {
    PlatformName.QQ_OFFICIAL.value,
    *PLATFORM_QQ_OFFICIAL_ALIASES,
}
WEIXIN_PLATFORMS = {PlatformName.WEIXIN_OC.value, *PLATFORM_WEIXIN_ALIASES}

WEIXIN_IMAGE_MAX_BYTES = 10 * 1024 * 1024
WEIXIN_GIF_MAX_BYTES = 5 * 1024 * 1024
WEIXIN_VIDEO_MAX_BYTES = 10 * 1024 * 1024
WEIXIN_FILE_MAX_BYTES = 20 * 1024 * 1024

GIF_COMPRESS_TARGET_MAX_BYTES = min(
    QQ_OFFICIAL_GIF_MAX_BYTES,
    WEIXIN_GIF_MAX_BYTES,
    TELEGRAM_ANIMATION_MAX_BYTES,
)
