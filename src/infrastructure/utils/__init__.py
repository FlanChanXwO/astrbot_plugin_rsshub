"""基础设施通用工具包"""

__all__ = [
    # Logger
    "get_logger",
    # Concurrent
    "AsyncTool",
    "retry",
    "timeout",
    "semaphore",
    # Expression Parser
    "ExpressionParser",
    "ExpressionEvaluator",
    "CompiledExpression",
    # Lock
    "LockManager",
    "get_lock_manager",
    "locked",
    # Cache
    "BaseCache",
    "MemoryCache",
    "DiskCache",
    "HybridCache",
    "CacheProviderType",
    "get_memory_cache",
    "set_cache_backend",
    "caching",
    "cacheput",
    "cacheevict",
    # FFmpeg
    "FFmpegTool",
    # Media Dispatch
    "MediaDispatchInfo",
    "MediaDispatchResolver",
    "MediaTypeDetection",
    "detect_media_bytes",
    "detect_media_file",
    "detect_media_hint",
    # Normalizer
    "normalize_text",
    "normalize_identifier",
    "normalize_path",
    "normalize_config_positive_int",
    # Paths
    "PLUGIN_NAME",
    "PLUGIN_ROOT",
    "get_plugin_data_dir",
    "get_plugin_cache_dir",
    "get_plugin_export_dir",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "BaseCache": ("caching", "BaseCache"),
    "CacheProviderType": ("caching", "CacheProviderType"),
    "DiskCache": ("caching", "DiskCache"),
    "HybridCache": ("caching", "HybridCache"),
    "MemoryCache": ("caching", "MemoryCache"),
    "cacheevict": ("caching", "cacheevict"),
    "cacheput": ("caching", "cacheput"),
    "caching": ("caching", "caching"),
    "get_memory_cache": ("caching", "get_memory_cache"),
    "set_cache_backend": ("caching", "set_cache_backend"),
    "AsyncTool": ("concurrent", "AsyncTool"),
    "retry": ("concurrent", "retry"),
    "semaphore": ("concurrent", "semaphore"),
    "timeout": ("concurrent", "timeout"),
    "CompiledExpression": ("expression_parser", "CompiledExpression"),
    "ExpressionEvaluator": ("expression_parser", "ExpressionEvaluator"),
    "ExpressionParser": ("expression_parser", "ExpressionParser"),
    "FFmpegTool": ("ffmpeg_helper", "FFmpegTool"),
    "LockManager": ("lock", "LockManager"),
    "get_lock_manager": ("lock", "get_lock_manager"),
    "locked": ("lock", "locked"),
    "get_logger": ("logger", "get_logger"),
    "MediaDispatchInfo": ("media_dispatch", "MediaDispatchInfo"),
    "MediaDispatchResolver": ("media_dispatch", "MediaDispatchResolver"),
    "MediaTypeDetection": ("media_type_detector", "MediaTypeDetection"),
    "detect_media_bytes": ("media_type_detector", "detect_media_bytes"),
    "detect_media_file": ("media_type_detector", "detect_media_file"),
    "detect_media_hint": ("media_type_detector", "detect_media_hint"),
    "normalize_config_positive_int": (
        "normalizer",
        "normalize_config_positive_int",
    ),
    "normalize_identifier": ("normalizer", "normalize_identifier"),
    "normalize_path": ("normalizer", "normalize_path"),
    "normalize_text": ("normalizer", "normalize_text"),
    "PLUGIN_NAME": ("paths", "PLUGIN_NAME"),
    "PLUGIN_ROOT": ("paths", "PLUGIN_ROOT"),
    "get_plugin_cache_dir": ("paths", "get_plugin_cache_dir"),
    "get_plugin_data_dir": ("paths", "get_plugin_data_dir"),
    "get_plugin_export_dir": ("paths", "get_plugin_export_dir"),
}


def __getattr__(name: str):
    """按需加载工具模块，避免无关可选依赖阻塞轻量路径。"""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    from importlib import import_module

    value = getattr(import_module(f"{__name__}.{module_name}"), attr_name)
    globals()[name] = value
    return value
