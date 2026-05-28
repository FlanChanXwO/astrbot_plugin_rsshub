"""媒体处理基础设施

提供媒体文件下载、缓存管理和格式转换功能。
"""

__all__ = [
    "HttpMediaFingerprintService",
    "MediaDownloader",
]


def __getattr__(name: str):
    """按需加载媒体适配器，避免 HTTP 下载依赖阻塞轻量导入。"""
    if name == "HttpMediaFingerprintService":
        from .fingerprint_service import HttpMediaFingerprintService

        return HttpMediaFingerprintService
    if name == "MediaDownloader":
        from .media_downloader import MediaDownloader

        return MediaDownloader
    raise AttributeError(name)
