"""RSSHub Plugin Configuration

统一的配置管理类，提供类型安全的配置访问。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from astrbot.api import AstrBotConfig


@dataclass
class BasicConfig:
    """基础设施配置（系统级，不继承）"""

    # 网络配置
    proxy: str = ""
    rsshub_base_url: str = "https://rsshub.app"
    timeout: int = 30

    # 系统限制
    minimal_interval: int = 1

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

    # 队列与策略
    failed_queue_capacity: int = 50
    failed_queue_max_retries: int = 3
    deduplicate_multi_bot: bool = True
    bootstrap_skip_history: bool = True
    debug_payload: bool = False
    history_entry_limit: int = 0  # 默认不限制，避免漏推

    # 媒体配置
    download_media_before_send: bool = False
    download_media_timeout: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BasicConfig:
        """从字典创建配置"""
        if not data:
            return cls()

        return cls(
            proxy=data.get("proxy", ""),
            rsshub_base_url=data.get("rsshub_base_url", "https://rsshub.app"),
            timeout=data.get("timeout", 30),
            minimal_interval=data.get("minimal_interval", 1),
            hash_history_min=data.get("hash_history_min", 200),
            hash_history_multiplier=data.get("hash_history_multiplier", 2),
            hash_history_hard_limit=data.get("hash_history_hard_limit", 5000),
            tracking_query_params=data.get(
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
            failed_queue_capacity=data.get("failed_queue_capacity", 50),
            failed_queue_max_retries=data.get("failed_queue_max_retries", 3),
            deduplicate_multi_bot=data.get("deduplicate_multi_bot", True),
            bootstrap_skip_history=data.get("bootstrap_skip_history", True),
            debug_payload=data.get("debug_payload", False),
            history_entry_limit=data.get(
                "history_entry_limit", 0
            ),  # 默认0不限制，避免漏推
            download_media_before_send=data.get("download_media_before_send", False),
            download_media_timeout=data.get("download_media_timeout", 30),
        )


@dataclass
class GlobalConfig:
    """全局默认配置（订阅级，可继承）

    用户友好的配置格式（bool/options），内部转换为数据库存储值
    """

    # 基础配置
    interval: int = 10
    notify: bool = True
    send_mode: str = "自动"
    length_limit: int = 0

    # 显示配置
    link_preview: str = "自动"
    display_author: str = "自动"
    display_via: str = "自动"
    display_title: str = "自动"
    display_entry_tags: bool = False
    style: str = "RSStT"
    display_media: bool = True

    # 翻译配置
    translate: bool = False
    translate_target_lang: str = "zh-CN"

    # === 值转换方法 ===

    # 映射表：用户值 -> 数据库存储值
    _SEND_MODE_MAP = {"仅链接": -1, "自动": 0, "直接消息": 2}
    _LINK_PREVIEW_MAP = {"自动": 0, "强制启用": 1}
    _DISPLAY_AUTHOR_MAP = {"禁用": -1, "自动": 0, "强制": 1}
    _DISPLAY_VIA_MAP = {"完全禁用": -2, "仅链接": -1, "自动": 0, "强制": 1}
    _DISPLAY_TITLE_MAP = {"禁用": -1, "自动": 0, "强制": 1}
    _STYLE_MAP = {"RSStT": 0, "flowerss": 1}

    # 反向映射表：数据库存储值 -> 用户值
    _SEND_MODE_RMAP = {-1: "仅链接", 0: "自动", 2: "直接消息"}
    _LINK_PREVIEW_RMAP = {0: "自动", 1: "强制启用"}
    _DISPLAY_AUTHOR_RMAP = {-1: "禁用", 0: "自动", 1: "强制"}
    _DISPLAY_VIA_RMAP = {-2: "完全禁用", -1: "仅链接", 0: "自动", 1: "强制"}
    _DISPLAY_TITLE_RMAP = {-1: "禁用", 0: "自动", 1: "强制"}
    _STYLE_RMAP = {0: "RSStT", 1: "flowerss"}

    def to_db_values(self) -> dict[str, Any]:
        """转换为数据库存储的整数值"""
        return {
            "interval": self.interval,
            "notify": 1 if self.notify else 0,
            "send_mode": self._SEND_MODE_MAP.get(self.send_mode, 0),
            "length_limit": self.length_limit,
            "link_preview": self._LINK_PREVIEW_MAP.get(self.link_preview, 0),
            "display_author": self._DISPLAY_AUTHOR_MAP.get(self.display_author, 0),
            "display_via": self._DISPLAY_VIA_MAP.get(self.display_via, 0),
            "display_title": self._DISPLAY_TITLE_MAP.get(self.display_title, 0),
            "display_entry_tags": -1 if not self.display_entry_tags else 0,
            "style": self._STYLE_MAP.get(self.style, 0),
            "display_media": -1 if not self.display_media else 0,
            "translate": 1 if self.translate else 0,
            "translate_target_lang": self.translate_target_lang,
        }

    @classmethod
    def from_db_values(cls, values: dict[str, Any]) -> GlobalConfig:
        """从数据库整数值创建配置"""
        return cls(
            interval=values.get("interval", 10),
            notify=values.get("notify", 1) == 1,
            send_mode=cls._SEND_MODE_RMAP.get(values.get("send_mode", 0), "自动"),
            length_limit=values.get("length_limit", 0),
            link_preview=cls._LINK_PREVIEW_RMAP.get(
                values.get("link_preview", 0), "自动"
            ),
            display_author=cls._DISPLAY_AUTHOR_RMAP.get(
                values.get("display_author", 0), "自动"
            ),
            display_via=cls._DISPLAY_VIA_RMAP.get(values.get("display_via", 0), "自动"),
            display_title=cls._DISPLAY_TITLE_RMAP.get(
                values.get("display_title", 0), "自动"
            ),
            display_entry_tags=values.get("display_entry_tags", -1) != -1,
            style=cls._STYLE_RMAP.get(values.get("style", 0), "RSStT"),
            display_media=values.get("display_media", 0) != -1,
            translate=values.get("translate", 0) == 1,
            translate_target_lang=values.get("translate_target_lang", "zh-CN"),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> GlobalConfig:
        """从字典创建配置（用户友好的格式）"""
        if not data:
            return cls()

        return cls(
            interval=data.get("interval", 10),
            notify=data.get("notify", True),
            send_mode=data.get("send_mode", "自动"),
            length_limit=data.get("length_limit", 0),
            link_preview=data.get("link_preview", "自动"),
            display_author=data.get("display_author", "自动"),
            display_via=data.get("display_via", "自动"),
            display_title=data.get("display_title", "自动"),
            display_entry_tags=data.get("display_entry_tags", False),
            style=data.get("style", "RSStT"),
            display_media=data.get("display_media", True),
            translate=data.get("translate", False),
            translate_target_lang=data.get("translate_target_lang", "zh-CN"),
        )


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
class RsshubPluginConfig:
    """RSSHub 插件统一配置类

    使用示例:
        config = RsshubPluginConfig.from_astrbot_config(astrbot_config_dict)
        print(config.basic_config.rsshub_base_url)
        print(config.global_config.notify)
        print(config.ffmpeg.video_transcode)
    """

    # 基础设施配置（系统级）
    basic_config: BasicConfig = field(default_factory=BasicConfig)

    # 全局默认配置（订阅级，可继承）
    global_config: GlobalConfig = field(default_factory=GlobalConfig)

    # 子配置对象
    ffmpeg: FFmpegConfig = field(default_factory=FFmpegConfig)
    sender_strategies: SenderStrategiesConfig = field(
        default_factory=SenderStrategiesConfig
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

        # 处理旧格式配置迁移
        # 如果存在顶层旧配置名，将其移到 basic_config 并使用新名称
        if (
            "download_image_before_send" in astrbot_config
            and "basic_config" in astrbot_config
        ):
            astrbot_config["basic_config"]["download_media_before_send"] = (
                astrbot_config.pop("download_image_before_send")
            )
        if (
            "m3u8_download_timeout" in astrbot_config
            and "basic_config" in astrbot_config
        ):
            astrbot_config["basic_config"]["download_media_timeout"] = (
                astrbot_config.pop("m3u8_download_timeout")
            )

        # 提取各个配置项
        basic_cfg = astrbot_config.get("basic_config", {})
        global_cfg = astrbot_config.get("global_config", {})
        ffmpeg_cfg = astrbot_config.get("ffmpeg", {})
        sender_strategies_cfg = astrbot_config.get("sender_strategies", {})
        translation_cfg = astrbot_config.get("translation", {})
        webui_cfg = astrbot_config.get("webui", {})

        return cls(
            basic_config=BasicConfig.from_dict(basic_cfg),
            global_config=GlobalConfig.from_dict(global_cfg),
            ffmpeg=FFmpegConfig.from_dict(ffmpeg_cfg),
            sender_strategies=SenderStrategiesConfig.from_dict(sender_strategies_cfg),
            translation=TranslationConfig.from_dict(translation_cfg),
            webui=WebUIConfig.from_dict(webui_cfg),
            db_file=astrbot_config.get("db_file", "rsshub.db"),
        )

    def to_dict(self) -> dict[str, Any]:
        """将配置转换为字典（用于保存）"""
        return {
            "basic_config": {
                "proxy": self.basic_config.proxy,
                "rsshub_base_url": self.basic_config.rsshub_base_url,
                "timeout": self.basic_config.timeout,
                "minimal_interval": self.basic_config.minimal_interval,
                "hash_history_min": self.basic_config.hash_history_min,
                "hash_history_multiplier": self.basic_config.hash_history_multiplier,
                "hash_history_hard_limit": self.basic_config.hash_history_hard_limit,
                "tracking_query_params": self.basic_config.tracking_query_params,
                "failed_queue_capacity": self.basic_config.failed_queue_capacity,
                "failed_queue_max_retries": self.basic_config.failed_queue_max_retries,
                "deduplicate_multi_bot": self.basic_config.deduplicate_multi_bot,
                "bootstrap_skip_history": self.basic_config.bootstrap_skip_history,
                "debug_payload": self.basic_config.debug_payload,
                "history_entry_limit": self.basic_config.history_entry_limit,
                "download_media_before_send": self.basic_config.download_media_before_send,
                "download_media_timeout": self.basic_config.download_media_timeout,
            },
            "global_config": {
                "interval": self.global_config.interval,
                "notify": self.global_config.notify,
                "send_mode": self.global_config.send_mode,
                "length_limit": self.global_config.length_limit,
                "link_preview": self.global_config.link_preview,
                "display_author": self.global_config.display_author,
                "display_via": self.global_config.display_via,
                "display_title": self.global_config.display_title,
                "display_entry_tags": self.global_config.display_entry_tags,
                "style": self.global_config.style,
                "display_media": self.global_config.display_media,
                "translate": self.global_config.translate,
                "translate_target_lang": self.global_config.translate_target_lang,
            },
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

    # === 向后兼容属性 ===

    @property
    def proxy(self) -> str:
        """代理地址（兼容旧代码）"""
        return self.basic_config.proxy

    @property
    def rsshub_base_url(self) -> str:
        """RSSHub 域名（兼容旧代码）"""
        return self.basic_config.rsshub_base_url

    @property
    def timeout(self) -> int:
        """请求超时（兼容旧代码）"""
        return self.basic_config.timeout

    @property
    def minimal_interval(self) -> int:
        """最小监控间隔（兼容旧代码）"""
        return self.basic_config.minimal_interval

    @property
    def hash_history_min(self) -> int:
        """去重历史最小值（兼容旧代码）"""
        return self.basic_config.hash_history_min

    @property
    def hash_history_multiplier(self) -> int:
        """去重历史倍数（兼容旧代码）"""
        return self.basic_config.hash_history_multiplier

    @property
    def hash_history_hard_limit(self) -> int:
        """去重历史硬上限（兼容旧代码）"""
        return self.basic_config.hash_history_hard_limit

    @property
    def tracking_query_params(self) -> list[str]:
        """追踪参数（兼容旧代码）"""
        return self.basic_config.tracking_query_params

    @property
    def failed_queue_capacity(self) -> int:
        """失败队列容量（兼容旧代码）"""
        return self.basic_config.failed_queue_capacity

    @property
    def failed_queue_max_retries(self) -> int:
        """失败队列重试次数（兼容旧代码）"""
        return self.basic_config.failed_queue_max_retries

    @property
    def deduplicate_multi_bot(self) -> bool:
        """多BOT去重（兼容旧代码）"""
        return self.basic_config.deduplicate_multi_bot

    @property
    def bootstrap_skip_history(self) -> bool:
        """首轮跳过历史（兼容旧代码）"""
        return self.basic_config.bootstrap_skip_history

    @property
    def debug_payload(self) -> bool:
        """调试字段（兼容旧代码）"""
        return self.basic_config.debug_payload

    @property
    def history_entry_limit(self) -> int:
        """历史条目限制（兼容旧代码）"""
        return self.basic_config.history_entry_limit

    @property
    def default_interval(self) -> int:
        """默认监控间隔（兼容旧代码）"""
        return self.global_config.interval

    @property
    def download_media_before_send(self) -> bool:
        """先下载后发送（兼容旧代码）"""
        return self.basic_config.download_media_before_send

    @property
    def download_media_timeout(self) -> int:
        """媒体下载超时（兼容旧代码）"""
        return self.basic_config.download_media_timeout

    # 向后兼容的旧名称
    @property
    def download_image_before_send(self) -> bool:
        """先下载后发送（兼容旧代码，请使用 download_media_before_send）"""
        return self.basic_config.download_media_before_send
