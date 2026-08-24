"""RSSHub plugin bootstrap wiring.

This module owns startup composition: config parsing, database setup,
application dependency wiring, scheduler startup, and Web API registration.
`main.py` keeps the AstrBot lifecycle and command decorators.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, TypedDict

from astrbot.api import AstrBotConfig
from astrbot.api.star import Context

from .src.application.commands import (
    BatchActivateCommand,
    BatchDeactivateCommand,
    BatchUnsubscribeCommand,
    BundleCommand,
    ExportSubscriptionsCommand,
    GetUserSettingsCommand,
    ImportSubscriptionsCommand,
    SetUserSettingsCommand,
    SubscribeFeedCommand,
    SubStateCommand,
    TestSubscriptionCommand,
    UnsubscribeFeedCommand,
    UpdateSubscriptionCommand,
)
from .src.application.queries import (
    GetFeedItemsQuery,
    GetFeedListQuery,
    GetSubscriptionsQuery,
    SearchFeedsQuery,
)
from .src.application.services.agent_xml_push_service import AgentXmlPushService
from .src.application.services.bundle_batch_delivery_service import (
    BundleBatchDeliveryService,
)
from .src.application.services.bundle_card_management_service import (
    BundleCardManagementService,
)
from .src.application.services.bundle_collection_service import (
    BundleCollectionService,
)
from .src.application.services.bundle_document_service import (
    BundleDocumentHandlerRuntime,
    BundleDocumentService,
)
from .src.application.services.bundle_output_executor import BundleOutputExecutor
from .src.application.services.card_renderer import CardRenderer
from .src.application.services.card_template_service import (
    CardTemplateDownloadService,
    CardTemplateManagementService,
)
from .src.application.services.content_handlers import ContentHandlerRuntime
from .src.application.services.feed_polling_service import FeedPollingService
from .src.application.services.notification_dispatcher import NotificationDispatcher
from .src.application.services.output_orchestrator import OutputOrchestrator
from .src.application.services.route_knowledge_service import (
    RouteKnowledgeSyncService,
)
from .src.application.services.session_push_queue import SessionPushQueue
from .src.application.services.subscription_batch_delivery_service import (
    SubscriptionBatchDeliveryService,
)
from .src.application.services.subscription_card_management_service import (
    SubscriptionCardManagementService,
)
from .src.application.services.subscription_output_executor import (
    SubscriptionOutputExecutor,
)
from .src.domain.repositories.feed_repository import FeedRepository
from .src.domain.repositories.subscription_repository import SubscriptionRepository
from .src.infrastructure.config import (
    ApplicationSettings,
    RsshubPluginConfig,
    build_application_settings,
    heal_astrbot_plugin_config,
    set_config,
)
from .src.infrastructure.fetcher.rss import RSSFeedFetcher
from .src.infrastructure.fetcher.rss.parser import RSSParser
from .src.infrastructure.knowledge import (
    AstrBotRouteKnowledgeRepository,
    build_route_knowledge_source,
)
from .src.infrastructure.media import MediaDownloader
from .src.infrastructure.messaging import (
    DefaultMessageSender,
    InfrastructureMessageSenderProvider,
    set_bot_client_provider,
    set_bot_self_id_provider,
)
from .src.infrastructure.persistence import (
    get_bundle_repository,
    get_database,
    get_delivery_repository,
    get_feed_repository,
    get_push_history_repository,
    get_subscription_repository,
    get_user_repository,
)
from .src.infrastructure.pipeline import EntryTextFormatter
from .src.infrastructure.rendering import (
    AstrBotHtmlImageRenderer,
    CardArtifactStore,
    TableImageRenderer,
)
from .src.infrastructure.rendering.font_manager import (
    configure_table_font_download,
    prefetch_table_font,
)
from .src.infrastructure.schedule import RSSScheduler
from .src.infrastructure.templates import (
    AiohttpCardTemplateArchiveDownloader,
    CardTemplatePackageRepository,
    CardTemplateService,
    DatabaseCardTemplateReferenceLookup,
    get_builtin_card_template_dirs,
)
from .src.infrastructure.utils import (
    get_logger,
    get_plugin_cache_dir,
    get_plugin_data_dir,
)
from .src.infrastructure.utils.media_integrity import configure_media_integrity
from .src.interfaces import WebApiHandler

logger = get_logger()


class PluginDeps(TypedDict, total=False):
    """Dependencies used by command handlers."""

    subscribe_cmd: SubscribeFeedCommand
    unsubscribe_cmd: UnsubscribeFeedCommand
    sub_state_cmd: SubStateCommand
    update_sub_cmd: UpdateSubscriptionCommand
    list_query: GetFeedListQuery
    batch_activate_cmd: BatchActivateCommand
    batch_deactivate_cmd: BatchDeactivateCommand
    batch_unsub_cmd: BatchUnsubscribeCommand
    export_cmd: ExportSubscriptionsCommand
    import_cmd: ImportSubscriptionsCommand
    get_user_settings_cmd: GetUserSettingsCommand
    set_user_settings_cmd: SetUserSettingsCommand
    test_sub_cmd: TestSubscriptionCommand
    get_subs_query: GetSubscriptionsQuery
    get_items_query: GetFeedItemsQuery
    search_feeds_query: SearchFeedsQuery
    polling_service: FeedPollingService
    feed_repo: FeedRepository
    subscription_repo: SubscriptionRepository
    push_history_repo: Any
    route_knowledge_service: RouteKnowledgeSyncService
    notification_dispatcher: NotificationDispatcher
    agent_xml_push_service: AgentXmlPushService
    subscription_batch_delivery_service: SubscriptionBatchDeliveryService
    card_management_service: SubscriptionCardManagementService
    template_repository: Any
    template_download_service: CardTemplateDownloadService
    template_management_service: CardTemplateManagementService
    delivery_repository: Any
    bundle_repository: Any
    bundle_collection_service: BundleCollectionService
    bundle_document_service: BundleDocumentService
    bundle_batch_delivery_service: BundleBatchDeliveryService
    bundle_card_management_service: BundleCardManagementService
    bundle_cmd: BundleCommand


@dataclass(slots=True)
class PluginRuntime:
    """Initialized runtime objects for the plugin lifecycle."""

    app_settings: ApplicationSettings
    deps: PluginDeps
    scheduler: RSSScheduler
    web_api: WebApiHandler
    push_job_queue: SessionPushQueue
    notification_dispatcher: NotificationDispatcher
    route_knowledge_service: RouteKnowledgeSyncService
    db_initialized: bool

    async def stop(self) -> None:
        """Stop runtime-owned background work and shared resources."""
        await self.route_knowledge_service.close()
        await self.scheduler.stop()
        await self.push_job_queue.stop_all()
        db = get_database()
        if db:
            await db.close()


async def create_plugin_runtime(
    context: Context,
    config: AstrBotConfig | None,
    *,
    push_job_queue: SessionPushQueue | None = None,
) -> PluginRuntime:
    """Initialize the plugin runtime and register Web API endpoints."""
    logger.info("正在初始化 RSSHub 插件...")
    runtime: PluginRuntime | None = None
    scheduler: RSSScheduler | None = None
    queue: SessionPushQueue | None = None
    try:
        plugin_config, app_settings = _init_config(config)
        _schedule_table_font(app_settings)
        await _configure_ffmpeg_bundler(app_settings)
        _configure_message_senders(app_settings)
        _register_bot_client_provider(context)
        await _init_database(plugin_config)

        queue = push_job_queue or SessionPushQueue()
        sender_provider = InfrastructureMessageSenderProvider(
            app_settings.sender_strategies
        )
        deps, notification_dispatcher = await _build_dependencies(
            app_settings=app_settings,
            sender_provider=sender_provider,
            push_job_queue=queue,
            context=context,
        )
        web_api = _register_web_api(context, plugin_config, deps, config)
        scheduler = await _start_scheduler(
            app_settings=app_settings,
            deps=deps,
            notification_dispatcher=notification_dispatcher,
        )

        runtime = PluginRuntime(
            app_settings=app_settings,
            deps=deps,
            scheduler=scheduler,
            web_api=web_api,
            push_job_queue=queue,
            notification_dispatcher=notification_dispatcher,
            route_knowledge_service=deps["route_knowledge_service"],
            db_initialized=True,
        )
        logger.info("RSSHub 插件初始化完成")
        return runtime
    except Exception:
        if runtime is not None:
            await runtime.stop()
        else:
            if scheduler is not None:
                await scheduler.stop()
            if queue is not None:
                await queue.stop_all()
            db = get_database()
            if db.is_initialized:
                await db.close()
        raise


def _schedule_table_font(app_settings: ApplicationSettings) -> None:
    """配置字体下载参数；启用表格转图时后台预取，不阻塞插件启动。

    始终配置代理/超时，使首次表格渲染的按需门控也能复用同一代理；仅当开启
    table_to_image 时才触发后台预取，避免无谓下载。
    """
    configure_table_font_download(
        http_proxy=app_settings.http.proxy,
        timeout=app_settings.http.media_timeout,
    )
    if app_settings.media.table_to_image:
        prefetch_table_font()


def _init_config(
    config: AstrBotConfig | None,
) -> tuple[RsshubPluginConfig, ApplicationSettings]:
    raw_config = dict(config) if config else {}
    if config is not None:
        schema = getattr(config, "schema", None)
        healed_config, healed_changes = heal_astrbot_plugin_config(raw_config, schema)
        if healed_changes:
            config.clear()
            config.update(healed_config)
            config.save_config()
            logger.info(
                "插件配置已按 schema 自愈: fields=%s",
                ", ".join(healed_changes[:20]),
            )
            raw_config = healed_config
    plugin_config = RsshubPluginConfig.from_astrbot_config(raw_config)
    set_config(plugin_config)
    app_settings = build_application_settings(plugin_config)
    logger.debug("配置已加载")
    return plugin_config, app_settings


def _register_bot_client_provider(context: Context) -> None:
    """注册 bot client / bot self_id provider，供主动推送场景使用。

    主动推送没有消息事件，sender 无法从 event 取 bot 客户端。
    这里通过 AstrBot platform_manager 按平台名解析出底层 bot 客户端
    （如 aiocqhttp 的 CQHttp 实例），用于调用 NapCat stream action，
    并从中解析出 bot 的 self_id（QQ 号）供合并转发节点使用。
    """

    def _resolve_bot_client(platform_name: str) -> object | None:
        if not platform_name:
            return None
        try:
            platform_manager = getattr(context, "platform_manager", None)
            if platform_manager is None:
                return None
            for inst in platform_manager.get_insts():
                meta = inst.meta() if hasattr(inst, "meta") else None
                inst_name = getattr(meta, "name", None) or getattr(
                    inst, "platform_name", None
                )
                if inst_name == platform_name and hasattr(inst, "get_client"):
                    return inst.get_client()
        except Exception:
            logger.debug(
                "解析 bot client 失败: platform=%s", platform_name, exc_info=True
            )
        return None

    def _resolve_bot_self_id(platform_name: str) -> str:
        """从已连接的反向 WebSocket 客户端中解析 bot 的 self_id（QQ 号）。

        aiocqhttp 的 CQHttp 实例以 self_id 为键保存已连接的 API 客户端
        （``_wsr_api_clients``）。只有连接中恰有一个非零 self_id 时才返回，
        避免多 bot 平台把其他账号误写入合并转发节点；解析失败时返回空串，
        由调用方保留 SDK 的默认值。
        """
        client = _resolve_bot_client(platform_name)
        if client is None:
            return ""
        api_clients = getattr(client, "_wsr_api_clients", None)
        if isinstance(api_clients, dict):
            self_ids = [
                str(self_id).strip()
                for self_id in list(api_clients)
                if str(self_id or "").strip() not in {"", "0"}
            ]
            if len(self_ids) == 1:
                return self_ids[0]
            if len(self_ids) > 1:
                logger.warning(
                    "无法唯一解析 bot self_id，保留合并转发节点默认值: "
                    "platform=%s, candidates=%s",
                    platform_name,
                    self_ids,
                )
        return ""

    set_bot_client_provider(_resolve_bot_client)
    set_bot_self_id_provider(_resolve_bot_self_id)


async def _configure_ffmpeg_bundler(app_settings: ApplicationSettings) -> None:
    """配置 FFmpeg 捆绑下载参数，后台异步准备。

    - system：只使用系统 PATH，不下载
    - auto：优先系统 PATH；系统缺失时后台异步下载捆绑 FFmpeg，不阻塞启动
    """
    from .src.infrastructure.utils.ffmpeg_helper import FFmpegTool

    FFmpegTool.configure_bundler(
        http_proxy=app_settings.http.proxy,
        timeout=app_settings.http.media_timeout,
        ffmpeg_source=app_settings.media.ffmpeg_source,
        ffmpeg_mirror=app_settings.media.ffmpeg_mirror,
        ffmpeg_mirror_custom_url=app_settings.media.ffmpeg_mirror_custom_url,
    )

    # ffmpeg 已可用（系统 PATH 或已有捆绑缓存）→ 无需下载
    if FFmpegTool.ensure_ffmpeg_ready(auto_install=True) is not None:
        return

    # system 模式不下载
    if not FFmpegTool.allows_bundled_download():
        return

    # 后台异步下载，不阻塞插件启动；需要 ffmpeg 的媒体操作在下载完成前静默跳过
    logger.info("系统未检测到 FFmpeg，正在后台异步下载捆绑包...")
    FFmpegTool.prefetch_bundled_ffmpeg()


def _configure_message_senders(app_settings: ApplicationSettings) -> None:
    """Apply runtime config consumed by concrete message senders."""
    DefaultMessageSender.configure_runtime(
        timeout_seconds=app_settings.http.media_timeout,
        proxy=app_settings.http.proxy,
        image_relay_base_url=app_settings.media.image_relay_base_url,
        media_relay_base_url=app_settings.media.media_relay_base_url,
        media_download_concurrency=app_settings.media.media_download_concurrency,
    )
    DefaultMessageSender.configure_behavior(
        video_transcode=app_settings.media.video_transcode,
        video_transcode_timeout=app_settings.media.video_transcode_timeout,
        gif_transcode=app_settings.media.gif_transcode,
        gif_transcode_timeout=app_settings.media.gif_transcode_timeout,
        gif_transcode_profile=app_settings.media.gif_transcode_profile,
        telegram_photo_max_bytes=app_settings.media_platform_limits.telegram_photo_max_bytes,
        onebot_napcat_stream_mode=(
            app_settings.media_platform_limits.onebot_napcat_stream_mode
        ),
        qq_official_media_threshold=app_settings.media_platform_limits.qq_official_media_threshold,
        qq_official_degrade_strategy=(
            app_settings.media_platform_limits.qq_official_degrade_strategy
        ),
    )
    MediaDownloader.configure_cache(
        enabled=app_settings.media_platform_limits.cache_enabled,
        ttl_seconds=app_settings.media_platform_limits.cache_ttl_seconds,
        gc_interval_seconds=app_settings.media_platform_limits.cache_gc_interval_seconds,
        gc_grace_seconds=app_settings.media_platform_limits.cache_gc_grace_seconds,
    )
    TableImageRenderer.configure_cache(
        enabled=app_settings.media_platform_limits.cache_enabled,
        ttl_seconds=app_settings.media_platform_limits.cache_ttl_seconds,
    )
    configure_media_integrity(
        min_valid_bytes=app_settings.media_platform_limits.min_valid_bytes
    )
    EntryTextFormatter.configure_table_to_image(app_settings.media.table_to_image)
    logger.info(
        "sender behavior configured: gif_transcode=%s, gif_profile=%s, "
        "video_transcode=%s, "
        "ffmpeg_source=%s, image_relay=%s, media_relay=%s, "
        "napcat_stream=%s, table_to_image=%s",
        app_settings.media.gif_transcode,
        app_settings.media.gif_transcode_profile,
        app_settings.media.video_transcode,
        app_settings.media.ffmpeg_source,
        app_settings.media.image_relay_base_url or "(none)",
        app_settings.media.media_relay_base_url or "(none)",
        app_settings.media_platform_limits.onebot_napcat_stream_mode,
        app_settings.media.table_to_image,
    )


async def _init_database(config: RsshubPluginConfig) -> None:
    data_dir = get_plugin_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(data_dir / config.db_file)

    db = get_database()
    await db.init(db_path)
    logger.info("数据库已初始化: %s", db_path)


async def _build_dependencies(
    *,
    app_settings: ApplicationSettings,
    sender_provider: InfrastructureMessageSenderProvider,
    push_job_queue: SessionPushQueue,
    context: Context | None = None,
) -> tuple[PluginDeps, NotificationDispatcher]:
    feed_repo = get_feed_repository()
    sub_repo = get_subscription_repository()
    user_repo = get_user_repository()
    push_history_repo = get_push_history_repository()
    delivery_repo = get_delivery_repository()
    bundle_repo = get_bundle_repository()

    content_handler_runtime = ContentHandlerRuntime(
        context=context,
        settings=app_settings.content_handlers,
    )
    notification_dispatcher = NotificationDispatcher(
        subscription_repo=sub_repo,
        user_repo=user_repo,
        push_history_repo=push_history_repo,
        sender_provider=sender_provider,
        push_job_queue=push_job_queue,
        content_handler_runtime=content_handler_runtime,
        subscription_defaults=app_settings.subscription_defaults,
        basic_settings=app_settings.basic,
    )
    template_repository = CardTemplatePackageRepository(
        builtin_package_dirs=get_builtin_card_template_dirs(),
    )
    template_service = CardTemplateService()
    image_renderer = AstrBotHtmlImageRenderer()
    card_renderer = CardRenderer(
        template_service=template_service,
        artifact_store=CardArtifactStore(),
        image_renderer=image_renderer,
        history_repository=push_history_repo,
    )
    output_executor = SubscriptionOutputExecutor(
        notification_dispatcher=notification_dispatcher,
        card_renderer=card_renderer,
    )
    output_orchestrator = OutputOrchestrator(
        push_history_repo,
        output_executor,
        delivery_repo,
    )
    bundle_output_executor = BundleOutputExecutor(
        notification_dispatcher=notification_dispatcher,
        card_renderer=card_renderer,
    )
    bundle_output_orchestrator = OutputOrchestrator(
        push_history_repo,
        bundle_output_executor,
        delivery_repo,
    )
    subscription_batch_delivery_service = SubscriptionBatchDeliveryService(
        delivery_repository=delivery_repo,
        subscription_repository=sub_repo,
        feed_repository=feed_repo,
        user_repository=user_repo,
        template_repository=template_repository,
        template_service=template_service,
        content_handler_runtime=content_handler_runtime,
        notification_dispatcher=notification_dispatcher,
        output_orchestrator=output_orchestrator,
        history_entry_limit=app_settings.scheduler.history_entry_limit,
        max_retries=app_settings.basic.failed_queue_max_retries,
    )
    polling_service = FeedPollingService(
        feed_repo=feed_repo,
        subscription_repo=sub_repo,
        fetch_settings=app_settings.fetch,
        rss_settings=app_settings.rss,
        fetcher_factory=RSSFeedFetcher,
        parser=RSSParser(),
        notification_dispatcher=notification_dispatcher,
        delivery_repository=delivery_repo,
        subscription_batch_delivery_service=subscription_batch_delivery_service,
        history_entry_limit=app_settings.scheduler.history_entry_limit,
    )
    bundle_collection_service = BundleCollectionService(
        bundle_repository=bundle_repo,
        feed_repository=feed_repo,
        polling_service=polling_service,
        delivery_repository=delivery_repo,
        rss_settings=app_settings.rss,
    )
    bundle_document_service = BundleDocumentService(
        handler_runtime=BundleDocumentHandlerRuntime(context=context),
    )
    bundle_batch_delivery_service = BundleBatchDeliveryService(
        delivery_repository=delivery_repo,
        bundle_repository=bundle_repo,
        feed_repository=feed_repo,
        template_repository=template_repository,
        template_service=template_service,
        document_service=bundle_document_service,
        output_orchestrator=bundle_output_orchestrator,
        notification_dispatcher=notification_dispatcher,
        user_repository=user_repo,
        history_entry_limit=app_settings.scheduler.history_entry_limit,
        max_retries=app_settings.basic.failed_queue_max_retries,
    )
    bundle_command = BundleCommand(
        bundle_repository=bundle_repo,
        feed_repository=feed_repo,
        user_repository=user_repo,
        delivery_repository=delivery_repo,
        template_repository=template_repository,
        polling_service=polling_service,
        bundle_batch_delivery_service=bundle_batch_delivery_service,
        default_interval=app_settings.scheduler.default_interval,
    )
    card_management_service = SubscriptionCardManagementService(
        subscription_repository=sub_repo,
        feed_repository=feed_repo,
        template_repository=template_repository,
        delivery_repository=delivery_repo,
        polling_service=polling_service,
        user_repository=user_repo,
        content_handler_runtime=content_handler_runtime,
        template_service=template_service,
        image_renderer=image_renderer,
    )
    bundle_card_management_service = BundleCardManagementService(
        bundle_repository=bundle_repo,
        feed_repository=feed_repo,
        template_repository=template_repository,
        polling_service=polling_service,
        document_service=bundle_document_service,
        template_service=template_service,
        image_renderer=image_renderer,
    )
    template_download_service = CardTemplateDownloadService(
        template_repository,
        AiohttpCardTemplateArchiveDownloader(),
    )
    template_management_service = CardTemplateManagementService(
        template_repository,
        DatabaseCardTemplateReferenceLookup(get_database()),
    )
    route_source = await build_route_knowledge_source(
        app_settings.route_knowledge,
        proxy=app_settings.http.proxy,
    )
    route_repository = AstrBotRouteKnowledgeRepository(
        context=context,
        settings=app_settings.route_knowledge,
    )
    route_knowledge_service = RouteKnowledgeSyncService(
        settings=app_settings.route_knowledge,
        source=route_source,
        repository=route_repository,
        state_dir=get_plugin_cache_dir("route_knowledge"),
    )

    deps = PluginDeps(
        subscribe_cmd=SubscribeFeedCommand(
            subscription_repo=sub_repo,
            feed_repo=feed_repo,
            fetch_settings=app_settings.fetch,
            fetcher_factory=RSSFeedFetcher,
            user_repo=user_repo,
        ),
        unsubscribe_cmd=UnsubscribeFeedCommand(
            subscription_repo=sub_repo,
            feed_repo=feed_repo,
            delivery_repo=delivery_repo,
        ),
        sub_state_cmd=SubStateCommand(subscription_repo=sub_repo),
        update_sub_cmd=UpdateSubscriptionCommand(
            subscription_repo=sub_repo,
            card_management_service=card_management_service,
        ),
        list_query=GetFeedListQuery(subscription_repo=sub_repo, feed_repo=feed_repo),
        batch_activate_cmd=BatchActivateCommand(subscription_repo=sub_repo),
        batch_deactivate_cmd=BatchDeactivateCommand(subscription_repo=sub_repo),
        batch_unsub_cmd=BatchUnsubscribeCommand(
            subscription_repo=sub_repo,
            delivery_repo=delivery_repo,
        ),
        export_cmd=ExportSubscriptionsCommand(
            subscription_repo=sub_repo,
            feed_repo=feed_repo,
        ),
        import_cmd=ImportSubscriptionsCommand(
            subscription_repo=sub_repo,
            feed_repo=feed_repo,
            user_repo=user_repo,
            card_management_service=card_management_service,
        ),
        get_user_settings_cmd=GetUserSettingsCommand(user_repo=user_repo),
        set_user_settings_cmd=SetUserSettingsCommand(user_repo=user_repo),
        test_sub_cmd=TestSubscriptionCommand(
            subscription_repo=sub_repo,
            feed_repo=feed_repo,
            polling_service=polling_service,
            notification_dispatcher=notification_dispatcher,
        ),
        get_subs_query=GetSubscriptionsQuery(subscription_repo=sub_repo),
        get_items_query=GetFeedItemsQuery(feed_repo=feed_repo),
        search_feeds_query=SearchFeedsQuery(feed_repo=feed_repo),
        polling_service=polling_service,
        feed_repo=feed_repo,
        subscription_repo=sub_repo,
        push_history_repo=push_history_repo,
        route_knowledge_service=route_knowledge_service,
        notification_dispatcher=notification_dispatcher,
        agent_xml_push_service=AgentXmlPushService(notification_dispatcher),
        subscription_batch_delivery_service=subscription_batch_delivery_service,
        card_management_service=card_management_service,
        template_repository=template_repository,
        template_download_service=template_download_service,
        template_management_service=template_management_service,
        delivery_repository=delivery_repo,
        bundle_repository=bundle_repo,
        bundle_collection_service=bundle_collection_service,
        bundle_document_service=bundle_document_service,
        bundle_batch_delivery_service=bundle_batch_delivery_service,
        bundle_card_management_service=bundle_card_management_service,
        bundle_cmd=bundle_command,
    )
    return deps, notification_dispatcher


async def _start_scheduler(
    *,
    app_settings: ApplicationSettings,
    deps: PluginDeps,
    notification_dispatcher: NotificationDispatcher,
) -> RSSScheduler:
    scheduler = RSSScheduler(
        feed_polling_service=deps["polling_service"],
        notification_dispatcher=notification_dispatcher,
        subscription_batch_delivery_service=deps["subscription_batch_delivery_service"],
        bundle_repository=deps["bundle_repository"],
        bundle_collection_service=deps["bundle_collection_service"],
        bundle_batch_delivery_service=deps["bundle_batch_delivery_service"],
        default_interval=app_settings.scheduler.default_interval,
        history_retention_days=app_settings.scheduler.history_retention_days,
    )

    await scheduler.start()

    async def _run_periodic() -> None:
        while scheduler._running:
            try:
                await scheduler.run_periodic_task()
            except Exception:
                logger.exception("RSS 定时任务执行异常")
            await asyncio.sleep(60)

    scheduler._bg_task = asyncio.create_task(_run_periodic())
    logger.info("RSS 调度器已启动并开始定时检查")
    return scheduler


def _register_web_api(
    context: Context,
    config: RsshubPluginConfig,
    deps: PluginDeps,
    raw_config: AstrBotConfig | None = None,
) -> WebApiHandler:
    web_api = WebApiHandler(
        subscribe_cmd=deps["subscribe_cmd"],
        unsubscribe_cmd=deps["unsubscribe_cmd"],
        update_sub_cmd=deps["update_sub_cmd"],
        batch_activate_cmd=deps["batch_activate_cmd"],
        batch_deactivate_cmd=deps["batch_deactivate_cmd"],
        batch_unsub_cmd=deps["batch_unsub_cmd"],
        export_cmd=deps["export_cmd"],
        import_cmd=deps["import_cmd"],
        get_user_settings_cmd=deps["get_user_settings_cmd"],
        set_user_settings_cmd=deps["set_user_settings_cmd"],
        test_sub_cmd=deps["test_sub_cmd"],
        get_items_query=deps["get_items_query"],
        polling_service=deps["polling_service"],
        feed_repo=deps["feed_repo"],
        sub_repo=deps["subscription_repo"],
        user_repo=get_user_repository(),
        push_history_repo=get_push_history_repository(),
        notification_dispatcher=deps["notification_dispatcher"],
        route_knowledge_service=deps["route_knowledge_service"],
        config=config,
        raw_config=raw_config,
        card_management_service=deps["card_management_service"],
        template_repository=deps["template_repository"],
        template_download_service=deps["template_download_service"],
        template_management_service=deps["template_management_service"],
        subscription_batch_delivery_service=deps["subscription_batch_delivery_service"],
        delivery_repository=deps["delivery_repository"],
        bundle_cmd=deps["bundle_cmd"],
        bundle_repository=deps["bundle_repository"],
        bundle_card_management_service=deps["bundle_card_management_service"],
        bundle_batch_delivery_service=deps["bundle_batch_delivery_service"],
    )
    web_api.register_all(context)
    logger.info("Web API 已注册")
    return web_api
