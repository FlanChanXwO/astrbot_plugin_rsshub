"""FFmpeg + FFprobe 捆绑下载与管理。

从 GitHub 公开源自动下载 ffmpeg+ffprobe 静态构建，安装到插件数据目录。
替代 imageio-ffmpeg（不含 ffprobe），保证两个二进制都可用。

下载源：
- Linux / Windows: BtbN/FFmpeg-Builds (GPL 静态版)
- macOS: vanloctech/ffmpeg-macos (含 ffmpeg + ffprobe)

架构参考: font_manager.py 的 configure + prefetch + lock + 双检模式。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path
from typing import Final
from uuid import uuid4

from ..fetcher.http import HttpFetcher
from ..utils.logger import get_logger
from ..utils.mirror_helper import MIRROR_PREFIXES, speed_test_mirrors
from ..utils.paths import get_plugin_data_dir

logger = get_logger()

# ---------------------------------------------------------------------------
# 平台 → 下载配置映射
# ---------------------------------------------------------------------------

_BTBN_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
_MACOS_BASE = "https://github.com/vanloctech/ffmpeg-macos/releases/latest/download/"

# 单次下载超时（秒）；总耗时受 _MAX_ATTEMPTS × 单次超时影响
_PER_ATTEMPT_TIMEOUT = 60
_MAX_ATTEMPTS = 3

# (archive_filename, url_prefix, format, ffmpeg_bin_name, ffprobe_bin_name)
_PlatformConfig = tuple[str, str, str, str, str]

_PLATFORM_MAP: dict[str, _PlatformConfig] = {
    # BtbN — Linux / Windows
    "linux-x86_64": (
        "ffmpeg-master-latest-linux64-gpl.tar.xz",
        _BTBN_BASE,
        "tar.xz",
        "ffmpeg",
        "ffprobe",
    ),
    "linux-aarch64": (
        "ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
        _BTBN_BASE,
        "tar.xz",
        "ffmpeg",
        "ffprobe",
    ),
    "windows-amd64": (
        "ffmpeg-master-latest-win64-gpl.zip",
        _BTBN_BASE,
        "zip",
        "ffmpeg.exe",
        "ffprobe.exe",
    ),
    "windows-x86_64": (
        "ffmpeg-master-latest-win64-gpl.zip",
        _BTBN_BASE,
        "zip",
        "ffmpeg.exe",
        "ffprobe.exe",
    ),
    # vanloctech — macOS
    "darwin-arm64": (
        "ffmpeg-macos-arm64.tar.gz",
        _MACOS_BASE,
        "tar.gz",
        "ffmpeg",
        "ffprobe",
    ),
    "darwin-x86_64": (
        "ffmpeg-macos-x64.tar.gz",
        _MACOS_BASE,
        "tar.gz",
        "ffmpeg",
        "ffprobe",
    ),
}

_DATA_SUBDIR: Final = "ffmpeg"
_READY_MARKER: Final = "_bundled_ready"
_MIN_BINARY_SIZE: Final = 1_000_000  # 1 MB — ffmpeg 静态构建至少几 MB

# 已知归档的 SHA256 校验值。当前使用 latest 源，校验值不稳定，保持空映射；
# _verify_checksum 对未知校验值放行并打 warning，由文件大小检查兜底。
_ARCHIVE_SHA256: Final[dict[str, str]] = {}

# ---------------------------------------------------------------------------
# 模块级状态
# ---------------------------------------------------------------------------

_download_lock = asyncio.Lock()
_configured_proxy = ""
_configured_timeout = 300
_configured = False
_configured_mirror = "default"
_configured_mirror_custom_url = ""

# 缓存最近一次成功解析的路径，避免重复文件系统检查
_cached_bundled: tuple[Path, Path] | None = None

# 持有 prefetch 后台任务的强引用，防止 Python 3.11+ 弱引用机制下被 GC 中断
_bg_tasks: set[asyncio.Task[None]] = set()


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def configure_ffmpeg_bundler(
    *,
    http_proxy: str = "",
    timeout: int = 300,
    mirror: str = "default",
    mirror_custom_url: str = "",
) -> None:
    """配置捆绑下载使用的代理、超时与镜像（启动装配时调用一次）。

    未配置时 ensure_bundled_ffmpeg 仍可工作，但不会使用代理/镜像。
    """
    global _configured, _configured_proxy, _configured_timeout
    global _configured_mirror, _configured_mirror_custom_url
    _configured = True
    _configured_proxy = http_proxy or ""
    _configured_timeout = max(60, int(timeout or 300))
    _configured_mirror = str(mirror or "default")
    _configured_mirror_custom_url = str(mirror_custom_url or "").strip()


def _resolve_mirror_prefix() -> str:
    """根据当前配置返回镜像 URL 前缀，无效时回退到 default（直连）。"""
    mirror = _configured_mirror
    if mirror == "custom":
        custom = _configured_mirror_custom_url
        if not custom:
            return ""
        # 自定义 URL 必须以 / 结尾才能直接拼接 https://github.com/...
        return custom if custom.endswith("/") else custom + "/"
    return MIRROR_PREFIXES.get(mirror, "")


def prefetch_bundled_ffmpeg() -> None:
    """后台异步预取 ffmpeg 捆绑包，不阻塞插件启动（幂等）。

    需先调用 configure_ffmpeg_bundler。已有可用二进制时直接返回。
    """
    if _check_bundled_ready():
        return

    async def _run() -> None:
        try:
            result = await ensure_bundled_ffmpeg(
                http_proxy=_configured_proxy,
                timeout=_configured_timeout,
                mirror=_configured_mirror,
                mirror_custom_url=_configured_mirror_custom_url,
            )
            if result is not None:
                logger.info("FFmpeg 捆绑二进制后台预取成功")
            else:
                logger.warning("FFmpeg 捆绑二进制后台预取失败，将回退到系统 PATH")
        except Exception as ex:
            logger.warning(
                "FFmpeg 捆绑二进制后台预取异常: err_type=%s, err=%s",
                type(ex).__name__,
                ex,
            )

    _spawn_bg_task(_run())


def _spawn_bg_task(coro) -> None:
    """启动后台任务并保留强引用，防止任务被 GC。"""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def ensure_bundled_ffmpeg(
    *,
    http_proxy: str = "",
    timeout: int = 300,
    mirror: str = "default",
    mirror_custom_url: str = "",
) -> tuple[Path, Path] | None:
    """确保捆绑 ffmpeg+ffprobe 可用，返回 (ffmpeg_path, ffprobe_path) 或 None。

    双检 + 异步锁保证并发安全。成功后缓存路径，后续调用直接返回。
    """
    global _cached_bundled

    # 快速路径：已有缓存
    if _cached_bundled is not None:
        ffmpeg_p, ffprobe_p = _cached_bundled
        if ffmpeg_p.exists() and ffprobe_p.exists():
            return _cached_bundled

    async with _download_lock:
        # 双检：等锁期间可能已被其他协程完成
        if _cached_bundled is not None:
            ffmpeg_p, ffprobe_p = _cached_bundled
            if ffmpeg_p.exists() and ffprobe_p.exists():
                return _cached_bundled

        if _check_bundled_ready():
            return _cached_bundled

        # 锁内同步配置镜像，避免半路被改
        global _configured_mirror, _configured_mirror_custom_url
        _configured_mirror = str(mirror or "default")
        _configured_mirror_custom_url = str(mirror_custom_url or "").strip()

        # 锁内清理上次中断遗留的临时目录，避免与并发解包路径打架
        _cleanup_stale_tmp_dirs()

        result = await _download_and_setup(http_proxy, timeout)
        if result is not None:
            _cached_bundled = result
        return result


def get_bundled_ffmpeg_path() -> Path | None:
    """同步查询已缓存的捆绑 ffmpeg 路径（不触发下载）。

    供 ffmpeg_helper.py 的 ensure_ffmpeg_ready 在同步上下文中调用。
    """
    if _cached_bundled is not None:
        ffmpeg_p, _ = _cached_bundled
        if ffmpeg_p.exists():
            return ffmpeg_p
    # 回退到文件系统检查
    dest_dir = _get_dest_dir()
    cfg = _get_platform_config()
    if cfg is None:
        return None
    _, _, _, ffmpeg_name, _ = cfg
    ffmpeg_path = dest_dir / ffmpeg_name
    if ffmpeg_path.exists() and ffmpeg_path.stat().st_size >= _MIN_BINARY_SIZE:
        return ffmpeg_path
    return None


def get_bundled_ffprobe_path() -> Path | None:
    """同步查询已缓存的捆绑 ffprobe 路径（不触发下载）。"""
    if _cached_bundled is not None:
        _, ffprobe_p = _cached_bundled
        if ffprobe_p.exists():
            return ffprobe_p
    dest_dir = _get_dest_dir()
    cfg = _get_platform_config()
    if cfg is None:
        return None
    _, _, _, _, ffprobe_name = cfg
    ffprobe_path = dest_dir / ffprobe_name
    if ffprobe_path.exists() and ffprobe_path.stat().st_size >= _MIN_BINARY_SIZE:
        return ffprobe_path
    return None


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------


def _get_platform_key() -> str:
    """返回平台键，如 'linux-x86_64'、'darwin-arm64'、'windows-amd64'。"""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Linux":
        arch = "x86_64" if machine in ("x86_64", "amd64") else "aarch64"
        return f"linux-{arch}"
    elif system == "Darwin":
        arch = "arm64" if machine == "arm64" else "x86_64"
        return f"darwin-{arch}"
    elif system == "Windows":
        return "windows-amd64"
    return f"{system.lower()}-{machine}"


def _get_platform_config() -> _PlatformConfig | None:
    """获取当前平台的下载配置。"""
    key = _get_platform_key()
    return _PLATFORM_MAP.get(key)


def _get_dest_dir() -> Path:
    """捆绑二进制文件的目标目录。"""
    return get_plugin_data_dir(_DATA_SUBDIR)


def _cleanup_stale_tmp_dirs() -> None:
    """清理上次下载中断遗留的 .tmp_* 临时目录。"""
    dest_dir = _get_dest_dir()
    if not dest_dir.exists():
        return
    for entry in dest_dir.iterdir():
        if entry.is_dir() and entry.name.startswith(".tmp_"):
            try:
                shutil.rmtree(entry)
                logger.debug("已清理残留临时目录: %s", entry)
            except OSError as ex:
                logger.debug(
                    "清理残留临时目录失败: path=%s, err_type=%s, err=%s",
                    entry,
                    type(ex).__name__,
                    ex,
                )


def _check_bundled_ready() -> bool:
    """检查缓存目录中是否已有可用的 ffmpeg+ffprobe。"""
    global _cached_bundled

    cfg = _get_platform_config()
    if cfg is None:
        return False

    dest_dir = _get_dest_dir()
    _, _, _, ffmpeg_name, ffprobe_name = cfg
    ffmpeg_path = dest_dir / ffmpeg_name
    ffprobe_path = dest_dir / ffprobe_name

    if not ffmpeg_path.exists() or not ffprobe_path.exists():
        return False

    try:
        if (
            ffmpeg_path.stat().st_size < _MIN_BINARY_SIZE
            or ffprobe_path.stat().st_size < _MIN_BINARY_SIZE
        ):
            return False
    except OSError:
        return False

    _cached_bundled = (ffmpeg_path, ffprobe_path)
    return True


async def _download_and_setup(
    http_proxy: str,
    timeout: int,
) -> tuple[Path, Path] | None:
    """下载、解包、校验 ffmpeg+ffprobe，返回路径或 None。

    策略：按镜像前缀依次尝试，单次超时 _PER_ATTEMPT_TIMEOUT，最多 _MAX_ATTEMPTS 次。
    timeout 参数作为整体预算兜底，避免无限重试。
    """
    cfg = _get_platform_config()
    if cfg is None:
        logger.warning(
            "当前平台不支持自动下载 FFmpeg: platform=%s", _get_platform_key()
        )
        return None

    archive_name, url_prefix, fmt, ffmpeg_name, ffprobe_name = cfg
    # 原始 GitHub URL（镜像前缀会拼在前面）
    base_url = url_prefix + archive_name

    dest_dir = _get_dest_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 构建下载 URL 列表
    mirror_mode = _configured_mirror
    attempt_urls: list[str] = []
    if _configured_mirror == "auto":
        # 自动测速选最快镜像；把 custom_url（如有）也加入候选池
        extra_candidates: list[tuple[str, str]] = []
        custom_prefix = _configured_mirror_custom_url
        if custom_prefix:
            if not custom_prefix.endswith("/"):
                custom_prefix = custom_prefix + "/"
            extra_candidates.append(("custom", custom_prefix + base_url))
        try:
            best_url = await speed_test_mirrors(
                base_url, proxy=http_proxy, extra_candidates=extra_candidates
            )
        except Exception as ex:
            # 测速本身异常（aiohttp / 事件循环问题等）时退到直连，避免影响下载
            logger.warning(
                "FFmpeg 下载: 镜像测速异常，回退直连 GitHub: err_type=%s, err=%s",
                type(ex).__name__,
                ex,
            )
            attempt_urls.append(base_url)
            mirror_mode = "auto (fallback-direct)"
        else:
            attempt_urls.append(best_url)
            # 测速冠军不是直连时，保留直连作为最终兜底
            if best_url != base_url:
                attempt_urls.append(base_url)
            mirror_mode = "auto (speed-test)"
    else:
        # 手动选择镜像
        mirror_prefix = _resolve_mirror_prefix()
        if mirror_prefix:
            attempt_urls.append(mirror_prefix + base_url)
        attempt_urls.append(base_url)  # 直连 GitHub 作为最后兜底
    logger.info(
        "FFmpeg 下载: mirror=%s, 候选 URL 数=%d", mirror_mode, len(attempt_urls)
    )

    # 总预算：取 min(用户 timeout, 单次超时×尝试次数)
    per_attempt = _PER_ATTEMPT_TIMEOUT
    max_attempts = min(_MAX_ATTEMPTS, len(attempt_urls))
    total_budget = max(
        per_attempt, min(int(timeout or 300), per_attempt * max_attempts)
    )

    archive_data: bytes | None = None
    last_error: str = ""
    for attempt_idx in range(max_attempts):
        download_url = attempt_urls[attempt_idx]
        attempt_timeout = min(per_attempt, total_budget)
        if attempt_timeout < 30:
            logger.warning("FFmpeg 下载总预算已耗尽，停止重试")
            break

        fetcher = HttpFetcher(timeout=attempt_timeout, proxy=http_proxy)
        try:
            logger.info(
                "开始下载 FFmpeg 捆绑包: url=%s, attempt=%s/%s, timeout=%ss",
                download_url,
                attempt_idx + 1,
                max_attempts,
                attempt_timeout,
            )
            result = await fetcher.fetch(download_url, verbose=False)
        except Exception as ex:
            last_error = f"{type(ex).__name__}: {ex}"
            logger.warning(
                "FFmpeg 捆绑包下载异常: attempt=%s, err=%s",
                attempt_idx + 1,
                last_error,
            )
            total_budget -= attempt_timeout
            continue
        finally:
            await fetcher.close()

        if result.error is not None or result.status != 200 or not result.content:
            last_error = f"status={result.status}, error={result.error}"
            logger.warning(
                "FFmpeg 捆绑包下载失败: attempt=%s, %s",
                attempt_idx + 1,
                last_error,
            )
            total_budget -= attempt_timeout
            continue

        archive_data = result.content
        logger.info(
            "FFmpeg 捆绑包下载完成: size=%s bytes, url=%s",
            len(archive_data),
            download_url,
        )
        break

    if archive_data is None:
        logger.warning(
            "FFmpeg 捆绑包所有下载尝试均失败: last_error=%s", last_error or "unknown"
        )
        return None

    if not _verify_checksum(archive_data, archive_name):
        logger.warning("FFmpeg 捆绑包校验失败，拒绝安装: archive=%s", archive_name)
        return None

    # 解包
    return _extract_binaries(archive_data, fmt, ffmpeg_name, ffprobe_name, dest_dir)


def _verify_checksum(
    archive_data: bytes,
    archive_name: str,
) -> bool:
    """校验下载归档的 SHA256。

    已知校验值时严格比对；未知时放行并打 warning，由文件大小检查兜底。
    """
    expected = _ARCHIVE_SHA256.get(archive_name)
    if not expected:
        logger.warning(
            "FFmpeg 捆绑包缺少 SHA256 校验值，跳过校验: archive=%s, size=%d",
            archive_name,
            len(archive_data),
        )
        return True
    actual = hashlib.sha256(archive_data).hexdigest()
    if actual.lower() != expected.lower():
        logger.warning(
            "FFmpeg 捆绑包 SHA256 不匹配: archive=%s, expected=%s, actual=%s",
            archive_name,
            expected,
            actual,
        )
        return False
    return True


def _extract_binaries(
    archive_data: bytes,
    fmt: str,
    ffmpeg_name: str,
    ffprobe_name: str,
    dest_dir: Path,
) -> tuple[Path, Path] | None:
    """从压缩包中提取 ffmpeg 和 ffprobe 二进制文件。"""

    # 写入临时文件
    tmp_dir = dest_dir / f".tmp_{uuid4().hex[:8]}"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        suffix = (
            ".tar.xz" if fmt == "tar.xz" else (".zip" if fmt == "zip" else ".tar.gz")
        )
        tmp_archive = tmp_dir / f"ffmpeg_archive{suffix}"
        tmp_archive.write_bytes(archive_data)

        extract_dir = tmp_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        # 解包
        if fmt == "tar.xz" or fmt == "tar.gz":
            with tarfile.open(str(tmp_archive), "r:*") as tar:
                tar.extractall(extract_dir, filter="data")
        elif fmt == "zip":
            with zipfile.ZipFile(str(tmp_archive), "r") as zf:
                # zip slip 校验：拒绝绝对路径、含 ../ 的成员、Windows 驱动器前缀
                for info in zf.infolist():
                    name = info.filename
                    if (
                        name.startswith("/")
                        or name.startswith("\\")
                        or ".." in Path(name).parts
                        or (len(name) >= 2 and name[1] == ":")
                    ):
                        logger.warning(
                            "FFmpeg 捆绑包含非法 zip 路径: name=%s",
                            name,
                        )
                        return None
                zf.extractall(extract_dir)
        else:
            logger.warning("不支持的压缩格式: %s", fmt)
            return None

        # 在解包目录中查找 ffmpeg 和 ffprobe
        ffmpeg_src = _find_binary(extract_dir, ffmpeg_name)
        ffprobe_src = _find_binary(extract_dir, ffprobe_name)

        if ffmpeg_src is None or ffprobe_src is None:
            logger.warning(
                "FFmpeg 捆绑包中未找到二进制文件: ffmpeg=%s, ffprobe=%s, search_dir=%s",
                "found" if ffmpeg_src else "missing",
                "found" if ffprobe_src else "missing",
                extract_dir,
            )
            return None

        # 验证文件大小
        if (
            ffmpeg_src.stat().st_size < _MIN_BINARY_SIZE
            or ffprobe_src.stat().st_size < _MIN_BINARY_SIZE
        ):
            logger.warning("FFmpeg 捆绑二进制文件大小异常，可能损坏")
            return None

        # 原子复制到目标位置
        ffmpeg_dest = dest_dir / ffmpeg_name
        ffprobe_dest = dest_dir / ffprobe_name

        _atomic_copy(ffmpeg_src, ffmpeg_dest)
        _atomic_copy(ffprobe_src, ffprobe_dest)

        # 设置可执行权限 (Unix)
        if platform.system() != "Windows":
            _make_executable(ffmpeg_dest)
            _make_executable(ffprobe_dest)

        logger.info(
            "FFmpeg 捆绑二进制已就绪: ffmpeg=%s, ffprobe=%s",
            ffmpeg_dest,
            ffprobe_dest,
        )

        # 写 ready 标记
        marker = dest_dir / _READY_MARKER
        try:
            marker.write_text(f"extracted_at={_now_iso()}")
        except OSError:
            pass

        return (ffmpeg_dest, ffprobe_dest)

    except Exception as ex:
        logger.warning(
            "FFmpeg 捆绑包解包失败: err_type=%s, err=%s",
            type(ex).__name__,
            ex,
        )
        return None
    finally:
        # 清理临时目录
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _find_binary(search_dir: Path, binary_name: str) -> Path | None:
    """在解包目录（含子目录）中查找指定二进制文件。"""
    # 直接匹配
    direct = search_dir / binary_name
    if direct.is_file():
        return direct

    # 递归搜索（BtbN tarball 结构为 ffmpeg-xxx/bin/ffmpeg）
    for root, _, files in os.walk(search_dir):
        for fname in files:
            if fname == binary_name:
                candidate = Path(root) / fname
                if candidate.is_file():
                    return candidate

    return None


def _atomic_copy(src: Path, dest: Path) -> None:
    """通过临时文件 + rename 原子写入目标路径。"""
    tmp_path = dest.with_name(
        f".{dest.stem}.{os.getpid()}.{uuid4().hex[:8]}.tmp{dest.suffix}"
    )
    try:
        shutil.copy2(str(src), str(tmp_path))
        tmp_path.replace(dest)
    except OSError:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def _make_executable(path: Path) -> None:
    """设置可执行权限。"""
    try:
        current = path.stat().st_mode
        path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as ex:
        logger.debug("设置可执行权限失败: path=%s, err=%s", path, ex)


def _now_iso() -> str:
    """返回当前时间的 ISO 格式字符串。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
