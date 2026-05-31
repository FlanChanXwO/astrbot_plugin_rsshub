"""平台媒体发送策略与候选链路。

此模块集中维护平台媒体软阈值和回退顺序。sender 只消费候选，不在各自
实现里散落大小判断。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...shared.constants import (
    ONEBOT_PLATFORMS,
    ONEBOT_VIDEO_MAX_BYTES,
    PLATFORM_ONEBOT,
    PLATFORM_QQ_OFFICIAL,
    PLATFORM_TELEGRAM,
    PLATFORM_WEIXIN_OC,
    QQ_OFFICIAL_GIF_MAX_BYTES,
    QQ_OFFICIAL_IMAGE_MAX_BYTES,
    QQ_OFFICIAL_PLATFORMS,
    QQ_OFFICIAL_VIDEO_MAX_BYTES,
    TELEGRAM_ANIMATION_MAX_BYTES,
    TELEGRAM_DOCUMENT_MAX_BYTES,
    TELEGRAM_PHOTO_MAX_BYTES,
    TELEGRAM_PLATFORMS,
    TELEGRAM_VIDEO_MAX_BYTES,
    WEIXIN_FILE_MAX_BYTES,
    WEIXIN_GIF_MAX_BYTES,
    WEIXIN_IMAGE_MAX_BYTES,
    WEIXIN_PLATFORMS,
    WEIXIN_VIDEO_MAX_BYTES,
)
from .senders.types import MediaVariant, PreparedMedia

SEND_ACTION_MEDIA = "media"
SEND_ACTION_FILE = "file"
SEND_ACTION_LINK = "link"


@dataclass(frozen=True)
class PlatformMediaPolicy:
    """单个平台的媒体软限制和兜底能力。"""

    platform: str
    image_max_bytes: int | None = None
    gif_max_bytes: int | None = None
    video_max_bytes: int | None = None
    file_max_bytes: int | None = None
    supports_file_fallback: bool = True
    prefer_file_for_oversize: bool = True


@dataclass(frozen=True)
class MediaSendCandidate:
    """一个媒体发送候选。"""

    action: str
    media_type: str
    file: str = ""
    original_url: str = ""
    name: str = ""
    stage: str = ""
    variant: str = ""
    reason: str = ""

    @property
    def is_media(self) -> bool:
        return self.action == SEND_ACTION_MEDIA

    @property
    def is_file(self) -> bool:
        return self.action == SEND_ACTION_FILE

    @property
    def is_link(self) -> bool:
        return self.action == SEND_ACTION_LINK


PLATFORM_MEDIA_POLICIES: dict[str, PlatformMediaPolicy] = {
    PLATFORM_TELEGRAM: PlatformMediaPolicy(
        platform=PLATFORM_TELEGRAM,
        image_max_bytes=TELEGRAM_PHOTO_MAX_BYTES,
        gif_max_bytes=TELEGRAM_ANIMATION_MAX_BYTES,
        video_max_bytes=TELEGRAM_VIDEO_MAX_BYTES,
        file_max_bytes=TELEGRAM_DOCUMENT_MAX_BYTES,
    ),
    PLATFORM_ONEBOT: PlatformMediaPolicy(
        platform=PLATFORM_ONEBOT,
        video_max_bytes=ONEBOT_VIDEO_MAX_BYTES,
        file_max_bytes=None,
    ),
    PLATFORM_QQ_OFFICIAL: PlatformMediaPolicy(
        platform=PLATFORM_QQ_OFFICIAL,
        image_max_bytes=QQ_OFFICIAL_IMAGE_MAX_BYTES,
        gif_max_bytes=QQ_OFFICIAL_GIF_MAX_BYTES,
        video_max_bytes=QQ_OFFICIAL_VIDEO_MAX_BYTES,
        file_max_bytes=None,
    ),
    PLATFORM_WEIXIN_OC: PlatformMediaPolicy(
        platform=PLATFORM_WEIXIN_OC,
        image_max_bytes=WEIXIN_IMAGE_MAX_BYTES,
        gif_max_bytes=WEIXIN_GIF_MAX_BYTES,
        video_max_bytes=WEIXIN_VIDEO_MAX_BYTES,
        file_max_bytes=WEIXIN_FILE_MAX_BYTES,
    ),
}


class MediaSendPlanner:
    """根据平台策略为 PreparedMedia 生成发送候选。"""

    @classmethod
    def policy_for_platform(cls, platform: str | None) -> PlatformMediaPolicy:
        normalized = str(platform or "").strip().lower()
        if normalized in TELEGRAM_PLATFORMS:
            return PLATFORM_MEDIA_POLICIES[PLATFORM_TELEGRAM]
        if normalized in ONEBOT_PLATFORMS:
            return PLATFORM_MEDIA_POLICIES[PLATFORM_ONEBOT]
        if normalized in QQ_OFFICIAL_PLATFORMS:
            return PLATFORM_MEDIA_POLICIES[PLATFORM_QQ_OFFICIAL]
        if normalized in WEIXIN_PLATFORMS:
            return PLATFORM_MEDIA_POLICIES[PLATFORM_WEIXIN_OC]
        return PlatformMediaPolicy(platform=normalized or "default")

    @classmethod
    def candidates_for(
        cls,
        item: PreparedMedia,
        *,
        platform: str | None,
    ) -> list[MediaSendCandidate]:
        if item.download_failed:
            return [
                MediaSendCandidate(
                    action=SEND_ACTION_LINK,
                    media_type=item.media_type,
                    original_url=item.original_url,
                    stage="download_failed_link",
                    reason="download_failed",
                )
            ]

        item.ensure_primary_variant()
        policy = cls.policy_for_platform(platform)
        candidates: list[MediaSendCandidate] = []
        variants = cls._ordered_variants(item)

        for variant in variants:
            if not variant.path:
                continue
            media_type = cls._candidate_media_type(variant)
            size = cls._size(variant)
            max_bytes = cls._max_bytes_for(policy, media_type, variant)
            if max_bytes is not None and size > max_bytes:
                continue
            file_value = str(variant.path)
            candidates.append(
                MediaSendCandidate(
                    action=SEND_ACTION_MEDIA,
                    media_type=media_type,
                    file=file_value,
                    original_url=item.original_url,
                    stage=f"send_{variant.variant}_{media_type}",
                    variant=variant.variant,
                )
            )

        file_variant = cls._first_file_variant(variants)
        if policy.supports_file_fallback and file_variant is not None:
            size = cls._size(file_variant)
            if policy.file_max_bytes is None or size <= policy.file_max_bytes:
                candidates.append(
                    MediaSendCandidate(
                        action=SEND_ACTION_FILE,
                        media_type="file",
                        file=str(file_variant.path),
                        original_url=item.original_url,
                        name=file_variant.path.name
                        or cls._filename_from_url(item.original_url),
                        stage="send_file",
                        variant=file_variant.variant,
                    )
                )

        candidates.append(
            MediaSendCandidate(
                action=SEND_ACTION_LINK,
                media_type=item.media_type,
                original_url=item.original_url,
                stage="send_link",
            )
        )
        return cls._deduplicate_candidates(candidates)

    @staticmethod
    def _ordered_variants(item: PreparedMedia) -> list[MediaVariant]:
        variants = list(item.variants or [])
        order = {
            "gif": 0,
            "compressed_gif": 1,
            "primary": 2,
            "transcoded": 3,
            "original": 4,
        }
        return sorted(variants, key=lambda item: order.get(item.variant, 50))

    @staticmethod
    def _candidate_media_type(variant: MediaVariant) -> str:
        if variant.suffix.lower() == ".gif" or variant.variant.endswith("gif"):
            return "image"
        return variant.media_type

    @staticmethod
    def _max_bytes_for(
        policy: PlatformMediaPolicy,
        media_type: str,
        variant: MediaVariant,
    ) -> int | None:
        suffix = variant.suffix.lower() or variant.path.suffix.lower()
        if media_type == "image" and suffix == ".gif":
            return policy.gif_max_bytes
        if media_type == "image":
            return policy.image_max_bytes
        if media_type == "video":
            return policy.video_max_bytes
        return None

    @staticmethod
    def _size(variant: MediaVariant) -> int:
        if variant.size_bytes > 0:
            return variant.size_bytes
        try:
            return variant.path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _exists(path: Path) -> bool:
        try:
            return path.exists()
        except OSError:
            return False

    @classmethod
    def _first_existing_variant(
        cls,
        variants: list[MediaVariant],
    ) -> MediaVariant | None:
        for variant in variants:
            if variant.path:
                return variant
        return None

    @classmethod
    def _first_file_variant(
        cls,
        variants: list[MediaVariant],
    ) -> MediaVariant | None:
        for preferred in ("compressed_gif", "gif", "transcoded", "primary", "original"):
            for variant in variants:
                if variant.path and variant.variant == preferred:
                    return variant
        return cls._first_existing_variant(variants)

    @staticmethod
    def _filename_from_url(url: str) -> str:
        from urllib.parse import unquote, urlparse

        return unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "attachment"

    @staticmethod
    def _deduplicate_candidates(
        candidates: list[MediaSendCandidate],
    ) -> list[MediaSendCandidate]:
        deduped: list[MediaSendCandidate] = []
        seen: set[tuple[str, str, str, str]] = set()
        for candidate in candidates:
            key = (
                candidate.action,
                candidate.media_type,
                candidate.file,
                candidate.original_url,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped
