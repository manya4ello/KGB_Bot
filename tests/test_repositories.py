import pytest

from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def test_upsert_chat_idempotent(conn):
    a = repo.upsert_chat(conn, 100, "A")
    b = repo.upsert_chat(conn, 100, "A renamed")
    assert a == b
    assert repo.get_chat_by_tg(conn, 100)["title"] == "A renamed"


def test_upsert_user_idempotent(conn):
    a = repo.upsert_user(conn, 7, "bob")
    b = repo.upsert_user(conn, 7, None)
    assert a == b


def test_bind_and_sanctioned(conn):
    chat_id = repo.upsert_chat(conn, 100, "A")
    assert repo.is_chat_sanctioned(conn, chat_id) is False
    pid = repo.create_project(conn, "proj", "Proj")
    repo.bind_chat_to_project(conn, pid, chat_id)
    assert repo.is_chat_sanctioned(conn, chat_id) is True
    assert repo.project_for_chat(conn, chat_id) == pid
    assert repo.chats_in_project(conn, pid) == [chat_id]


def test_one_chat_one_project(conn):
    chat_id = repo.upsert_chat(conn, 100, "A")
    p1 = repo.create_project(conn, "p1", "P1")
    p2 = repo.create_project(conn, "p2", "P2")
    repo.bind_chat_to_project(conn, p1, chat_id)
    repo.bind_chat_to_project(conn, p2, chat_id)  # re-binding moves the chat
    assert repo.project_for_chat(conn, chat_id) == p2


def test_whitelist_and_admin(conn):
    assert repo.is_whitelisted(conn, 7) is False
    repo.add_to_whitelist(conn, 7, is_admin=True)
    assert repo.is_whitelisted(conn, 7) is True
    assert repo.is_admin(conn, 7) is True
    repo.add_to_whitelist(conn, 7, is_admin=False)  # demote
    assert repo.is_admin(conn, 7) is False
    repo.remove_from_whitelist(conn, 7)
    assert repo.is_whitelisted(conn, 7) is False


def test_optout_global_and_per_chat(conn):
    assert repo.is_opted_out(conn, 7, 1) is False
    repo.add_optout(conn, 7, chat_id=1)
    assert repo.is_opted_out(conn, 7, 1) is True
    assert repo.is_opted_out(conn, 7, 2) is False
    repo.add_optout(conn, 8, chat_id=None)  # global
    assert repo.is_opted_out(conn, 8, 99) is True
    repo.remove_optout(conn, 7, chat_id=1)
    assert repo.is_opted_out(conn, 7, 1) is False


def test_add_message_idempotent(conn):
    chat_id = repo.upsert_chat(conn, 100, "A")
    m1 = repo.add_message(
        conn, chat_id=chat_id, tg_message_id=5, tg_user_id=7, text="hi", reply_to=None, ts="t"
    )
    m2 = repo.add_message(
        conn, chat_id=chat_id, tg_message_id=5, tg_user_id=7, text="hi", reply_to=None, ts="t"
    )
    assert isinstance(m1, int)
    assert m2 is None  # duplicate (chat_id, tg_message_id)
    assert len(repo.unprocessed_messages(conn, chat_id)) == 1


def test_membership_record_and_read(conn):
    repo.record_membership(conn, 1, 7, is_member=True, source="observed", checked_at="t")
    row = repo.get_membership(conn, 1, 7)
    assert row["is_member"] == 1
    assert row["source"] == "observed"
