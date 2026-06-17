from secretary_bot.config import Settings
from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db
from secretary_bot.knowledge import vector
from secretary_bot.pipeline.consolidate import consolidate_item
from secretary_bot.pipeline.extract import ExtractedItem


class FakeLLM:
    def __init__(self, embed_vec, relation="distinct"):
        self.embed_vec = embed_vec
        self.relation = relation
        self.classify_calls = 0

    def embed(self, texts, model):
        return [self.embed_vec for _ in texts]

    def complete_json(self, model, system, user):
        self.classify_calls += 1
        return {"relation": self.relation}

    def chat(self, model, system, user):  # pragma: no cover
        raise NotImplementedError


def _settings(**over):
    return Settings(_env_file=None, telegram_bot_token="x", openai_api_key="y", **over)


def _item(statement):
    return ExtractedItem(type="decision", statement=statement, confidence=0.9)


def _seed(conn, statement, vec):
    pid = repo.create_project(conn, "p", "P")
    iid = repo.add_knowledge_item(
        conn, project_id=pid, type="decision", statement=statement, rationale=None,
        participants=None, confidence=0.9, content_hash=None, ts="t", source_message_ids=[],
    )
    vector.index_item(conn, iid, pid, vec)
    return pid, iid


def test_add_to_empty_project():
    conn = init_db(":memory:")
    pid = repo.create_project(conn, "p", "P")
    llm = FakeLLM([1.0, 0.0])
    out = consolidate_item(conn, llm, _settings(), project_id=pid, item=_item("Use SQLite"), db_sources=[])
    assert out == "added"
    assert len(repo.active_items(conn, pid)) == 1
    assert llm.classify_calls == 0  # nothing to compare against


def test_duplicate_merges():
    conn = init_db(":memory:")
    pid, _ = _seed(conn, "Use SQLite", [1.0, 0.0])
    llm = FakeLLM([1.0, 0.0], relation="duplicate")
    out = consolidate_item(conn, llm, _settings(), project_id=pid, item=_item("We use SQLite"), db_sources=[])
    assert out == "merged"
    assert len(repo.active_items(conn, pid)) == 1  # no new item


def test_update_supersedes():
    conn = init_db(":memory:")
    pid, old_id = _seed(conn, "Use MySQL", [1.0, 0.0])
    llm = FakeLLM([1.0, 0.0], relation="update")
    out = consolidate_item(conn, llm, _settings(), project_id=pid, item=_item("Switch to Postgres"), db_sources=[])
    assert out == "superseded"
    active = repo.active_items(conn, pid)
    assert len(active) == 1 and active[0]["statement"] == "Switch to Postgres"
    old = conn.execute("SELECT status FROM knowledge_items WHERE id = ?", (old_id,)).fetchone()
    assert old["status"] == "superseded"
    # superseded item drops out of retrieval
    hits = vector.retrieve(conn, [1.0, 0.0], [pid])
    assert old_id not in [h[0] for h in hits]


def test_distinct_keeps_both():
    conn = init_db(":memory:")
    pid, _ = _seed(conn, "Use SQLite", [1.0, 0.0])
    llm = FakeLLM([1.0, 0.0], relation="distinct")  # high similarity but independent
    out = consolidate_item(conn, llm, _settings(), project_id=pid, item=_item("Add Redis cache"), db_sources=[])
    assert out == "added"
    assert len(repo.active_items(conn, pid)) == 2


def test_below_threshold_skips_classify():
    conn = init_db(":memory:")
    pid, _ = _seed(conn, "Use SQLite", [1.0, 0.0])
    llm = FakeLLM([0.0, 1.0], relation="update")  # orthogonal -> sim 0 < threshold
    out = consolidate_item(conn, llm, _settings(), project_id=pid, item=_item("Unrelated"), db_sources=[])
    assert out == "added"
    assert llm.classify_calls == 0
