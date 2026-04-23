"""RSSHub Plugin Runtime Configuration.

运行时配置包装器，提供数据目录管理和配置保存功能。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .plugin_config import RsshubPluginConfig


class RuntimeConfig:
    """运行时配置包装器

    职责:
    - 管理插件数据目录
    - 加载和保存配置
    - 代理所有配置访问到 RsshubPluginConfig

    使用示例:
        config = RuntimeConfig(
            plugin_name="astrbot_plugin_rsshub",
            astrbot_config=astrbot_config_dict,
        )
        # 直接访问配置属性
        print(config.proxy)
        print(config.ffmpeg.video_transcode)
        print(config.translation.auto_translate)

        # 访问运行时属性
        print(config.data_dir)
        print(config.db_path)
        print(config.local_imports_dir)

        # 保存配置
        config.save()
    """

    def __init__(
        self,
        *,
        plugin_name: str,
        astrbot_config: dict[str, Any] | None = None,
    ):
        """初始化运行时配置

        Args:
            plugin_name: 插件名称
            astrbot_config: AstrBot 配置字典
        """
        self._plugin_name = plugin_name
        self._astrbot_config = astrbot_config

        # 数据目录管理
        self.data_dir = Path(get_astrbot_plugin_data_path()) / plugin_name
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 加载配置
        self.config = RsshubPluginConfig.from_astrbot_config(astrbot_config)

    @property
    def db_path(self) -> str:
        """返回数据库文件路径"""
        return str(self.data_dir / (self.config.db_file or "rsshub.db"))

    @property
    def local_imports_dir(self) -> Path:
        """返回本地导入文件目录"""
        return self.data_dir / "imports"

    def save(self) -> None:
        """保存配置到 AstrBotConfig"""
        if self._astrbot_config:
            self.config.save(self._astrbot_config)

    def __getattr__(self, name: str):
        """代理所有配置访问到 RsshubPluginConfig

        这使得可以直接访问 config.proxy, config.ffmpeg 等属性
        """
        return getattr(self.config, name)

    def __repr__(self) -> str:
        return f"RuntimeConfig(plugin_name={self._plugin_name!r}, data_dir={self.data_dir!r})"
