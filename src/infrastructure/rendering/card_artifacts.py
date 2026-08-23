"""卡片 HTML/PNG 历史产物仓储。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath

from ..utils.paths import get_plugin_data_dir


class CardArtifactError(ValueError):
    """卡片产物引用或文件操作无效。"""


class CardArtifactStore:
    """在插件数据目录中以受控相对引用保存卡片产物。"""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = Path(storage_dir or get_plugin_data_dir("card_artifacts"))

    def write_html(self, history_id: int, html: str) -> str:
        """原子保存一个历史输出的 HTML。"""
        reference = self._reference(history_id, "card.html")
        self._atomic_write(reference, html.encode("utf-8"))
        return reference

    def write_png(self, history_id: int, image: bytes) -> str:
        """原子保存一个历史输出的 PNG。"""
        reference = self._reference(history_id, "card.png")
        self._atomic_write(reference, image)
        return reference

    def read_html(self, reference: str) -> str:
        """读取受控 HTML 引用；缺失时显式失败。"""
        try:
            return self.path(reference).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CardArtifactError(
                f"无法读取卡片 HTML 产物 {reference!r}: {exc}"
            ) from exc

    def path(self, reference: str) -> Path:
        """解析受控引用，并确认文件真实存在于产物目录。"""
        relative = PurePosixPath(reference)
        if (
            not reference
            or relative.is_absolute()
            or len(relative.parts) != 2
            or ".." in relative.parts
            or relative.name not in {"card.html", "card.png"}
        ):
            raise CardArtifactError(f"无效的卡片产物引用: {reference!r}")
        path = self._storage_dir.joinpath(*relative.parts)
        try:
            storage_root = self._storage_dir.resolve()
            resolved = path.resolve(strict=True)
            resolved.relative_to(storage_root)
        except (OSError, ValueError) as exc:
            raise CardArtifactError(
                f"卡片产物不在受控产物目录中: {reference!r}"
            ) from exc
        if path.is_symlink() or not resolved.is_file():
            raise CardArtifactError(f"卡片产物不存在: {reference!r}")
        return resolved

    @staticmethod
    def _reference(history_id: int, filename: str) -> str:
        if history_id <= 0:
            raise CardArtifactError("卡片产物要求已持久化的历史 ID")
        return f"{history_id}/{filename}"

    def _atomic_write(self, reference: str, data: bytes) -> None:
        destination = self._storage_dir.joinpath(*PurePosixPath(reference).parts)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        storage_root = self._storage_dir.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.parent.resolve().relative_to(storage_root)
        except ValueError as exc:
            raise CardArtifactError(
                f"卡片产物目标不在受控产物目录中: {reference!r}"
            ) from exc
        if destination.parent.is_symlink() or destination.is_symlink():
            raise CardArtifactError(f"卡片产物目录不允许符号链接: {reference!r}")
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                delete=False,
            ) as temp_file:
                temp_file.write(data)
                temp_path = Path(temp_file.name)
            os.replace(temp_path, destination)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise CardArtifactError(f"无法保存卡片产物 {reference!r}: {exc}") from exc
