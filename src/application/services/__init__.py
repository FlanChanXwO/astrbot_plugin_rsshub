"""应用服务包的兼容导出层。

优先从具体模块导入，避免包导入时拉起整片实现。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MAP = {
    "AgentXmlPushService": "agent_xml_push_service",
    "AgentXmlValidationError": "agent_xml_push_service",
    "CardTemplateDownloadService": "card_template_service",
    "CardTemplateInUseError": "card_template_service",
    "CardTemplateManagementService": "card_template_service",
    "CardRenderer": "card_renderer",
    "CardRenderResult": "card_renderer",
    "FeedPollingService": "feed_polling_service",
    "FeedPollingResult": "feed_polling_service",
    "FeedReadResult": "feed_polling_service",
    "FeedEntrySnapshot": "feed_polling_service",
    "BundleCollectionService": "bundle_collection_service",
    "BundleCollectionResult": "bundle_collection_service",
    "BundleMemberCollectionResult": "bundle_collection_service",
    "BundleBatchDeliveryError": "bundle_batch_delivery_service",
    "BundleBatchDeliveryResult": "bundle_batch_delivery_service",
    "BundleBatchDeliveryService": "bundle_batch_delivery_service",
    "BundleAggregateDocument": "bundle_document_service",
    "BundleDocumentBuilder": "bundle_document_service",
    "BundleDocumentEntry": "bundle_document_service",
    "BundleDocumentHandlerResult": "bundle_document_service",
    "BundleDocumentHandlerRuntime": "bundle_document_service",
    "BundleDocumentService": "bundle_document_service",
    "BundleDocumentValidationError": "bundle_document_service",
    "BundleRssDocumentBuilder": "bundle_document_service",
    "BundleRssDocumentValidator": "bundle_document_service",
    "BundleOutputExecutor": "bundle_output_executor",
    "NotificationDispatcher": "notification_dispatcher",
    "OutputOrchestrationResult": "output_orchestrator",
    "OutputOrchestrator": "output_orchestrator",
    "SessionPushQueue": "session_push_queue",
    "SubscriptionBatchDeliveryError": "subscription_batch_delivery_service",
    "SubscriptionBatchDeliveryResult": "subscription_batch_delivery_service",
    "SubscriptionBatchDeliveryService": "subscription_batch_delivery_service",
    "SubscriptionCardManagementService": "subscription_card_management_service",
    "SubscriptionOutputExecutor": "subscription_output_executor",
    "RouteKnowledgeSyncService": "route_knowledge_service",
    "RouteKnowledgeSyncPlan": "route_knowledge_service",
    "RouteKnowledgeSyncResult": "route_knowledge_service",
    "RouteKnowledgeStatus": "route_knowledge_service",
    "RouteKnowledgeTaskStatus": "route_knowledge_service",
    "RouteKnowledgeSyncAlreadyRunning": "route_knowledge_service",
    "build_sync_plan": "route_knowledge_service",
    "PushJob": "session_push_queue",
    "PushJobResult": "session_push_queue",
    "StopPushJobResult": "session_push_queue",
    "HTMLParser": "html_parser",
    "HTMLCleaner": "html_parser",
    "InsecureCardTemplateDownloadError": "card_template_service",
    "parse_html": "html_parser",
    "clean_html": "html_parser",
    "serialize_subscriptions_to_toml": "subscription_serializer",
    "parse_subscriptions_toml": "subscription_serializer",
    "SubscriptionImportPayload": "subscription_serializer",
    "UnsupportedCardTemplateUrlError": "card_template_service",
    "ImportSubscriptionRecord": "subscription_serializer",
}

# 兼容导出由上方映射统一生成，避免映射与静态列表发生漂移。
__all__ = sorted(_EXPORT_MAP)  # noqa: PLE0605


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MAP.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
