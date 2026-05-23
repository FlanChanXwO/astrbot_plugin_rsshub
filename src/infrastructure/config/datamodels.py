"""Typed config and runtime data models for the RSSHub plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from ...shared.constants import (
    PLATFORM_QQ_OFFICIAL,
    PLATFORM_STRATEGY_TEMPLATE_KEYS,
    SENDER_STRATEGY_ENABLED_PLATFORMS,
)

if TYPE_CHECKING:
    from astrbot.api import AstrBotConfig

_SENDER_STRATEGY_KEYS: tuple[str, ...] = SENDER_STRATEGY_ENABLED_PLATFORMS

_PLATFORM_STRATEGY_TEMPLATE_KEYS: dict[str, str] = PLATFORM_STRATEGY_TEMPLATE_KEYS


@dataclass(frozen=True)
class PlatformStrategySettings:
    """Platform-specific sender strategy settings."""

    enable_telegraph: bool = False
    telegraph_token: str = ""
    prefer_local_video: bool = False


@dataclass(frozen=True)
class BasicSettings:
    """Global infrastructure-facing defaults used by application use cases."""

    proxy: str = ""
    timeout: int = 30
    rsshub_base_url: str = "https://rsshub.app"
    minimal_interval: int = 1
    failed_queue_capacity: int = 50
    failed_queue_max_retries: int = 3
    deduplicate_multi_bot: bool = True
    history_entry_limit: int = 0
    download_media_before_send: bool = True
    download_media_timeout: int = 30


@dataclass(frozen=True)
class FeedFetchSettings:
    """HTTP/RSS fetch defaults."""

    timeout: int = 30
    proxy: str = ""
    rsshub_base_url: str = "https://rsshub.app"


@dataclass(frozen=True)
class RSSSettings:
    """RSS parser and dedup history settings."""

    hash_history_min: int = 200
    hash_history_multiplier: int = 2
    hash_history_hard_limit: int = 5000
    tracking_query_params: tuple[str, ...] = field(default_factory=tuple)
    bootstrap_skip_history: bool = True


@dataclass(frozen=True)
class SchedulerSettings:
    """Scheduler defaults."""

    default_interval: int = 10
    history_retention_days: int = 30
    history_entry_limit: int = 0


@dataclass(frozen=True)
class SubscriptionDefaults:
    """Default values applied to new subscriptions."""

    interval: int = 10
    notify: bool = True
    send_mode: str = "自动"
    length_limit: int = 0
    display_author: str = "自动"
    display_via: str = "自动"
    display_title: str = "自动"
    display_entry_tags: bool = False
    style: str = "auto"
    display_media: bool = True


@dataclass(frozen=True)
class ContentHandlerSettings:
    """Global defaults for builtin content handlers."""

    ai_provider_id: str = ""
    ai_persona_id: str = ""


@dataclass(frozen=True)
class SenderStrategySettings:
    """Per-platform sender strategy toggles."""

    telegram: bool = True
    aiocqhttp: bool = True
    qq_official: bool = True
    telegram_settings: PlatformStrategySettings = field(
        default_factory=PlatformStrategySettings
    )
    aiocqhttp_settings: PlatformStrategySettings = field(
        default_factory=PlatformStrategySettings
    )


@dataclass(frozen=True)
class FFmpegSettings:
    """Media transcoding settings used by senders."""

    video_transcode: bool = False
    video_transcode_timeout: int = 120
    gif_transcode: bool = False
    gif_transcode_timeout: int = 60


@dataclass(frozen=True)
class RouteKnowledgeSettings:
    """RSSHub Routes knowledge-base sync settings."""

    kb_name: str = "RSSHub Routes"
    embedding_provider_id: str = ""
    rerank_provider_id: str = ""
    source_mode: str = "mirror"
    source_base_url: str = (
        "https://raw.githubusercontent.com/FlanChanXwO/rsshub-routes-knowledgebase/main"
    )
    fallback_base_url: str = (
        "https://raw.githubusercontent.com/FlanChanXwO/rsshub-routes-knowledgebase/main"
    )
    local_source_dir: str = ""
    timeout: int = 30
    batch_size: int = 32
    tasks_limit: int = 3
    max_retries: int = 3


@dataclass(frozen=True)
class ApplicationSettings:
    """Settings consumed by the application layer."""

    basic: BasicSettings = field(default_factory=BasicSettings)
    fetch: FeedFetchSettings = field(default_factory=FeedFetchSettings)
    rss: RSSSettings = field(default_factory=RSSSettings)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)
    subscription_defaults: SubscriptionDefaults = field(
        default_factory=SubscriptionDefaults
    )
    content_handlers: ContentHandlerSettings = field(
        default_factory=ContentHandlerSettings
    )
    sender_strategies: SenderStrategySettings = field(
        default_factory=SenderStrategySettings
    )
    ffmpeg: FFmpegSettings = field(default_factory=FFmpegSettings)
    route_knowledge: RouteKnowledgeSettings = field(
        default_factory=RouteKnowledgeSettings
    )


class PlatformSenderStrategyConfig(BaseModel):
    """平台专属 sender 策略。"""

    enable_telegraph: bool = Field(default=False, description="启用 Telegraph 自动分流")
    telegraph_token: str = Field(default="", description="Telegraph access token")
    prefer_local_video: bool = Field(
        default=False, description="是否优先使用本地视频文件"
    )

    @classmethod
    def from_dict(cls, data: Any) -> PlatformSenderStrategyConfig:
        if not data:
            return cls()
        if isinstance(data, list):
            data = next((item for item in data if isinstance(item, dict)), None)
        if not isinstance(data, dict):
            return cls()
        clean_data = {k: v for k, v in data.items() if k != "__template_key"}
        return cls.model_validate({**cls().model_dump(), **clean_data})

    def to_template_item(
        self, template_key: str, include_fields: set[str] | None = None
    ) -> dict[str, Any] | None:
        data = self.model_dump()
        default_data = type(self)().model_dump()
        if include_fields is not None:
            data = {key: value for key, value in data.items() if key in include_fields}
            default_data = {
                key: value
                for key, value in default_data.items()
                if key in include_fields
            }
        if data == default_data:
            return None
        return {"__template_key": template_key, **data}


def _first_strategy_template(data: Any, template_key: str) -> dict[str, Any] | None:
    if not isinstance(data, list):
        return None
    return next(
        (
            item
            for item in data
            if isinstance(item, dict) and item.get("__template_key") == template_key
        ),
        None,
    )


class BasicConfig(BaseModel):
    """基础设施配置（系统级，不继承）"""

    proxy: str = Field(default="", description="代理地址")
    rsshub_base_url: str = Field(
        default="https://rsshub.app", description="RSSHub基础URL"
    )
    timeout: int = Field(default=30, description="请求超时（秒）")
    minimal_interval: int = Field(default=1, description="最小监控间隔（分钟）")
    hash_history_min: int = Field(default=200, description="去重历史最小值")
    hash_history_multiplier: int = Field(default=2, description="去重历史倍数")
    hash_history_hard_limit: int = Field(default=5000, description="去重历史硬上限")
    tracking_query_params: list[str] = Field(
        default_factory=lambda: [
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "utm_id",
            "gclid",
            "fbclid",
            "mc_cid",
            "mc_eid",
            "spm",
            "ref",
            "ref_src",
        ]
    )
    failed_queue_capacity: int = Field(default=50, description="失败队列容量")
    failed_queue_max_retries: int = Field(default=3, description="失败队列最大重试次数")
    deduplicate_multi_bot: bool = Field(default=True, description="多BOT去重")
    bootstrap_skip_history: bool = Field(default=True, description="首轮跳过历史")
    history_entry_limit: int = Field(default=0, description="历史条目限制")
    history_retention_days: int = Field(default=30, description="推送历史保留天数")
    download_media_before_send: bool = Field(
        default=True,
        description="兼容旧配置；运行时始终先下载媒体后发送",
    )
    download_media_timeout: int = Field(default=30, description="媒体下载超时")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BasicConfig:
        if not data:
            return cls()
        return cls.model_validate({**cls().model_dump(), **(data or {})})


class GlobalConfig(BaseModel):
    """全局默认配置（订阅级，可继承）"""

    interval: int = Field(default=10, description="监控间隔（分钟）")
    notify: bool = Field(default=True, description="是否通知")
    send_mode: str = Field(default="自动", description="发送模式")
    length_limit: int = Field(default=0, description="长度限制")
    display_author: str = Field(default="自动", description="显示作者")
    display_via: str = Field(default="自动", description="显示来源")
    display_title: str = Field(default="自动", description="显示标题")
    display_entry_tags: bool = Field(default=False, description="显示标签")
    style: str = Field(default="auto", description="推送排版策略")
    display_media: bool = Field(default=True, description="显示媒体")

    _SEND_MODE_MAP: ClassVar[dict[str, int]] = {"仅链接": -1, "自动": 0, "直接发送": 1}
    _DISPLAY_AUTHOR_MAP: ClassVar[dict[str, int]] = {"禁用": -1, "自动": 0, "强制": 1}
    _DISPLAY_VIA_MAP: ClassVar[dict[str, int]] = {
        "完全禁用": -2,
        "仅链接": -1,
        "自动": 0,
        "强制": 1,
    }
    _DISPLAY_TITLE_MAP: ClassVar[dict[str, int]] = {
        "禁用": -1,
        "自动": 0,
        "强制": 1,
    }
    _STYLE_MAP: ClassVar[dict[str, int]] = {
        "auto": 0,
        "classic": 0,
        "RSStT": 0,
        "rssrt": 1,
        "RSSRT": 1,
        "flowerss": 0,
        "original": 2,
    }

    _SEND_MODE_RMAP: ClassVar[dict[int, str]] = {-1: "仅链接", 0: "自动", 1: "直接发送"}
    _DISPLAY_AUTHOR_RMAP: ClassVar[dict[int, str]] = {
        -1: "禁用",
        0: "自动",
        1: "强制",
    }
    _DISPLAY_VIA_RMAP: ClassVar[dict[int, str]] = {
        -2: "完全禁用",
        -1: "仅链接",
        0: "自动",
        1: "强制",
    }
    _DISPLAY_TITLE_RMAP: ClassVar[dict[int, str]] = {
        -1: "禁用",
        0: "自动",
        1: "强制",
    }
    _STYLE_RMAP: ClassVar[dict[int, str]] = {0: "auto", 1: "rssrt", 2: "original"}

    def to_db_values(self) -> dict[str, Any]:
        return {
            "interval": self.interval,
            "notify": 1 if self.notify else 0,
            "send_mode": self._SEND_MODE_MAP.get(self.send_mode, 0),
            "length_limit": self.length_limit,
            "display_author": self._DISPLAY_AUTHOR_MAP.get(self.display_author, 0),
            "display_via": self._DISPLAY_VIA_MAP.get(self.display_via, 0),
            "display_title": self._DISPLAY_TITLE_MAP.get(self.display_title, 0),
            "display_entry_tags": -1 if not self.display_entry_tags else 0,
            "style": self._STYLE_MAP.get(self.style, 0),
            "display_media": -1 if not self.display_media else 0,
        }

    @classmethod
    def normalize_send_mode_value(cls, value: Any) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return 0
        if normalized == 2:
            return 1
        if normalized == 1:
            return 0
        if normalized in {-1, 0}:
            return normalized
        return 0

    @classmethod
    def from_db_values(cls, values: dict[str, Any]) -> GlobalConfig:
        send_mode_value = cls.normalize_send_mode_value(values.get("send_mode", 0))
        return cls(
            interval=values.get("interval", 10),
            notify=values.get("notify", 1) == 1,
            send_mode=cls._SEND_MODE_RMAP.get(send_mode_value, "自动"),
            length_limit=values.get("length_limit", 0),
            display_author=cls._DISPLAY_AUTHOR_RMAP.get(
                values.get("display_author", 0), "自动"
            ),
            display_via=cls._DISPLAY_VIA_RMAP.get(values.get("display_via", 0), "自动"),
            display_title=cls._DISPLAY_TITLE_RMAP.get(
                values.get("display_title", 0), "自动"
            ),
            display_entry_tags=values.get("display_entry_tags", -1) != -1,
            style=cls._STYLE_RMAP.get(values.get("style", 0), "auto"),
            display_media=values.get("display_media", 0) != -1,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> GlobalConfig:
        if not data:
            return cls()
        return cls.model_validate({**cls().model_dump(), **(data or {})})


class FFmpegConfig(BaseModel):
    """FFmpeg 配置"""

    video_transcode: bool = Field(default=False, description="视频转码")
    video_transcode_timeout: int = Field(default=120, description="视频转码超时")
    gif_transcode: bool = Field(default=False, description="GIF转码")
    gif_transcode_timeout: int = Field(default=60, description="GIF转码超时")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> FFmpegConfig:
        if not data:
            return cls()
        return cls.model_validate({**cls().model_dump(), **(data or {})})


class ContentHandlersConfig(BaseModel):
    """全局内容处理器配置"""

    ai_provider_id: str = Field(default="", description="AI Provider ID")
    ai_persona_id: str = Field(default="", description="AI Persona ID")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ContentHandlersConfig:
        if not data:
            return cls()
        return cls.model_validate({**cls().model_dump(), **(data or {})})


class SenderStrategiesConfig(BaseModel):
    """发送策略配置"""

    telegram: bool = Field(default=True, description="Telegram策略")
    aiocqhttp: bool = Field(default=True, description="QQ策略")
    qq_official: bool = Field(default=True, description="QQ官方策略")
    telegram_settings: PlatformSenderStrategyConfig = Field(
        default_factory=PlatformSenderStrategyConfig, alias="telegram_config"
    )
    aiocqhttp_settings: PlatformSenderStrategyConfig = Field(
        default_factory=PlatformSenderStrategyConfig, alias="aiocqhttp_config"
    )

    @classmethod
    def from_config(cls, data: Any) -> SenderStrategiesConfig:
        if data is None:
            return cls()
        if isinstance(data, dict):
            known_values = dict.fromkeys(_SENDER_STRATEGY_KEYS, True)
            if "enabled_platforms" in data:
                enabled = _enabled_from_sender_config(data) or set()
                known_values.update(
                    {key: key in enabled for key in _SENDER_STRATEGY_KEYS}
                )
            else:
                known_values.update(
                    {
                        key: bool(value)
                        for key, value in data.items()
                        if key in _SENDER_STRATEGY_KEYS and isinstance(value, bool)
                    }
                )
            platform_strategies = data.get("platform_strategies")
            telegram_source = _first_strategy_template(
                platform_strategies,
                _PLATFORM_STRATEGY_TEMPLATE_KEYS["telegram"],
            )
            if telegram_source is None:
                telegram_source = data.get("telegram") or data.get("telegram_config")
            aiocqhttp_source = _first_strategy_template(
                platform_strategies,
                _PLATFORM_STRATEGY_TEMPLATE_KEYS["aiocqhttp"],
            )
            if aiocqhttp_source is None:
                aiocqhttp_source = data.get("aiocqhttp") or data.get("aiocqhttp_config")
            return cls.model_validate(
                {
                    **known_values,
                    PLATFORM_QQ_OFFICIAL: known_values[PLATFORM_QQ_OFFICIAL],
                    "telegram_config": PlatformSenderStrategyConfig.from_dict(
                        telegram_source
                    ),
                    "aiocqhttp_config": PlatformSenderStrategyConfig.from_dict(
                        aiocqhttp_source
                    ),
                }
            )
        if isinstance(data, str):
            parts = data.replace(",", "\n").splitlines()
            enabled = {part.strip() for part in parts if part.strip()}
            return cls.from_enabled_platforms(enabled)
        if isinstance(data, (list, tuple, set)):
            enabled = {str(item).strip() for item in data if str(item).strip()}
            return cls.from_enabled_platforms(enabled)
        return cls.model_validate({**cls().model_dump(), **(data or {})})

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SenderStrategiesConfig:
        return cls.from_config(data)

    @classmethod
    def from_enabled_platforms(cls, enabled: set[str]) -> SenderStrategiesConfig:
        enabled = {item for item in enabled if item in _SENDER_STRATEGY_KEYS}
        return cls(**{key: key in enabled for key in _SENDER_STRATEGY_KEYS})

    def to_enabled_platforms(self) -> list[str]:
        return [key for key in _SENDER_STRATEGY_KEYS if getattr(self, key)]

    def to_config_dict(self) -> dict[str, Any]:
        platform_strategies = [
            item
            for item in (
                self.telegram_settings.to_template_item(
                    _PLATFORM_STRATEGY_TEMPLATE_KEYS["telegram"],
                    include_fields={"enable_telegraph", "telegraph_token"},
                ),
                self.aiocqhttp_settings.to_template_item(
                    _PLATFORM_STRATEGY_TEMPLATE_KEYS["aiocqhttp"],
                    include_fields={"prefer_local_video"},
                ),
            )
            if item is not None
        ]
        return {
            "enabled_platforms": self.to_enabled_platforms(),
            "platform_strategies": platform_strategies,
        }


def _enabled_from_sender_config(data: dict[str, Any]) -> set[str] | None:
    if "enabled_platforms" in data:
        raw = data.get("enabled_platforms")
        if isinstance(raw, str):
            return {
                part.strip()
                for part in raw.replace(",", "\n").splitlines()
                if part.strip()
            }
        if isinstance(raw, (list, tuple, set)):
            return {str(item).strip() for item in raw if str(item).strip()}
        return set()

    bool_keys = {
        key for key in _SENDER_STRATEGY_KEYS if isinstance(data.get(key), bool)
    }
    if bool_keys:
        return {key for key in bool_keys if bool(data.get(key))}
    return None


class RouteKnowledgeConfig(BaseModel):
    """RSSHub Routes 知识库同步配置"""

    kb_name: str = Field(default="RSSHub Routes", description="AstrBot 知识库名称")
    embedding_provider_id: str = Field(
        default="", description="默认向量模型 Provider ID"
    )
    rerank_provider_id: str = Field(
        default="", description="默认重排序模型 Provider ID"
    )
    source_mode: str = Field(default="mirror", description="知识库来源模式")
    source_base_url: str = Field(
        default=(
            "https://raw.githubusercontent.com/"
            "FlanChanXwO/rsshub-routes-knowledgebase/main"
        ),
        description="Routes 知识库文件源 base URL",
    )
    fallback_base_url: str = Field(
        default=(
            "https://raw.githubusercontent.com/"
            "FlanChanXwO/rsshub-routes-knowledgebase/main"
        ),
        description="auto 模式下的 fallback base URL",
    )
    local_source_dir: str = Field(default="", description="local 模式本地目录")
    timeout: int = Field(default=30, description="同步请求超时（秒）")
    batch_size: int = Field(default=32, description="KB embedding 批大小")
    tasks_limit: int = Field(default=3, description="KB embedding 并发任务数")
    max_retries: int = Field(default=3, description="KB embedding 最大重试次数")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RouteKnowledgeConfig:
        if not data:
            return cls()
        return cls.model_validate({**cls().model_dump(), **(data or {})})


class RsshubPluginConfig(BaseModel):
    """RSSHub 插件统一配置类"""

    basic_config: BasicConfig = Field(default_factory=BasicConfig)
    global_config: GlobalConfig = Field(default_factory=GlobalConfig)
    ffmpeg: FFmpegConfig = Field(default_factory=FFmpegConfig)
    content_handlers: ContentHandlersConfig = Field(
        default_factory=ContentHandlersConfig
    )
    sender_strategies: SenderStrategiesConfig = Field(
        default_factory=SenderStrategiesConfig
    )
    route_knowledge: RouteKnowledgeConfig = Field(default_factory=RouteKnowledgeConfig)
    db_file: str = Field(default="rsshub.db", description="数据库文件名")

    @classmethod
    def from_astrbot_config(
        cls, astrbot_config: dict[str, Any] | None
    ) -> RsshubPluginConfig:
        if not astrbot_config:
            return cls()

        astrbot_config.pop("download_image_before_send", None)
        if (
            "m3u8_download_timeout" in astrbot_config
            and "basic_config" in astrbot_config
        ):
            astrbot_config["basic_config"]["download_media_timeout"] = (
                astrbot_config.pop("m3u8_download_timeout")
            )

        basic_cfg = astrbot_config.get("basic_config", {})
        global_cfg = astrbot_config.get("global_config", {})
        ffmpeg_cfg = astrbot_config.get("ffmpeg", {})
        content_handlers_cfg = astrbot_config.get("content_handlers", {})
        sender_strategies_cfg = astrbot_config.get("sender_strategies")
        route_knowledge_cfg = astrbot_config.get("route_knowledge", {})

        return cls(
            basic_config=BasicConfig.from_dict(basic_cfg),
            global_config=GlobalConfig.from_dict(global_cfg),
            ffmpeg=FFmpegConfig.from_dict(ffmpeg_cfg),
            content_handlers=ContentHandlersConfig.from_dict(content_handlers_cfg),
            sender_strategies=SenderStrategiesConfig.from_config(sender_strategies_cfg),
            route_knowledge=RouteKnowledgeConfig.from_dict(route_knowledge_cfg),
            db_file=astrbot_config.get("db_file", "rsshub.db"),
        )

    def save(self, astrbot_config: AstrBotConfig) -> None:
        config_dict = self.model_dump()
        config_dict.get("basic_config", {}).pop("download_media_before_send", None)
        config_dict["sender_strategies"] = self.sender_strategies.to_config_dict()
        for key, value in config_dict.items():
            if key != "db_file":
                astrbot_config[key] = value
        astrbot_config.save_config()

    @property
    def proxy(self) -> str:
        return self.basic_config.proxy

    @property
    def rsshub_base_url(self) -> str:
        return self.basic_config.rsshub_base_url

    @property
    def timeout(self) -> int:
        return self.basic_config.timeout

    @property
    def minimal_interval(self) -> int:
        return self.basic_config.minimal_interval

    @property
    def hash_history_min(self) -> int:
        return self.basic_config.hash_history_min

    @property
    def hash_history_multiplier(self) -> int:
        return self.basic_config.hash_history_multiplier

    @property
    def hash_history_hard_limit(self) -> int:
        return self.basic_config.hash_history_hard_limit

    @property
    def tracking_query_params(self) -> list[str]:
        return self.basic_config.tracking_query_params

    @property
    def failed_queue_capacity(self) -> int:
        return self.basic_config.failed_queue_capacity

    @property
    def failed_queue_max_retries(self) -> int:
        return self.basic_config.failed_queue_max_retries

    @property
    def deduplicate_multi_bot(self) -> bool:
        return self.basic_config.deduplicate_multi_bot

    @property
    def bootstrap_skip_history(self) -> bool:
        return self.basic_config.bootstrap_skip_history

    @property
    def history_entry_limit(self) -> int:
        return self.basic_config.history_entry_limit

    @property
    def history_retention_days(self) -> int:
        return self.basic_config.history_retention_days

    @property
    def default_interval(self) -> int:
        return self.global_config.interval

    @property
    def download_media_before_send(self) -> bool:
        return True

    @property
    def download_media_timeout(self) -> int:
        return self.basic_config.download_media_timeout

    @property
    def download_image_before_send(self) -> bool:
        return True
