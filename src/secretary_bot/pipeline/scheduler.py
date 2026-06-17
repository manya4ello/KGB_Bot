"""Extraction scheduler (full U13).

Periodically sweeps sanctioned chats and runs extraction when a chat has enough
new messages, or on demand via /runextract (force=True). A single asyncio lock
serialises scheduled and manual runs (single-writer). A coarse global budget
(messages per period, a proxy for token spend) caps run-away cost (KTD10).

Extraction runs synchronously inside the event loop (one SQLite connection, one
thread) — simple and corruption-free at this scale; it briefly pauses polling
during a run.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time

from ..config import Settings
from ..db import repositories as repo
from ..llm.client import SupportsLLM
from ..logging import get_logger
from .runner import RunReport, SupportsKB, run_extraction_for_chat

log = get_logger(__name__)


class Scheduler:
    def __init__(
        self,
        conn: sqlite3.Connection,
        llm: SupportsLLM,
        settings: Settings,
        kb: SupportsKB,
        *,
        clock=time.monotonic,
    ) -> None:
        self.conn = conn
        self.llm = llm
        self.settings = settings
        self.kb = kb
        self._clock = clock
        self._lock = asyncio.Lock()
        self._period_start = clock()
        self._spent = 0  # messages processed this budget period

    def _reset_budget_if_needed(self) -> None:
        if self._clock() - self._period_start >= self.settings.budget_period_seconds:
            self._period_start = self._clock()
            self._spent = 0

    async def run_due(self, *, force: bool) -> list[RunReport]:
        """Run extraction for due chats. force=True ignores the per-chat threshold."""
        async with self._lock:
            self._reset_budget_if_needed()
            push = bool(self.settings.kb_repo_url)
            reports: list[RunReport] = []
            for chat_id in repo.sanctioned_chats(self.conn):
                pending = len(repo.unprocessed_messages(self.conn, chat_id))
                if pending == 0:
                    continue
                if not force and pending < self.settings.extract_message_threshold:
                    continue
                if self._spent >= self.settings.extract_budget_global:
                    log.warning("global extraction budget reached; deferring remaining chats")
                    break
                try:
                    report = run_extraction_for_chat(
                        self.conn, self.llm, self.settings, self.kb, chat_id=chat_id, push=push
                    )
                except Exception:
                    log.exception("extraction failed for chat %s", chat_id)
                    reports.append(RunReport(chat_id, skipped=True, reason="error"))
                    continue
                self._spent += min(pending, self.settings.extract_budget_per_chat)
                reports.append(report)
            return reports

    async def loop(self) -> None:
        """Background loop: scan on an interval."""
        while True:
            try:
                await asyncio.sleep(self.settings.scan_interval_seconds)
                await self.run_due(force=False)
            except asyncio.CancelledError:
                raise
            except Exception:  # never let the loop die on a transient error
                log.exception("scheduler loop iteration failed")
