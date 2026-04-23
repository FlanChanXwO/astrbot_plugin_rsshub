"""RSSHub plugin config bridge for WebUI and commands."""

import json
from pathlib import Path

from astrbot.api import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from ..config import RsshubPluginConfig
from .log_utils import logger

DEFAULT_RSSHUB_BASE_URL = "https://rsshub.app"
DEFAULT_LOCAL_IMPORTS_DIRNAME = "imports"


class PluginConfig:
    """Runtime config wrapper with RsshubPluginConfig for type-safe access.

    This class provides backward compatibility with existing code while
    enabling type-safe configuration access through RsshubPluginConfig.

    Usage:
        config = PluginConfig.load(
            plugin_name="astrbot_plugin_rsshub", astrbot_config=...
        )
        # Type-safe access
        print(config.rsshub_config.translation.auto_translate)
        print(config.rsshub_config.ffmpeg.video_transcode)

        # Backward compatibility (deprecated, migrate to rsshub_config)
        print(config.default_interval)
    """

    def __init__(
        self,
        data_dir: Path,
        astrbot_config: AstrBotConfig | None = None,
    ):
        self.data_dir = data_dir
        self.astrbot_config = astrbot_config
        self._rsshub_config: RsshubPluginConfig | None = None

        # Backward compatibility attributes (deprecated)
        if astrbot_config:
            self.default_interval = int(astrbot_config.get("default_interval", 10))
            self.minimal_interval = int(astrbot_config.get("minimal_interval", 1))
            self.timeout = int(astrbot_config.get("timeout", 30))
            self.proxy = str(astrbot_config.get("proxy", "") or "")
            self.rsshub_base_url = str(
                astrbot_config.get("rsshub_base_url", DEFAULT_RSSHUB_BASE_URL)
                or DEFAULT_RSSHUB_BASE_URL
            )
            self.download_image_before_send = bool(
                astrbot_config.get("download_image_before_send", True)
            )
            self.failed_queue_capacity = int(
                astrbot_config.get("failed_queue_capacity", 50)
            )
            self.failed_queue_max_retries = int(
                astrbot_config.get("failed_queue_max_retries", 3)
            )
            self.deduplicate_multi_bot = bool(
                astrbot_config.get("deduplicate_multi_bot", True)
            )
            self.bootstrap_skip_history = bool(
                astrbot_config.get("bootstrap_skip_history", True)
            )
            self.debug_payload = bool(astrbot_config.get("debug_payload", False))
            self.history_entry_limit = int(
                astrbot_config.get("history_entry_limit", 10)
            )
            self.db_file = str(astrbot_config.get("db_file", "rsshub.db"))
        else:
            # Defaults
            self.default_interval = 10
            self.minimal_interval = 1
            self.timeout = 30
            self.proxy = ""
            self.rsshub_base_url = DEFAULT_RSSHUB_BASE_URL
            self.download_image_before_send = True
            self.failed_queue_capacity = 50
            self.failed_queue_max_retries = 3
            self.deduplicate_multi_bot = True
            self.bootstrap_skip_history = True
            self.debug_payload = False
            self.history_entry_limit = 10
            self.db_file = "rsshub.db"

        self.local_imports_dirname = DEFAULT_LOCAL_IMPORTS_DIRNAME

    @property
    def rsshub_config(self) -> RsshubPluginConfig:
        """Get the type-safe configuration object.

        This is the recommended way to access configuration.

        Returns:
            RsshubPluginConfig instance
        """
        if self._rsshub_config is None:
            config_dict = dict(self.astrbot_config) if self.astrbot_config else None
            self._rsshub_config = RsshubPluginConfig.from_astrbot_config(config_dict)
        return self._rsshub_config

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

        # Try to load legacy config file for backward compatibility
        if astrbot_config is None:
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
                    config.failed_queue_max_retries = int(
                        data.get("failed_queue_max_retries", 3)
                    )
                    config.deduplicate_multi_bot = bool(
                        data.get("deduplicate_multi_bot", True)
                    )
                    config.bootstrap_skip_history = bool(
                        data.get("bootstrap_skip_history", True)
                    )
                    config.debug_payload = bool(data.get("debug_payload", False))
                    config.history_entry_limit = int(
                        data.get("history_entry_limit", 10)
                    )
                    logger.info(f"Loaded legacy config from {legacy_path}")
                except Exception as ex:
                    logger.warning(f"Failed to load legacy config file: {ex}")

        return config

    def save(self) -> None:
        """Persist configuration to AstrBotConfig if available."""
        if self.astrbot_config is None:
            return

        # Update AstrBotConfig from rsshub_config
        config_dict = self.rsshub_config.to_dict()

        # Copy to astrbot_config
        for key, value in config_dict.items():
            if key != "db_file":  # Don't save db_file to user config
                self.astrbot_config[key] = value

        self.astrbot_config.save_config()

    @property
    def local_imports_dir(self) -> Path:
        """Return directory for admin local-path import files."""
        return self.data_dir / self.local_imports_dirname

    @property
    def db_path(self) -> str:
        """Return sqlite db path under plugin data directory."""
        return str(self.data_dir / self.db_file)

    def get(self, key: str, default=None):
        """Get a config value by key (backward compatibility).

        Deprecated: Use rsshub_config instead.
        """
        logger.warning(
            f"PluginConfig.get() is deprecated. Use config.rsshub_config.{key} instead."
        )
        return getattr(self, key, default)

    def set(self, key: str, value):
        """Set a config value by key (backward compatibility).

        Deprecated: Use rsshub_config instead.
        """
        logger.warning(
            f"PluginConfig.set() is deprecated. "
            f"Modify config.rsshub_config.{key} instead."
        )
        if hasattr(self, key):
            setattr(self, key, value)
            self.save()
        else:
            logger.warning(f"Unknown config key: {key}")
