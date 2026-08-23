"""卡片模板包的本地存储与安装能力。"""

from .download import (
    AiohttpCardTemplateArchiveDownloader,
    CardTemplateDownloadError,
    CardTemplateHttpStatusError,
    CardTemplateNetworkError,
)
from .repository import (
    CardTemplatePackage,
    CardTemplatePackageError,
    CardTemplatePackageRepository,
)
from .reference_lookup import DatabaseCardTemplateReferenceLookup

__all__ = [
    "AiohttpCardTemplateArchiveDownloader",
    "CardTemplateDownloadError",
    "CardTemplateHttpStatusError",
    "CardTemplateNetworkError",
    "DatabaseCardTemplateReferenceLookup",
    "CardTemplatePackage",
    "CardTemplatePackageError",
    "CardTemplatePackageRepository",
]
