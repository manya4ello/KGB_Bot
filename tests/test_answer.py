from secretary_bot.config import Settings
from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db
from secretary_bot.knowledge import vector
from secretary_bot.qa.answer import answer_question


class FakeLLM:
    def __init__(self, qvec, answer="Ответ."):
        self.qvec = qvec
        self.answer = answer

    def embed(self, texts, model):
        return [self.qvec for _ in texts]

    def chat(self, model, system, user):
        return self.answer

    def complete_json(self, model, system, user):  # pragma: no cover
        raise NotImplementedError


def _settings(**over):
    return Settings(_env_file=None, telegram_bot_token="x", openai_api_key="y", **over)


def _seed_item(conn, project_id, statement, vec):
    iid = repo.add_knowledge_item(
        conn,
        project_id=project_id,
        type="decision",
        statement=statement,
        rationale="simple",
        participants=None,
        confidence=0.9,
        content_hash=None,
        ts="t",
        source_message_ids=[],
    )
    vector.index_item(conn, iid, project_id, vec)
    return iid


def test_answer_with_match():
    conn = init_db(":memory:")
    pid = repo.create_project(conn, "p", "P")
    iid = _seed_item(conn, pid, "Use SQLite", [1.0, 0.0])
    llm = FakeLLM([1.0, 0.0], "Решили использовать SQLite.")
    res = answer_question(conn, llm, _settings(), query="что с БД?", project_ids={pid})
    assert res["status"] == "answer"
    assert iid in res["item_ids"]


def test_no_data_below_threshold():
    conn = init_db(":memory:")
    pid = repo.create_project(conn, "p", "P")
    _seed_item(conn, pid, "Use SQLite", [1.0, 0.0])
    llm = FakeLLM([0.0, 1.0])  # orthogonal -> cosine 0, below threshold
    res = answer_question(conn, llm, _settings(), query="x", project_ids={pid})
    assert res["status"] == "no_data"


def test_no_access_for_empty_scope():
    conn = init_db(":memory:")
    res = answer_question(conn, FakeLLM([1.0, 0.0]), _settings(), query="x", project_ids=set())
    assert res["status"] == "no_access"


def test_scope_isolation_hides_other_projects():
    conn = init_db(":memory:")
    p1 = repo.create_project(conn, "p1", "P1")
    p2 = repo.create_project(conn, "p2", "P2")
    _seed_item(conn, p2, "secret of p2", [1.0, 0.0])  # only in p2
    res = answer_question(conn, FakeLLM([1.0, 0.0]), _settings(), query="x", project_ids={p1})
    assert res["status"] == "no_data"  # p1 has nothing; p2 is out of scope
