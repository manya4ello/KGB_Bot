"""End-to-end extraction runner (minimal U13).

One pass over a chat's unprocessed messages:
    segment -> triage -> extract -> persist -> mark processed -> render -> git.

This is the minimal sweep wired to ``/runextract``. The full U13 (periodic
scheduler, token-budget accounting, crash reconciliation) is layered later;
here we honour a simple per-run message cap (KTD10) so a flood cannot run away.
Consolidation (U8) is not applied yet — items are appended as extracted.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from ..config import Settings
from ..db import repositories as repo
from ..knowledge.storage import render_project
from ..llm.client import SupportsLLM
from ..logging import get_logger
from .consolidate import consolidate_item
from .extract import extract_window
from .segment import segment_messages
from .triage import triage_window

log = get_logger(__name__)


class SupportsKB(Protocol):
    def sync(self, files: dict[str, str], message: str, *, push: bool = False) -> bool: ...


@dataclass
class RunReport:
    chat_id: int
    skipped: bool = False
    reason: str = ""
    windows: int = 0
    windows_with_signal: int = 0
    items_added: int = 0
    items_merged: int = 0
    over_budget: bool = False
    committed: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_extraction_for_chat(
    conn: sqlite3.Connection,
    llm: SupportsLLM,
    settings: Settings,
    kb: SupportsKB,
    *,
    chat_id: int,
    push: bool = False,
) -> RunReport:
    project_id = repo.project_for_chat(conn, chat_id)
    if project_id is None:  # not sanctioned (KTD10) — never reaches the LLM
        return RunReport(chat_id, skipped=True, reason="unsanctioned")

    messages = repo.unprocessed_messages(conn, chat_id)
    if not messages:
        return RunReport(chat_id, skipped=True, reason="no_new_messages")

    # KTD10 budget cap: process at most N messages per run.
    cap = settings.extract_budget_per_chat
    over_budget = len(messages) > cap
    batch = messages[:cap]
    if over_budget:
        log.warning("chat %s over per-run budget (%s > %s)", chat_id, len(messages), cap)

    tg_to_db = {int(m["tg_message_id"]): int(m["id"]) for m in batch}
    windows = segment_messages(batch)

    items_added = 0
    items_merged = 0
    windows_signal = 0
    for window in windows:
        triage = triage_window(llm, settings.llm_triage_model, window)
        if not triage.has_signal:
            continue
        windows_signal += 1
        items = extract_window(
            llm,
            settings.llm_extract_model,
            window,
            confidence_threshold=settings.confidence_threshold,
        )
        for item in items:
            db_sources = [tg_to_db[s] for s in item.source_message_ids if s in tg_to_db]
            outcome = consolidate_item(
                conn,
                llm,
                settings,
                project_id=project_id,
                item=item,
                db_sources=db_sources,
                ts=_now_iso(),
            )
            if outcome == "merged":
                items_merged += 1
            else:
                items_added += 1

    repo.mark_processed(conn, [int(m["id"]) for m in batch])

    committed = _render_and_sync(conn, kb, project_id, push=push)
    return RunReport(
        chat_id=chat_id,
        windows=len(windows),
        windows_with_signal=windows_signal,
        items_added=items_added,
        items_merged=items_merged,
        over_budget=over_budget,
        committed=committed,
    )


def _render_and_sync(
    conn: sqlite3.Connection, kb: SupportsKB, project_id: int, *, push: bool
) -> bool:
    project = conn.execute(
        "SELECT slug, title FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    render_items: list[dict[str, Any]] = []
    for it in repo.active_items(conn, project_id):
        db_sources = repo.item_source_messages(conn, int(it["id"]))
        tg_sources = []
        for mid in db_sources:
            row = conn.execute(
                "SELECT tg_message_id FROM messages WHERE id = ?", (mid,)
            ).fetchone()
            if row:
                tg_sources.append(int(row["tg_message_id"]))
        render_items.append(
            {
                "type": it["type"],
                "statement": it["statement"],
                "rationale": it["rationale"],
                "participants": it["participants"],
                "source_ids": tg_sources,
            }
        )
    files = render_project(project["slug"], project["title"], render_items)
    return kb.sync(files, f"chore: update knowledge for {project['slug']}", push=push)


def run_all(
    conn: sqlite3.Connection,
    llm: SupportsLLM,
    settings: Settings,
    kb: SupportsKB,
    *,
    push: bool = False,
) -> list[RunReport]:
    reports = []
    for chat_id in repo.sanctioned_chats(conn):
        try:
            reports.append(
                run_extraction_for_chat(conn, llm, settings, kb, chat_id=chat_id, push=push)
            )
        except Exception:  # isolate per-chat failures (KTD: one chat must not kill others)
            log.exception("extraction failed for chat %s", chat_id)
            reports.append(RunReport(chat_id, skipped=True, reason="error"))
    return reports
