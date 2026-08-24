from __future__ import annotations

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_rsshub.src.domain.entities.delivery import (
    DeliveryBatchDraft,
    DeliveryInboxItemDraft,
    DeliveryOwner,
)
from astrbot_plugin_rsshub.src.domain.entities.push_history import PushHistory
from astrbot_plugin_rsshub.src.domain.repositories.delivery_repository import (
    DeliveryConsistencyError,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.bundle_repository_impl import (
    get_bundle_mutation_lock,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import (
    DatabaseManager,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.delivery_repository_impl import (
    DeliveryRepositoryImpl,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.migrations import (
    MigrationRunner,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.models import (
    FeedORM,
    SubORM,
    UserORM,
)
from astrbot_plugin_rsshub.src.interfaces.web_api import WebApiHandler
from quart import Quart
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _handler(**overrides):
    dependencies = {
        "subscribe_cmd": MagicMock(),
        "unsubscribe_cmd": MagicMock(),
        "update_sub_cmd": MagicMock(),
        "batch_activate_cmd": MagicMock(),
        "batch_deactivate_cmd": MagicMock(),
        "batch_unsub_cmd": MagicMock(),
        "export_cmd": MagicMock(),
        "import_cmd": MagicMock(),
        "get_user_settings_cmd": MagicMock(),
        "set_user_settings_cmd": MagicMock(),
        "test_sub_cmd": MagicMock(),
        "get_items_query": MagicMock(),
        "polling_service": MagicMock(),
        "feed_repo": MagicMock(),
        "sub_repo": MagicMock(),
        "user_repo": MagicMock(),
        "push_history_repo": MagicMock(),
        "config": MagicMock(),
    }
    dependencies.update(overrides)
    return WebApiHandler(**dependencies)


@pytest.mark.asyncio
async def test_delete_user_blocks_existing_bundle_owner_before_mutation():
    bundle_repository = MagicMock()
    bundle_repository.get_by_user = AsyncMock(
        return_value=[MagicMock(id=7, user_id="alice")]
    )
    sub_repository = MagicMock()
    sub_repository.get_by_user = AsyncMock(return_value=[])
    delivery_repository = MagicMock()
    delivery_repository.delete_subscription_owners = AsyncMock(return_value=0)
    user_repository = MagicMock()
    user_repository.delete = AsyncMock(return_value=True)
    handler = _handler(
        bundle_repository=bundle_repository,
        sub_repo=sub_repository,
        delivery_repository=delivery_repository,
        user_repo=user_repository,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/users/delete",
        method="POST",
        json={"user_id": "alice"},
    ):
        response = await handler.handle_delete_user()

    payload = await response.get_json()
    assert payload["ok"] is False
    assert payload["blocked_users"] == [
        {"user_id": "alice", "blockers": {"bundles": 1}}
    ]
    delivery_repository.delete_subscription_owners.assert_not_awaited()
    user_repository.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_feed_blocks_bundle_member_reference_before_mutation():
    bundle_repository = MagicMock()
    bundle_repository.count_members_by_feed_ids = AsyncMock(return_value={9: 1})
    sub_repository = MagicMock()
    sub_repository.list_for_dashboard = AsyncMock(return_value=[])
    delivery_repository = MagicMock()
    delivery_repository.delete_subscription_owners = AsyncMock(return_value=0)
    feed_repository = MagicMock()
    feed_repository.delete_many = AsyncMock(return_value=1)
    handler = _handler(
        bundle_repository=bundle_repository,
        sub_repo=sub_repository,
        delivery_repository=delivery_repository,
        feed_repo=feed_repository,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/delete",
        method="POST",
        json={"feed_id": 9},
    ):
        response = await handler.handle_delete_feeds()

    payload = await response.get_json()
    assert payload["ok"] is False
    assert payload["blocked_feeds"] == [
        {"feed_id": 9, "blockers": {"bundle_members": 1}}
    ]
    delivery_repository.delete_subscription_owners.assert_not_awaited()
    feed_repository.delete_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_feed_serializes_bundle_mutation_while_deleting():
    mutation_lock = get_bundle_mutation_lock()
    mutation_entered = asyncio.Event()
    bundle_repository = MagicMock()
    bundle_repository.count_members_by_feed_ids = AsyncMock(return_value={})
    feed_repository = MagicMock()

    async def delete_many(_feed_ids):
        async def competing_bundle_write():
            async with mutation_lock:
                mutation_entered.set()

        competing_task = asyncio.create_task(competing_bundle_write())
        await asyncio.sleep(0)
        assert not mutation_entered.is_set()
        competing_task.cancel()
        with suppress(asyncio.CancelledError):
            await competing_task
        return 1

    feed_repository.delete_many = delete_many
    delivery_repository = MagicMock()
    delivery_repository.delete_subscription_owners = AsyncMock(return_value=0)
    sub_repository = MagicMock()
    sub_repository.list_for_dashboard = AsyncMock(return_value=[])
    handler = _handler(
        bundle_repository=bundle_repository,
        feed_repo=feed_repository,
        sub_repo=sub_repository,
        delivery_repository=delivery_repository,
        mutation_lock=mutation_lock,
    )

    app = Quart(__name__)
    async with app.test_request_context(
        "/astrbot_plugin_rsshub/feeds/delete",
        method="POST",
        json={"feed_id": 9},
    ):
        response = await handler.handle_delete_feeds()

    payload = await response.get_json()
    assert payload["ok"] is True
    assert not mutation_entered.is_set()


@pytest.mark.asyncio
async def test_legacy_v2_file_upgrades_and_repeated_startup_preserves_rows(tmp_path):
    db_path = tmp_path / "legacy-v2.db"
    legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with legacy_engine.begin() as connection:
        assert await MigrationRunner().run_to(connection, 2) == [1, 2]
        await connection.exec_driver_sql(
            "INSERT INTO rsshub_user (id) VALUES ('legacy-user')"
        )
        await connection.exec_driver_sql(
            "INSERT INTO rsshub_feed (id, link, title) "
            "VALUES (1, 'https://example.com/legacy', 'Legacy')"
        )
        await connection.exec_driver_sql(
            "INSERT INTO rsshub_sub (id, user_id, feed_id, title) "
            "VALUES (1, 'legacy-user', 1, 'Legacy subscription')"
        )
    await legacy_engine.dispose()

    database = DatabaseManager()
    await database.init(str(db_path))
    await database.init(str(db_path))
    async with database.engine.connect() as connection:
        versions = [
            str(row[0])
            for row in (
                await connection.exec_driver_sql(
                    "SELECT version FROM rsshub_migration_record ORDER BY version"
                )
            ).fetchall()
        ]
        subscription = (
            await connection.exec_driver_sql(
                "SELECT title, send_card, template_id FROM rsshub_sub WHERE id=1"
            )
        ).one()
        batch_columns = {
            str(row[1])
            for row in (
                await connection.exec_driver_sql(
                    "PRAGMA table_info(rsshub_delivery_batch)"
                )
            ).fetchall()
        }

    assert versions == ["1", "2", "3", "4"]
    assert subscription == ("Legacy subscription", 0, None)
    assert "output_manifest" in batch_columns
    await database.close()


async def _create_audit_batch(tmp_path):
    database = DatabaseManager()
    await database.init(str(tmp_path / "abnormal-batch.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="audit-user"))
        session.add(FeedORM(id=1, link="https://example.com/audit", title="Audit"))
        await session.flush()
        subscription = SubORM(
            id=1,
            user_id="audit-user",
            feed_id=1,
            send_card=False,
        )
        session.add(subscription)
        await session.commit()

    repository = DeliveryRepositoryImpl(database)
    owner = DeliveryOwner(owner_type="subscription", owner_id=1)
    await repository.store_inbox_items(
        owner,
        [
            DeliveryInboxItemDraft(
                feed_id=1,
                item_key="audit-entry",
                discovery_key="audit-discovery",
            )
        ],
    )
    batch = await repository.claim_batch(
        owner,
        DeliveryBatchDraft(
            target_sessions=["test:Group:1"],
            config_snapshot={"send_card": False},
        ),
        [
            PushHistory(
                user_id="audit-user",
                sub_id=1,
                target_session="test:Group:1",
                output_kind="standard",
                output_order=0,
                status="pending",
            )
        ],
    )
    return database, repository, batch


@pytest.mark.asyncio
async def test_abnormal_persisted_batch_status_fails_closed(tmp_path):
    database, repository, batch = await _create_audit_batch(tmp_path)
    async with database.get_session() as session:
        await session.execute(text("PRAGMA ignore_check_constraints = ON"))
        await session.execute(
            text("UPDATE rsshub_delivery_batch SET status='corrupted' WHERE id=:id"),
            {"id": batch.id},
        )
        await session.commit()

    with pytest.raises(DeliveryConsistencyError, match="状态"):
        await repository.reconcile_batch(batch.id)

    await database.close()
