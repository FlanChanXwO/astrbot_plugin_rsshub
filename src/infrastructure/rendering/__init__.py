"""内容渲染基础设施。"""

from .font_manager import (
    TABLE_FONT_FILENAME,
    ensure_table_font,
    get_runtime_font_dir,
    get_runtime_font_path,
)
from .table_image_renderer import (
    TABLE_FONT_DIR_ENV,
    TABLE_FONT_PATH_ENV,
    TableImageRenderer,
    TableImageRenderResult,
    resolve_table_image_path,
)

__all__ = [
    "TABLE_FONT_DIR_ENV",
    "TABLE_FONT_FILENAME",
    "TABLE_FONT_PATH_ENV",
    "TableImageRenderer",
    "TableImageRenderResult",
    "ensure_table_font",
    "get_runtime_font_dir",
    "get_runtime_font_path",
    "resolve_table_image_path",
]
