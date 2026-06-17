"""Import chat history from a Telegram Desktop JSON export (U15).

Telegram Bot API does not expose history, so historical messages are seeded
from a `result.json` export (Settings -> Export chat history -> JSON). Parsed
messages are inserted idempotently into a chat bound to the target project;
the normal pipeline then extracts knowledge from them.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..db import repositories as repo
from ..logging import get_logger

log = get_logger(__name__)


def _parse_text(text: Any) -> str:
    """Telegram `text` is a string or a list of strings / entity dicts."""
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        parts = []
        for p in text:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                parts.append(str(p.get("text", "")))
        return "".join(parts)
    return ""


def _parse_from_id(raw: Any) -> int | None:
    """`from_id` looks like 'user123456789'. Channels/others -> None (skip user)."""
    if not raw:
        return None
    s = str(raw)
    if s.startswith("user"):
        digits = s[4:]
        if digits.isdigit():
            return int(digits)
    return None


def parse_export(data: dict) -> tuple[int | None, str | None, list[dict]]:
    """Return (chat_tg_id, chat_name, [normalized messages])."""
    chat_tg_id = data.get("id")
    name = data.get("name")
    messages: list[dict] = []
    for m in data.get("messages", []):
        if m.get("type") != "message":
            continue
        text = _parse_text(m.get("text", ""))
        if not text.strip():
            continue
        messages.append(
            {
                "tg_message_id": int(m["id"]),
                "tg_user_id": _parse_from_id(m.get("from_id")),
                "text": text,
                "reply_to": m.get("reply_to_message_id"),
                "ts": m.get("date"),
            }
        )
    return (int(chat_tg_id) if chat_tg_id is not None else None), name, messages


def import_messages(
    conn: sqlite3.Connection,
    chat_id: int,
    messages: list[dict],
    *,
    skip_optout: bool = True,
) -> int:
    """Insert normalized messages idempotently. Returns count newly inserted."""
    inserted = 0
    for m in messages:
        uid = m["tg_user_id"]
        if skip_optout and uid is not None and repo.is_opted_out(conn, uid, chat_id):
            continue
        mid = repo.add_message(
            conn,
            chat_id=chat_id,
            tg_message_id=m["tg_message_id"],
            tg_user_id=uid,
            text=m["text"],
            reply_to=m["reply_to"],
            ts=m["ts"],
        )
        if mid is not None:
            if uid is not None:
                repo.upsert_user(conn, uid)
            inserted += 1
    return inserted


def import_export_file(
    conn: sqlite3.Connection,
    path: str | Path,
    *,
    project_slug: str,
    title: str | None = None,
) -> dict:
    """Load an export file, bind its chat to the project, import messages."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    chat_tg_id, name, messages = parse_export(data)
    if chat_tg_id is None:
        raise ValueError("export has no chat id")
    project = repo.get_project_by_slug(conn, project_slug)
    if project is None:
        raise ValueError(f"project '{project_slug}' not found")
    chat_id = repo.upsert_chat(conn, chat_tg_id, title or name)
    repo.bind_chat_to_project(conn, int(project["id"]), chat_id)
    inserted = import_messages(conn, chat_id, messages)
    log.info("import: project=%s chat=%s inserted=%s/%s", project_slug, chat_id, inserted, len(messages))
    return {"chat_id": chat_id, "imported": inserted, "total": len(messages)}
