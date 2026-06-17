"""Ingestion logic (U2), decoupled from aiogram for testability.

The aiogram handlers in ``bot.py`` extract plain fields from Telegram updates
and call into these functions. Core policy lives here:

* KTD10 — store/process messages only from *sanctioned* (bound) chats.
* B5 — respect per-user/per-chat opt-out; announce on join.
"""

from __future__ import annotations

import sqlite3
from enum import Enum

from ..db import repositories as repo


class IngestResult(str, Enum):
    STORED = "stored"
    UNSANCTIONED = "unsanctioned"
    OPTED_OUT = "opted_out"
    SKIPPED_EMPTY = "skipped_empty"
    DUPLICATE = "duplicate"


ANNOUNCE_TEXT = (
    "Привет! Я веду базу знаний команды: читаю сообщения этого чата и извлекаю "
    "из них решения, идеи и аргументы. Я начинаю собирать данные только после "
    "того, как администратор привяжет этот чат к проекту.\n\n"
    "Если не хотите, чтобы ваши сообщения учитывались — отправьте /optout "
    "(вернуть — /optin)."
)


def register_chat(
    conn: sqlite3.Connection,
    tg_chat_id: int,
    title: str | None = None,
    ts: str | None = None,
) -> int:
    """Register a chat (e.g. when the bot is added) so an admin can bind it.

    Registration does not authorize ingestion — that requires binding (KTD10).
    """
    chat_id = repo.upsert_chat(conn, tg_chat_id, title)
    if ts:
        conn.execute(
            "UPDATE chats SET joined_at = COALESCE(joined_at, ?) WHERE id = ?", (ts, chat_id)
        )
        conn.commit()
    return chat_id


def handle_incoming(
    conn: sqlite3.Connection,
    *,
    tg_chat_id: int,
    tg_message_id: int,
    chat_title: str | None = None,
    tg_user_id: int | None = None,
    username: str | None = None,
    text: str | None = None,
    reply_to: int | None = None,
    ts: str | None = None,
) -> IngestResult:
    """Apply ingestion policy to one incoming message.

    Returns an :class:`IngestResult`. Only ``STORED`` writes a message row.
    """
    chat = repo.get_chat_by_tg(conn, tg_chat_id)
    # KTD10: unknown or unbound chat -> drop, never reaches the LLM pipeline.
    if chat is None or not repo.is_chat_sanctioned(conn, int(chat["id"])):
        return IngestResult.UNSANCTIONED

    chat_id = int(chat["id"])

    if not text or not text.strip():
        return IngestResult.SKIPPED_EMPTY

    if tg_user_id is not None and repo.is_opted_out(conn, tg_user_id, chat_id):
        return IngestResult.OPTED_OUT

    if tg_user_id is not None:
        repo.upsert_user(conn, tg_user_id, username)
        # observed membership warms the cache only; it is not the source of truth (KTD6).
        repo.record_membership(
            conn, chat_id, tg_user_id, is_member=True, source="observed", checked_at=ts
        )

    message_id = repo.add_message(
        conn,
        chat_id=chat_id,
        tg_message_id=tg_message_id,
        tg_user_id=tg_user_id,
        text=text,
        reply_to=reply_to,
        ts=ts,
    )
    if message_id is None:
        return IngestResult.DUPLICATE
    return IngestResult.STORED


def opt_out(
    conn: sqlite3.Connection, tg_user_id: int, chat_id: int | None = None, ts: str | None = None
) -> None:
    repo.add_optout(conn, tg_user_id, chat_id, ts)


def opt_in(conn: sqlite3.Connection, tg_user_id: int, chat_id: int | None = None) -> None:
    repo.remove_optout(conn, tg_user_id, chat_id)
