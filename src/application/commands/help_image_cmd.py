"""帮助图片命令。

只负责选择预生成帮助图，不在运行时生成图片。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HELP_IMAGE_DIR = Path(__file__).resolve().parents[3] / "assets" / "help"
HELP_IMAGE_LIGHT_PATH = HELP_IMAGE_DIR / "rsshelp_light.png"
HELP_IMAGE_DARK_PATH = HELP_IMAGE_DIR / "rsshelp_dark.png"


class _AstrBotContextLike(Protocol):
    """帮助命令所需的最小 AstrBot Context 接口。"""

    def get_config(self) -> dict: ...


class HelpImageCommand:
    """选择 RSSHub 帮助图。"""

    def __init__(
        self,
        light_path: Path | None = None,
        dark_path: Path | None = None,
    ):
        self._light_path = light_path or HELP_IMAGE_LIGHT_PATH
        self._dark_path = dark_path or HELP_IMAGE_DARK_PATH

    def execute(self, context: _AstrBotContextLike | None = None) -> Path:
        """根据 AstrBot 时区选择日间/夜间帮助图。"""
        now = self._current_time(context)
        primary = self._light_path if 6 <= now.hour < 18 else self._dark_path
        fallback = self._dark_path if primary == self._light_path else self._light_path
        return primary if primary.exists() else fallback

    def _current_time(self, context: _AstrBotContextLike | None) -> datetime:
        timezone_name = self._read_timezone_name(context)
        if not timezone_name:
            return datetime.now()
        try:
            return datetime.now(ZoneInfo(timezone_name))
        except (ZoneInfoNotFoundError, ValueError):
            return datetime.now()

    def _read_timezone_name(self, context: _AstrBotContextLike | None) -> str | None:
        for config in self._iter_configs(context):
            value = config.get("timezone")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _iter_configs(
        self,
        context: _AstrBotContextLike | None,
    ):
        if context is None:
            return

        get_config = getattr(context, "get_config", None)
        if callable(get_config):
            try:
                config = get_config()
                if isinstance(config, dict):
                    yield config
            except Exception:
                pass

        config_mgr = getattr(context, "astrbot_config_mgr", None)
        confs = getattr(config_mgr, "confs", None)
        if isinstance(confs, dict):
            config = confs.get("default")
            if isinstance(config, dict):
                yield config
