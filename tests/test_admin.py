import pytest

from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db
from secretary_bot.telegram import admin


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def test_create_and_bind(conn):
    admin.create_project(conn, "proj", "Proj")
    assert repo.get_project_by_slug(conn, "proj") is not None
    pid, chat_id = admin.bind_chat(conn, 100, "proj", "Chat A")
    assert repo.is_chat_sanctioned(conn, chat_id) is True
    assert repo.project_for_chat(conn, chat_id) == pid


def test_bind_unknown_project_raises(conn):
    with pytest.raises(ValueError):
        admin.bind_chat(conn, 100, "missing")


def test_whitelist_and_admin(conn):
    admin.whitelist_add(conn, 7, is_admin=True)
    assert repo.is_admin(conn, 7) is True
    admin.whitelist_remove(conn, 7)
    assert repo.is_whitelisted(conn, 7) is False


def test_whitelist_add_with_note(conn):
    admin.whitelist_add(conn, 7, is_admin=False, note="Олег, PM")
    rows = repo.list_whitelist(conn)
    assert len(rows) == 1
    assert rows[0]["note"] == "Олег, PM"
    # re-adding without a note keeps the existing one
    admin.whitelist_add(conn, 7, is_admin=True)
    assert repo.list_whitelist(conn)[0]["note"] == "Олег, PM"
    assert repo.is_admin(conn, 7) is True


def test_grant(conn):
    admin.create_project(conn, "proj", "Proj")
    pid = admin.grant(conn, "proj", 42, by=1)
    assert repo.has_project_grant(conn, pid, 42) is True


def test_grant_unknown_project_raises(conn):
    with pytest.raises(ValueError):
        admin.grant(conn, "nope", 42)


def test_add_note(conn):
    admin.create_project(conn, "team", "Team")
    mid = admin.add_note(conn, "team", "Решение: используем X.", author_id=1, ts="t")
    assert isinstance(mid, int)
    pid = repo.get_project_by_slug(conn, "team")["id"]
    chats = repo.chats_in_project(conn, pid)
    assert len(chats) == 1  # synthetic notes chat
    assert len(repo.unprocessed_messages(conn, chats[0])) == 1
    admin.add_note(conn, "team", "Ещё заметка", author_id=1, ts="t")
    assert len(repo.unprocessed_messages(conn, chats[0])) == 2  # id incremented, no clash


def test_add_note_unknown_project_raises(conn):
    with pytest.raises(ValueError):
        admin.add_note(conn, "nope", "x")


def test_decode_text_file_utf8_and_cp1251():
    assert admin.decode_text_file("привет".encode("utf-8")) == "привет"
    assert admin.decode_text_file("привет".encode("cp1251")) == "привет"


def test_decode_text_file_rejects_binary():
    with pytest.raises(ValueError):
        admin.decode_text_file(b"%PDF-1.4\x00\x00\x01binary")


def test_status_counts(conn):
    admin.create_project(conn, "proj", "Proj")
    admin.bind_chat(conn, 100, "proj")
    s = admin.status(conn)
    assert s["projects"] == 1
    assert s["chats_bound"] == 1


def test_bootstrap_admin(conn):
    admin.bootstrap_admin(conn, 999)
    assert repo.is_admin(conn, 999) is True
    admin.bootstrap_admin(conn, None)  # no-op, must not raise
