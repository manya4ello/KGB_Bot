from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db
from secretary_bot.knowledge import vector


def _item(conn, project_id, statement):
    return repo.add_knowledge_item(
        conn,
        project_id=project_id,
        type="decision",
        statement=statement,
        rationale=None,
        participants=None,
        confidence=0.9,
        content_hash=None,
        ts="t",
        source_message_ids=[],
    )


def test_index_and_retrieve_ranks_by_cosine():
    conn = init_db(":memory:")
    pid = repo.create_project(conn, "p", "P")
    i1, i2 = _item(conn, pid, "SQLite"), _item(conn, pid, "caching")
    vector.index_item(conn, i1, pid, [1.0, 0.0])
    vector.index_item(conn, i2, pid, [0.0, 1.0])
    hits = vector.retrieve(conn, [1.0, 0.0], [pid], k=5)
    assert hits[0][0] == i1 and hits[0][1] > 0.99


def test_retrieve_is_scoped_by_project():
    conn = init_db(":memory:")
    p1, p2 = repo.create_project(conn, "p1", "P1"), repo.create_project(conn, "p2", "P2")
    i1, i2 = _item(conn, p1, "a"), _item(conn, p2, "b")
    vector.index_item(conn, i1, p1, [1.0, 0.0])
    vector.index_item(conn, i2, p2, [1.0, 0.0])
    assert [h[0] for h in vector.retrieve(conn, [1.0, 0.0], [p1])] == [i1]


def test_retrieve_empty_scope():
    conn = init_db(":memory:")
    assert vector.retrieve(conn, [1.0], []) == []


def test_superseded_not_returned():
    conn = init_db(":memory:")
    pid = repo.create_project(conn, "p", "P")
    i1 = _item(conn, pid, "x")
    vector.index_item(conn, i1, pid, [1.0, 0.0])
    vector.set_status(conn, i1, "superseded")
    assert vector.retrieve(conn, [1.0, 0.0], [pid]) == []
