from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from astrbot_plugin_rsshub.src.infrastructure.rendering import font_manager
from astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager import (
    TABLE_FONT_FILENAME,
    TABLE_FONT_SHA256,
    TABLE_FONT_SIZE,
    _verify_font,
    ensure_table_font,
    ensure_table_font_runtime,
    get_runtime_font_dir,
    get_runtime_font_path,
)


@pytest.fixture(autouse=True)
def _reset_font_cache():
    """每个用例前后清空已校验字体缓存，避免模块级缓存跨用例泄漏。"""
    font_manager._cached_verified_font = None
    yield
    font_manager._cached_verified_font = None


def test_verify_font_accepts_valid_file(tmp_path: Path):
    content = b"\x00" * TABLE_FONT_SIZE
    target = tmp_path / TABLE_FONT_FILENAME
    target.write_bytes(content)

    with patch(
        "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager.hashlib.sha256"
    ) as mock_sha:
        digest = MagicMock()
        digest.hexdigest.return_value = TABLE_FONT_SHA256
        digest.update = MagicMock()
        mock_sha.return_value = digest
        assert _verify_font(target) is True


def test_verify_font_rejects_wrong_size(tmp_path: Path):
    target = tmp_path / TABLE_FONT_FILENAME
    target.write_bytes(b"short")

    assert _verify_font(target) is False


def test_verify_font_rejects_wrong_sha(tmp_path: Path):
    content = b"\x00" * TABLE_FONT_SIZE
    target = tmp_path / TABLE_FONT_FILENAME
    target.write_bytes(content)

    with patch(
        "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager.hashlib.sha256"
    ) as mock_sha:
        digest = MagicMock()
        digest.hexdigest.return_value = "badcafe"
        digest.update = MagicMock()
        mock_sha.return_value = digest
        assert _verify_font(target) is False


def test_verify_font_rejects_missing_file(tmp_path: Path):
    assert _verify_font(tmp_path / "nonexistent.otf") is False


def test_get_runtime_font_path_returns_expected_filename():
    path = get_runtime_font_path()
    assert path.name == TABLE_FONT_FILENAME
    assert path.parent == get_runtime_font_dir()


@pytest.mark.asyncio
async def test_ensure_table_font_returns_existing_verified(tmp_path: Path):
    target = tmp_path / TABLE_FONT_FILENAME
    target.write_bytes(b"\x00" * TABLE_FONT_SIZE)

    with (
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager"
            ".get_runtime_font_path",
            return_value=target,
        ),
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager._verify_font",
            return_value=True,
        ),
    ):
        result = await ensure_table_font()
        assert result == target


@pytest.mark.asyncio
async def test_ensure_table_font_downloads_when_missing(tmp_path: Path):
    target = tmp_path / TABLE_FONT_FILENAME
    content = b"\x00" * TABLE_FONT_SIZE

    mock_result = MagicMock()
    mock_result.error = None
    mock_result.status = 200
    mock_result.content = content

    mock_fetcher = AsyncMock()
    mock_fetcher.fetch.return_value = mock_result
    mock_fetcher.close = AsyncMock()

    with (
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager"
            ".get_runtime_font_path",
            return_value=target,
        ),
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager._verify_font",
            side_effect=[False, False, True],
        ),
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager.HttpFetcher",
            return_value=mock_fetcher,
        ),
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager.hashlib.sha256"
        ) as mock_sha,
    ):
        digest = MagicMock()
        digest.hexdigest.return_value = TABLE_FONT_SHA256
        digest.update = MagicMock()
        mock_sha.return_value = digest

        result = await ensure_table_font(http_proxy="", timeout=300)
        assert result == target
        assert target.exists()
        assert target.stat().st_size == TABLE_FONT_SIZE


@pytest.mark.asyncio
async def test_ensure_table_font_returns_none_on_download_failure(tmp_path: Path):
    target = tmp_path / TABLE_FONT_FILENAME

    mock_result = MagicMock()
    mock_result.error = "timeout"
    mock_result.status = 0
    mock_result.content = b""

    mock_fetcher = AsyncMock()
    mock_fetcher.fetch.return_value = mock_result
    mock_fetcher.close = AsyncMock()

    with (
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager"
            ".get_runtime_font_path",
            return_value=target,
        ),
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager._verify_font",
            return_value=False,
        ),
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager.HttpFetcher",
            return_value=mock_fetcher,
        ),
    ):
        result = await ensure_table_font(http_proxy="", timeout=10)
        assert result is None


@pytest.mark.asyncio
async def test_ensure_table_font_runtime_caches_verification(tmp_path: Path):
    """运行时门控应缓存校验结果，重复调用不再重跑 _verify_font。"""
    target = tmp_path / TABLE_FONT_FILENAME
    target.write_bytes(b"\x00" * TABLE_FONT_SIZE)

    with (
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager"
            ".get_runtime_font_path",
            return_value=target,
        ),
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager._verify_font",
            return_value=True,
        ) as mock_verify,
    ):
        first = await ensure_table_font_runtime()
        second = await ensure_table_font_runtime()
        third = await ensure_table_font_runtime()

    assert first == target
    assert second == target
    assert third == target
    # 仅首次校验，后续命中缓存。
    assert mock_verify.call_count == 1


@pytest.mark.asyncio
async def test_ensure_table_font_runtime_no_download_when_unconfigured(tmp_path: Path):
    """未配置下载且字体缺失时，运行时门控返回 None 且不发起下载。"""
    target = tmp_path / TABLE_FONT_FILENAME  # 不创建文件

    font_manager._download_configured = False
    with (
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager"
            ".get_runtime_font_path",
            return_value=target,
        ),
        patch(
            "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager.HttpFetcher",
        ) as mock_fetcher_cls,
    ):
        result = await ensure_table_font_runtime()

    assert result is None
    mock_fetcher_cls.assert_not_called()
