from secretary_bot.config import Settings
from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db
from secretary_bot.pipeline.scheduler import Scheduler
from secretary_bot.telegram import admin


class FakeLLM:
    def __init__(self, signal=True):
        self.signal = signal

    def embed(self, texts, model):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def complete_json(self, model, system, user):
        if "фильтр шума" in system:  # triage
            return {"has_signal": self.signal, "categories": ["decision"]}
        if "Сравни два утверждения" in system:  # consolidation
            return {"relation": "distinct"}
        return {  # extraction
            "items": [
                {"type": "decision", "statement": "Use SQLite", "source_message_ids": [10], "confidence": 0.9}
            ]
        }

    def chat(self, model, system, user):  # pragma: no cover
        raise NotImplementedError


class FakeKB:
    def sync(self, files, message, *, push=False):
        return True


def _settings(**over):
    return Settings(_env_file=None, telegram_bot_token="x", openai_api_key="y", **over)


def _chat_with_messages(conn, n=1, base_id=10):
    admin.create_project(conn, "p", "P")
    _, chat_id = admin.bind_chat(conn, 100, "p", "Chat")
    for i in range(n):
        repo.add_message(
            conn, chat_id=chat_id, tg_message_id=base_id + i, tg_user_id=1,
            text="we decided to use SQLite", reply_to=None, ts="2026-06-17T10:00:00",
        )
    return chat_id


async def test_force_run_extracts():
    conn = init_db(":memory:")
    chat_id = _chat_with_messages(conn)
    sch = Scheduler(conn, FakeLLM(signal=True), _settings(), FakeKB())
    reports = await sch.run_due(force=True)
    assert any(r.items_added >= 1 for r in reports)
    assert repo.unprocessed_messages(conn, chat_id) == []


async def test_threshold_skips_when_below():
    conn = init_db(":memory:")
    chat_id = _chat_with_messages(conn, n=1)
    sch = Scheduler(conn, FakeLLM(), _settings(extract_message_threshold=50), FakeKB())
    reports = await sch.run_due(force=False)
    assert all(r.items_added == 0 for r in reports)
    assert len(repo.unprocessed_messages(conn, chat_id)) == 1  # untouched


async def test_global_budget_blocks():
    conn = init_db(":memory:")
    chat_id = _chat_with_messages(conn, n=1)
    sch = Scheduler(conn, FakeLLM(), _settings(extract_budget_global=0), FakeKB())
    reports = await sch.run_due(force=True)
    assert reports == []  # budget exhausted before any chat ran
    assert len(repo.unprocessed_messages(conn, chat_id)) == 1


async def test_budget_resets_after_period():
    conn = init_db(":memory:")
    chat_id = _chat_with_messages(conn, n=1, base_id=10)
    t = {"now": 0.0}
    sch = Scheduler(
        conn, FakeLLM(), _settings(extract_budget_global=1, budget_period_seconds=100), FakeKB(),
        clock=lambda: t["now"],
    )
    assert any(r.items_added >= 1 for r in await sch.run_due(force=True))  # first run spends budget

    repo.add_message(
        conn, chat_id=chat_id, tg_message_id=20, tg_user_id=1, text="we decided Y",
        reply_to=None, ts="2026-06-17T10:05:00",
    )
    assert await sch.run_due(force=True) == []  # budget exhausted this period
    assert len(repo.unprocessed_messages(conn, chat_id)) == 1

    t["now"] = 200.0  # past the budget period
    await sch.run_due(force=True)
    assert repo.unprocessed_messages(conn, chat_id) == []  # budget reset, processed
