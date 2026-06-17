"""Repository layer: all SQL lives here (U2).

Functions take an open ``sqlite3.Connection`` and are pure with respect to
time — callers pass timestamps (``ts``) so behaviour stays deterministic and
testable.
"""

from __future__ import annotations

import sqlite3
from typing import Any

# --------------------------------------------------------------------------- #
# Chats
# --------------------------------------------------------------------------- #


def upsert_chat(conn: sqlite3.Connection, tg_chat_id: int, title: str | None = None) -> int:
    conn.execute(
        """
        INSERT INTO chats (tg_chat_id, title) VALUES (?, ?)
        ON CONFLICT(tg_chat_id) DO UPDATE SET title = COALESCE(excluded.title, chats.title)
        """,
        (tg_chat_id, title),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM chats WHERE tg_chat_id = ?", (tg_chat_id,)).fetchone()
    return int(row["id"])


def get_chat_by_tg(conn: sqlite3.Connection, tg_chat_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM chats WHERE tg_chat_id = ?", (tg_chat_id,)).fetchone()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #


def upsert_user(conn: sqlite3.Connection, tg_user_id: int, username: str | None = None) -> int:
    conn.execute(
        """
        INSERT INTO users (tg_user_id, username) VALUES (?, ?)
        ON CONFLICT(tg_user_id) DO UPDATE SET username = COALESCE(excluded.username, users.username)
        """,
        (tg_user_id, username),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM users WHERE tg_user_id = ?", (tg_user_id,)).fetchone()
    return int(row["id"])


# --------------------------------------------------------------------------- #
# Projects & bindings
# --------------------------------------------------------------------------- #


def create_project(conn: sqlite3.Connection, slug: str, title: str) -> int:
    conn.execute(
        "INSERT INTO projects (slug, title) VALUES (?, ?) ON CONFLICT(slug) DO UPDATE SET title = excluded.title",
        (slug, title),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
    return int(row["id"])


def bind_chat_to_project(conn: sqlite3.Connection, project_id: int, chat_id: int) -> None:
    # One chat = one project (UNIQUE(chat_id)); re-binding moves it.
    conn.execute("DELETE FROM project_chats WHERE chat_id = ?", (chat_id,))
    conn.execute(
        "INSERT INTO project_chats (project_id, chat_id) VALUES (?, ?)",
        (project_id, chat_id),
    )
    conn.commit()


def unbind_chat(conn: sqlite3.Connection, chat_id: int) -> None:
    conn.execute("DELETE FROM project_chats WHERE chat_id = ?", (chat_id,))
    conn.commit()


def is_chat_sanctioned(conn: sqlite3.Connection, chat_id: int) -> bool:
    """KTD10: a chat is sanctioned only when an admin has bound it to a project."""
    row = conn.execute(
        "SELECT 1 FROM project_chats WHERE chat_id = ? LIMIT 1", (chat_id,)
    ).fetchone()
    return row is not None


def get_project_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()


def list_projects(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects ORDER BY slug").fetchall()


def sanctioned_chats(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT chat_id FROM project_chats").fetchall()
    return [int(r["chat_id"]) for r in rows]


def next_synthetic_message_id(conn: sqlite3.Connection, chat_id: int) -> int:
    """Next unused tg_message_id for a synthetic chat (notes)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(tg_message_id), 0) + 1 AS n FROM messages WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()
    return int(row["n"])


def project_for_chat(conn: sqlite3.Connection, chat_id: int) -> int | None:
    row = conn.execute(
        "SELECT project_id FROM project_chats WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    return int(row["project_id"]) if row else None


def chats_in_project(conn: sqlite3.Connection, project_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT chat_id FROM project_chats WHERE project_id = ?", (project_id,)
    ).fetchall()
    return [int(r["chat_id"]) for r in rows]


# --------------------------------------------------------------------------- #
# Whitelist & admin
# --------------------------------------------------------------------------- #


def add_to_whitelist(
    conn: sqlite3.Connection,
    tg_user_id: int,
    is_admin: bool = False,
    note: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO whitelist (tg_user_id, is_admin, note) VALUES (?, ?, ?)
        ON CONFLICT(tg_user_id) DO UPDATE SET
            is_admin = excluded.is_admin,
            note = COALESCE(excluded.note, whitelist.note)
        """,
        (tg_user_id, int(is_admin), note),
    )
    conn.commit()


def remove_from_whitelist(conn: sqlite3.Connection, tg_user_id: int) -> None:
    conn.execute("DELETE FROM whitelist WHERE tg_user_id = ?", (tg_user_id,))
    conn.commit()


def is_whitelisted(conn: sqlite3.Connection, tg_user_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM whitelist WHERE tg_user_id = ? LIMIT 1", (tg_user_id,)
    ).fetchone()
    return row is not None


def is_admin(conn: sqlite3.Connection, tg_user_id: int) -> bool:
    row = conn.execute(
        "SELECT is_admin FROM whitelist WHERE tg_user_id = ?", (tg_user_id,)
    ).fetchone()
    return bool(row["is_admin"]) if row else False


def list_whitelist(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM whitelist ORDER BY tg_user_id").fetchall()


def grant_project(
    conn: sqlite3.Connection,
    project_id: int,
    tg_user_id: int,
    granted_by: int | None = None,
    ts: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO project_grants (project_id, tg_user_id, granted_by, ts)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(project_id, tg_user_id) DO NOTHING
        """,
        (project_id, tg_user_id, granted_by, ts),
    )
    conn.commit()


def has_project_grant(conn: sqlite3.Connection, project_id: int, tg_user_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM project_grants WHERE project_id = ? AND tg_user_id = ? LIMIT 1",
        (project_id, tg_user_id),
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------- #
# Opt-out (B5)
# --------------------------------------------------------------------------- #


def add_optout(
    conn: sqlite3.Connection, tg_user_id: int, chat_id: int | None = None, ts: str | None = None
) -> None:
    conn.execute(
        """
        INSERT INTO optouts (tg_user_id, chat_id, ts) VALUES (?, ?, ?)
        ON CONFLICT(tg_user_id, chat_id) DO NOTHING
        """,
        (tg_user_id, chat_id, ts),
    )
    conn.commit()


def remove_optout(conn: sqlite3.Connection, tg_user_id: int, chat_id: int | None = None) -> None:
    if chat_id is None:
        conn.execute(
            "DELETE FROM optouts WHERE tg_user_id = ? AND chat_id IS NULL", (tg_user_id,)
        )
    else:
        conn.execute(
            "DELETE FROM optouts WHERE tg_user_id = ? AND chat_id = ?", (tg_user_id, chat_id)
        )
    conn.commit()


def is_opted_out(conn: sqlite3.Connection, tg_user_id: int, chat_id: int) -> bool:
    """Opted out globally (chat_id IS NULL) or specifically for this chat."""
    row = conn.execute(
        """
        SELECT 1 FROM optouts
        WHERE tg_user_id = ? AND (chat_id IS NULL OR chat_id = ?)
        LIMIT 1
        """,
        (tg_user_id, chat_id),
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #


def add_message(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    tg_message_id: int,
    tg_user_id: int | None,
    text: str | None,
    reply_to: int | None,
    ts: str | None,
) -> int | None:
    """Insert a raw message. Idempotent on (chat_id, tg_message_id).

    Returns the row id, or ``None`` if it already existed (duplicate import/edit).
    """
    cur = conn.execute(
        """
        INSERT INTO messages (chat_id, tg_message_id, tg_user_id, text, reply_to, ts, processed)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(chat_id, tg_message_id) DO NOTHING
        """,
        (chat_id, tg_message_id, tg_user_id, text, reply_to, ts),
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    row = conn.execute(
        "SELECT id FROM messages WHERE chat_id = ? AND tg_message_id = ?",
        (chat_id, tg_message_id),
    ).fetchone()
    return int(row["id"])


def unprocessed_messages(conn: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM messages WHERE chat_id = ? AND processed = 0 ORDER BY id",
        (chat_id,),
    ).fetchall()


def mark_processed(conn: sqlite3.Connection, message_ids: list[int]) -> None:
    if not message_ids:
        return
    conn.executemany("UPDATE messages SET processed = 1 WHERE id = ?", [(i,) for i in message_ids])
    conn.commit()


# --------------------------------------------------------------------------- #
# Membership cache (KTD6)
# --------------------------------------------------------------------------- #


def record_membership(
    conn: sqlite3.Connection,
    chat_id: int,
    tg_user_id: int,
    *,
    is_member: bool = True,
    source: str = "observed",
    checked_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO memberships (chat_id, tg_user_id, is_member, checked_at, source)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, tg_user_id) DO UPDATE SET
            is_member = excluded.is_member,
            checked_at = excluded.checked_at,
            source = excluded.source
        """,
        (chat_id, tg_user_id, int(is_member), checked_at, source),
    )
    conn.commit()


def get_membership(conn: sqlite3.Connection, chat_id: int, tg_user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM memberships WHERE chat_id = ? AND tg_user_id = ?",
        (chat_id, tg_user_id),
    ).fetchone()


# --------------------------------------------------------------------------- #
# Knowledge items (used by later units; CRUD lives here for cohesion)
# --------------------------------------------------------------------------- #


def add_knowledge_item(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    type: str,
    statement: str,
    rationale: str | None,
    participants: str | None,
    confidence: float | None,
    content_hash: str | None,
    ts: str | None,
    source_message_ids: list[int] | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO knowledge_items
            (project_id, type, statement, rationale, participants, confidence,
             status, content_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (project_id, type, statement, rationale, participants, confidence, content_hash, ts, ts),
    )
    item_id = int(cur.lastrowid)
    for mid in source_message_ids or []:
        conn.execute(
            "INSERT OR IGNORE INTO item_sources (item_id, message_id) VALUES (?, ?)",
            (item_id, mid),
        )
    conn.commit()
    return item_id


def active_items(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM knowledge_items WHERE project_id = ? AND status = 'active' ORDER BY type, id",
        (project_id,),
    ).fetchall()


def item_source_messages(conn: sqlite3.Connection, item_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT message_id FROM item_sources WHERE item_id = ?", (item_id,)
    ).fetchall()
    return [int(r["message_id"]) for r in rows]
