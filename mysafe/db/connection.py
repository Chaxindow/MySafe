"""Opening the SQLite database and applying migrations."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations() -> list[Migration]:
    """Read all bundled migration files, sorted by version number."""
    migrations: list[Migration] = []
    for item in resources.files("mysafe.db.migrations").iterdir():
        match = _MIGRATION_NAME.match(item.name)
        if match:
            migrations.append(
                Migration(int(match.group(1)), item.name, item.read_text(encoding="utf-8"))
            )
    migrations.sort(key=lambda m: m.version)
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(f"Migration numbers must be 1..N without gaps, got {versions}")
    return migrations


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def migrate(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> int:
    """Apply every migration newer than the database's version. Returns the new version."""
    migrations = load_migrations() if migrations is None else migrations
    current = schema_version(conn)
    latest = migrations[-1].version if migrations else 0
    if current > latest:
        raise RuntimeError(
            f"Database schema version {current} is newer than this app supports ({latest}). "
            "Please update MySafe."
        )
    for migration in migrations:
        if migration.version <= current:
            continue
        # executescript() commits any open transaction first, so wrap the whole
        # migration in its own BEGIN/COMMIT to keep it atomic.
        try:
            conn.executescript(
                f"BEGIN;\n{migration.sql}\nPRAGMA user_version = {migration.version};\nCOMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return schema_version(conn)


def open_database(path: Path | str) -> sqlite3.Connection:
    """Open (or create) the database at `path` and bring its schema up to date.

    Pass ":memory:" for a throwaway in-memory database (used by tests).
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def open_from_bytes(data: bytes | None = None) -> sqlite3.Connection:
    """Open an in-memory database, optionally loaded from a database image (`to_bytes`).

    Used by the encrypted vault: the decrypted database only ever lives in memory.
    A plain SQLite file's bytes are a valid image too (used to import an old mysafe.db).
    """
    conn = sqlite3.connect(":memory:")
    if data:
        conn.deserialize(data)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def to_bytes(conn: sqlite3.Connection) -> bytes:
    """Snapshot the whole database as bytes (to be encrypted and saved)."""
    return conn.serialize()
