"""Consolidation: dedup + supersede (U8, KTD5).

For each newly extracted item, find the nearest existing active item in the
project by embedding similarity. Above the duplicate threshold, ask the LLM to
classify the relation — and only supersede on an explicit "update" verdict, so
two similar-but-independent items both stay active (guard against false
overwrite). Below threshold → add as new.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from ..config import Settings
from ..db import repositories as repo
from ..knowledge import vector
from ..llm.client import SupportsLLM
from ..logging import get_logger
from .extract import ExtractedItem

log = get_logger(__name__)

CONSOLIDATE_SYSTEM = (
    "Сравни два утверждения из базы знаний команды по одной теме. Ответь СТРОГО "
    'JSON: {"relation": "duplicate"|"update"|"distinct"}. '
    "duplicate — по сути одно и то же. "
    "update — новое явно отменяет/заменяет старое (изменение решения, противоречие). "
    "distinct — про разное или независимы. Если не уверен — отвечай distinct."
)

VALID_RELATIONS = {"duplicate", "update", "distinct"}


def _content_hash(type_: str, statement: str) -> str:
    return hashlib.sha256(f"{type_}|{statement}".encode("utf-8")).hexdigest()


def _classify(llm: SupportsLLM, model: str, old_statement: str, new_statement: str) -> str:
    try:
        data = llm.complete_json(
            model, CONSOLIDATE_SYSTEM, f"Старое: {old_statement}\nНовое: {new_statement}"
        )
    except Exception:
        return "distinct"
    rel = str(data.get("relation", "distinct"))
    return rel if rel in VALID_RELATIONS else "distinct"


def _add_and_index(
    conn: sqlite3.Connection,
    project_id: int,
    item: ExtractedItem,
    db_sources: list[int],
    vec: list[float],
    ts: str | None,
) -> int:
    item_id = repo.add_knowledge_item(
        conn,
        project_id=project_id,
        type=item.type,
        statement=item.statement,
        rationale=item.rationale,
        participants=json.dumps(item.participants, ensure_ascii=False),
        confidence=item.confidence,
        content_hash=_content_hash(item.type, item.statement),
        ts=ts,
        source_message_ids=db_sources,
    )
    try:
        vector.index_item(conn, item_id, project_id, vec)
    except Exception:  # indexing best-effort; item still persisted
        log.warning("indexing failed for item %s", item_id)
    return item_id


def consolidate_item(
    conn: sqlite3.Connection,
    llm: SupportsLLM,
    settings: Settings,
    *,
    project_id: int,
    item: ExtractedItem,
    db_sources: list[int],
    ts: str | None = None,
) -> str:
    """Persist one extracted item with dedup/supersede. Returns the outcome:
    "added" | "merged" | "superseded"."""
    vec = llm.embed([item.statement], settings.llm_embed_model)[0]
    nearest = vector.retrieve(conn, vec, [project_id], k=1)

    if nearest and nearest[0][1] >= settings.dup_similarity_threshold:
        old_id, _score = nearest[0]
        old = conn.execute(
            "SELECT id, statement FROM knowledge_items WHERE id = ? AND status = 'active'",
            (old_id,),
        ).fetchone()
        if old is not None:
            relation = _classify(llm, settings.llm_extract_model, old["statement"], item.statement)
            if relation == "duplicate":
                for mid in db_sources:
                    conn.execute(
                        "INSERT OR IGNORE INTO item_sources (item_id, message_id) VALUES (?, ?)",
                        (old_id, mid),
                    )
                conn.execute(
                    "UPDATE knowledge_items SET updated_at = ? WHERE id = ?", (ts, old_id)
                )
                conn.commit()
                return "merged"
            if relation == "update":
                new_id = _add_and_index(conn, project_id, item, db_sources, vec, ts)
                conn.execute(
                    "UPDATE knowledge_items SET status = 'superseded', superseded_by = ? WHERE id = ?",
                    (new_id, old_id),
                )
                conn.commit()
                vector.set_status(conn, old_id, "superseded")
                return "superseded"
            # distinct -> fall through and add as a new item

    _add_and_index(conn, project_id, item, db_sources, vec, ts)
    return "added"
