"""Vector index over knowledge items (U10, KTD4).

Embeddings are stored as JSON in SQLite (``item_vectors``) and searched with
plain cosine similarity in Python. At the team's scale this is more than
enough, has no heavy dependency, and is trivially rebuildable from
``knowledge_items``. Retrieval is filtered by the caller's project scope (KTD6).
"""

from __future__ import annotations

import json
import math
import sqlite3


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def index_item(
    conn: sqlite3.Connection,
    item_id: int,
    project_id: int,
    vector: list[float],
    *,
    status: str = "active",
) -> None:
    conn.execute(
        """
        INSERT INTO item_vectors (item_id, project_id, vector, status)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
            project_id = excluded.project_id,
            vector = excluded.vector,
            status = excluded.status
        """,
        (item_id, project_id, json.dumps(vector), status),
    )
    conn.commit()


def set_status(conn: sqlite3.Connection, item_id: int, status: str) -> None:
    conn.execute("UPDATE item_vectors SET status = ? WHERE item_id = ?", (status, item_id))
    conn.commit()


def retrieve(
    conn: sqlite3.Connection,
    query_vector: list[float],
    project_ids: list[int],
    *,
    k: int = 5,
) -> list[tuple[int, float]]:
    """Return [(item_id, score)] for active items in the given projects, top-k."""
    if not project_ids:
        return []
    placeholders = ",".join("?" * len(project_ids))
    rows = conn.execute(
        f"SELECT item_id, vector FROM item_vectors "
        f"WHERE status = 'active' AND project_id IN ({placeholders})",
        tuple(project_ids),
    ).fetchall()
    scored = [(int(r["item_id"]), cosine(query_vector, json.loads(r["vector"]))) for r in rows]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]
