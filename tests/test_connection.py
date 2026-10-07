from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mysafe.db.connection import Migration, load_migrations, migrate, open_database, schema_version


def test_new_database_is_at_latest_version() -> None:
    conn = open_database(":memory:")
    assert schema_version(conn) == load_migrations()[-1].version
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"categories", "entries", "fields", "meta"} <= tables


def test_foreign_keys_are_enabled() -> None:
    conn = open_database(":memory:")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reopening_file_database_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    conn = open_database(path)
    conn.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")
    conn.commit()
    conn.close()

    conn = open_database(path)  # migrations must not run again
    assert conn.execute("SELECT value FROM meta WHERE key='k'").fetchone()[0] == "v"
    conn.close()


def test_migrations_are_numbered_without_gaps() -> None:
    versions = [m.version for m in load_migrations()]
    assert versions == list(range(1, len(versions) + 1))


def test_failed_migration_is_rolled_back() -> None:
    conn = sqlite3.connect(":memory:")
    good = Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER);")
    bad = Migration(2, "0002_b.sql", "CREATE TABLE b (x INTEGER); THIS IS NOT SQL;")
    with pytest.raises(sqlite3.Error):
        migrate(conn, [good, bad])
    assert schema_version(conn) == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "b" not in tables


def test_refuses_database_from_newer_app() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="newer"):
        migrate(conn)


def test_movies_category_is_renamed_to_streaming() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrations = load_migrations()
    migrate(conn, migrations[:1])
    conn.execute(
        "INSERT INTO categories (id, name, icon, sort_order, created_at, updated_at) "
        "VALUES ('c1', 'Movies & Series', 'film', 1, 0, 0)"
    )
    conn.commit()
    migrate(conn, migrations)
    row = conn.execute("SELECT name, icon FROM categories WHERE id = 'c1'").fetchone()
    assert (row["name"], row["icon"]) == ("Streaming", "tv")


def test_streaming_rename_skipped_if_name_taken() -> None:
    conn = sqlite3.connect(":memory:")
    migrations = load_migrations()
    migrate(conn, migrations[:1])
    conn.executemany(
        "INSERT INTO categories (id, name, icon, sort_order, created_at, updated_at) "
        "VALUES (?, ?, NULL, 0, 0, 0)",
        [("a", "Movies & Series"), ("b", "Streaming")],
    )
    conn.commit()
    migrate(conn, migrations)
    names = sorted(r[0] for r in conn.execute("SELECT name FROM categories"))
    assert names == ["Movies & Series", "Streaming"]
