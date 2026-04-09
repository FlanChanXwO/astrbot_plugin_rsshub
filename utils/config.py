"""RSSHub plugin config bridge for WebUI and commands."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

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
    failed_queue_capacity: int = 50
    sender_strategies: dict = None
    deduplicate_multi_bot: bool = True
    platform_shared_data: dict = None
    db_file: str = "rsshub.db"
    astrbot_config: AstrBotConfig | None = None

    def __post_init__(self):
        if self.sender_strategies is None:
            self.sender_strategies = {"telegram": True, "aiocqhttp": True}
        if self.platform_shared_data is None:
            self.platform_shared_data = {"aiocqhttp": False}

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
            config.failed_queue_capacity = int(
                astrbot_config.get("failed_queue_capacity", 50)
            )
            # Load sender strategies with defaults
            raw_strategies = astrbot_config.get("sender_strategies", {})
            config.sender_strategies = {
                "telegram": bool(raw_strategies.get("telegram", True)),
                "aiocqhttp": bool(raw_strategies.get("aiocqhttp", True)),
            }
            # Load multi-bot deduplication
            config.deduplicate_multi_bot = bool(
                astrbot_config.get("deduplicate_multi_bot", True)
            )
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
                config.failed_queue_capacity = int(
                    data.get("failed_queue_capacity", 50)
                )
                # Load sender strategies with defaults
                raw_strategies = data.get("sender_strategies", {})
                config.sender_strategies = {
                    "telegram": bool(raw_strategies.get("telegram", True)),
                    "aiocqhttp": bool(raw_strategies.get("aiocqhttp", True)),
                }
                # Load multi-bot deduplication
                config.deduplicate_multi_bot = bool(
                    data.get("deduplicate_multi_bot", True)
                )
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
        self.astrbot_config["failed_queue_capacity"] = int(self.failed_queue_capacity)
        self.astrbot_config["sender_strategies"] = dict(self.sender_strategies)
        self.astrbot_config["deduplicate_multi_bot"] = bool(self.deduplicate_multi_bot)
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
        # Handle platform_shared_data_* keys
        if key == "platform_shared_data_aiocqhttp":
            return self.platform_shared_data.get("aiocqhttp", False)
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
        # Handle platform_shared_data_* keys
        if key == "platform_shared_data_aiocqhttp":
            self.platform_shared_data["aiocqhttp"] = bool(value)
            self.save()
            return
        if hasattr(self, key):
            setattr(self, key, value)
            self.save()
        else:
            logger.warning(f"Unknown config key: {key}")
