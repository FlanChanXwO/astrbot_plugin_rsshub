"""Runtime settings consumed by application and infrastructure services."""

from __future__ import annotations

from dataclasses import dataclass, field

from ....shared.constants import (
    MEDIA_CACHE_TTL_SECONDS_DEFAULT,
    ONEBOT_NAPCAT_STREAM_MODE_DEFAULT,
    QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT,
    QQ_OFFICIAL_MARKDOWN_MODE_DEFAULT,
    QQ_OFFICIAL_MEDIA_THRESHOLD_DEFAULT,
    TELEGRAM_PHOTO_MAX_BYTES,
)

_DEFAULT_MEDIA_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class PlatformStrategySettings:
    """Platform-specific sender strategy settings."""

    enable_telegraph: bool = False
    telegraph_token: str = ""
    telegraph_proxy: str = ""
    napcat_stream_mode: str | None = None
    markdown_mode: str = QQ_OFFICIAL_MARKDOWN_MODE_DEFAULT


@dataclass(frozen=True)
class BasicSettings:
    """Global infrastructure-facing defaults used by application use cases."""

    proxy: str = ""
    timeout: int = 30
    rsshub_base_url: str = "https://rsshub.app"
    minimal_interval: int = 1
    failed_queue_capacity: int = 50
    failed_queue_max_retries: int = 3
    deduplicate_multi_bot: bool = True
    history_entry_limit: int = 0
    download_media_before_send: bool = True
    download_media_timeout: int = _DEFAULT_MEDIA_TIMEOUT_SECONDS


@dataclass(frozen=True)
class HttpSettings:
    """HTTP client defaults shared by feed fetching and media downloads."""

    proxy: str = ""
    timeout: int = 30
    media_timeout: int = _DEFAULT_MEDIA_TIMEOUT_SECONDS


@dataclass(frozen=True)
class FeedFetchSettings:
    """HTTP/RSS fetch defaults."""

    timeout: int = 30
    proxy: str = ""
    rsshub_base_url: str = "https://rsshub.app"


@dataclass(frozen=True)
class RSSSettings:
    """RSS parser and dedup history settings."""

    hash_history_min: int = 200
    hash_history_multiplier: int = 2
    hash_history_hard_limit: int = 5000
    tracking_query_params: tuple[str, ...] = field(default_factory=tuple)
    bootstrap_skip_history: bool = True


@dataclass(frozen=True)
class SchedulerSettings:
    """Scheduler defaults."""

    default_interval: int = 10
    history_retention_days: int = 30
    history_entry_limit: int = 0


@dataclass(frozen=True)
class SubscriptionDefaults:
    """Default values applied to new subscriptions."""

    interval: int = 10
    notify: bool = True
    send_mode: str = "自动"
    length_limit: int = 0
    display_author: str = "自动"
    display_via: str = "自动"
    display_title: str = "自动"
    display_entry_tags: bool = False
    style: str = "auto"
    display_media: bool = True


@dataclass(frozen=True)
class ContentHandlerSettings:
    """Global defaults for builtin content handlers."""

    ai_provider_id: str = ""
    ai_persona_id: str = ""


@dataclass(frozen=True)
class SenderStrategySettings:
    """Per-platform sender strategy toggles."""

    telegram: bool = True
    aiocqhttp: bool = True
    qq_official: bool = True
    telegram_settings: PlatformStrategySettings = field(
        default_factory=PlatformStrategySettings
    )
    aiocqhttp_settings: PlatformStrategySettings = field(
        default_factory=PlatformStrategySettings
    )
    qq_official_settings: PlatformStrategySettings = field(
        default_factory=PlatformStrategySettings
    )


@dataclass(frozen=True)
class MediaPlatformLimits:
    """Media download, cache and platform threshold settings."""

    download_media_timeout: int = _DEFAULT_MEDIA_TIMEOUT_SECONDS
    cache_enabled: bool = True
    cache_ttl_seconds: int = MEDIA_CACHE_TTL_SECONDS_DEFAULT
    cache_gc_interval_seconds: int = 5 * 60
    cache_gc_grace_seconds: int = 10 * 60
    min_valid_bytes: int = 1
    telegram_photo_max_bytes: int = TELEGRAM_PHOTO_MAX_BYTES
    onebot_napcat_stream_mode: str = ONEBOT_NAPCAT_STREAM_MODE_DEFAULT
    qq_official_media_threshold: int = QQ_OFFICIAL_MEDIA_THRESHOLD_DEFAULT
    qq_official_degrade_strategy: str = QQ_OFFICIAL_DEGRADE_STRATEGY_DEFAULT


@dataclass(frozen=True)
class MediaSettings:
    """Public media sending settings used by senders."""

    image_relay_base_url: str = ""
    media_relay_base_url: str = ""
    media_download_concurrency: int = 1
    table_to_image: bool = True
    video_transcode: bool = False
    video_transcode_timeout: int = 120
    gif_transcode: bool = False
    gif_transcode_timeout: int = 60
    ffmpeg_source: str = "auto"
    ffmpeg_mirror: str = "auto"
    ffmpeg_mirror_custom_url: str = ""


@dataclass(frozen=True)
class RouteKnowledgeSettings:
    """RSSHub Routes knowledge-base sync settings."""

    kb_name: str = "RSSHub Routes"
    embedding_provider_id: str = ""
    rerank_provider_id: str = ""
    source_mode: str = "speed_test"
    source_base_url: str = (
        "https://raw.githubusercontent.com/FlanChanXwO/rsshub-routes-knowledgebase/main"
    )
    fallback_base_url: str = (
        "https://raw.githubusercontent.com/FlanChanXwO/rsshub-routes-knowledgebase/main"
    )
    local_source_dir: str = ""
    timeout: int = 30
    batch_size: int = 32
    tasks_limit: int = 3
    max_retries: int = 3


@dataclass(frozen=True)
class ApplicationSettings:
    """Settings consumed by the application layer."""

    # Required fields first (no defaults)
    media: MediaSettings  # No default to prevent silent omissions in builder
    # Optional fields with defaults
    basic: BasicSettings = field(default_factory=BasicSettings)
    fetch: FeedFetchSettings = field(default_factory=FeedFetchSettings)
    rss: RSSSettings = field(default_factory=RSSSettings)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)
    subscription_defaults: SubscriptionDefaults = field(
        default_factory=SubscriptionDefaults
    )
    content_handlers: ContentHandlerSettings = field(
        default_factory=ContentHandlerSettings
    )
    sender_strategies: SenderStrategySettings = field(
        default_factory=SenderStrategySettings
    )
    http: HttpSettings = field(default_factory=HttpSettings)
    media_platform_limits: MediaPlatformLimits = field(
        default_factory=MediaPlatformLimits
    )
    route_knowledge: RouteKnowledgeSettings = field(
        default_factory=RouteKnowledgeSettings
    )
