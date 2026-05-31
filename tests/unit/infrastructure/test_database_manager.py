from __future__ import annotations

import pytest
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import (
    DatabaseManager,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.migrations import (
    MigrationRunner,
    cleanup_legacy_translation_tables,
    ensure_profile_schema,
    ensure_push_history_schema,
    ensure_user_rows,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.models import SubORM
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession


def test_database_is_initialized_requires_session_maker():
    db = DatabaseManager()
    db._engine = object()
    db._session_maker = None

    assert db.is_initialized is False


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, columns):
        self.columns = columns
        self.executed = []

    async def exec_driver_sql(self, sql, params=None):
        self.executed.append((sql, params))
        if "sqlite_master" in sql:
            if params and params[0] in {
                "rsshub_translation_cache",
                "rsshub_translate_cache",
                "rsshub_translation_history",
                "rsshub_translate_history",
            }:
                return _Result([])
            return _Result([("rsshub_push_history",)])
        if "PRAGMA table_info" in sql:
            return _Result([(0, col, "", 0, None, 0) for col in self.columns])
        return _Result([])


@pytest.mark.asyncio
async def test_ensure_push_history_schema_adds_missing_columns():
    conn = _Conn(columns=["id", "sub_id", "user_id", "feed_id"])

    applied = await ensure_push_history_schema(conn)

    assert applied == ["source_type", "source_key", "raw_xml", "handler_trace"]
    executed_sql = "\n".join(sql for sql, _ in conn.executed)
    assert "ADD COLUMN source_type" in executed_sql
    assert "ADD COLUMN source_key" in executed_sql
    assert "ADD COLUMN raw_xml" in executed_sql
    assert "ADD COLUMN handler_trace" in executed_sql


class _LegacyTableConn(_Conn):
    def __init__(self, existing_tables):
        super().__init__(columns=[])
        self.existing_tables = set(existing_tables)

    async def exec_driver_sql(self, sql, params=None):
        self.executed.append((sql, params))
        if "sqlite_master" in sql:
            table = params[0] if params else None
            if table in self.existing_tables:
                return _Result([(table,)])
            return _Result([])
        return _Result([])


@pytest.mark.asyncio
async def test_cleanup_legacy_translation_tables_drops_existing_tables():
    conn = _LegacyTableConn(
        {
            "rsshub_translation_cache",
            "rsshub_translate_history",
        }
    )

    dropped = await cleanup_legacy_translation_tables(conn)

    assert dropped == [
        "rsshub_translation_cache",
        "rsshub_translate_history",
    ]
    executed_sql = "\n".join(sql for sql, _ in conn.executed)
    assert "DROP TABLE IF EXISTS rsshub_translation_cache" in executed_sql
    assert "DROP TABLE IF EXISTS rsshub_translate_history" in executed_sql


@pytest.mark.asyncio
async def test_ensure_user_rows_backfills_orphan_subscription_and_history_users():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_user (
                id VARCHAR PRIMARY KEY,
                state INTEGER NOT NULL DEFAULT 1,
                interval INTEGER NOT NULL DEFAULT -100,
                notify INTEGER NOT NULL DEFAULT -100,
                send_mode INTEGER NOT NULL DEFAULT -100,
                handlers TEXT NOT NULL DEFAULT '[]',
                length_limit INTEGER NOT NULL DEFAULT -100,
                display_author INTEGER NOT NULL DEFAULT -100,
                display_via INTEGER NOT NULL DEFAULT -100,
                display_title INTEGER NOT NULL DEFAULT -100,
                display_entry_tags INTEGER NOT NULL DEFAULT -100,
                style INTEGER NOT NULL DEFAULT -100,
                display_media INTEGER NOT NULL DEFAULT -100,
                default_target_session TEXT,
                needs_binding_notice INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_sub (
                id INTEGER PRIMARY KEY,
                user_id VARCHAR NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_push_history (
                id INTEGER PRIMARY KEY,
                user_id VARCHAR
            )
            """
        )
        await conn.exec_driver_sql(
            "INSERT INTO rsshub_sub (id, user_id) VALUES (1, 'user-sub'), (2, '')"
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO rsshub_push_history (id, user_id)
            VALUES (1, 'user-history'), (2, 'user-sub'), (3, NULL)
            """
        )

        inserted = await ensure_user_rows(conn)
        inserted_again = await ensure_user_rows(conn)
        rows = (
            await conn.exec_driver_sql("SELECT id, state FROM rsshub_user ORDER BY id")
        ).fetchall()

    assert inserted == 2
    assert inserted_again == 0
    assert rows == [("user-history", 1), ("user-sub", 1)]
    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_user_rows_backfills_when_user_table_lacks_sql_defaults():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_user (
                id VARCHAR PRIMARY KEY,
                state INTEGER NOT NULL,
                interval INTEGER NOT NULL,
                notify INTEGER NOT NULL,
                send_mode INTEGER NOT NULL,
                handlers VARCHAR NOT NULL,
                length_limit INTEGER NOT NULL,
                display_author INTEGER NOT NULL,
                display_via INTEGER NOT NULL,
                display_title INTEGER NOT NULL,
                display_entry_tags INTEGER NOT NULL,
                style INTEGER NOT NULL,
                display_media INTEGER NOT NULL,
                default_target_session VARCHAR(255),
                needs_binding_notice INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_sub (
                id INTEGER PRIMARY KEY,
                user_id VARCHAR NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_push_history (
                id INTEGER PRIMARY KEY,
                user_id VARCHAR
            )
            """
        )
        await conn.exec_driver_sql(
            "INSERT INTO rsshub_sub (id, user_id) VALUES (1, 'legacy-user')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO rsshub_push_history (id, user_id) VALUES (1, 'legacy-user')"
        )

        inserted = await ensure_user_rows(conn)
        inserted_again = await ensure_user_rows(conn)
        rows = (
            await conn.exec_driver_sql(
                """
                SELECT
                    id,
                    state,
                    interval,
                    notify,
                    send_mode,
                    handlers,
                    length_limit,
                    display_author,
                    display_via,
                    display_title,
                    display_entry_tags,
                    style,
                    display_media,
                    needs_binding_notice,
                    created_at IS NOT NULL,
                    updated_at IS NOT NULL
                FROM rsshub_user
                ORDER BY id
                """
            )
        ).fetchall()

    assert inserted == 1
    assert inserted_again == 0
    assert rows == [
        (
            "legacy-user",
            1,
            -100,
            -100,
            -100,
            "[]",
            -100,
            -100,
            -100,
            -100,
            -100,
            -100,
            -100,
            0,
            1,
            1,
        )
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_profile_schema_adds_handlers_mode_to_existing_sub_table():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_user (
                id VARCHAR PRIMARY KEY
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_sub (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR NOT NULL,
                handlers TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO rsshub_user (id) VALUES ('u1')
            """
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO rsshub_sub (id, user_id, handlers)
            VALUES
                (1, 'u1', '[]'),
                (2, 'u1', '[{"id":"builtin.ai_filter.default"}]')
            """
        )

        applied = await ensure_profile_schema(conn)

        assert applied == ["rsshub_user.handlers", "rsshub_sub.handlers_mode"]
        sub_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_sub)")
            ).fetchall()
        }
        user_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_user)")
            ).fetchall()
        }
        rows = (
            await conn.exec_driver_sql(
                "SELECT id, handlers_mode FROM rsshub_sub ORDER BY id"
            )
        ).fetchall()

        assert "handlers" in user_columns
        assert "handlers_mode" in sub_columns
        assert rows == [(1, "inherit"), (2, "override")]

    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_profile_schema_allows_current_sub_orm_reads():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_user (
                id VARCHAR PRIMARY KEY
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_feed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link VARCHAR NOT NULL,
                title VARCHAR NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE rsshub_sub (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state INTEGER NOT NULL DEFAULT 1,
                user_id VARCHAR NOT NULL,
                feed_id INTEGER NOT NULL,
                title VARCHAR NOT NULL DEFAULT '',
                tags VARCHAR NOT NULL DEFAULT '',
                target_session VARCHAR,
                platform_name VARCHAR,
                interval INTEGER NOT NULL DEFAULT -100,
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
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        await conn.exec_driver_sql("INSERT INTO rsshub_user (id) VALUES ('u1')")
        await conn.exec_driver_sql(
            "INSERT INTO rsshub_feed (id, link, title) VALUES (1, 'https://example.com/rss', 'Feed')"
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO rsshub_sub (id, user_id, feed_id, title, handlers)
            VALUES (1, 'u1', 1, 'Sub', '[]')
            """
        )

        await ensure_profile_schema(conn)

    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        sub = await session.get(SubORM, 1)

    assert sub is not None
    assert sub.handlers_mode == "inherit"
    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_runner_only_discovers_current_baseline_migration():
    runner = MigrationRunner()

    assert [(item.version, item.name) for item in runner.scripts] == [
        (1, "V1_init"),
        (2, "V2_drop_link_preview"),
    ]


@pytest.mark.asyncio
async def test_v1_current_baseline_has_expected_core_columns_and_index():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        executed = await MigrationRunner().run_all(conn)

        assert executed == [1, 2]

        sub_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_sub)")
            ).fetchall()
        }
        user_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_user)")
            ).fetchall()
        }
        history_columns = {
            str(row[1])
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(rsshub_push_history)")
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

        assert "handlers_mode" in sub_columns
        assert "handlers_mode" not in user_columns
        assert "link_preview" not in user_columns
        assert "link_preview" not in sub_columns
        assert {"source_type", "source_key", "raw_xml", "handler_trace"}.issubset(
            history_columns
        )
        assert "idx_rsshub_push_history_scope_guid" in indexes

    await engine.dispose()
