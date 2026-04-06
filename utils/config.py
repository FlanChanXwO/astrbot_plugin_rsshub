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
    db_file: str = "rsshub.db"
    astrbot_config: AstrBotConfig | None = None

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
        return getattr(self, key, default)

    def set(self, key: str, value: Any) -> None:
        """Set known config and persist when possible."""
        if hasattr(self, key):
            setattr(self, key, value)
            self.save()
        else:
            logger.warning(f"Unknown config key: {key}")
