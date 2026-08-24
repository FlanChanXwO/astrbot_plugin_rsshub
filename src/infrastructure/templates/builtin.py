"""内置卡片模板目录 registry。"""

from __future__ import annotations

from pathlib import Path

_BUILTIN_ROOT = Path(__file__).with_name("builtin")


def get_builtin_card_template_dirs() -> tuple[Path, ...]:
    """返回随插件发布的内置模板包目录。"""
    if not _BUILTIN_ROOT.is_dir():
        return ()
    return tuple(
        sorted(
            (
                path
                for path in _BUILTIN_ROOT.iterdir()
                if path.is_dir() and not path.is_symlink()
            ),
            key=lambda path: path.name,
        )
    )
