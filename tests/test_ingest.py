import pytest

from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db
from secretary_bot.telegram import ingest
from secretary_bot.telegram.ingest import IngestResult


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def _sanctioned_chat(conn, tg_chat_id=100):
    chat_id = ingest.register_chat(conn, tg_chat_id, "A", ts="t0")
    pid = repo.create_project(conn, "proj", "Proj")
    repo.bind_chat_to_project(conn, pid, chat_id)
    return chat_id


def _count_messages(conn):
    return conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]


def test_unknown_chat_dropped(conn):
    res = ingest.handle_incoming(
        conn, tg_chat_id=999, tg_message_id=1, tg_user_id=7, text="hello", ts="t"
    )
    assert res is IngestResult.UNSANCTIONED
    assert _count_messages(conn) == 0


def test_registered_but_unbound_dropped(conn):
    ingest.register_chat(conn, 100, "A", ts="t0")  # registered, not bound
    res = ingest.handle_incoming(
        conn, tg_chat_id=100, tg_message_id=1, tg_user_id=7, text="hi", ts="t"
    )
    assert res is IngestResult.UNSANCTIONED
    assert _count_messages(conn) == 0


def test_sanctioned_message_stored_with_membership(conn):
    chat_id = _sanctioned_chat(conn)
    res = ingest.handle_incoming(
        conn,
        tg_chat_id=100,
        tg_message_id=1,
        tg_user_id=7,
        username="bob",
        text="we decided to use SQLite",
        ts="t1",
    )
    assert res is IngestResult.STORED
    assert len(repo.unprocessed_messages(conn, chat_id)) == 1
    assert repo.get_membership(conn, chat_id, 7)["source"] == "observed"


def test_empty_text_skipped(conn):
    _sanctioned_chat(conn)
    res = ingest.handle_incoming(
        conn, tg_chat_id=100, tg_message_id=1, tg_user_id=7, text="   ", ts="t"
    )
    assert res is IngestResult.SKIPPED_EMPTY
    assert _count_messages(conn) == 0


def test_opted_out_user_dropped(conn):
    chat_id = _sanctioned_chat(conn)
    ingest.opt_out(conn, 7, chat_id=chat_id, ts="t")
    res = ingest.handle_incoming(
        conn, tg_chat_id=100, tg_message_id=1, tg_user_id=7, text="secret plan", ts="t"
    )
    assert res is IngestResult.OPTED_OUT
    assert _count_messages(conn) == 0


def test_duplicate_message(conn):
    _sanctioned_chat(conn)
    ingest.handle_incoming(conn, tg_chat_id=100, tg_message_id=1, tg_user_id=7, text="hi", ts="t")
    res = ingest.handle_incoming(
        conn, tg_chat_id=100, tg_message_id=1, tg_user_id=7, text="hi", ts="t"
    )
    assert res is IngestResult.DUPLICATE


def test_register_chat_sets_joined_at(conn):
    ingest.register_chat(conn, 100, "A", ts="t0")
    assert repo.get_chat_by_tg(conn, 100)["joined_at"] == "t0"
