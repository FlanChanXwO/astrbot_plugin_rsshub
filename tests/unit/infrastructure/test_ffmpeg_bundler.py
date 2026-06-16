from __future__ import annotations

import hashlib

from astrbot_plugin_rsshub.src.infrastructure.utils import ffmpeg_bundler


def test_verify_checksum_passes_through_unknown_digest_with_warning(
    monkeypatch,
) -> None:
    """没有固定 SHA256 时放行未知归档，但写 warning 留追踪。

    plugin 当前使用 latest 源，校验值不稳定；放行 + 1 MB 大小兜底是当前安全
    姿态的一部分，校验严格化需要先 pin release tag 才能恢复。
    """
    warnings: list[str] = []

    def _spy(msg, *args, **_kwargs):
        warnings.append(str(msg))

    monkeypatch.setattr(ffmpeg_bundler.logger, "warning", _spy)

    assert ffmpeg_bundler._verify_checksum(b"archive", "ffmpeg-test.tar.xz") is True
    assert any("缺少 SHA256 校验值" in msg for msg in warnings), warnings


def test_verify_checksum_accepts_known_digest(monkeypatch) -> None:
    """固定 SHA256 匹配时才允许进入解包安装链路。"""
    archive = b"trusted archive"
    digest = hashlib.sha256(archive).hexdigest()
    monkeypatch.setitem(ffmpeg_bundler._ARCHIVE_SHA256, "ffmpeg-test.tar.xz", digest)

    assert ffmpeg_bundler._verify_checksum(archive, "ffmpeg-test.tar.xz") is True


def test_verify_checksum_rejects_mismatched_digest(monkeypatch) -> None:
    """固定 SHA256 不匹配时拒绝安装，避免执行被替换的二进制。"""
    monkeypatch.setitem(ffmpeg_bundler._ARCHIVE_SHA256, "ffmpeg-test.tar.xz", "0" * 64)

    assert ffmpeg_bundler._verify_checksum(b"archive", "ffmpeg-test.tar.xz") is False
