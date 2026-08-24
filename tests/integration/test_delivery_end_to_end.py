"""跨层验证：Feed/Bundle 抓取、handler、可靠批次与输出恢复。"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from astrbot_plugin_rsshub.src.application.ports.message_sender import SendResult
from astrbot_plugin_rsshub.src.application.services.bundle_batch_delivery_service import (
    BundleBatchDeliveryService,
)
from astrbot_plugin_rsshub.src.application.services.bundle_collection_service import (
    BundleCollectionService,
)
from astrbot_plugin_rsshub.src.application.services.bundle_document_service import (
    BundleDocumentHandlerRuntime,
    BundleDocumentService,
)
from astrbot_plugin_rsshub.src.application.services.content_handlers import (
    EntryContentContext,
    HandlerProcessResult,
)
from astrbot_plugin_rsshub.src.application.services.feed_polling_service import (
    FeedPollingService,
)
from astrbot_plugin_rsshub.src.application.services.notification_dispatcher import (
    PreparedSubscriptionDispatch,
)
from astrbot_plugin_rsshub.src.application.services.output_orchestrator import (
    OutputOrchestrator,
)
from astrbot_plugin_rsshub.src.application.services.subscription_batch_delivery_service import (
    SubscriptionBatchDeliveryService,
)
from astrbot_plugin_rsshub.src.domain.entities.delivery import (
    DeliveryInboxItemDraft,
    DeliveryOwner,
)
from astrbot_plugin_rsshub.src.infrastructure.config import (
    FeedFetchSettings,
    RSSSettings,
)
from astrbot_plugin_rsshub.src.infrastructure.fetcher import RSSParser
from astrbot_plugin_rsshub.src.infrastructure.persistence import (
    feed_repository_impl,
    push_history_repository_impl,
    subscription_repository_impl,
    user_repository_impl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.bundle_repository_impl import (
    BundleRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import (
    DatabaseManager,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.delivery_repository_impl import (
    DeliveryRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.feed_repository_impl import (
    FeedRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.models import (
    BundleFeedORM,
    BundleORM,
    FeedORM,
    SubORM,
    UserORM,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.push_history_repository_impl import (
    PushHistoryRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.subscription_repository_impl import (
    SubscriptionRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.user_repository_impl import (
    UserRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.templates import (
    CardTemplatePackageRepository,
    CardTemplateService,
    get_builtin_card_template_dirs,
)


class _FixtureFetcher:
    """把本地 fixture 接到 FeedPollingService 的 fetcher port。"""

    def __init__(self, feeds: dict[str, str]) -> None:
        self._feeds = feeds

    async def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        verbose: bool = False,
    ) -> SimpleNamespace:
        del headers, verbose
        return SimpleNamespace(
            status=200,
            error=None,
            content=self._feeds[url],
            etag='"fixture-etag"',
            last_modified=None,
            rss_d=SimpleNamespace(feed={"title": "Fixture Feed"}),
        )

    async def close(self) -> None:
        return None


class _EntryHandler:
    def __init__(self) -> None:
        self.calls = 0

    async def process_entry_with_trace(self, **kwargs: object) -> HandlerProcessResult:
        self.calls += 1
        entry = kwargs["entry"]
        assert isinstance(entry, EntryContentContext)
        processed = replace(
            entry,
            title=f"{entry.title}（handler）",
            summary="handler 摘要",
            content="handler 正文",
        )
        return HandlerProcessResult(
            entry=processed,
            trace=({"name": "fixture_handler", "status": "ok"},),
        )


class _PreparingDispatcher:
    async def prepare_subscription_entry(
        self, **kwargs: object
    ) -> PreparedSubscriptionDispatch:
        subscription = kwargs["subscription"]
        entry = kwargs["entry"]
        handler_trace = kwargs.get("handler_trace")
        assert isinstance(entry, EntryContentContext)
        return PreparedSubscriptionDispatch(
            subscription=subscription,
            processed_entry=entry,
            handler_trace=handler_trace,
            effective_title=entry.title,
            effective_link=entry.link,
            effective_content=entry.content,
            effective_send_mode=1,
            effective_style=0,
            effective_media_urls=None,
            effective_media_items=None,
            effective_layout=None,
            persisted_media_urls=None,
        )


class _RecordingExecutor:
    """发送边界替身：首个 card 失败，其余尝试成功。"""

    def __init__(self) -> None:
        self.mode = "fail-first-card"
        self.calls: list[str] = []
        self.card_contexts: list[dict[str, Any]] = []

    async def execute(self, history: Any) -> SendResult:
        self.calls.append(history.output_kind)
        if history.output_kind == "card":
            self.card_contexts.append(copy.deepcopy(history.source_context))
            if self.mode == "fail-first-card" and self.calls.count("card") == 1:
                return SendResult(ok=False, detail="fixture card failed")
            if self.mode == "always-fail":
                return SendResult(ok=False, detail="fixture card remains blocked")
        return SendResult(ok=True)


async def _isolated_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> DatabaseManager:
    database = DatabaseManager()
    await database.init(str(tmp_path / "delivery-e2e.db"))
    for module in (
        feed_repository_impl,
        push_history_repository_impl,
        subscription_repository_impl,
        user_repository_impl,
    ):
        monkeypatch.setattr(module, "get_database", lambda database=database: database)
    return database


def _fetcher_factory(feeds: dict[str, str]):
    def factory(*, timeout: int, proxy: str) -> _FixtureFetcher:
        del timeout, proxy
        return _FixtureFetcher(feeds)

    return factory


def _polling_service(
    *,
    feed_repository: FeedRepositoryImpl,
    subscription_repository: SubscriptionRepositoryImpl,
    delivery_repository: DeliveryRepositoryImpl,
    feeds: dict[str, str],
) -> FeedPollingService:
    return FeedPollingService(
        feed_repo=feed_repository,
        subscription_repo=subscription_repository,
        fetch_settings=FeedFetchSettings(),
        rss_settings=RSSSettings(bootstrap_skip_history=False),
        fetcher_factory=_fetcher_factory(feeds),
        parser=RSSParser(),
        delivery_repository=delivery_repository,
    )


def _template_repository(tmp_path: Path) -> CardTemplatePackageRepository:
    return CardTemplatePackageRepository(
        storage_dir=tmp_path / "installed-card-templates",
        builtin_package_dirs=get_builtin_card_template_dirs(),
    )


async def _seed_subscription(database: DatabaseManager) -> None:
    async with database.get_session() as session:
        session.add(UserORM(id="feed-user"))
        session.add(
            FeedORM(
                id=1,
                link="https://rsshub.app/juya/ai",
                title="Juya AI",
            )
        )
        await session.commit()
        session.add(
            SubORM(
                id=1,
                user_id="feed-user",
                feed_id=1,
                target_session="test:Group:feed",
                platform_name="test",
                send_card=True,
                template_id="astrbot_plugin_rsshub_card_juya",
                card_send_original_content=True,
                interval=10,
                notify=1,
            )
        )
        await session.commit()


async def _seed_bundle(database: DatabaseManager) -> None:
    handler_config = [
        {
            "id": "bundle.transform",
            "name": "ai_transform",
            "status": 1,
            "config": {"prompt": "rewrite", "scope": "plaintext"},
        }
    ]
    async with database.get_session() as session:
        session.add(UserORM(id="bundle-user"))
        session.add_all(
            [
                FeedORM(id=2, link="https://example.com/source-a", title="Source A"),
                FeedORM(id=3, link="https://example.com/source-b", title="Source B"),
            ]
        )
        await session.commit()
        session.add(
            BundleORM(
                id=2,
                user_id="bundle-user",
                name="Fixture Bundle",
                target_sessions=["test:Group:bundle"],
                interval=30,
                state=1,
                send_card=True,
                template_id="astrbot_plugin_rsshub_card_bundle",
                card_send_original_content=True,
                handlers=json.dumps(handler_config),
            )
        )
        await session.commit()
        session.add_all(
            [
                BundleFeedORM(id=21, bundle_id=2, feed_id=2, position=0),
                BundleFeedORM(id=22, bundle_id=2, feed_id=3, position=1),
            ]
        )
        await session.commit()


class _Provider:
    def __init__(self) -> None:
        self.calls = 0

    async def text_chat(self, **kwargs: object) -> SimpleNamespace:
        del kwargs
        self.calls += 1
        return SimpleNamespace(completion_text='{"text":"handler bundle text"}')


class _ProviderContext:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider

    def get_using_provider(self, _session_id: str | None = None) -> _Provider:
        return self.provider


@pytest.mark.asyncio
async def test_feed_fetch_handler_card_standard_history_and_retry(
    fixtures_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = await _isolated_database(tmp_path, monkeypatch)
    try:
        await _seed_subscription(database)
        xml = (fixtures_dir / "feeds" / "juya_ai_daily_minimal.xml").read_text(
            encoding="utf-8"
        )
        feed_repository = FeedRepositoryImpl()
        subscription_repository = SubscriptionRepositoryImpl()
        delivery_repository = DeliveryRepositoryImpl(database)
        polling = _polling_service(
            feed_repository=feed_repository,
            subscription_repository=subscription_repository,
            delivery_repository=delivery_repository,
            feeds={"https://rsshub.app/juya/ai": xml},
        )

        poll_result = await polling.poll_feed(1, notify_new_entries=True)
        assert poll_result.success is True
        assert poll_result.new_entries == 1
        assert (
            len(
                await delivery_repository.list_inbox_items(
                    owner=DeliveryOwner(owner_type="subscription", owner_id=1)
                )
            )
            == 1
        )

        handler = _EntryHandler()
        executor = _RecordingExecutor()
        history_repository = PushHistoryRepositoryImpl()
        orchestrator = OutputOrchestrator(
            history_repository,
            executor,
            delivery_repository,
        )
        service = SubscriptionBatchDeliveryService(
            delivery_repository=delivery_repository,
            subscription_repository=subscription_repository,
            feed_repository=feed_repository,
            user_repository=UserRepositoryImpl(),
            template_repository=_template_repository(tmp_path),
            template_service=CardTemplateService(),
            content_handler_runtime=handler,
            notification_dispatcher=_PreparingDispatcher(),
            output_orchestrator=orchestrator,
            max_retries=2,
        )

        first = await service.deliver(1)
        assert first.ready_to_confirm is False
        assert executor.calls == ["card"]

        second = await service.deliver(1, retry_failed=True)
        assert second.ready_to_confirm is True
        assert executor.calls == ["card", "card", "standard"]
        assert handler.calls == 1
        assert executor.card_contexts[0] == executor.card_contexts[1]
        assert (
            "（handler）"
            in executor.card_contexts[0]["document_snapshot"]["entries"][0]["title"]
        )

        histories = await history_repository.get_by_user("feed-user", limit=20)
        assert {(item.output_kind, item.status) for item in histories} == {
            ("card", "success"),
            ("standard", "success"),
        }
        confirmed = await delivery_repository.get_batch(first.batch_id)
        assert confirmed is not None
        assert confirmed.status == "confirmed"
        assert confirmed.inbox_items == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_bundle_fetch_handler_card_standard_retry_and_discard(
    fixtures_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = await _isolated_database(tmp_path, monkeypatch)
    try:
        await _seed_bundle(database)
        xml = (fixtures_dir / "feeds" / "simple_rss.xml").read_text(encoding="utf-8")
        feed_repository = FeedRepositoryImpl()
        subscription_repository = SubscriptionRepositoryImpl()
        delivery_repository = DeliveryRepositoryImpl(database)
        polling = _polling_service(
            feed_repository=feed_repository,
            subscription_repository=subscription_repository,
            delivery_repository=delivery_repository,
            feeds={
                "https://example.com/source-a": xml,
                "https://example.com/source-b": xml,
            },
        )
        bundle_repository = BundleRepositoryImpl(
            database,
            delivery_repository=delivery_repository,
        )
        collection = BundleCollectionService(
            bundle_repository=bundle_repository,
            feed_repository=feed_repository,
            polling_service=polling,
            delivery_repository=delivery_repository,
            rss_settings=RSSSettings(bootstrap_skip_history=False),
        )

        collected = await collection.collect_bundle(2)
        assert collected.success is True
        assert collected.new_entries == 6

        provider = _Provider()
        document_service = BundleDocumentService(
            handler_runtime=BundleDocumentHandlerRuntime(_ProviderContext(provider))
        )
        executor = _RecordingExecutor()
        history_repository = PushHistoryRepositoryImpl()
        orchestrator = OutputOrchestrator(
            history_repository,
            executor,
            delivery_repository,
        )
        service = BundleBatchDeliveryService(
            delivery_repository=delivery_repository,
            bundle_repository=bundle_repository,
            feed_repository=feed_repository,
            template_repository=_template_repository(tmp_path),
            template_service=CardTemplateService(),
            document_service=document_service,
            output_orchestrator=orchestrator,
            max_retries=2,
        )

        first = await service.deliver(2)
        assert first.ready_to_confirm is False
        second = await service.retry(2)
        assert second.ready_to_confirm is True
        assert executor.calls == ["card", "card", "standard"]
        assert provider.calls == 1
        assert executor.card_contexts[0] == executor.card_contexts[1]
        document_snapshot = executor.card_contexts[0]["document_snapshot"]
        assert document_snapshot["document"]["text"] == "handler bundle text"
        assert document_snapshot["document"]["rss_xml"].startswith('<rss version="2.0"')
        assert document_snapshot["handler_trace"][0]["name"] == "ai_transform"

        extra = DeliveryInboxItemDraft(
            feed_id=2,
            bundle_feed_id=21,
            member_position=0,
            item_key="extra-entry",
            hash_group=["extra-entry"],
            discovery_key="bundle-extra-discovery",
            entry_payload={
                "title": "Extra",
                "link": "https://example.com/extra",
                "summary": "extra",
            },
        )
        await delivery_repository.store_inbox_items(
            owner=DeliveryOwner(owner_type="bundle", owner_id=2),
            items=[extra],
        )
        executor.mode = "always-fail"
        blocked = await service.deliver(2)
        assert blocked.ready_to_confirm is False
        discarded = await service.discard(2, reason="fixture discard")
        assert discarded is not None
        assert discarded.status == "discarded"
        assert (
            await delivery_repository.list_inbox_items(
                owner=DeliveryOwner(owner_type="bundle", owner_id=2)
            )
            == []
        )
        discarded_histories = await history_repository.get_by_user(
            "bundle-user", limit=20
        )
        assert any(item.status == "discarded" for item in discarded_histories)
    finally:
        await database.close()
