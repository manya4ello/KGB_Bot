"""SQLite connection + idempotent schema application (U1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection, ensuring the parent directory exists.

    ``:memory:`` is supported for tests (no directory is created).
    """
    if db_path != ":memory:":
        parent = Path(db_path).expanduser().parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Add a column to an existing table if missing (lightweight migration)."""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def apply_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql and idempotent migrations. Safe to call repeatedly."""
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    # Migrations for DBs created before a column was added.
    _ensure_column(conn, "whitelist", "note", "TEXT")
    conn.commit()


def init_db(db_path: str) -> sqlite3.Connection:
    """Connect and apply the schema in one step."""
    conn = connect(db_path)
    apply_schema(conn)
    return conn
