"""RSSHub Plugin ConfigProxy Singleton

配置代理单例模块，提供全局配置访问接口。
支持细粒度锁、配置热重载和钩子机制。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from .runtime_config import RuntimeConfig


class ConfigProxy:
    """RSSHub Plugin 配置代理单例

    使用方式:
        from ..config import cfg

        # 直接访问属性（读操作无锁）
        timeout = cfg.timeout
        ffmpeg_cfg = cfg.ffmpeg

        # 检查是否已初始化
        if cfg:
            ...

    配置修改（写操作加锁）:
        await cfg.set_value("timeout", 60)
        await cfg.reload(new_config)  # 完整重载

    注册重载钩子:
        def on_reload():
            # 清理缓存或重新初始化
            pass
        ConfigProxy.register_reload_hook(on_reload)
    """

    _instance: ConfigProxy | None = None
    _config: RuntimeConfig | None = None
    _write_lock: asyncio.Lock = None  # type: ignore[assignment]
    _reload_hooks: list[Callable[[], Any]] = []
    _initialized: bool = False

    def __new__(cls) -> ConfigProxy:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            if cls._write_lock is None:
                cls._write_lock = asyncio.Lock()
        return cls._instance

    @classmethod
    async def init(cls, config: RuntimeConfig) -> None:
        """初始化配置（插件启动时调用一次）

        Args:
            config: RuntimeConfig 实例
        """
        instance = cls()
        instance._config = config
        instance._initialized = True

    @classmethod
    async def reload(cls, config: RuntimeConfig) -> None:
        """重新加载完整配置（写操作加锁）

        触发所有已注册的重载钩子。

        Args:
            config: 新的 RuntimeConfig 实例
        """
        instance = cls()
        if instance._write_lock is None:
            instance._write_lock = asyncio.Lock()

        async with instance._write_lock:
            instance._config = config

        # 触发重载钩子
        for hook in cls._reload_hooks:
            try:
                result = hook()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                # 钩子异常不应影响配置重载
                import logging

                logging.getLogger(__name__).warning(
                    f"Config reload hook failed: {e}", exc_info=True
                )

    @classmethod
    async def set_value(cls, key: str, value: Any) -> None:
        """设置单个配置项值（写操作加锁）

        Args:
            key: 配置项名称（支持点号分隔，如 "ffmpeg.video_transcode"）
            value: 配置值

        Raises:
            RuntimeError: 配置未初始化
            AttributeError: 配置项不存在
        """
        instance = cls()
        if instance._config is None:
            raise RuntimeError("ConfigProxy not initialized. Call init() first.")

        if instance._write_lock is None:
            instance._write_lock = asyncio.Lock()

        async with instance._write_lock:
            if "." in key:
                # 处理嵌套属性，如 "ffmpeg.video_transcode"
                parts = key.split(".")
                target = instance._config
                for part in parts[:-1]:
                    target = getattr(target, part)
                setattr(target, parts[-1], value)
            else:
                setattr(instance._config, key, value)

    @classmethod
    def register_reload_hook(cls, hook: Callable[[], Any]) -> None:
        """注册配置重载钩子

        钩子函数在每次配置 reload() 后被调用。
        可以是同步或异步函数。

        Args:
            hook: 无参回调函数
        """
        if hook not in cls._reload_hooks:
            cls._reload_hooks.append(hook)

    @classmethod
    def unregister_reload_hook(cls, hook: Callable[[], Any]) -> None:
        """注销配置重载钩子

        Args:
            hook: 之前注册的回调函数
        """
        if hook in cls._reload_hooks:
            cls._reload_hooks.remove(hook)

    @classmethod
    def get(cls) -> RuntimeConfig:
        """获取配置实例（读操作不加锁）

        Returns:
            RuntimeConfig 实例

        Raises:
            RuntimeError: 配置未初始化
        """
        instance = cls()
        if instance._config is None:
            raise RuntimeError(
                "ConfigProxy not initialized. Call init() in plugin initialize()."
            )
        return instance._config

    @classmethod
    def is_initialized(cls) -> bool:
        """检查是否已初始化

        Returns:
            True 如果已初始化
        """
        return cls._initialized and cls._instance is not None

    def __getattr__(self, name: str) -> Any:
        """代理属性访问到 RuntimeConfig

        这使得可以直接使用 cfg.timeout, cfg.ffmpeg 等语法。

        Args:
            name: 属性名

        Returns:
            属性值

        Raises:
            RuntimeError: 配置未初始化
            AttributeError: 属性不存在
        """
        if self._config is None:
            raise RuntimeError(
                "ConfigProxy not initialized. Call init() in plugin initialize()."
            )
        return getattr(self._config, name)

    def __bool__(self) -> bool:
        """检查是否已初始化

        使得可以使用 `if cfg:` 判断。
        """
        return self._initialized and self._config is not None

    def __repr__(self) -> str:
        status = "initialized" if self else "uninitialized"
        return f"ConfigProxy({status})"


# 全局单例实例
# 使用方式: from ..config import cfg
cfg = ConfigProxy()


# 便捷函数
def get_config() -> RuntimeConfig:
    """获取配置实例的便捷函数"""
    return ConfigProxy.get()


def is_config_ready() -> bool:
    """检查配置是否已就绪"""
    return ConfigProxy.is_initialized()
