"""卡片模板包的本地存储与安装能力。"""

from .builtin import get_builtin_card_template_dirs
from .download import (
    AiohttpCardTemplateArchiveDownloader,
    CardTemplateDownloadError,
    CardTemplateHttpStatusError,
    CardTemplateNetworkError,
)
from .reference_lookup import DatabaseCardTemplateReferenceLookup
from .rendering import (
    CardTemplateRenderError,
    CardTemplateService,
    CardTemplateSnapshot,
)
from .repository import (
    CardTemplatePackage,
    CardTemplatePackageError,
    CardTemplatePackageRepository,
)

__all__ = [
    "AiohttpCardTemplateArchiveDownloader",
    "CardTemplateDownloadError",
    "CardTemplateHttpStatusError",
    "CardTemplateNetworkError",
    "CardTemplatePackage",
    "CardTemplatePackageError",
    "CardTemplatePackageRepository",
    "CardTemplateRenderError",
    "CardTemplateService",
    "CardTemplateSnapshot",
    "DatabaseCardTemplateReferenceLookup",
    "get_builtin_card_template_dirs",
]
