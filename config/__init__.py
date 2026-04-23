"""RSSHub Plugin Configuration Package

统一配置管理模块，提供类型安全的配置访问接口。
"""

from .constants import (
    PLUGIN_CONFIG_KEYS,
    SESSION_DEFAULT_KEYS,
    SESSION_DEFAULT_KV_PREFIX,
    SUB_OPTION_CASTERS,
    USER_DEFAULT_OPTION_KEYS,
)
from .plugin_config import (
    FFmpegConfig,
    PlatformSharedDataConfig,
    RsshubPluginConfig,
    SenderStrategiesConfig,
    TranslationConfig,
    WebUIConfig,
)

__all__ = [
    "RsshubPluginConfig",
    "TranslationConfig",
    "FFmpegConfig",
    "WebUIConfig",
    "SenderStrategiesConfig",
    "PlatformSharedDataConfig",
    "SUB_OPTION_CASTERS",
    "USER_DEFAULT_OPTION_KEYS",
    "PLUGIN_CONFIG_KEYS",
    "SESSION_DEFAULT_KEYS",
    "SESSION_DEFAULT_KV_PREFIX",
]
