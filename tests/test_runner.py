import pytest

from secretary_bot.config import Settings
from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db
from secretary_bot.pipeline.runner import run_extraction_for_chat
from secretary_bot.telegram import admin


class FakeLLM:
    """Triage returns `signal`; extract returns one decision citing tg id 10."""

    def __init__(self, signal=True):
        self.signal = signal

    def complete_json(self, model, system, user):
        if "фильтр шума" in system:  # triage system prompt
            return {"has_signal": self.signal, "categories": ["decision"]}
        return {
            "items": [
                {
                    "type": "decision",
                    "statement": "Use SQLite",
                    "rationale": "simple",
                    "participants": ["1"],
                    "source_message_ids": [10],
                    "confidence": 0.9,
                }
            ]
        }

    def chat(self, model, system, user):  # pragma: no cover
        raise NotImplementedError

    def embed(self, texts, model):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeKB:
    def __init__(self):
        self.synced = None

    def sync(self, files, message, *, push=False):
        self.synced = (files, message, push)
        return True


def _settings(**over):
    return Settings(_env_file=None, telegram_bot_token="x", openai_api_key="y", **over)


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def _sanctioned_chat_with_message(conn, tg_chat_id=100, tg_message_id=10):
    admin.create_project(conn, "proj", "Proj")
    _, chat_id = admin.bind_chat(conn, tg_chat_id, "proj", "Chat")
    repo.add_message(
        conn,
        chat_id=chat_id,
        tg_message_id=tg_message_id,
        tg_user_id=1,
        text="we decided to use SQLite",
        reply_to=None,
        ts="2026-06-17T10:00:00",
    )
    return chat_id


def test_full_pass_extracts_persists_and_syncs(conn):
    chat_id = _sanctioned_chat_with_message(conn)
    kb = FakeKB()
    report = run_extraction_for_chat(conn, FakeLLM(signal=True), _settings(), kb, chat_id=chat_id)

    assert report.items_added == 1
    assert report.windows_with_signal == 1
    assert report.committed is True
    # persisted with source mapping
    items = repo.active_items(conn, repo.project_for_chat(conn, chat_id))
    assert len(items) == 1
    assert repo.item_source_messages(conn, int(items[0]["id"]))  # mapped to a db message id
    # messages marked processed
    assert repo.unprocessed_messages(conn, chat_id) == []
    # KB received rendered files containing the statement
    files, _, _ = kb.synced
    assert any("Use SQLite" in content for content in files.values())


def test_noise_window_produces_no_items(conn):
    chat_id = _sanctioned_chat_with_message(conn)
    report = run_extraction_for_chat(conn, FakeLLM(signal=False), _settings(), FakeKB(), chat_id=chat_id)
    assert report.items_added == 0
    assert report.windows_with_signal == 0


def test_unsanctioned_chat_skipped(conn):
    chat_id = repo.upsert_chat(conn, 100, "Unbound")  # registered, not bound
    report = run_extraction_for_chat(conn, FakeLLM(), _settings(), FakeKB(), chat_id=chat_id)
    assert report.skipped is True
    assert report.reason == "unsanctioned"


def test_no_messages_skipped(conn):
    admin.create_project(conn, "proj", "Proj")
    _, chat_id = admin.bind_chat(conn, 100, "proj")
    report = run_extraction_for_chat(conn, FakeLLM(), _settings(), FakeKB(), chat_id=chat_id)
    assert report.skipped is True
    assert report.reason == "no_new_messages"


def test_budget_cap_flags_over_budget(conn):
    admin.create_project(conn, "proj", "Proj")
    _, chat_id = admin.bind_chat(conn, 100, "proj")
    for mid in (10, 11):
        repo.add_message(
            conn, chat_id=chat_id, tg_message_id=mid, tg_user_id=1, text="we decided X", reply_to=None, ts="2026-06-17T10:00:00"
        )
    report = run_extraction_for_chat(
        conn, FakeLLM(signal=False), _settings(extract_budget_per_chat=1), FakeKB(), chat_id=chat_id
    )
    assert report.over_budget is True
    # only one message consumed this run; the other remains unprocessed
    assert len(repo.unprocessed_messages(conn, chat_id)) == 1
