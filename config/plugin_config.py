"""RSSHub Plugin Configuration

统一的配置管理类，提供类型安全的配置访问。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from astrbot.api import AstrBotConfig


@dataclass
class TranslationConfig:
    """翻译配置"""

    provider: str = "google"
    target_lang: str = "zh-CN"
    auto_translate: bool = False
    force_translate: bool = False
    translate_title: bool = True
    translate_content: bool = True
    display_orignal_content: bool = False
    cache_translations: bool = True
    translation_template: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TranslationConfig:
        """从字典创建配置"""
        if not data:
            return cls()

        return cls(
            provider=data.get("provider", "google"),
            target_lang=data.get("target_lang", "zh-CN"),
            auto_translate=data.get("auto_translate", False),
            force_translate=data.get("force_translate", False),
            translate_title=data.get("translate_title", True),
            translate_content=data.get("translate_content", True),
            display_orignal_content=data.get("display_orignal_content", False),
            cache_translations=data.get("cache_translations", True),
            translation_template=data.get("translation_template", []),
        )


@dataclass
class FFmpegConfig:
    """FFmpeg 配置"""

    video_transcode: bool = False
    video_transcode_timeout: int = 120
    gif_transcode: bool = False
    gif_transcode_timeout: int = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> FFmpegConfig:
        """从字典创建配置"""
        if not data:
            return cls()

        return cls(
            video_transcode=data.get("video_transcode", False),
            video_transcode_timeout=data.get("video_transcode_timeout", 120),
            gif_transcode=data.get("gif_transcode", False),
            gif_transcode_timeout=data.get("gif_transcode_timeout", 60),
        )


@dataclass
class WebUIConfig:
    """WebUI 配置"""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 9191
    auth_enabled: bool = True
    password: str = ""
    session_timeout: int = 3600

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> WebUIConfig:
        """从字典创建配置"""
        if not data:
            return cls()

        return cls(
            enabled=data.get("enabled", False),
            host=data.get("host", "0.0.0.0"),
            port=data.get("port", 9191),
            auth_enabled=data.get("auth_enabled", True),
            password=data.get("password", ""),
            session_timeout=data.get("session_timeout", 3600),
        )


@dataclass
class SenderStrategiesConfig:
    """发送策略配置"""

    telegram: bool = True
    aiocqhttp: bool = True
    weixin_oc: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SenderStrategiesConfig:
        """从字典创建配置"""
        if not data:
            return cls()

        return cls(
            telegram=data.get("telegram", True),
            aiocqhttp=data.get("aiocqhttp", True),
            weixin_oc=data.get("weixin_oc", True),
        )


@dataclass
class PlatformSharedDataConfig:
    """平台共享数据配置"""

    aiocqhttp: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PlatformSharedDataConfig:
        """从字典创建配置"""
        if not data:
            return cls()

        return cls(aiocqhttp=data.get("aiocqhttp", False))


@dataclass
class RsshubPluginConfig:
    """RSSHub 插件统一配置类

    使用示例:
        config = RsshubPluginConfig.from_astrbot_config(astrbot_config_dict)
        print(config.rsshub_base_url)
        print(config.translation.auto_translate)
        print(config.ffmpeg.video_transcode)
    """

    # 网络配置
    proxy: str = ""
    rsshub_base_url: str = "https://rsshub.app"
    timeout: int = 30

    # 监控配置
    default_interval: int = 10
    minimal_interval: int = 1
    bootstrap_skip_history: bool = True
    history_entry_limit: int = 10

    # 去重配置
    hash_history_min: int = 200
    hash_history_multiplier: int = 2
    hash_history_hard_limit: int = 5000
    tracking_query_params: list[str] = field(
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

    # 发送配置
    download_image_before_send: bool = True
    failed_queue_capacity: int = 50
    failed_queue_max_retries: int = 3
    deduplicate_multi_bot: bool = True
    debug_payload: bool = False

    # 子配置对象
    ffmpeg: FFmpegConfig = field(default_factory=FFmpegConfig)
    sender_strategies: SenderStrategiesConfig = field(
        default_factory=SenderStrategiesConfig
    )
    platform_shared_data: PlatformSharedDataConfig = field(
        default_factory=PlatformSharedDataConfig
    )
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    webui: WebUIConfig = field(default_factory=WebUIConfig)

    # 数据库配置
    db_file: str = "rsshub.db"

    @classmethod
    def from_astrbot_config(
        cls, astrbot_config: dict[str, Any] | None
    ) -> RsshubPluginConfig:
        """从 AstrBot 配置字典创建配置对象

        Args:
            astrbot_config: AstrBot 配置字典

        Returns:
            RsshubPluginConfig 实例
        """
        if not astrbot_config:
            return cls()

        # 提取各个配置项
        ffmpeg_cfg = astrbot_config.get("ffmpeg", {})
        sender_strategies_cfg = astrbot_config.get("sender_strategies", {})
        platform_shared_data_cfg = astrbot_config.get("platform_shared_data", {})
        translation_cfg = astrbot_config.get("translation", {})
        webui_cfg = astrbot_config.get("webui", {})

        return cls(
            # 网络配置
            proxy=astrbot_config.get("proxy", ""),
            rsshub_base_url=astrbot_config.get("rsshub_base_url", "https://rsshub.app"),
            timeout=astrbot_config.get("timeout", 30),
            # 监控配置
            default_interval=astrbot_config.get("default_interval", 10),
            minimal_interval=astrbot_config.get("minimal_interval", 1),
            bootstrap_skip_history=astrbot_config.get("bootstrap_skip_history", True),
            history_entry_limit=astrbot_config.get("history_entry_limit", 10),
            # 去重配置
            hash_history_min=astrbot_config.get("hash_history_min", 200),
            hash_history_multiplier=astrbot_config.get("hash_history_multiplier", 2),
            hash_history_hard_limit=astrbot_config.get("hash_history_hard_limit", 5000),
            tracking_query_params=astrbot_config.get(
                "tracking_query_params",
                [
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
                ],
            ),
            # 发送配置
            download_image_before_send=astrbot_config.get(
                "download_image_before_send", True
            ),
            failed_queue_capacity=astrbot_config.get("failed_queue_capacity", 50),
            failed_queue_max_retries=astrbot_config.get("failed_queue_max_retries", 3),
            deduplicate_multi_bot=astrbot_config.get("deduplicate_multi_bot", True),
            debug_payload=astrbot_config.get("debug_payload", False),
            # 子配置对象
            ffmpeg=FFmpegConfig.from_dict(ffmpeg_cfg),
            sender_strategies=SenderStrategiesConfig.from_dict(sender_strategies_cfg),
            platform_shared_data=PlatformSharedDataConfig.from_dict(
                platform_shared_data_cfg
            ),
            translation=TranslationConfig.from_dict(translation_cfg),
            webui=WebUIConfig.from_dict(webui_cfg),
            # 数据库配置
            db_file=astrbot_config.get("db_file", "rsshub.db"),
        )

    def to_dict(self) -> dict[str, Any]:
        """将配置转换为字典（用于保存）"""
        return {
            "proxy": self.proxy,
            "rsshub_base_url": self.rsshub_base_url,
            "timeout": self.timeout,
            "default_interval": self.default_interval,
            "minimal_interval": self.minimal_interval,
            "bootstrap_skip_history": self.bootstrap_skip_history,
            "history_entry_limit": self.history_entry_limit,
            "hash_history_min": self.hash_history_min,
            "hash_history_multiplier": self.hash_history_multiplier,
            "hash_history_hard_limit": self.hash_history_hard_limit,
            "tracking_query_params": self.tracking_query_params,
            "download_image_before_send": self.download_image_before_send,
            "failed_queue_capacity": self.failed_queue_capacity,
            "failed_queue_max_retries": self.failed_queue_max_retries,
            "deduplicate_multi_bot": self.deduplicate_multi_bot,
            "debug_payload": self.debug_payload,
            "ffmpeg": {
                "video_transcode": self.ffmpeg.video_transcode,
                "video_transcode_timeout": self.ffmpeg.video_transcode_timeout,
                "gif_transcode": self.ffmpeg.gif_transcode,
                "gif_transcode_timeout": self.ffmpeg.gif_transcode_timeout,
            },
            "sender_strategies": {
                "telegram": self.sender_strategies.telegram,
                "aiocqhttp": self.sender_strategies.aiocqhttp,
                "weixin_oc": self.sender_strategies.weixin_oc,
            },
            "platform_shared_data": {
                "aiocqhttp": self.platform_shared_data.aiocqhttp,
            },
            "translation": {
                "provider": self.translation.provider,
                "target_lang": self.translation.target_lang,
                "auto_translate": self.translation.auto_translate,
                "force_translate": self.translation.force_translate,
                "translate_title": self.translation.translate_title,
                "translate_content": self.translation.translate_content,
                "display_orignal_content": self.translation.display_orignal_content,
                "cache_translations": self.translation.cache_translations,
                "translation_template": self.translation.translation_template,
            },
            "webui": {
                "enabled": self.webui.enabled,
                "host": self.webui.host,
                "port": self.webui.port,
                "auth_enabled": self.webui.auth_enabled,
                "password": self.webui.password,
                "session_timeout": self.webui.session_timeout,
            },
            "db_file": self.db_file,
        }

    def save(self, astrbot_config: AstrBotConfig) -> None:
        """保存配置到 AstrBotConfig

        Args:
            astrbot_config: AstrBot 配置对象
        """
        config_dict = self.to_dict()
        for key, value in config_dict.items():
            if key != "db_file":  # 不保存 db_file 到用户配置
                astrbot_config[key] = value
        astrbot_config.save_config()
