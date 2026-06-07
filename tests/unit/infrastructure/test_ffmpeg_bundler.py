from __future__ import annotations

import hashlib

from astrbot_plugin_rsshub.src.infrastructure.utils import ffmpeg_bundler


def test_verify_checksum_rejects_archive_without_known_digest() -> None:
    """缺少固定校验值时不得接受远端可执行归档。"""
    assert ffmpeg_bundler._verify_checksum(b"archive", "ffmpeg-test.tar.xz") is False


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
