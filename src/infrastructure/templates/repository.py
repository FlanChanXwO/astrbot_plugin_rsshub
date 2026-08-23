"""卡片模板包文件仓储。"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import threading
import weakref
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

import yaml
from pydantic import ValidationError as PydanticValidationError

from ...domain.entities.card_template import (
    CardTemplateMetadata,
    is_valid_card_template_id,
)
from ..utils.paths import get_plugin_data_dir

_STORAGE_LOCKS_GUARD = threading.Lock()
_STORAGE_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = (
    weakref.WeakValueDictionary()
)


def _shared_storage_lock(storage_dir: Path) -> threading.RLock:
    """同一进程内访问同一模板目录的仓储实例必须共享切换边界。"""
    key = os.path.normcase(os.path.abspath(storage_dir))
    with _STORAGE_LOCKS_GUARD:
        return _STORAGE_LOCKS.setdefault(key, threading.RLock())


class CardTemplatePackageError(ValueError):
    """模板包内容或存储操作无效。"""


@dataclass(frozen=True, slots=True)
class CardTemplatePackage:
    """一个已经校验、可读取的模板包。"""

    metadata: CardTemplateMetadata
    root: Path
    origin: str


class CardTemplatePackageRepository:
    """管理插件数据目录中的卡片模板包。"""

    def __init__(
        self,
        storage_dir: Path | None = None,
        *,
        builtin_package_dirs: list[Path] | tuple[Path, ...] = (),
    ) -> None:
        self._storage_dir = Path(storage_dir or get_plugin_data_dir("card_templates"))
        self._builtin_package_dirs = tuple(Path(path) for path in builtin_package_dirs)
        self._storage_lock = _shared_storage_lock(self._storage_dir)

    def get(self, template_id: str) -> CardTemplatePackage | None:
        """按模板 ID 返回已安装模板。"""
        with self._storage_lock:
            return self._get(template_id)

    def _get(self, template_id: str) -> CardTemplatePackage | None:
        self._validate_template_id(template_id)
        package_dir = self._storage_dir / template_id
        self._reject_installed_symlink(package_dir)
        if package_dir.is_dir():
            return self._load_package(package_dir, origin="installed")
        for builtin_dir in self._builtin_package_dirs:
            package = self._load_package(builtin_dir, origin="builtin")
            if package.metadata.id == template_id:
                return package
        return None

    def list_packages(self) -> list[CardTemplatePackage]:
        """列出内置与本地模板；同 ID 的本地安装包优先。"""
        with self._storage_lock:
            return self._list_packages()

    def _list_packages(self) -> list[CardTemplatePackage]:
        packages = {
            package.metadata.id: package
            for package in (
                self._load_package(path, origin="builtin")
                for path in self._builtin_package_dirs
            )
        }
        if self._storage_dir.is_dir():
            for path in self._storage_dir.iterdir():
                if path.name.startswith("."):
                    continue
                self._reject_installed_symlink(path)
                if path.is_dir():
                    package = self._load_package(path, origin="installed")
                    packages[package.metadata.id] = package
        return [packages[template_id] for template_id in sorted(packages)]

    def delete(self, template_id: str) -> bool:
        """删除本地安装包；内置包由代码分发，不在此删除。"""
        with self._storage_lock:
            return self._delete(template_id)

    def _delete(self, template_id: str) -> bool:
        self._validate_template_id(template_id)
        package_dir = self._storage_dir / template_id
        self._reject_installed_symlink(package_dir)
        if package_dir.is_dir():
            shutil.rmtree(package_dir)
            return True
        for builtin_dir in self._builtin_package_dirs:
            package = self._load_package(builtin_dir, origin="builtin")
            if package.metadata.id == template_id:
                raise CardTemplatePackageError("内置模板不能删除")
        return False

    def install_archive(self, archive_data: bytes) -> CardTemplatePackage:
        """校验 ZIP 并安装到插件数据目录。"""
        with self._storage_lock:
            return self._install_archive(archive_data)

    def _install_archive(self, archive_data: bytes) -> CardTemplatePackage:
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".card-template-", dir=self._storage_dir.parent
        ) as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            extract_dir = temp_dir / "package"
            extract_dir.mkdir()
            archive_path = temp_dir / "template.zip"
            archive_path.write_bytes(archive_data)
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    seen_members: set[str] = set()
                    for member in archive.infolist():
                        self._validate_archive_member(member)
                        canonical_name = member.filename.rstrip("/").casefold()
                        if canonical_name in seen_members:
                            raise CardTemplatePackageError(
                                f"模板归档包含重复条目: {member.filename!r}"
                            )
                        seen_members.add(canonical_name)
                    archive.extractall(extract_dir)
            except (OSError, zipfile.BadZipFile) as exc:
                raise CardTemplatePackageError("模板归档不是有效 ZIP") from exc

            package = self._load_package(extract_dir, origin="installed")
            destination = self._storage_dir / package.metadata.id
            self._replace_package(extract_dir, destination)

        return self._load_package(destination, origin="installed")

    @staticmethod
    def _validate_template_id(template_id: str) -> None:
        if not is_valid_card_template_id(template_id):
            raise CardTemplatePackageError(f"无效的模板 ID: {template_id!r}")

    @staticmethod
    def _reject_installed_symlink(package_dir: Path) -> None:
        if package_dir.is_symlink():
            raise CardTemplatePackageError(
                f"本地模板目录不允许符号链接: {package_dir.name!r}"
            )

    def _replace_package(self, source: Path, destination: Path) -> None:
        self._reject_installed_symlink(destination)
        backup = self._storage_dir / f".{destination.name}.backup-{uuid4().hex}"
        had_previous = destination.exists()
        try:
            if had_previous:
                os.replace(destination, backup)
            os.replace(source, destination)
        except OSError as exc:
            if had_previous and backup.exists() and not destination.exists():
                try:
                    os.replace(backup, destination)
                except OSError as rollback_exc:
                    raise CardTemplatePackageError(
                        f"模板覆盖失败且旧包恢复失败，旧包保留于 {backup}: "
                        f"{rollback_exc}"
                    ) from exc
            raise CardTemplatePackageError(f"模板覆盖失败: {exc}") from exc
        if backup.exists():
            shutil.rmtree(backup)

    @staticmethod
    def _validate_archive_member(member: zipfile.ZipInfo) -> None:
        name = member.filename
        posix_path = PurePosixPath(name)
        windows_path = PureWindowsPath(name)
        if (
            not name
            or "\x00" in name
            or name.startswith(("/", "\\"))
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in posix_path.parts
            or ".." in windows_path.parts
        ):
            raise CardTemplatePackageError(f"模板归档包含非法路径: {name!r}")
        parts = posix_path.parts
        if not parts or (
            parts[0] not in {"partials", "assets"}
            and name not in {"metadata.yaml", "template.html"}
        ):
            raise CardTemplatePackageError(
                f"模板归档包含固定包结构以外的文件: {name!r}"
            )
        mode = (member.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise CardTemplatePackageError(f"模板归档不允许符号链接: {name!r}")

    @staticmethod
    def _load_package(package_dir: Path, *, origin: str) -> CardTemplatePackage:
        metadata_path = package_dir / "metadata.yaml"
        template_path = package_dir / "template.html"
        if not metadata_path.is_file() or not template_path.is_file():
            raise CardTemplatePackageError(
                "模板包必须在根目录包含 metadata.yaml 和 template.html"
            )
        try:
            payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
            metadata = CardTemplateMetadata.model_validate(payload)
        except (OSError, UnicodeError, yaml.YAMLError, PydanticValidationError) as exc:
            raise CardTemplatePackageError(f"模板 metadata.yaml 无效: {exc}") from exc
        return CardTemplatePackage(metadata=metadata, root=package_dir, origin=origin)
