"""RSSHub Plugin Configuration Package

统一配置管理模块，提供类型安全的配置访问接口。
"""

from .config_proxy import ConfigProxy, cfg, get_config, is_config_ready
from .constants import (
    PLUGIN_CONFIG_KEYS,
    SESSION_DEFAULT_KEYS,
    SESSION_DEFAULT_KV_PREFIX,
    SUB_OPTION_CASTERS,
    USER_DEFAULT_OPTION_KEYS,
)
from .plugin_config import (
    BasicConfig,
    FFmpegConfig,
    GlobalConfig,
    RsshubPluginConfig,
    SenderStrategiesConfig,
    TranslationConfig,
    WebUIConfig,
)
from .runtime_config import RuntimeConfig

__all__ = [
    # ConfigProxy 单例
    "cfg",
    "ConfigProxy",
    "get_config",
    "is_config_ready",
    # 运行时配置
    "RuntimeConfig",
    # 配置类
    "RsshubPluginConfig",
    "BasicConfig",
    "GlobalConfig",
    "TranslationConfig",
    "FFmpegConfig",
    "WebUIConfig",
    "SenderStrategiesConfig",
    # 常量
    "SUB_OPTION_CASTERS",
    "USER_DEFAULT_OPTION_KEYS",
    "PLUGIN_CONFIG_KEYS",
    "SESSION_DEFAULT_KEYS",
    "SESSION_DEFAULT_KV_PREFIX",
]
