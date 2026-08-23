from __future__ import annotations

from datetime import datetime, timezone

import pytest
from astrbot_plugin_rsshub.src.domain.entities.push_history import PushHistory
from astrbot_plugin_rsshub.src.domain.entities.subscription import Subscription
from astrbot_plugin_rsshub.src.infrastructure.persistence import (
    database as database_module,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence import (
    push_history_repository_impl,
    subscription_repository_impl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import (
    DatabaseManager,
    RSSHubBaseModel,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.migrations import (
    MigrationRunner,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.migrations import (
    V3_unified_delivery_schema as migration_v3,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.migrations.migration_runner import (
    MigrationScript,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.models import (
    BundleFeedORM,
    BundleORM,
    DeliveryBatchORM,
    DeliveryInboxItemORM,
    FeedORM,
    PushHistoryORM,
    UserORM,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.push_history_repository_impl import (
    PushHistoryRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.subscription_repository_impl import (
    SubscriptionRepositoryImpl,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_subscription_card_fields_round_trip(monkeypatch, tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "subscription-card-fields.db"))
    monkeypatch.setattr(
        subscription_repository_impl,
        "get_database",
        lambda: database,
    )
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(
            FeedORM(
                id=1,
                link="https://example.com/feed",
                title="Example Feed",
            )
        )
        await session.commit()

    repository = SubscriptionRepositoryImpl()
    saved = await repository.save(
        Subscription(
            user_id="user-1",
            feed_id=1,
            send_card=True,
            template_id="astrbot_plugin_rsshub_card_generic",
            card_send_original_content=True,
        )
    )
    loaded = await repository.get_by_id(saved.id)

    assert loaded is not None
    assert loaded.send_card is True
    assert loaded.template_id == "astrbot_plugin_rsshub_card_generic"
    assert loaded.card_send_original_content is True
    await database.close()


@pytest.mark.asyncio
async def test_delivery_output_fields_round_trip(monkeypatch, tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "delivery-output-fields.db"))
    monkeypatch.setattr(
        push_history_repository_impl,
        "get_database",
        lambda: database,
    )
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        await session.commit()

    repository = PushHistoryRepositoryImpl()
    saved = await repository.save(
        PushHistory(
            user_id="user-1",
            status="waiting",
            output_kind="card",
            output_order=2,
            source_context={
                "owner_type": "bundle",
                "owner_id": 9,
                "feed_ids": [1, 2],
            },
        )
    )
    loaded = await repository.get_by_id(saved.id)

    assert loaded is not None
    assert loaded.status == "waiting"
    assert loaded.output_kind == "card"
    assert loaded.output_order == 2
    assert loaded.source_context == {
        "owner_type": "bundle",
        "owner_id": 9,
        "feed_ids": [1, 2],
    }
    await database.close()


@pytest.mark.asyncio
async def test_bundle_orm_round_trip_uses_delivery_defaults(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bundle-round-trip.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        await session.commit()
        session.add(
            BundleORM(
                user_id="user-1",
                name="Daily digest",
                target_sessions=["test:Group:1", "test:Group:2"],
                interval=30,
            )
        )
        await session.commit()

    async with database.get_session() as session:
        bundle = await session.get(BundleORM, 1)

    assert bundle is not None
    assert bundle.target_sessions == ["test:Group:1", "test:Group:2"]
    assert bundle.state == 0
    assert bundle.next_check_time is None
    assert bundle.handlers == "[]"
    assert bundle.send_card is False
    assert bundle.template_id is None
    assert bundle.card_send_original_content is False
    await database.close()


@pytest.mark.asyncio
async def test_bundle_name_is_unique_per_user(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bundle-name-unique.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        await session.commit()
        session.add_all(
            [
                BundleORM(
                    user_id="user-1",
                    name="Daily digest",
                    target_sessions=["test:Group:1"],
                    interval=30,
                ),
                BundleORM(
                    user_id="user-1",
                    name="Daily digest",
                    target_sessions=["test:Group:2"],
                    interval=60,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await database.close()


@pytest.mark.parametrize(
    ("case", "overrides"),
    [
        ("state", {"state": 2}),
        ("interval", {"interval": 0}),
        ("targets", {"target_sessions": []}),
    ],
)
@pytest.mark.asyncio
async def test_bundle_storage_rejects_invalid_invariants(
    case: str,
    overrides: dict[str, object],
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / f"bundle-invalid-{case}.db"))
    payload = {
        "user_id": "user-1",
        "name": "Daily digest",
        "target_sessions": ["test:Group:1"],
        "interval": 30,
    }
    payload.update(overrides)
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        await session.commit()
        session.add(BundleORM(**payload))
        with pytest.raises(IntegrityError):
            await session.commit()

    await database.close()


@pytest.mark.asyncio
async def test_bundle_feed_private_watermark_round_trip(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bundle-feed-watermark.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(
            FeedORM(
                id=1,
                link="https://example.com/feed",
                title="Example Feed",
            )
        )
        await session.commit()
        session.add(
            BundleORM(
                id=1,
                user_id="user-1",
                name="Daily digest",
                target_sessions=["test:Group:1"],
                interval=30,
            )
        )
        await session.commit()
        session.add(
            BundleFeedORM(
                bundle_id=1,
                feed_id=1,
                position=0,
                entry_hashes=["hash-a", "hash-b"],
                etag='"etag-1"',
                last_check_status="success",
            )
        )
        await session.commit()

    async with database.get_session() as session:
        member = await session.get(BundleFeedORM, 1)

    assert member is not None
    assert member.position == 0
    assert member.entry_hashes == ["hash-a", "hash-b"]
    assert member.etag == '"etag-1"'
    assert member.last_modified is None
    assert member.last_check_status == "success"
    assert member.last_checked_at is None
    await database.close()


@pytest.mark.parametrize(
    ("case", "second_feed_id", "second_position"),
    [
        ("duplicate-feed", 1, 1),
        ("duplicate-position", 2, 0),
        ("negative-position", 2, -1),
    ],
)
@pytest.mark.asyncio
async def test_bundle_feed_storage_rejects_invalid_membership(
    case: str,
    second_feed_id: int,
    second_position: int,
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / f"bundle-feed-invalid-{case}.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add_all(
            [
                FeedORM(id=1, link="https://example.com/1", title="Feed 1"),
                FeedORM(id=2, link="https://example.com/2", title="Feed 2"),
            ]
        )
        await session.commit()
        session.add(
            BundleORM(
                id=1,
                user_id="user-1",
                name="Daily digest",
                target_sessions=["test:Group:1"],
                interval=30,
            )
        )
        await session.commit()
        session.add(BundleFeedORM(bundle_id=1, feed_id=1, position=0))
        await session.commit()
        session.add(
            BundleFeedORM(
                bundle_id=1,
                feed_id=second_feed_id,
                position=second_position,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await database.close()


@pytest.mark.asyncio
async def test_delivery_batch_snapshots_round_trip(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "delivery-batch-round-trip.db"))
    async with database.get_session() as session:
        session.add(
            DeliveryBatchORM(
                owner_type="bundle",
                owner_id=9,
                target_sessions=["test:Group:1", "test:Group:2"],
                config_snapshot={"send_card": True, "send_mode": 0},
                template_snapshot={
                    "id": "astrbot_plugin_rsshub_card_generic",
                    "version": "1.0.0",
                    "html": "<main>{{ entries }}</main>",
                },
                document_snapshot={
                    "text": "Daily digest",
                    "rss_xml": "<rss version='2.0'/>",
                },
            )
        )
        await session.commit()

    async with database.get_session() as session:
        batch = await session.get(DeliveryBatchORM, 1)

    assert batch is not None
    assert batch.owner_type == "bundle"
    assert batch.owner_id == 9
    assert batch.status == "pending"
    assert batch.target_sessions == ["test:Group:1", "test:Group:2"]
    assert batch.config_snapshot == {"send_card": True, "send_mode": 0}
    assert batch.template_snapshot == {
        "id": "astrbot_plugin_rsshub_card_generic",
        "version": "1.0.0",
        "html": "<main>{{ entries }}</main>",
    }
    assert batch.document_snapshot == {
        "text": "Daily digest",
        "rss_xml": "<rss version='2.0'/>",
    }
    assert batch.confirmed_at is None
    await database.close()


@pytest.mark.parametrize(
    ("case", "overrides"),
    [
        ("owner-type", {"owner_type": "feed"}),
        ("status", {"status": "failed"}),
        ("targets", {"target_sessions": []}),
    ],
)
@pytest.mark.asyncio
async def test_delivery_batch_storage_rejects_invalid_contracts(
    case: str,
    overrides: dict[str, object],
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / f"delivery-batch-invalid-{case}.db"))
    payload = {
        "owner_type": "subscription",
        "owner_id": 1,
        "target_sessions": ["test:Group:1"],
    }
    payload.update(overrides)
    async with database.get_session() as session:
        session.add(DeliveryBatchORM(**payload))
        with pytest.raises(IntegrityError):
            await session.commit()

    await database.close()


@pytest.mark.asyncio
async def test_delivery_batch_allows_only_one_pending_batch_per_owner(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "delivery-batch-one-pending.db"))
    async with database.get_session() as session:
        session.add(
            DeliveryBatchORM(
                owner_type="subscription",
                owner_id=5,
                target_sessions=["test:Group:1"],
            )
        )
        await session.commit()
        session.add(
            DeliveryBatchORM(
                owner_type="subscription",
                owner_id=5,
                target_sessions=["test:Group:1"],
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await database.close()


@pytest.mark.asyncio
async def test_delivery_inbox_item_round_trip(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "delivery-inbox-round-trip.db"))
    published_at = datetime(2026, 8, 24, 8, 30, tzinfo=timezone.utc)
    updated_at = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(
            FeedORM(
                id=1,
                link="https://example.com/feed",
                title="Example Feed",
            )
        )
        await session.commit()
        session.add(
            DeliveryInboxItemORM(
                owner_type="subscription",
                owner_id=7,
                feed_id=1,
                item_key="guid:item-1",
                hash_group=["guid:item-1", "link:https://example.com/item-1"],
                discovery_key="subscription:7:discovery:abc",
                entry_payload={
                    "title": "Item 1",
                    "link": "https://example.com/item-1",
                },
                raw_xml="<item><title>Item 1</title></item>",
                media_items=[{"url": "https://example.com/image.png"}],
                published_at=published_at,
                entry_updated_at=updated_at,
            )
        )
        await session.commit()

    async with database.get_session() as session:
        item = await session.get(DeliveryInboxItemORM, 1)

    assert item is not None
    assert item.owner_type == "subscription"
    assert item.owner_id == 7
    assert item.feed_id == 1
    assert item.bundle_feed_id is None
    assert item.member_position is None
    assert item.item_key == "guid:item-1"
    assert item.hash_group == [
        "guid:item-1",
        "link:https://example.com/item-1",
    ]
    assert item.discovery_key == "subscription:7:discovery:abc"
    assert item.entry_payload["title"] == "Item 1"
    assert item.raw_xml == "<item><title>Item 1</title></item>"
    assert item.media_items == [{"url": "https://example.com/image.png"}]
    assert item.published_at == published_at.replace(tzinfo=None)
    assert item.entry_updated_at == updated_at.replace(tzinfo=None)
    assert item.batch_id is None
    await database.close()


@pytest.mark.asyncio
async def test_delivery_inbox_item_is_idempotent_per_owner_source_and_key(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "delivery-inbox-idempotent.db"))
    async with database.get_session() as session:
        session.add(
            FeedORM(
                id=1,
                link="https://example.com/feed",
                title="Example Feed",
            )
        )
        await session.commit()
        session.add(
            DeliveryInboxItemORM(
                owner_type="subscription",
                owner_id=7,
                feed_id=1,
                item_key="guid:item-1",
                discovery_key="discovery-1",
            )
        )
        await session.commit()
        session.add(
            DeliveryInboxItemORM(
                owner_type="subscription",
                owner_id=7,
                feed_id=1,
                item_key="guid:item-1",
                discovery_key="discovery-2",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await database.close()


@pytest.mark.parametrize(
    ("case", "overrides"),
    [
        ("owner-type", {"owner_type": "feed"}),
        (
            "subscription-source",
            {
                "owner_type": "subscription",
                "bundle_feed_id": 1,
                "member_position": 0,
            },
        ),
        (
            "bundle-source",
            {
                "owner_type": "bundle",
                "bundle_feed_id": None,
                "member_position": 0,
            },
        ),
        (
            "member-position",
            {
                "owner_type": "bundle",
                "bundle_feed_id": 1,
                "member_position": -1,
            },
        ),
        ("item-key", {"item_key": "   "}),
        ("discovery-key", {"discovery_key": ""}),
    ],
)
@pytest.mark.asyncio
async def test_delivery_inbox_rejects_invalid_owner_source_contract(
    case: str,
    overrides: dict[str, object],
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / f"delivery-inbox-invalid-{case}.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(
            FeedORM(
                id=1,
                link="https://example.com/feed",
                title="Example Feed",
            )
        )
        await session.commit()
        session.add(
            BundleORM(
                id=1,
                user_id="user-1",
                name="Daily digest",
                target_sessions=["test:Group:1"],
                interval=30,
            )
        )
        await session.commit()
        session.add(BundleFeedORM(id=1, bundle_id=1, feed_id=1, position=0))
        await session.commit()
        payload = {
            "owner_type": "subscription",
            "owner_id": 7,
            "feed_id": 1,
            "item_key": "guid:item-1",
            "discovery_key": "discovery-1",
        }
        payload.update(overrides)
        session.add(DeliveryInboxItemORM(**payload))
        with pytest.raises(IntegrityError):
            await session.commit()

    await database.close()


@pytest.mark.asyncio
async def test_push_history_batch_and_bundle_links_round_trip(
    monkeypatch,
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "push-history-delivery-links.db"))
    monkeypatch.setattr(
        push_history_repository_impl,
        "get_database",
        lambda: database,
    )
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        await session.commit()
        session.add(
            BundleORM(
                id=1,
                user_id="user-1",
                name="Daily digest",
                target_sessions=["test:Group:1"],
                interval=30,
            )
        )
        session.add(
            DeliveryBatchORM(
                id=1,
                owner_type="bundle",
                owner_id=1,
                target_sessions=["test:Group:1"],
            )
        )
        await session.commit()

    repository = PushHistoryRepositoryImpl()
    saved = await repository.save(
        PushHistory(
            user_id="user-1",
            batch_id=1,
            bundle_id=1,
            source_type="bundle",
            source_key="bundle:1",
            status="pending",
        )
    )
    loaded = await repository.get_by_id(saved.id)

    assert loaded is not None
    assert loaded.batch_id == 1
    assert loaded.bundle_id == 1
    assert loaded.source_type == "bundle"
    assert loaded.source_key == "bundle:1"
    await database.close()


@pytest.mark.parametrize(
    ("case", "overrides"),
    [
        ("output-kind", {"output_kind": "image"}),
        ("output-order", {"output_order": -1}),
        ("status", {"status": "unknown"}),
    ],
)
@pytest.mark.asyncio
async def test_push_history_rejects_invalid_delivery_output_contract(
    case: str,
    overrides: dict[str, object],
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / f"push-history-invalid-{case}.db"))
    payload = {
        "user_id": "user-1",
        "status": "waiting",
    }
    payload.update(overrides)
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(PushHistoryORM(**payload))
        with pytest.raises(IntegrityError):
            await session.commit()

    await database.close()


@pytest.mark.asyncio
async def test_database_manager_enforces_declared_foreign_keys(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "foreign-keys.db"))
    async with database.get_session() as session:
        session.add(
            BundleORM(
                user_id="missing-user",
                name="Daily digest",
                target_sessions=["test:Group:1"],
                interval=30,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await database.close()


@pytest.mark.asyncio
async def test_v3_upgrades_v2_database_without_losing_existing_rows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        assert await MigrationRunner().run_to(conn, 2) == [1, 2]
        await conn.exec_driver_sql("INSERT INTO rsshub_user (id) VALUES ('user-1')")
        await conn.exec_driver_sql(
            "INSERT INTO rsshub_feed (id, link, title) "
            "VALUES (1, 'https://example.com/feed', 'Example Feed')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO rsshub_sub (id, user_id, feed_id, title) "
            "VALUES (1, 'user-1', 1, 'Existing subscription')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO rsshub_push_history "
            "(id, sub_id, user_id, feed_id, content, status) "
            "VALUES (1, 1, 'user-1', 1, 'Existing history', 'success')"
        )

    async with engine.begin() as conn:
        executed = await MigrationRunner().run_all(conn)
        tables = {
            str(row[0])
            for row in (
                await conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ).fetchall()
        }
        indexes = {
            str(row[0])
            for row in (
                await conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            ).fetchall()
        }
        sub_row = (
            await conn.exec_driver_sql(
                "SELECT title, send_card, template_id, "
                "card_send_original_content FROM rsshub_sub WHERE id=1"
            )
        ).one()
        history_row = (
            await conn.exec_driver_sql(
                "SELECT content, batch_id, bundle_id, output_kind, output_order, "
                "source_context FROM rsshub_push_history WHERE id=1"
            )
        ).one()
        batch_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_delivery_batch)")
            ).fetchall()
        }

    assert executed == [3, 4]
    assert {
        "rsshub_bundle",
        "rsshub_bundle_feed",
        "rsshub_delivery_batch",
        "rsshub_delivery_inbox",
    }.issubset(tables)
    assert {
        "uq_rsshub_delivery_batch_pending_owner",
        "idx_rsshub_delivery_inbox_unclaimed",
        "idx_rsshub_delivery_inbox_discovery",
        "idx_rsshub_push_history_batch_output",
    }.issubset(indexes)
    assert sub_row == ("Existing subscription", 0, None, 0)
    assert history_row == ("Existing history", None, None, "standard", 0, None)
    assert "output_manifest" in batch_columns
    await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_metadata_contains_delivery_query_indexes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(RSSHubBaseModel.metadata.create_all)
        indexes = {
            str(row[0])
            for row in (
                await conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            ).fetchall()
        }

    assert {
        "idx_rsshub_bundle_due",
        "uq_rsshub_delivery_batch_pending_owner",
        "idx_rsshub_delivery_batch_owner_status",
        "idx_rsshub_delivery_inbox_unclaimed",
        "idx_rsshub_delivery_inbox_discovery",
        "idx_rsshub_push_history_batch_output",
    }.issubset(indexes)
    await engine.dispose()


@pytest.mark.asyncio
async def test_database_init_rolls_back_and_remains_retryable_on_migration_failure(
    monkeypatch,
    tmp_path,
) -> None:
    class MigrationFailure(RuntimeError):
        pass

    db_path = tmp_path / "migration-failure.db"
    setup_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with setup_engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE migration_probe (value VARCHAR NOT NULL)"
        )
    await setup_engine.dispose()

    async def fail_migration(conn):
        await conn.exec_driver_sql(
            "INSERT INTO migration_probe (value) VALUES ('must-roll-back')"
        )
        raise MigrationFailure("original migration failure")

    monkeypatch.setattr(database_module, "run_migrations", fail_migration)
    database = DatabaseManager()

    with pytest.raises(MigrationFailure, match="original migration failure"):
        await database.init(str(db_path))

    assert database.is_initialized is False
    inspect_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with inspect_engine.connect() as conn:
        probe_count = int(
            (
                await conn.exec_driver_sql("SELECT COUNT(*) FROM migration_probe")
            ).scalar_one()
        )
    assert probe_count == 0
    await inspect_engine.dispose()


@pytest.mark.asyncio
async def test_database_startup_is_idempotent_after_v3(tmp_path) -> None:
    db_path = tmp_path / "repeat-startup.db"
    first = DatabaseManager()
    await first.init(str(db_path))
    await first.close()

    second = DatabaseManager()
    await second.init(str(db_path))
    async with second.engine.connect() as conn:
        migration_versions = [
            str(row[0])
            for row in (
                await conn.exec_driver_sql(
                    "SELECT version FROM rsshub_migration_record ORDER BY version"
                )
            ).fetchall()
        ]
        new_table_counts = {
            str(row[0]): int(row[1])
            for row in (
                await conn.exec_driver_sql(
                    "SELECT name, COUNT(*) FROM sqlite_master "
                    "WHERE type='table' AND name IN "
                    "('rsshub_bundle', 'rsshub_bundle_feed', "
                    "'rsshub_delivery_batch', 'rsshub_delivery_inbox') "
                    "GROUP BY name"
                )
            ).fetchall()
        }

    assert migration_versions == ["1", "2", "3", "4"]
    assert new_table_counts == {
        "rsshub_bundle": 1,
        "rsshub_bundle_feed": 1,
        "rsshub_delivery_batch": 1,
        "rsshub_delivery_inbox": 1,
    }
    await second.close()


@pytest.mark.asyncio
async def test_v3_ddl_rolls_back_when_migration_fails_midway() -> None:
    class MigrationFailure(RuntimeError):
        pass

    class FailingConnection:
        def __init__(self, connection) -> None:
            self._connection = connection

        async def exec_driver_sql(self, statement, parameters=None):
            normalized = " ".join(str(statement).split())
            if "ADD COLUMN batch_id" in normalized:
                raise MigrationFailure("injected V3 failure")
            if parameters is None:
                return await self._connection.exec_driver_sql(statement)
            return await self._connection.exec_driver_sql(statement, parameters)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        assert await MigrationRunner().run_to(conn, 2) == [1, 2]

    async def failing_upgrade(conn) -> None:
        await migration_v3.upgrade(FailingConnection(conn))

    runner = MigrationRunner()
    runner._scripts = [
        MigrationScript(
            version=3,
            name="V3_injected_failure",
            module_name="tests.V3_injected_failure",
            upgrade=failing_upgrade,
        )
    ]
    with pytest.raises(MigrationFailure, match="injected V3 failure"):
        async with engine.begin() as conn:
            await runner.run_all(conn)

    async with engine.connect() as conn:
        new_tables = {
            str(row[0])
            for row in (
                await conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                    "('rsshub_bundle', 'rsshub_bundle_feed', "
                    "'rsshub_delivery_batch', 'rsshub_delivery_inbox')"
                )
            ).fetchall()
        }
        sub_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_sub)")
            ).fetchall()
        }
        history_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_push_history)")
            ).fetchall()
        }
        migration_versions = [
            str(row[0])
            for row in (
                await conn.exec_driver_sql(
                    "SELECT version FROM rsshub_migration_record ORDER BY version"
                )
            ).fetchall()
        ]

    assert new_tables == set()
    assert "send_card" not in sub_columns
    assert "batch_id" not in history_columns
    assert migration_versions == ["1", "2"]
    await engine.dispose()
