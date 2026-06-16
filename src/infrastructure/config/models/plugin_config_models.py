"""Pydantic models for persisted AstrBot plugin configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from .sender_strategy_models import SenderStrategiesConfig

if TYPE_CHECKING:
    from astrbot.api import AstrBotConfig

_DEFAULT_MEDIA_TIMEOUT_SECONDS = 300


class BasicConfig(BaseModel):
    """基础设施配置（系统级，不继承）"""

    rsshub_base_url: str = Field(
        default="https://rsshub.app", description="RSSHub基础URL"
    )
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
    download_media_timeout: int = Field(
        default=_DEFAULT_MEDIA_TIMEOUT_SECONDS,
        description="媒体下载超时",
    )

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


class MediaConfig(BaseModel):
    """媒体与转码配置，字段集与 _conf_schema.json media.items 对齐。"""

    image_relay_base_url: str = Field(default="", description="图片反代基础URL")
    media_relay_base_url: str = Field(default="", description="通用媒体反代基础URL")
    media_download_concurrency: int = Field(default=1, description="媒体预下载并发数")
    table_to_image: bool = Field(default=True, description="HTML表格转图片")
    video_transcode: bool = Field(default=False, description="视频转码为MP4(H264)")
    video_transcode_timeout: int = Field(default=120, description="视频转码超时（秒）")
    gif_transcode: bool = Field(default=False, description="无声视频自动转GIF")
    gif_transcode_timeout: int = Field(default=60, description="GIF转码超时（秒）")
    ffmpeg_source: str = Field(default="auto", description="FFmpeg来源")
    ffmpeg_mirror: str = Field(default="auto", description="FFmpeg下载镜像")
    ffmpeg_mirror_custom_url: str = Field(default="", description="自定义FFmpeg镜像URL")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> MediaConfig:
        if not data:
            return cls()
        return cls.model_validate({**cls().model_dump(), **(data or {})})


class HttpConfig(BaseModel):
    """HTTP 网络配置。"""

    proxy: str = Field(default="", description="代理地址")
    timeout: int = Field(default=30, description="请求超时（秒）")
    media_timeout: int = Field(
        default=_DEFAULT_MEDIA_TIMEOUT_SECONDS,
        description="媒体下载超时（秒）",
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HttpConfig:
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


class RouteKnowledgeConfig(BaseModel):
    """RSSHub Routes 知识库同步配置"""

    kb_name: str = Field(default="RSSHub Routes", description="AstrBot 知识库名称")
    embedding_provider_id: str = Field(
        default="", description="默认向量模型 Provider ID"
    )
    rerank_provider_id: str = Field(
        default="", description="默认重排序模型 Provider ID"
    )
    source_mode: str = Field(default="speed_test", description="知识库来源模式")
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
    http_config: HttpConfig = Field(default_factory=HttpConfig)
    global_config: GlobalConfig = Field(default_factory=GlobalConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
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

        astrbot_config = dict(astrbot_config)
        astrbot_config.pop("download_image_before_send", None)
        http_cfg = dict(astrbot_config.get("http_config") or {})
        media_cfg = dict(astrbot_config.get("media") or {})
        if "m3u8_download_timeout" in astrbot_config:
            http_cfg.setdefault(
                "media_timeout", astrbot_config.pop("m3u8_download_timeout")
            )
        if "download_media_timeout" in astrbot_config:
            http_cfg.setdefault(
                "media_timeout", astrbot_config.pop("download_media_timeout")
            )
        basic_cfg = dict(astrbot_config.get("basic_config") or {})
        if "proxy" in basic_cfg:
            http_cfg.setdefault("proxy", basic_cfg.pop("proxy"))
        if "timeout" in basic_cfg:
            http_cfg.setdefault("timeout", basic_cfg.pop("timeout"))
        if "download_media_timeout" in basic_cfg:
            http_cfg.setdefault(
                "media_timeout", basic_cfg.pop("download_media_timeout")
            )
        if "download_media_timeout" in media_cfg:
            http_cfg.setdefault(
                "media_timeout", media_cfg.get("download_media_timeout")
            )

        global_cfg = astrbot_config.get("global_config", {})
        content_handlers_cfg = astrbot_config.get("content_handlers", {})
        sender_strategies_cfg = astrbot_config.get("sender_strategies")
        route_knowledge_cfg = astrbot_config.get("route_knowledge", {})

        return cls(
            basic_config=BasicConfig.from_dict(basic_cfg),
            http_config=HttpConfig.from_dict(http_cfg),
            global_config=GlobalConfig.from_dict(global_cfg),
            media=MediaConfig.from_dict(media_cfg),
            content_handlers=ContentHandlersConfig.from_dict(content_handlers_cfg),
            sender_strategies=SenderStrategiesConfig.from_config(sender_strategies_cfg),
            route_knowledge=RouteKnowledgeConfig.from_dict(route_knowledge_cfg),
            db_file=astrbot_config.get("db_file", "rsshub.db"),
        )

    def to_astrbot_config(self) -> dict[str, Any]:
        config_dict = self.model_dump()
        config_dict.get("basic_config", {}).pop("download_media_before_send", None)
        config_dict.get("basic_config", {}).pop("download_media_timeout", None)
        config_dict.get("basic_config", {}).pop("proxy", None)
        config_dict.get("basic_config", {}).pop("timeout", None)
        config_dict["sender_strategies"] = self.sender_strategies.to_config_dict()
        return config_dict

    def save(self, astrbot_config: AstrBotConfig) -> None:
        config_dict = self.to_astrbot_config()
        for key, value in config_dict.items():
            if key != "db_file":
                astrbot_config[key] = value
        astrbot_config.save_config()

    @property
    def proxy(self) -> str:
        return self.http_config.proxy

    @property
    def rsshub_base_url(self) -> str:
        return self.basic_config.rsshub_base_url

    @property
    def timeout(self) -> int:
        return self.http_config.timeout

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
        return self.http_config.media_timeout

    @property
    def download_image_before_send(self) -> bool:
        return True
