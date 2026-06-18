"""Access control and project scoping (U5, KTD6).

* Global whitelist gate (``is_allowed``).
* Project-level scope: a user can see a project if they belong to at least one
  of its chats (verified via an injected ``member_check``) or were granted
  access. The per-project chat loop short-circuits on the first confirmed chat.

``member_check(tg_chat_id, user_id) -> bool`` is async and provided by the bot
layer (which maps Telegram ChatMember statuses). Keeping it injected makes this
module testable without Telegram.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Awaitable, Callable

from ..config import Settings
from ..db import repositories as repo

MemberCheck = Callable[[int, int], Awaitable[bool]]


def is_allowed(conn: sqlite3.Connection, tg_user_id: int) -> bool:
    return repo.is_whitelisted(conn, tg_user_id)


def is_superadmin(settings: Settings, tg_user_id: int) -> bool:
    """The single super-admin (configured ADMIN_USER_ID) sees all projects."""
    return settings.admin_user_id is not None and tg_user_id == int(settings.admin_user_id)


def all_project_ids(conn: sqlite3.Connection) -> set[int]:
    return {int(p["id"]) for p in repo.list_projects(conn)}


def project_for_tg_chat(conn: sqlite3.Connection, tg_chat_id: int) -> int | None:
    chat = repo.get_chat_by_tg(conn, tg_chat_id)
    if chat is None:
        return None
    return repo.project_for_chat(conn, int(chat["id"]))


def _fresh(checked_at: str | None, now: datetime, ttl_seconds: int) -> bool:
    if not checked_at:
        return False
    try:
        t = datetime.fromisoformat(checked_at)
    except (ValueError, TypeError):
        return False
    return (now - t).total_seconds() < ttl_seconds


async def _is_member(
    conn: sqlite3.Connection,
    member_check: MemberCheck,
    chat_id: int,
    tg_chat_id: int,
    user_id: int,
    ttl_seconds: int,
    now: datetime,
) -> bool:
    cached = repo.get_membership(conn, chat_id, user_id)
    if cached is not None and _fresh(cached["checked_at"], now, ttl_seconds):
        return bool(cached["is_member"])
    ok = await member_check(tg_chat_id, user_id)
    repo.record_membership(
        conn, chat_id, user_id, is_member=ok, source="checked", checked_at=now.isoformat()
    )
    return ok


async def accessible_projects(
    conn: sqlite3.Connection,
    member_check: MemberCheck,
    tg_user_id: int,
    *,
    ttl_seconds: int = 3600,
    now: datetime | None = None,
) -> set[int]:
    now = now or datetime.now(timezone.utc)
    result: set[int] = set()
    for project in repo.list_projects(conn):
        pid = int(project["id"])
        if repo.has_project_grant(conn, pid, tg_user_id):
            result.add(pid)
            continue
        for chat_id in repo.chats_in_project(conn, pid):
            row = conn.execute(
                "SELECT tg_chat_id FROM chats WHERE id = ?", (chat_id,)
            ).fetchone()
            if row is None:
                continue
            try:
                if await _is_member(
                    conn, member_check, chat_id, int(row["tg_chat_id"]), tg_user_id, ttl_seconds, now
                ):
                    result.add(pid)
                    break  # short-circuit: one confirmed chat opens the project
            except Exception:
                continue  # synthetic / unreachable chat — skip
    return result
