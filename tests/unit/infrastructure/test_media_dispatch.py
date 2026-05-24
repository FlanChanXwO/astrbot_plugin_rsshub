"""Tests for MediaDispatchResolver — GIF conversion type correction and path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.domain.entities.content_types import LayoutFragment
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import PreparedMedia
from astrbot_plugin_rsshub.src.infrastructure.utils.media_dispatch import (
    MediaDispatchInfo,
    MediaDispatchResolver,
)


def test_video_gif_resolves_as_image_media():
    """无声视频转 .gif 后按 image media 发送，使用本地文件路径。"""
    info = MediaDispatchResolver.resolve_prepared(
        PreparedMedia(
            media_type="video",
            original_url="https://example.com/video.mp4",
            local_path=Path("/tmp/video.gif"),
        )
    )
    assert info.media_type == "image"
    assert info.component_kind == "media"
    assert info.file == "/tmp/video.gif"
    assert info.original_url == "https://example.com/video.mp4"


def test_video_gif_ignores_prefer_local_video_false():
    """prefer_local_video=False 对普通视频使用 original_url，但 GIF 转换结果仍用本地 .gif。"""
    info = MediaDispatchResolver.resolve_prepared(
        PreparedMedia(
            media_type="video",
            original_url="https://example.com/video.mp4",
            local_path=Path("/tmp/video.gif"),
        ),
        prefer_local_video=False,
    )
    assert info.media_type == "image"
    assert info.component_kind == "media"
    assert info.file == "/tmp/video.gif"


def test_normal_video_uses_local_path_by_default():
    """普通视频默认使用本地路径。"""
    info = MediaDispatchResolver.resolve_prepared(
        PreparedMedia(
            media_type="video",
            original_url="https://example.com/video.mp4",
            local_path=Path("/tmp/video.mp4"),
        )
    )
    assert info.media_type == "video"
    assert info.component_kind == "media"
    assert info.file == "/tmp/video.mp4"


def test_normal_video_prefer_local_video_false_uses_original_url():
    """prefer_local_video=False 对普通视频使用原始 URL。"""
    info = MediaDispatchResolver.resolve_prepared(
        PreparedMedia(
            media_type="video",
            original_url="https://example.com/video.mp4",
            local_path=Path("/tmp/video.mp4"),
        ),
        prefer_local_video=False,
    )
    assert info.media_type == "video"
    assert info.component_kind == "media"
    assert info.file == "https://example.com/video.mp4"


def test_image_resolves_as_media():
    info = MediaDispatchResolver.resolve_prepared(
        PreparedMedia(
            media_type="image",
            original_url="https://example.com/photo.jpg",
            local_path=Path("/tmp/photo.jpg"),
        )
    )
    assert info.media_type == "image"
    assert info.component_kind == "media"
    assert info.file == "/tmp/photo.jpg"


def test_audio_resolves_as_tail():
    info = MediaDispatchResolver.resolve_prepared(
        PreparedMedia(
            media_type="audio",
            original_url="https://example.com/sound.mp3",
            local_path=Path("/tmp/sound.mp3"),
        )
    )
    assert info.media_type == "audio"
    assert info.component_kind == "tail"
    assert info.file == "/tmp/sound.mp3"


def test_file_resolves_as_tail_with_name():
    info = MediaDispatchResolver.resolve_prepared(
        PreparedMedia(
            media_type="file",
            original_url="https://example.com/archive.zip",
            local_path=Path("/tmp/archive.zip"),
        )
    )
    assert info.media_type == "file"
    assert info.component_kind == "tail"
    assert info.file == "/tmp/archive.zip"
    assert info.name == "archive.zip"


def test_resolve_layout_fragment_hits_prepared_media():
    """Layout URL 命中预下载结果时，使用 resolve_prepared 的分发逻辑。"""
    prepared_map = {
        "https://example.com/video.gif": PreparedMedia(
            media_type="video",
            original_url="https://example.com/video.gif",
            local_path=Path("/tmp/video.gif"),
        )
    }
    info = MediaDispatchResolver.resolve_layout_fragment(
        LayoutFragment(kind="video", url="https://example.com/video.gif"),
        prepared_media_by_url=prepared_map,
    )
    assert info.media_type == "image"
    assert info.component_kind == "media"
    assert info.file == "/tmp/video.gif"


def test_resolve_layout_fragment_miss_preserves_original():
    """未命中预下载结果时保留原始类型和 URL。"""
    info = MediaDispatchResolver.resolve_layout_fragment(
        LayoutFragment(kind="video", url="https://example.com/remote.mp4"),
        prepared_media_by_url=None,
    )
    assert info.media_type == "video"
    assert info.component_kind == "media"
    assert info.file == "https://example.com/remote.mp4"


def test_resolve_layout_fragment_audio_is_tail():
    info = MediaDispatchResolver.resolve_layout_fragment(
        LayoutFragment(kind="audio", url="https://example.com/podcast.mp3"),
    )
    assert info.media_type == "audio"
    assert info.component_kind == "tail"


def test_resolve_layout_fragment_file_is_tail_with_name():
    info = MediaDispatchResolver.resolve_layout_fragment(
        LayoutFragment(
            kind="file",
            url="https://example.com/doc.pdf",
            name="doc.pdf",
        ),
    )
    assert info.media_type == "file"
    assert info.component_kind == "tail"
    assert info.name == "doc.pdf"