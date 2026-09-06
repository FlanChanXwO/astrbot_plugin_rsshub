# ruff: noqa: N999  # 迁移发现器要求使用 V{version}_{name}.py 命名。
"""V3：增加统一卡片与多源聚合投递持久化结构。"""

from __future__ import annotations

from ...utils import get_logger

logger = get_logger()


async def _table_exists(conn, table: str) -> bool:
    result = await conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return result.fetchone() is not None


async def _column_names(conn, table: str) -> set[str]:
    result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in result.fetchall()}


async def _add_missing_columns(
    conn,
    table: str,
    definitions: dict[str, str],
) -> None:
    if not await _table_exists(conn, table):
        return
    columns = await _column_names(conn, table)
    for name, definition in definitions.items():
        if name in columns:
            continue
        await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {definition}")
        logger.info("迁移 V3: 为 %s 添加 %s 字段", table, name)


async def upgrade(conn) -> None:
    """以纯加法方式创建可靠投递表并扩展既有表。"""
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS rsshub_bundle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id VARCHAR NOT NULL,
            name VARCHAR(255) NOT NULL,
            target_sessions JSON NOT NULL,
            state INTEGER NOT NULL DEFAULT 0,
            interval INTEGER NOT NULL,
            next_check_time DATETIME,
            notify INTEGER NOT NULL DEFAULT -100,
            send_mode INTEGER NOT NULL DEFAULT -100,
            length_limit INTEGER NOT NULL DEFAULT -100,
            display_author INTEGER NOT NULL DEFAULT -100,
            display_via INTEGER NOT NULL DEFAULT -100,
            display_title INTEGER NOT NULL DEFAULT -100,
            display_entry_tags INTEGER NOT NULL DEFAULT -100,
            style INTEGER NOT NULL DEFAULT -100,
            display_media INTEGER NOT NULL DEFAULT -100,
            handlers TEXT NOT NULL DEFAULT '[]',
            send_card BOOLEAN NOT NULL DEFAULT 0,
            template_id VARCHAR(255),
            card_send_original_content BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_rsshub_bundle_user_name UNIQUE (user_id, name),
            CONSTRAINT ck_rsshub_bundle_state CHECK (state IN (0, 1)),
            CONSTRAINT ck_rsshub_bundle_interval CHECK (interval > 0),
            CONSTRAINT ck_rsshub_bundle_target_sessions CHECK (
                json_valid(target_sessions)
                AND json_array_length(target_sessions) > 0
            ),
            FOREIGN KEY (user_id) REFERENCES rsshub_user (id)
        )
        """
    )
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS rsshub_bundle_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_id INTEGER NOT NULL,
            feed_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            entry_hashes JSON,
            etag VARCHAR(128),
            last_modified DATETIME,
            last_check_status VARCHAR(32),
            last_checked_at DATETIME,
            CONSTRAINT uq_rsshub_bundle_feed_member UNIQUE (bundle_id, feed_id),
            CONSTRAINT uq_rsshub_bundle_feed_position UNIQUE (bundle_id, position),
            CONSTRAINT ck_rsshub_bundle_feed_position CHECK (position >= 0),
            FOREIGN KEY (bundle_id) REFERENCES rsshub_bundle (id) ON DELETE CASCADE,
            FOREIGN KEY (feed_id) REFERENCES rsshub_feed (id) ON DELETE RESTRICT
        )
        """
    )
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS rsshub_delivery_batch (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_type VARCHAR(16) NOT NULL,
            owner_id INTEGER NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            target_sessions JSON NOT NULL,
            config_snapshot JSON NOT NULL DEFAULT '{}',
            template_snapshot JSON,
            document_snapshot JSON,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            confirmed_at DATETIME,
            CONSTRAINT ck_rsshub_delivery_batch_owner_type CHECK (
                owner_type IN ('subscription', 'bundle')
            ),
            CONSTRAINT ck_rsshub_delivery_batch_status CHECK (
                status IN ('pending', 'confirmed', 'discarded')
            ),
            CONSTRAINT ck_rsshub_delivery_batch_target_sessions CHECK (
                json_valid(target_sessions)
                AND json_array_length(target_sessions) > 0
            )
        )
        """
    )
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS rsshub_delivery_inbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_type VARCHAR(16) NOT NULL,
            owner_id INTEGER NOT NULL,
            feed_id INTEGER NOT NULL,
            bundle_feed_id INTEGER,
            member_position INTEGER,
            item_key VARCHAR(512) NOT NULL,
            hash_group JSON NOT NULL DEFAULT '[]',
            discovery_key VARCHAR(512) NOT NULL,
            entry_payload JSON NOT NULL DEFAULT '{}',
            raw_xml TEXT,
            media_items JSON NOT NULL DEFAULT '[]',
            published_at DATETIME,
            entry_updated_at DATETIME,
            discovered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            batch_id INTEGER,
            CONSTRAINT uq_rsshub_delivery_inbox_owner_source_item UNIQUE (
                owner_type,
                owner_id,
                feed_id,
                item_key
            ),
            CONSTRAINT ck_rsshub_delivery_inbox_owner_type CHECK (
                owner_type IN ('subscription', 'bundle')
            ),
            CONSTRAINT ck_rsshub_delivery_inbox_owner_source CHECK (
                (
                    owner_type = 'subscription'
                    AND bundle_feed_id IS NULL
                    AND member_position IS NULL
                ) OR (
                    owner_type = 'bundle'
                    AND bundle_feed_id IS NOT NULL
                    AND member_position IS NOT NULL
                    AND member_position >= 0
                )
            ),
            CONSTRAINT ck_rsshub_delivery_inbox_item_key CHECK (
                length(trim(item_key)) > 0
            ),
            CONSTRAINT ck_rsshub_delivery_inbox_discovery_key CHECK (
                length(trim(discovery_key)) > 0
            ),
            FOREIGN KEY (feed_id) REFERENCES rsshub_feed (id) ON DELETE RESTRICT,
            FOREIGN KEY (bundle_feed_id)
                REFERENCES rsshub_bundle_feed (id) ON DELETE RESTRICT,
            FOREIGN KEY (batch_id)
                REFERENCES rsshub_delivery_batch (id) ON DELETE RESTRICT
        )
        """
    )

    await _add_missing_columns(
        conn,
        "rsshub_sub",
        {
            "send_card": "send_card BOOLEAN NOT NULL DEFAULT 0",
            "template_id": "template_id VARCHAR(255)",
            "card_send_original_content": (
                "card_send_original_content BOOLEAN NOT NULL DEFAULT 0"
            ),
        },
    )
    await _add_missing_columns(
        conn,
        "rsshub_push_history",
        {
            "batch_id": (
                "batch_id INTEGER REFERENCES rsshub_delivery_batch(id) "
                "ON DELETE RESTRICT"
            ),
            "bundle_id": (
                "bundle_id INTEGER REFERENCES rsshub_bundle(id) ON DELETE RESTRICT"
            ),
            "output_kind": (
                "output_kind VARCHAR(16) NOT NULL DEFAULT 'standard' "
                "CHECK (output_kind IN ('card', 'standard'))"
            ),
            "output_order": (
                "output_order INTEGER NOT NULL DEFAULT 0 CHECK (output_order >= 0)"
            ),
            "source_context": "source_context JSON",
        },
    )

    index_statements = (
        """
        CREATE INDEX IF NOT EXISTS idx_rsshub_bundle_due
        ON rsshub_bundle (state, next_check_time, id)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_rsshub_delivery_batch_pending_owner
        ON rsshub_delivery_batch (owner_type, owner_id)
        WHERE status = 'pending'
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_rsshub_delivery_batch_owner_status
        ON rsshub_delivery_batch (owner_type, owner_id, status, id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_rsshub_delivery_inbox_unclaimed
        ON rsshub_delivery_inbox (
            owner_type,
            owner_id,
            batch_id,
            discovered_at,
            id
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_rsshub_delivery_inbox_discovery
        ON rsshub_delivery_inbox (owner_type, owner_id, discovery_key, id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_rsshub_push_history_batch_output
        ON rsshub_push_history (batch_id, target_session, output_order, id)
        """,
    )
    for statement in index_statements:
        await conn.exec_driver_sql(statement)

    logger.info("迁移 V3 完成: 增加统一可靠投递 schema")
