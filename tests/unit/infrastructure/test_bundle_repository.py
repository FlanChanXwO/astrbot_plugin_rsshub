from __future__ import annotations

from datetime import datetime, timezone

import pytest
from astrbot_plugin_rsshub.src.domain.entities.bundle import Bundle
from astrbot_plugin_rsshub.src.domain.entities.delivery import (
    DeliveryInboxItemDraft,
    DeliveryOwner,
)
from astrbot_plugin_rsshub.src.domain.repositories.delivery_repository import (
    DeliveryDeletionBlockedError,
    DeliverySourceMismatchError,
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
from astrbot_plugin_rsshub.src.infrastructure.persistence.models import (
    BundleFeedORM,
    DeliveryInboxItemORM,
    FeedORM,
    UserORM,
)
from sqlmodel import select


async def _create_database(tmp_path) -> DatabaseManager:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bundle-repository.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add_all(
            [
                FeedORM(id=1, link="https://example.com/one", title="One"),
                FeedORM(id=2, link="https://example.com/two", title="Two"),
                FeedORM(id=3, link="https://example.com/three", title="Three"),
            ]
        )
        await session.commit()
    return database


@pytest.mark.asyncio
async def test_bundle_repository_crud_and_atomic_member_reordering(tmp_path) -> None:
    database = await _create_database(tmp_path)
    repository = BundleRepositoryImpl(
        database,
        delivery_repository=DeliveryRepositoryImpl(database),
    )
    bundle = await repository.save(
        Bundle(
            user_id="user-1",
            name="Daily",
            target_sessions=["test:Group:1"],
            interval=30,
        )
    )

    assert bundle.id is not None
    assert (await repository.get_by_id(bundle.id)).name == "Daily"
    await repository.replace_members(bundle.id, [1, 2])
    added = await repository.add_member(bundle.id, 3, position=1)
    assert added.position == 1
    assert [member.feed_id for member in await repository.list_members(bundle.id)] == [
        1,
        3,
        2,
    ]

    await repository.move_member(added.id, 0)
    assert [member.feed_id for member in await repository.list_members(bundle.id)] == [
        3,
        1,
        2,
    ]
    await repository.replace_members(bundle.id, [2, 1])
    assert [member.feed_id for member in await repository.list_members(bundle.id)] == [
        2,
        1,
    ]
    await database.close()


@pytest.mark.asyncio
async def test_bundle_discovery_commits_inbox_and_private_watermark_together(
    tmp_path,
) -> None:
    database = await _create_database(tmp_path)
    repository = BundleRepositoryImpl(
        database,
        delivery_repository=DeliveryRepositoryImpl(database),
    )
    bundle = await repository.save(
        Bundle(
            user_id="user-1",
            name="Daily",
            target_sessions=["test:Group:1"],
            interval=30,
        )
    )
    members = await repository.replace_members(bundle.id, [1])
    member = members[0]
    delivery = DeliveryRepositoryImpl(database)
    owner = DeliveryOwner(owner_type="bundle", owner_id=bundle.id)
    checked_at = datetime(2026, 8, 24, tzinfo=timezone.utc)

    stored = await delivery.store_bundle_discovery(
        owner=owner,
        bundle_feed_id=member.id,
        member_position=member.position,
        items=[
            DeliveryInboxItemDraft(
                feed_id=1,
                bundle_feed_id=member.id,
                member_position=member.position,
                item_key="sid:item-1",
                hash_group=["sid:item-1"],
                discovery_key="bundle-discovery-1",
                entry_payload={"title": "first"},
            )
        ],
        entry_hashes=[["sid:item-1"]],
        etag="etag-1",
        last_modified=checked_at,
        status="updated",
        checked_at=checked_at,
    )

    assert stored.inserted_count == 1
    async with database.get_session() as session:
        persisted_member = await session.get(BundleFeedORM, member.id)
        inbox = await session.get(DeliveryInboxItemORM, 1)
    assert persisted_member.entry_hashes == [["sid:item-1"]]
    assert persisted_member.etag == "etag-1"
    assert persisted_member.last_check_status == "updated"
    assert persisted_member.last_checked_at.replace(tzinfo=timezone.utc) == checked_at
    assert inbox is not None

    duplicate = await delivery.store_bundle_discovery(
        owner=owner,
        bundle_feed_id=member.id,
        member_position=member.position,
        items=[
            DeliveryInboxItemDraft(
                feed_id=1,
                bundle_feed_id=member.id,
                member_position=member.position,
                item_key="sid:item-1",
                hash_group=["sid:item-1"],
                discovery_key="bundle-discovery-2",
                entry_payload={"title": "same item"},
            )
        ],
        entry_hashes=[["sid:item-1"], ["sid:item-2"]],
        etag="etag-2",
        last_modified=checked_at,
        status="no_new_entries",
        checked_at=checked_at,
    )
    assert duplicate.inserted_count == 0
    assert duplicate.duplicate_count == 1

    with pytest.raises(DeliverySourceMismatchError):
        await delivery.store_bundle_discovery(
            owner=owner,
            bundle_feed_id=member.id,
            member_position=member.position,
            items=[
                DeliveryInboxItemDraft(
                    feed_id=2,
                    bundle_feed_id=member.id,
                    member_position=member.position,
                    item_key="sid:wrong-feed",
                    hash_group=["sid:wrong-feed"],
                    discovery_key="invalid-discovery",
                )
            ],
            entry_hashes=[["sid:wrong-feed"]],
            etag="should-not-commit",
            last_modified=checked_at,
            status="updated",
            checked_at=checked_at,
        )

    async with database.get_session() as session:
        persisted_member = await session.get(BundleFeedORM, member.id)
    assert persisted_member.etag == "etag-2"

    async def fail_after_insert(*_args) -> None:
        raise RuntimeError("injected bundle discovery failure")

    delivery._after_bundle_discovery = fail_after_insert
    with pytest.raises(RuntimeError, match="injected"):
        await delivery.store_bundle_discovery(
            owner=owner,
            bundle_feed_id=member.id,
            member_position=member.position,
            items=[
                DeliveryInboxItemDraft(
                    feed_id=1,
                    bundle_feed_id=member.id,
                    member_position=member.position,
                    item_key="sid:atomic-failure",
                    hash_group=["sid:atomic-failure"],
                    discovery_key="atomic-failure",
                )
            ],
            entry_hashes=[["sid:atomic-failure"]],
            etag="must-rollback",
            last_modified=checked_at,
            status="updated",
            checked_at=checked_at,
        )

    async with database.get_session() as session:
        persisted_member = await session.get(BundleFeedORM, member.id)
        result = await session.execute(
            select(DeliveryInboxItemORM).where(
                DeliveryInboxItemORM.item_key == "sid:atomic-failure"
            )
        )
    assert persisted_member.etag == "etag-2"
    assert result.scalar_one_or_none() is None
    await database.close()


@pytest.mark.asyncio
async def test_replacing_member_with_unresolved_inbox_is_atomic(tmp_path) -> None:
    database = await _create_database(tmp_path)
    delivery = DeliveryRepositoryImpl(database)
    repository = BundleRepositoryImpl(database, delivery_repository=delivery)
    bundle = await repository.save(
        Bundle(
            user_id="user-1",
            name="Protected",
            target_sessions=["test:Group:1"],
            interval=30,
        )
    )
    members = await repository.replace_members(bundle.id, [1, 2, 3])
    await delivery.store_inbox_items(
        DeliveryOwner(owner_type="bundle", owner_id=bundle.id),
        [
            DeliveryInboxItemDraft(
                feed_id=3,
                bundle_feed_id=members[2].id,
                member_position=members[2].position,
                item_key="sid:pending",
                hash_group=["sid:pending"],
                discovery_key="protected-discovery",
            )
        ],
    )

    with pytest.raises(DeliveryDeletionBlockedError):
        await repository.replace_members(bundle.id, [1, 2])

    assert [member.feed_id for member in await repository.list_members(bundle.id)] == [
        1,
        2,
        3,
    ]
    await database.close()


@pytest.mark.asyncio
async def test_enabled_bundle_requires_two_members(tmp_path) -> None:
    database = await _create_database(tmp_path)
    delivery = DeliveryRepositoryImpl(database)
    repository = BundleRepositoryImpl(database, delivery_repository=delivery)
    bundle = await repository.save(
        Bundle(
            user_id="user-1",
            name="Minimum",
            target_sessions=["test:Group:1"],
            interval=30,
        )
    )
    await repository.replace_members(bundle.id, [1, 2])
    bundle.state = 1
    await repository.save(bundle)

    with pytest.raises(ValueError, match="至少需要两个"):
        await repository.replace_members(bundle.id, [1])

    bundle.state = 0
    await repository.save(bundle)
    await repository.replace_members(bundle.id, [1])
    bundle.state = 1
    with pytest.raises(ValueError, match="至少需要两个"):
        await repository.save(bundle)

    assert [member.feed_id for member in await repository.list_members(bundle.id)] == [
        1
    ]
    await database.close()
