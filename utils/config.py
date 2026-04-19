"""RSSHub plugin config bridge for WebUI and commands."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .log_utils import logger

DEFAULT_RSSHUB_BASE_URL = "https://rsshub.app"
DEFAULT_LOCAL_IMPORTS_DIRNAME = "imports"


@dataclass
class PluginConfig:
    """Runtime config with optional AstrBotConfig backing."""

    data_dir: Path
    default_interval: int = 10
    minimal_interval: int = 1
    timeout: int = 30
    proxy: str = ""
    rsshub_base_url: str = DEFAULT_RSSHUB_BASE_URL
    local_imports_dirname: str = DEFAULT_LOCAL_IMPORTS_DIRNAME
    download_image_before_send: bool = True
    qq_official_video_transcode: bool = True
    qq_official_auto_install_ffmpeg: bool = True
    ffmpeg: dict = None
    failed_queue_capacity: int = 50
    failed_queue_max_retries: int = 3
    sender_strategies: dict = None
    deduplicate_multi_bot: bool = True
    bootstrap_skip_history: bool = True
    debug_payload: bool = False
    platform_shared_data: dict = None
    db_file: str = "rsshub.db"
    astrbot_config: AstrBotConfig | None = None

    def __post_init__(self):
        if self.sender_strategies is None:
            self.sender_strategies = {
                "telegram": True,
                "aiocqhttp": True,
                "weixin_oc": True,
            }
        if self.platform_shared_data is None:
            self.platform_shared_data = {"aiocqhttp": False}
        if self.ffmpeg is None:
            self.ffmpeg = {
                "qq_official_video_transcode": bool(self.qq_official_video_transcode),
                "qq_official_auto_install_ffmpeg": bool(
                    self.qq_official_auto_install_ffmpeg
                ),
            }

    @classmethod
    def load(
        cls,
        *,
        plugin_name: str,
        astrbot_config: AstrBotConfig | None = None,
    ) -> "PluginConfig":
        """Load runtime config from AstrBotConfig with legacy fallback."""
        data_dir = Path(get_astrbot_plugin_data_path()) / plugin_name
        data_dir.mkdir(parents=True, exist_ok=True)

        config = cls(data_dir=data_dir, astrbot_config=astrbot_config)

        if astrbot_config is not None:
            config.default_interval = int(astrbot_config.get("default_interval", 10))
            config.minimal_interval = int(astrbot_config.get("minimal_interval", 1))
            config.timeout = int(astrbot_config.get("timeout", 30))
            config.proxy = str(astrbot_config.get("proxy", "") or "")
            config.rsshub_base_url = str(
                astrbot_config.get("rsshub_base_url", DEFAULT_RSSHUB_BASE_URL)
                or DEFAULT_RSSHUB_BASE_URL
            )
            config.download_image_before_send = bool(
                astrbot_config.get("download_image_before_send", True)
            )
            raw_ffmpeg = astrbot_config.get("ffmpeg", {})
            if not isinstance(raw_ffmpeg, dict):
                raw_ffmpeg = {}
            config.qq_official_video_transcode = bool(
                raw_ffmpeg.get(
                    "qq_official_video_transcode",
                    astrbot_config.get("qq_official_video_transcode", True),
                )
            )
            config.qq_official_auto_install_ffmpeg = bool(
                raw_ffmpeg.get(
                    "qq_official_auto_install_ffmpeg",
                    astrbot_config.get("qq_official_auto_install_ffmpeg", True),
                )
            )
            config.ffmpeg = {
                "qq_official_video_transcode": bool(config.qq_official_video_transcode),
                "qq_official_auto_install_ffmpeg": bool(
                    config.qq_official_auto_install_ffmpeg
                ),
            }
            config.failed_queue_capacity = int(
                astrbot_config.get("failed_queue_capacity", 50)
            )
            config.failed_queue_max_retries = int(
                astrbot_config.get("failed_queue_max_retries", 3)
            )
            # Load sender strategies with defaults
            raw_strategies = astrbot_config.get("sender_strategies", {})
            config.sender_strategies = {
                "telegram": bool(raw_strategies.get("telegram", True)),
                "aiocqhttp": bool(raw_strategies.get("aiocqhttp", True)),
                "weixin_oc": bool(raw_strategies.get("weixin_oc", True)),
            }
            # Load multi-bot deduplication
            config.deduplicate_multi_bot = bool(
                astrbot_config.get("deduplicate_multi_bot", True)
            )
            config.bootstrap_skip_history = bool(
                astrbot_config.get("bootstrap_skip_history", True)
            )
            config.debug_payload = bool(astrbot_config.get("debug_payload", False))
            # Load platform shared data
            raw_shared = astrbot_config.get("platform_shared_data", {})
            config.platform_shared_data = {
                "aiocqhttp": bool(raw_shared.get("aiocqhttp", False)),
            }
            return config

        legacy_path = data_dir / "config.json"
        if legacy_path.exists():
            try:
                data = json.loads(legacy_path.read_text(encoding="utf-8"))
                config.default_interval = int(data.get("default_interval", 10))
                config.minimal_interval = int(data.get("minimal_interval", 1))
                config.timeout = int(data.get("timeout", 30))
                config.proxy = str(data.get("proxy", "") or "")
                config.rsshub_base_url = str(
                    data.get("rsshub_base_url", DEFAULT_RSSHUB_BASE_URL)
                    or DEFAULT_RSSHUB_BASE_URL
                )
                config.download_image_before_send = bool(
                    data.get("download_image_before_send", True)
                )
                raw_ffmpeg = data.get("ffmpeg", {})
                if not isinstance(raw_ffmpeg, dict):
                    raw_ffmpeg = {}
                config.qq_official_video_transcode = bool(
                    raw_ffmpeg.get(
                        "qq_official_video_transcode",
                        data.get("qq_official_video_transcode", True),
                    )
                )
                config.qq_official_auto_install_ffmpeg = bool(
                    raw_ffmpeg.get(
                        "qq_official_auto_install_ffmpeg",
                        data.get("qq_official_auto_install_ffmpeg", True),
                    )
                )
                config.ffmpeg = {
                    "qq_official_video_transcode": bool(
                        config.qq_official_video_transcode
                    ),
                    "qq_official_auto_install_ffmpeg": bool(
                        config.qq_official_auto_install_ffmpeg
                    ),
                }
                config.failed_queue_capacity = int(
                    data.get("failed_queue_capacity", 50)
                )
                config.failed_queue_max_retries = int(
                    data.get("failed_queue_max_retries", 3)
                )
                # Load sender strategies with defaults
                raw_strategies = data.get("sender_strategies", {})
                config.sender_strategies = {
                    "telegram": bool(raw_strategies.get("telegram", True)),
                    "aiocqhttp": bool(raw_strategies.get("aiocqhttp", True)),
                    "weixin_oc": bool(raw_strategies.get("weixin_oc", True)),
                }
                # Load multi-bot deduplication
                config.deduplicate_multi_bot = bool(
                    data.get("deduplicate_multi_bot", True)
                )
                config.bootstrap_skip_history = bool(
                    data.get("bootstrap_skip_history", True)
                )
                config.debug_payload = bool(data.get("debug_payload", False))
                # Load platform shared data
                raw_shared = data.get("platform_shared_data", {})
                config.platform_shared_data = {
                    "aiocqhttp": bool(raw_shared.get("aiocqhttp", False)),
                }
                logger.info(f"Loaded legacy config from {legacy_path}")
            except Exception as ex:
                logger.warning(f"Failed to load legacy config file: {ex}")

        return config

    def save(self) -> None:
        """Persist mutable fields to AstrBotConfig if available."""
        if self.astrbot_config is None:
            return

        self.astrbot_config["default_interval"] = int(self.default_interval)
        self.astrbot_config["minimal_interval"] = int(self.minimal_interval)
        self.astrbot_config["timeout"] = int(self.timeout)
        self.astrbot_config["proxy"] = str(self.proxy)
        self.astrbot_config["rsshub_base_url"] = str(self.rsshub_base_url)
        self.astrbot_config["download_image_before_send"] = bool(
            self.download_image_before_send
        )
        self.ffmpeg = {
            "qq_official_video_transcode": bool(self.qq_official_video_transcode),
            "qq_official_auto_install_ffmpeg": bool(
                self.qq_official_auto_install_ffmpeg
            ),
        }
        self.astrbot_config["ffmpeg"] = dict(self.ffmpeg)
        # Keep legacy flat keys for backward compatibility with older runtimes.
        self.astrbot_config["qq_official_video_transcode"] = bool(
            self.qq_official_video_transcode
        )
        self.astrbot_config["qq_official_auto_install_ffmpeg"] = bool(
            self.qq_official_auto_install_ffmpeg
        )
        self.astrbot_config["failed_queue_capacity"] = int(self.failed_queue_capacity)
        self.astrbot_config["failed_queue_max_retries"] = int(
            self.failed_queue_max_retries
        )
        self.astrbot_config["sender_strategies"] = dict(self.sender_strategies)
        self.astrbot_config["deduplicate_multi_bot"] = bool(self.deduplicate_multi_bot)
        self.astrbot_config["bootstrap_skip_history"] = bool(
            self.bootstrap_skip_history
        )
        self.astrbot_config["debug_payload"] = bool(self.debug_payload)
        self.astrbot_config["platform_shared_data"] = dict(self.platform_shared_data)
        self.astrbot_config.save_config()

    @property
    def local_imports_dir(self) -> Path:
        """Return directory for admin local-path import files."""
        return self.data_dir / self.local_imports_dirname

    @property
    def db_path(self) -> str:
        """Return sqlite db path under plugin data directory."""
        return str(self.data_dir / self.db_file)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by key."""
        # Handle sender_strategy_* keys
        if key == "sender_strategy_telegram":
            return self.sender_strategies.get("telegram", True)
        if key == "sender_strategy_aiocqhttp":
            return self.sender_strategies.get("aiocqhttp", True)
        if key == "sender_strategy_weixin_oc":
            return self.sender_strategies.get("weixin_oc", True)
        # Handle platform_shared_data_* keys
        if key == "platform_shared_data_aiocqhttp":
            return self.platform_shared_data.get("aiocqhttp", False)
        if key in {"ffmpeg_qq_official_video_transcode", "qq_official_video_transcode"}:
            return bool(self.ffmpeg.get("qq_official_video_transcode", True))
        if key in {
            "ffmpeg_qq_official_auto_install_ffmpeg",
            "qq_official_auto_install_ffmpeg",
        }:
            return bool(self.ffmpeg.get("qq_official_auto_install_ffmpeg", True))
        return getattr(self, key, default)

    def set(self, key: str, value: Any) -> None:
        """Set known config and persist when possible."""
        # Handle sender_strategy_* keys
        if key == "sender_strategy_telegram":
            self.sender_strategies["telegram"] = bool(value)
            self.save()
            return
        if key == "sender_strategy_aiocqhttp":
            self.sender_strategies["aiocqhttp"] = bool(value)
            self.save()
            return
        if key == "sender_strategy_weixin_oc":
            self.sender_strategies["weixin_oc"] = bool(value)
            self.save()
            return
        # Handle platform_shared_data_* keys
        if key == "platform_shared_data_aiocqhttp":
            self.platform_shared_data["aiocqhttp"] = bool(value)
            self.save()
            return
        if key in {"ffmpeg_qq_official_video_transcode", "qq_official_video_transcode"}:
            parsed = bool(value)
            self.qq_official_video_transcode = parsed
            self.ffmpeg["qq_official_video_transcode"] = parsed
            self.save()
            return
        if key in {
            "ffmpeg_qq_official_auto_install_ffmpeg",
            "qq_official_auto_install_ffmpeg",
        }:
            parsed = bool(value)
            self.qq_official_auto_install_ffmpeg = parsed
            self.ffmpeg["qq_official_auto_install_ffmpeg"] = parsed
            self.save()
            return
        if hasattr(self, key):
            setattr(self, key, value)
            self.save()
        else:
            logger.warning(f"Unknown config key: {key}")
