"""内容渲染基础设施。"""

from .card_artifacts import CardArtifactError, CardArtifactStore
from .font_manager import (
    TABLE_FONT_FILENAME,
    ensure_table_font,
    get_runtime_font_dir,
    get_runtime_font_path,
)
from .html_image_renderer import AstrBotHtmlImageRenderer, CardImageRenderError
from .table_image_renderer import (
    TABLE_FONT_DIR_ENV,
    TABLE_FONT_PATH_ENV,
    TableImageRenderer,
    TableImageRenderResult,
    cleanup_ephemeral_generated_media_paths,
    is_ephemeral_generated_media_path,
    resolve_table_image_path,
)

__all__ = [
    "TABLE_FONT_DIR_ENV",
    "TABLE_FONT_FILENAME",
    "TABLE_FONT_PATH_ENV",
    "AstrBotHtmlImageRenderer",
    "CardArtifactError",
    "CardArtifactStore",
    "CardImageRenderError",
    "TableImageRenderResult",
    "TableImageRenderer",
    "cleanup_ephemeral_generated_media_paths",
    "ensure_table_font",
    "get_runtime_font_dir",
    "get_runtime_font_path",
    "is_ephemeral_generated_media_path",
    "resolve_table_image_path",
]
