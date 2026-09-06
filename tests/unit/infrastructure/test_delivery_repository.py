from __future__ import annotations

import asyncio

import pytest
from astrbot_plugin_rsshub.src.application.services.output_orchestrator import (
    OutputOrchestrator,
)
from astrbot_plugin_rsshub.src.domain.entities.delivery import (
    DeliveryBatchDraft,
    DeliveryInboxItemDraft,
    DeliveryOwner,
    SubscriptionInboxDiscovery,
)
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.domain.entities.push_history import PushHistory
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import (
    DatabaseManager,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.delivery_repository_impl import (
    DeliveryBatchConflictError,
    DeliveryBatchNotReadyError,
    DeliveryConsistencyError,
    DeliveryDeletionBlockedError,
    DeliveryOutputMismatchError,
    DeliveryOwnerNotFoundError,
    DeliveryRepositoryImpl,
    DeliverySourceMismatchError,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.models import (
    BundleFeedORM,
    BundleORM,
    DeliveryBatchORM,
    FeedORM,
    PushHistoryORM,
    SubORM,
    UserORM,
)
from sqlalchemy import func
from sqlmodel import select


async def _create_subscription_owner(database: DatabaseManager) -> DeliveryOwner:
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(FeedORM(id=1, link="https://example.com/feed", title="Feed"))
        await session.flush()
        subscription = SubORM(user_id="user-1", feed_id=1, send_card=True)
        session.add(subscription)
        await session.commit()
        await session.refresh(subscription)
    return DeliveryOwner(owner_type="subscription", owner_id=subscription.id)


@pytest.mark.asyncio
async def test_store_inbox_items_is_idempotent_and_keeps_first_snapshot(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "delivery-inbox.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)

    first = DeliveryInboxItemDraft(
        feed_id=1,
        item_key="entry-1",
        hash_group=["guid:entry-1"],
        discovery_key="discovery-1",
        entry_payload={"title": "first"},
    )
    duplicate = first.model_copy(update={"entry_payload": {"title": "changed"}})

    first_result = await repository.store_inbox_items(owner, [first])
    duplicate_result = await repository.store_inbox_items(owner, [duplicate])
    inbox = await repository.list_inbox_items(owner)

    assert first_result.inserted_count == 1
    assert first_result.duplicate_count == 0
    assert duplicate_result.inserted_count == 0
    assert duplicate_result.duplicate_count == 1
    assert len(inbox) == 1
    assert inbox[0].entry_payload == {"title": "first"}
    await database.close()


@pytest.mark.asyncio
async def test_subscription_discovery_rolls_back_every_owner_and_feed_watermark(
    monkeypatch,
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "subscription-fanout-rollback.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(FeedORM(id=1, link="https://example.com/feed", title="Feed"))
        await session.flush()
        subscriptions = [
            SubORM(user_id="user-1", feed_id=1, send_card=True) for _index in range(2)
        ]
        session.add_all(subscriptions)
        await session.commit()
        for subscription in subscriptions:
            await session.refresh(subscription)
    repository = DeliveryRepositoryImpl(database)
    updated_feed = Feed(
        id=1,
        link="https://example.com/feed",
        title="Updated Feed",
        entry_hashes=[["sid:new-entry"]],
        etag="new-etag",
    )
    discoveries = [
        SubscriptionInboxDiscovery(
            owner=DeliveryOwner(
                owner_type="subscription",
                owner_id=subscription.id,
            ),
            items=[
                DeliveryInboxItemDraft(
                    feed_id=1,
                    item_key="sid:new-entry",
                    hash_group=["sid:new-entry"],
                    discovery_key=f"subscription:{subscription.id}:discovery:test",
                    entry_payload={"guid": "new-entry"},
                )
            ],
        )
        for subscription in subscriptions
    ]

    async def fail_after_second_owner(_session, owner_index: int) -> None:
        if owner_index == 1:
            raise RuntimeError("injected second owner failure")

    monkeypatch.setattr(
        repository,
        "_after_subscription_discovery_owner",
        fail_after_second_owner,
        raising=False,
    )
    with pytest.raises(RuntimeError, match="injected second owner failure"):
        await repository.store_subscription_discovery(updated_feed, discoveries)

    for discovery in discoveries:
        assert await repository.list_inbox_items(discovery.owner) == []
    async with database.get_session() as session:
        persisted_feed = await session.get(FeedORM, 1)
        assert persisted_feed.title == "Feed"
        assert persisted_feed.entry_hashes is None
        assert persisted_feed.etag is None
    await database.close()


@pytest.mark.asyncio
async def test_subscription_discovery_retry_is_idempotent_for_every_owner(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "subscription-fanout-idempotent.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(FeedORM(id=1, link="https://example.com/feed", title="Feed"))
        await session.flush()
        subscriptions = [
            SubORM(user_id="user-1", feed_id=1, send_card=True) for _index in range(2)
        ]
        session.add_all(subscriptions)
        await session.commit()
        for subscription in subscriptions:
            await session.refresh(subscription)
    repository = DeliveryRepositoryImpl(database)
    updated_feed = Feed(
        id=1,
        link="https://example.com/feed",
        title="Updated Feed",
        entry_hashes=[["sid:new-entry"]],
        etag="new-etag",
    )
    discoveries = [
        SubscriptionInboxDiscovery(
            owner=DeliveryOwner(
                owner_type="subscription",
                owner_id=subscription.id,
            ),
            items=[
                DeliveryInboxItemDraft(
                    feed_id=1,
                    item_key="sid:new-entry",
                    hash_group=["sid:new-entry"],
                    discovery_key=f"subscription:{subscription.id}:discovery:test",
                    entry_payload={"title": "first snapshot"},
                )
            ],
        )
        for subscription in subscriptions
    ]

    first = await repository.store_subscription_discovery(updated_feed, discoveries)
    changed_discoveries = [
        discovery.model_copy(
            update={
                "items": [
                    discovery.items[0].model_copy(
                        update={"entry_payload": {"title": "changed snapshot"}}
                    )
                ]
            }
        )
        for discovery in discoveries
    ]
    repeated = await repository.store_subscription_discovery(
        updated_feed,
        changed_discoveries,
    )

    assert first.entry_hashes == [["sid:new-entry"]]
    assert repeated.etag == "new-etag"
    for discovery in discoveries:
        inbox = await repository.list_inbox_items(discovery.owner)
        assert len(inbox) == 1
        assert inbox[0].entry_payload == {"title": "first snapshot"}
    await database.close()


@pytest.mark.asyncio
async def test_subscription_discovery_rejects_empty_fanout_without_updating_feed(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "subscription-empty-fanout.db"))
    async with database.get_session() as session:
        session.add(FeedORM(id=1, link="https://example.com/feed", title="Feed"))
        await session.commit()
    repository = DeliveryRepositoryImpl(database)
    updated_feed = Feed(
        id=1,
        link="https://example.com/feed",
        title="Updated Feed",
        entry_hashes=[["sid:new-entry"]],
        etag="new-etag",
    )

    with pytest.raises(DeliverySourceMismatchError, match="至少一个"):
        await repository.store_subscription_discovery(updated_feed, [])

    async with database.get_session() as session:
        persisted_feed = await session.get(FeedORM, 1)
        assert persisted_feed.title == "Feed"
        assert persisted_feed.entry_hashes is None
        assert persisted_feed.etag is None
    await database.close()


async def _create_bundle_owner(database: DatabaseManager):
    async with database.get_session() as session:
        session.add(UserORM(id="bundle-user"))
        session.add_all(
            [
                FeedORM(id=10, link="https://example.com/one", title="One"),
                FeedORM(id=11, link="https://example.com/two", title="Two"),
            ]
        )
        await session.flush()
        bundle = BundleORM(
            user_id="bundle-user",
            name="Bundle",
            target_sessions=["test:Group:1"],
            interval=30,
        )
        session.add(bundle)
        await session.flush()
        member = BundleFeedORM(bundle_id=bundle.id, feed_id=10, position=0)
        session.add(member)
        await session.commit()
        await session.refresh(bundle)
        await session.refresh(member)
    return DeliveryOwner(owner_type="bundle", owner_id=bundle.id), member


async def _claim_two_output_batch(
    database: DatabaseManager,
    repository: DeliveryRepositoryImpl,
    owner: DeliveryOwner,
):
    await repository.store_inbox_items(
        owner,
        [
            DeliveryInboxItemDraft(
                feed_id=1,
                item_key="entry-1",
                discovery_key="discovery-1",
            )
        ],
    )
    return await repository.claim_batch(
        owner,
        DeliveryBatchDraft(target_sessions=["test:Group:1"]),
        [
            PushHistory(
                user_id="user-1",
                sub_id=owner.owner_id,
                target_session="test:Group:1",
                output_kind="card",
                output_order=0,
                status="pending",
            ),
            PushHistory(
                user_id="user-1",
                sub_id=owner.owner_id,
                target_session="test:Group:1",
                output_kind="standard",
                output_order=1,
                status="waiting",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_claim_rejects_multiple_cards_for_the_same_target(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "duplicate-target-cards.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )

    with pytest.raises(DeliveryOutputMismatchError, match="card"):
        await repository.claim_batch(
            owner,
            DeliveryBatchDraft(
                target_sessions=["test:Group:1"],
                config_snapshot={"send_card": True},
            ),
            [
                PushHistory(
                    user_id="user-1",
                    sub_id=owner.owner_id,
                    target_session="test:Group:1",
                    output_kind="card",
                    output_order=0,
                    status="pending",
                ),
                PushHistory(
                    user_id="user-1",
                    sub_id=owner.owner_id,
                    target_session="test:Group:1",
                    output_kind="card",
                    output_order=1,
                    status="waiting",
                ),
            ],
        )

    assert await repository.get_pending_batch(owner) is None
    assert len(await repository.list_inbox_items(owner, claimed=False)) == 1
    await database.close()


@pytest.mark.asyncio
async def test_claim_rejects_card_that_is_not_first_for_its_target(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "late-target-card.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )

    with pytest.raises(DeliveryOutputMismatchError, match="order=0"):
        await repository.claim_batch(
            owner,
            DeliveryBatchDraft(
                target_sessions=["test:Group:1"],
                config_snapshot={"send_card": True},
            ),
            [
                PushHistory(
                    user_id="user-1",
                    sub_id=owner.owner_id,
                    target_session="test:Group:1",
                    output_kind="standard",
                    output_order=0,
                    status="waiting",
                ),
                PushHistory(
                    user_id="user-1",
                    sub_id=owner.owner_id,
                    target_session="test:Group:1",
                    output_kind="card",
                    output_order=1,
                    status="pending",
                ),
            ],
        )

    assert await repository.get_pending_batch(owner) is None
    assert len(await repository.list_inbox_items(owner, claimed=False)) == 1
    await database.close()


@pytest.mark.asyncio
async def test_claim_requires_one_card_per_target_when_card_is_enabled(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "missing-target-card.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )

    with pytest.raises(DeliveryOutputMismatchError, match="send_card=true"):
        await repository.claim_batch(
            owner,
            DeliveryBatchDraft(
                target_sessions=["test:Group:1"],
                config_snapshot={"send_card": True},
            ),
            [
                PushHistory(
                    user_id="user-1",
                    sub_id=owner.owner_id,
                    target_session="test:Group:1",
                    output_kind="standard",
                    output_order=0,
                    status="pending",
                )
            ],
        )

    assert await repository.get_pending_batch(owner) is None
    assert len(await repository.list_inbox_items(owner, claimed=False)) == 1
    await database.close()


@pytest.mark.asyncio
async def test_claim_rejects_card_when_card_is_disabled(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "disabled-target-card.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )

    with pytest.raises(DeliveryOutputMismatchError, match="send_card=false"):
        await repository.claim_batch(
            owner,
            DeliveryBatchDraft(
                target_sessions=["test:Group:1"],
                config_snapshot={"send_card": False},
            ),
            [
                PushHistory(
                    user_id="user-1",
                    sub_id=owner.owner_id,
                    target_session="test:Group:1",
                    output_kind="card",
                    output_order=0,
                    status="pending",
                )
            ],
        )

    assert await repository.get_pending_batch(owner) is None
    assert len(await repository.list_inbox_items(owner, claimed=False)) == 1
    await database.close()


@pytest.mark.asyncio
async def test_claim_accepts_card_first_outputs_for_multiple_targets(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "multiple-target-cards.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )
    targets = ["test:Group:1", "test:Group:2"]
    outputs = [
        PushHistory(
            user_id="user-1",
            sub_id=owner.owner_id,
            target_session=target,
            output_kind=kind,
            output_order=order,
            status="pending" if kind == "card" else "waiting",
        )
        for target in targets
        for kind, order in (("card", 0), ("standard", 1))
    ]

    batch = await repository.claim_batch(
        owner,
        DeliveryBatchDraft(
            target_sessions=targets,
            config_snapshot={"send_card": True},
        ),
        outputs,
    )

    assert [
        (identity.target_session, identity.output_kind, identity.output_order)
        for identity in batch.output_manifest
    ] == [
        (target, kind, order)
        for target in targets
        for kind, order in (("card", 0), ("standard", 1))
    ]
    await database.close()


@pytest.mark.asyncio
async def test_claim_subscription_batch_is_atomic_and_keeps_discovery_boundary(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "claim-subscription.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [
            DeliveryInboxItemDraft(
                feed_id=1,
                item_key="entry-1",
                discovery_key="discovery-1",
                entry_payload={"title": "one"},
            ),
            DeliveryInboxItemDraft(
                feed_id=1,
                item_key="entry-2",
                discovery_key="discovery-1",
                entry_payload={"title": "two"},
            ),
            DeliveryInboxItemDraft(
                feed_id=1,
                item_key="entry-3",
                discovery_key="discovery-2",
                entry_payload={"title": "three"},
            ),
        ],
    )

    batch = await repository.claim_batch(
        owner,
        DeliveryBatchDraft(
            target_sessions=["test:Group:1"],
            config_snapshot={"send_card": True},
        ),
        [
            PushHistory(
                user_id="user-1",
                sub_id=owner.owner_id,
                target_session="test:Group:1",
                output_kind="card",
                output_order=0,
                status="pending",
            )
        ],
    )
    unclaimed = await repository.list_inbox_items(owner, claimed=False)

    assert batch.status == "pending"
    assert [item.item_key for item in batch.inbox_items] == ["entry-1", "entry-2"]
    assert len(batch.outputs) == 1
    assert batch.outputs[0].batch_id == batch.id
    assert [item.item_key for item in unclaimed] == ["entry-3"]
    await database.close()


@pytest.mark.asyncio
async def test_confirm_requires_every_output_and_is_idempotent(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "confirm-batch.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    batch = await _claim_two_output_batch(database, repository, owner)
    async with database.get_session() as session:
        card = await session.get(PushHistoryORM, batch.outputs[0].id)
        standard = await session.get(PushHistoryORM, batch.outputs[1].id)
        card.status = "success"
        standard.status = "failed"
        await session.commit()

    with pytest.raises(DeliveryBatchNotReadyError) as exc_info:
        await repository.confirm_batch(batch.id)
    assert exc_info.value.blocking_statuses == {"failed": 1}
    assert len(await repository.list_inbox_items(owner, claimed=True)) == 1

    async with database.get_session() as session:
        standard = await session.get(PushHistoryORM, batch.outputs[1].id)
        standard.status = "skipped"
        await session.commit()

    confirmed = await repository.confirm_batch(batch.id)
    repeated = await repository.confirm_batch(batch.id)

    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_at is not None
    assert repeated.status == "confirmed"
    assert repeated.confirmed_at == confirmed.confirmed_at
    assert await repository.list_inbox_items(owner) == []
    await database.close()


@pytest.mark.asyncio
async def test_discard_only_consumes_claimed_input_and_incomplete_outputs(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "discard-batch.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    batch = await _claim_two_output_batch(database, repository, owner)
    async with database.get_session() as session:
        card = await session.get(PushHistoryORM, batch.outputs[0].id)
        standard = await session.get(PushHistoryORM, batch.outputs[1].id)
        card.status = "success"
        standard.status = "failed"
        await session.commit()
    await repository.store_inbox_items(
        owner,
        [
            DeliveryInboxItemDraft(
                feed_id=1,
                item_key="entry-backlog",
                discovery_key="discovery-2",
            )
        ],
    )

    discarded = await repository.discard_batch(batch.id, reason="用户明确丢弃")
    repeated = await repository.discard_batch(batch.id, reason="重复请求")
    remaining = await repository.list_inbox_items(owner)

    assert discarded.status == "discarded"
    assert [output.status for output in discarded.outputs] == ["success", "discarded"]
    assert discarded.outputs[1].fail_reason == "用户明确丢弃"
    assert [output.status for output in repeated.outputs] == ["success", "discarded"]
    assert [item.item_key for item in remaining] == ["entry-backlog"]
    await database.close()


@pytest.mark.asyncio
async def test_discard_rolls_back_every_write_and_retry_is_idempotent(
    monkeypatch,
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "discard-rollback.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    batch = await _claim_two_output_batch(database, repository, owner)
    orchestrator = OutputOrchestrator(object(), object(), repository)

    async def fail_after_discard(_session, _batch) -> None:
        raise RuntimeError("injected discard transaction failure")

    monkeypatch.setattr(
        repository,
        "_after_discard",
        fail_after_discard,
        raising=False,
    )
    with pytest.raises(RuntimeError, match="injected discard transaction failure"):
        await orchestrator.discard(batch, reason="用户明确丢弃")

    rolled_back = await repository.get_batch(batch.id)
    assert rolled_back is not None
    assert rolled_back.status == "pending"
    assert [output.status for output in rolled_back.outputs] == [
        "pending",
        "waiting",
    ]
    assert len(await repository.list_inbox_items(owner, claimed=True)) == 1

    monkeypatch.undo()
    discarded = await orchestrator.discard(batch, reason="用户明确丢弃")
    repeated = await orchestrator.discard(batch, reason="重复请求")

    assert discarded.status == "discarded"
    assert [output.status for output in discarded.outputs] == [
        "discarded",
        "discarded",
    ]
    assert repeated.status == "discarded"
    assert [output.status for output in repeated.outputs] == [
        "discarded",
        "discarded",
    ]
    assert await repository.list_inbox_items(owner) == []
    await database.close()


@pytest.mark.asyncio
async def test_concurrent_claim_creates_one_pending_batch_per_owner(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "concurrent-claim.db"))
    owner = await _create_subscription_owner(database)
    first_repository = DeliveryRepositoryImpl(database)
    second_repository = DeliveryRepositoryImpl(database)
    await first_repository.store_inbox_items(
        owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )

    def output() -> PushHistory:
        return PushHistory(
            user_id="user-1",
            sub_id=owner.owner_id,
            target_session="test:Group:1",
            output_kind="card",
            status="pending",
        )

    results = await asyncio.gather(
        first_repository.claim_batch(
            owner,
            DeliveryBatchDraft(target_sessions=["test:Group:1"]),
            [output()],
        ),
        second_repository.claim_batch(
            owner,
            DeliveryBatchDraft(target_sessions=["test:Group:1"]),
            [output()],
        ),
        return_exceptions=True,
    )
    pending = await first_repository.get_pending_batch(owner)

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    errors = [result for result in results if isinstance(result, BaseException)]
    assert len(errors) == 1
    assert isinstance(errors[0], DeliveryBatchConflictError)
    assert pending is not None
    assert len(pending.inbox_items) == 1
    assert len(pending.outputs) == 1
    await database.close()


@pytest.mark.asyncio
async def test_claim_failure_rolls_back_batch_inbox_and_histories(
    monkeypatch,
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "claim-rollback.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )

    async def fail_after_claim(_session, _batch) -> None:
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(repository, "_after_claim", fail_after_claim)
    with pytest.raises(RuntimeError, match="injected transaction failure"):
        await repository.claim_batch(
            owner,
            DeliveryBatchDraft(target_sessions=["test:Group:1"]),
            [
                PushHistory(
                    user_id="user-1",
                    sub_id=owner.owner_id,
                    target_session="test:Group:1",
                    output_kind="card",
                    status="pending",
                )
            ],
        )

    assert await repository.get_pending_batch(owner) is None
    inbox = await repository.list_inbox_items(owner)
    assert len(inbox) == 1
    assert inbox[0].batch_id is None
    async with database.get_session() as session:
        history_count = (
            await session.execute(select(func.count()).select_from(PushHistoryORM))
        ).scalar_one()
    assert history_count == 0
    await database.close()


@pytest.mark.asyncio
async def test_owner_and_bundle_member_deletion_report_unconsumed_inbox(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "delivery-protection.db"))
    owner, member = await _create_bundle_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [
            DeliveryInboxItemDraft(
                feed_id=member.feed_id,
                bundle_feed_id=member.id,
                member_position=member.position,
                item_key="entry-1",
                discovery_key="d1",
            )
        ],
    )

    with pytest.raises(DeliveryDeletionBlockedError) as owner_error:
        await repository.ensure_owner_deletable(owner)
    with pytest.raises(DeliveryDeletionBlockedError) as member_error:
        await repository.ensure_bundle_member_removable(member.id)

    assert owner_error.value.blocker_counts == {"unclaimed_inbox": 1}
    assert member_error.value.blocker_counts == {"unclaimed_inbox": 1}
    await database.close()


@pytest.mark.asyncio
async def test_bulk_subscription_deletion_checks_all_owners_before_mutation(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bulk-subscription-delete-protection.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(FeedORM(id=1, link="https://example.com/feed", title="Feed"))
        await session.flush()
        subscriptions = [
            SubORM(user_id="user-1", feed_id=1, send_card=True),
            SubORM(user_id="user-1", feed_id=1, send_card=False),
        ]
        session.add_all(subscriptions)
        await session.commit()
        for subscription in subscriptions:
            await session.refresh(subscription)

    repository = DeliveryRepositoryImpl(database)
    blocked_owner = DeliveryOwner(
        owner_type="subscription",
        owner_id=subscriptions[0].id,
    )
    await repository.store_inbox_items(
        blocked_owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )

    with pytest.raises(DeliveryDeletionBlockedError) as exc_info:
        await repository.delete_subscription_owners(
            [subscription.id for subscription in subscriptions]
        )

    assert exc_info.value.owner_blockers == {
        str(subscriptions[0].id): {"unclaimed_inbox": 1}
    }
    async with database.get_session() as session:
        remaining = (
            (await session.execute(select(SubORM).order_by(SubORM.id))).scalars().all()
        )
    assert [subscription.id for subscription in remaining] == [
        subscription.id for subscription in subscriptions
    ]
    await database.close()


@pytest.mark.asyncio
async def test_bulk_subscription_deletion_reports_pending_batch_and_claimed_inbox(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bulk-subscription-delete-claimed.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(FeedORM(id=1, link="https://example.com/feed", title="Feed"))
        await session.flush()
        subscription = SubORM(user_id="user-1", feed_id=1, send_card=True)
        session.add(subscription)
        await session.commit()
        await session.refresh(subscription)

    repository = DeliveryRepositoryImpl(database)
    owner = DeliveryOwner(owner_type="subscription", owner_id=subscription.id)
    await repository.store_inbox_items(
        owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )
    await repository.claim_batch(
        owner,
        DeliveryBatchDraft(target_sessions=["test:Group:1"]),
        [
            PushHistory(
                user_id="user-1",
                sub_id=subscription.id,
                target_session="test:Group:1",
                output_kind="card",
                output_order=0,
                status="pending",
            )
        ],
    )

    with pytest.raises(DeliveryDeletionBlockedError) as exc_info:
        await repository.delete_subscription_owners([subscription.id])

    assert exc_info.value.owner_blockers == {
        str(subscription.id): {"claimed_inbox": 1, "pending_batch": 1}
    }
    async with database.get_session() as session:
        assert await session.get(SubORM, subscription.id) is not None
    await database.close()


@pytest.mark.asyncio
async def test_bulk_subscription_deletion_releases_resolved_history_links(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bulk-subscription-delete-history.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(FeedORM(id=1, link="https://example.com/feed", title="Feed"))
        await session.flush()
        subscriptions = [
            SubORM(user_id="user-1", feed_id=1, send_card=True),
            SubORM(user_id="user-1", feed_id=1, send_card=False),
        ]
        session.add_all(subscriptions)
        await session.flush()
        history = PushHistoryORM(
            user_id="user-1",
            sub_id=subscriptions[0].id,
            feed_id=1,
            status="success",
            content="resolved history",
        )
        session.add(history)
        await session.commit()
        await session.refresh(history)

    repository = DeliveryRepositoryImpl(database)
    deleted = await repository.delete_subscription_owners(
        [subscription.id for subscription in subscriptions]
    )

    assert deleted == 2
    async with database.get_session() as session:
        assert (await session.execute(select(SubORM))).scalars().all() == []
        retained = await session.get(PushHistoryORM, history.id)
        assert retained is not None
        assert retained.sub_id is None
    await database.close()


@pytest.mark.asyncio
async def test_bulk_subscription_deletion_rolls_back_before_commit(
    monkeypatch,
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bulk-subscription-delete-rollback.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(FeedORM(id=1, link="https://example.com/feed", title="Feed"))
        await session.flush()
        subscription = SubORM(user_id="user-1", feed_id=1, send_card=True)
        session.add(subscription)
        await session.flush()
        history = PushHistoryORM(
            user_id="user-1",
            sub_id=subscription.id,
            feed_id=1,
            status="success",
            content="resolved history",
        )
        session.add(history)
        await session.commit()
        await session.refresh(history)

    repository = DeliveryRepositoryImpl(database)

    async def fail_before_commit(_session, _subscription_ids):
        raise RuntimeError("injected bulk deletion failure")

    monkeypatch.setattr(
        repository,
        "_after_subscription_owners_deleted",
        fail_before_commit,
        raising=False,
    )
    with pytest.raises(RuntimeError, match="injected bulk deletion failure"):
        await repository.delete_subscription_owners([subscription.id])

    async with database.get_session() as session:
        assert await session.get(SubORM, subscription.id) is not None
        retained = await session.get(PushHistoryORM, history.id)
        assert retained is not None
        assert retained.sub_id == subscription.id
    await database.close()


@pytest.mark.asyncio
async def test_reconciliation_exposes_partial_output_history(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "reconcile-partial-history.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [DeliveryInboxItemDraft(feed_id=1, item_key="entry-1", discovery_key="d1")],
    )
    batch = await repository.claim_batch(
        owner,
        DeliveryBatchDraft(target_sessions=["test:Group:1"]),
        [
            PushHistory(
                user_id="user-1",
                sub_id=owner.owner_id,
                target_session="test:Group:1",
                output_kind=output_kind,
                output_order=output_order,
                status="pending",
            )
            for output_kind, output_order in (("card", 0), ("standard", 1))
        ],
    )
    async with database.get_session() as session:
        remaining = await session.get(PushHistoryORM, batch.outputs[0].id)
        missing = await session.get(PushHistoryORM, batch.outputs[1].id)
        remaining.status = "success"
        await session.delete(missing)
        await session.commit()

    with pytest.raises(DeliveryConsistencyError, match="输出清单"):
        await repository.confirm_batch(batch.id)
    with pytest.raises(DeliveryConsistencyError, match="输出清单"):
        await repository.reconcile_batch(batch.id)
    still_pending = await repository.get_batch(batch.id)
    assert still_pending is not None
    assert still_pending.status == "pending"
    await database.close()


@pytest.mark.parametrize("operation", ["confirm_batch", "reconcile_batch"])
@pytest.mark.asyncio
async def test_resolving_batch_rejects_duplicate_persisted_manifest_identity(
    tmp_path,
    operation: str,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / f"duplicate-manifest-{operation}.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    batch = await _claim_two_output_batch(database, repository, owner)
    async with database.get_session() as session:
        batch_orm = await session.get(DeliveryBatchORM, batch.id)
        card = await session.get(PushHistoryORM, batch.outputs[0].id)
        standard = await session.get(PushHistoryORM, batch.outputs[1].id)
        duplicate_identity = dict(batch_orm.output_manifest[0])
        batch_orm.output_manifest = [duplicate_identity, duplicate_identity]
        card.status = "success"
        await session.delete(standard)
        await session.commit()

    with pytest.raises(DeliveryConsistencyError, match="输出清单"):
        await getattr(repository, operation)(batch.id)

    unresolved = await repository.get_batch(batch.id)
    assert unresolved is not None
    assert unresolved.status == "pending"
    assert len(await repository.list_inbox_items(owner, claimed=True)) == 1
    await database.close()


@pytest.mark.asyncio
async def test_confirm_rejects_persisted_card_that_is_not_first(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "persisted-late-card.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    batch = await _claim_two_output_batch(database, repository, owner)
    async with database.get_session() as session:
        batch_orm = await session.get(DeliveryBatchORM, batch.id)
        card = await session.get(PushHistoryORM, batch.outputs[0].id)
        standard = await session.get(PushHistoryORM, batch.outputs[1].id)
        card.output_order = 1
        card.status = "success"
        standard.output_order = 0
        standard.status = "skipped"
        batch_orm.output_manifest = [
            {
                "target_session": "test:Group:1",
                "output_kind": "standard",
                "output_order": 0,
            },
            {
                "target_session": "test:Group:1",
                "output_kind": "card",
                "output_order": 1,
            },
        ]
        await session.commit()

    with pytest.raises(DeliveryConsistencyError, match="order=0"):
        await repository.confirm_batch(batch.id)

    unresolved = await repository.get_batch(batch.id)
    assert unresolved is not None
    assert unresolved.status == "pending"
    assert len(await repository.list_inbox_items(owner, claimed=True)) == 1
    await database.close()


@pytest.mark.asyncio
async def test_unblocked_owner_and_member_deletion_happen_in_guarded_transaction(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "guarded-delete.db"))
    subscription_owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    resolved_batch = await _claim_two_output_batch(
        database,
        repository,
        subscription_owner,
    )
    async with database.get_session() as session:
        for output in resolved_batch.outputs:
            history = await session.get(PushHistoryORM, output.id)
            history.status = "success"
        await session.commit()
    await repository.confirm_batch(resolved_batch.id)

    assert await repository.delete_owner(subscription_owner) is True
    async with database.get_session() as session:
        assert await session.get(SubORM, subscription_owner.owner_id) is None
        retained_history = await session.get(
            PushHistoryORM,
            resolved_batch.outputs[0].id,
        )
        assert retained_history is not None
        assert retained_history.sub_id is None

    bundle_owner, member = await _create_bundle_owner(database)
    async with database.get_session() as session:
        second_member = BundleFeedORM(
            bundle_id=bundle_owner.owner_id,
            feed_id=11,
            position=1,
        )
        session.add(second_member)
        await session.commit()
        await session.refresh(second_member)
    assert await repository.remove_bundle_member(member.id) is True
    async with database.get_session() as session:
        assert await session.get(BundleFeedORM, member.id) is None
        compacted = await session.get(BundleFeedORM, second_member.id)
        assert compacted is not None
        assert compacted.position == 0
        assert await session.get(BundleORM, bundle_owner.owner_id) is not None
    await database.close()


@pytest.mark.asyncio
async def test_bundle_inbox_rejects_stale_member_position_atomically(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bundle-source-validation.db"))
    owner, member = await _create_bundle_owner(database)
    repository = DeliveryRepositoryImpl(database)

    with pytest.raises(DeliverySourceMismatchError):
        await repository.store_inbox_items(
            owner,
            [
                DeliveryInboxItemDraft(
                    feed_id=member.feed_id,
                    bundle_feed_id=member.id,
                    member_position=member.position + 1,
                    item_key="entry-1",
                    discovery_key="d1",
                )
            ],
        )

    assert await repository.list_inbox_items(owner) == []
    await database.close()


@pytest.mark.asyncio
async def test_bundle_claim_requires_explicit_selection(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "bundle-claim-selection.db"))
    owner, member = await _create_bundle_owner(database)
    repository = DeliveryRepositoryImpl(database)
    await repository.store_inbox_items(
        owner,
        [
            DeliveryInboxItemDraft(
                feed_id=member.feed_id,
                bundle_feed_id=member.id,
                member_position=member.position,
                item_key="entry-1",
                discovery_key="d1",
            )
        ],
    )
    output = PushHistory(
        user_id="bundle-user",
        bundle_id=owner.owner_id,
        target_session="test:Group:1",
        output_kind="standard",
        status="pending",
    )

    with pytest.raises(DeliverySourceMismatchError, match="显式指定"):
        await repository.claim_batch(
            owner,
            DeliveryBatchDraft(target_sessions=["test:Group:1"]),
            [output],
        )
    inbox = await repository.list_inbox_items(owner)
    batch = await repository.claim_batch(
        owner,
        DeliveryBatchDraft(
            target_sessions=["test:Group:1"],
            config_snapshot={"send_card": False},
        ),
        [output],
        item_ids=[inbox[0].id],
    )

    assert [item.id for item in batch.inbox_items] == [inbox[0].id]
    await database.close()


@pytest.mark.asyncio
async def test_confirm_rejects_cross_owner_persisted_members(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "cross-owner-batch.db"))
    owner = await _create_subscription_owner(database)
    repository = DeliveryRepositoryImpl(database)
    batch = await _claim_two_output_batch(database, repository, owner)
    async with database.get_session() as session:
        other = SubORM(user_id="user-1", feed_id=1, send_card=True)
        session.add(other)
        await session.flush()
        history = await session.get(PushHistoryORM, batch.outputs[0].id)
        history.sub_id = other.id
        history.status = "success"
        second = await session.get(PushHistoryORM, batch.outputs[1].id)
        second.status = "skipped"
        await session.commit()

    with pytest.raises(DeliveryConsistencyError, match="归属"):
        await repository.confirm_batch(batch.id)
    still_pending = await repository.get_batch(batch.id)
    assert still_pending is not None
    assert still_pending.status == "pending"
    await database.close()


@pytest.mark.asyncio
async def test_owner_queries_do_not_treat_unknown_owner_as_empty(tmp_path) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "unknown-owner.db"))
    repository = DeliveryRepositoryImpl(database)
    unknown = DeliveryOwner(owner_type="subscription", owner_id=999)

    with pytest.raises(DeliveryOwnerNotFoundError):
        await repository.store_inbox_items(unknown, [])
    with pytest.raises(DeliveryOwnerNotFoundError):
        await repository.list_inbox_items(unknown)
    with pytest.raises(DeliveryOwnerNotFoundError):
        await repository.get_pending_batch(unknown)
    await database.close()
