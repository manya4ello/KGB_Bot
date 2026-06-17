import json

import pytest

from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db
from secretary_bot.pipeline.import_export import (
    import_export_file,
    import_messages,
    parse_export,
)


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def _export():
    return {
        "id": 555,
        "name": "Team",
        "messages": [
            {"id": 1, "type": "message", "date": "2026-06-17T10:00:00", "from_id": "user100", "text": "we decided X"},
            {"id": 2, "type": "message", "date": "2026-06-17T10:01:00", "from_id": "user101", "text": [{"type": "bold", "text": "Idea: "}, "cache it"]},
            {"id": 3, "type": "service", "date": "2026-06-17T10:02:00", "action": "pin"},
            {"id": 4, "type": "message", "date": "2026-06-17T10:03:00", "from_id": "channel999", "text": "from channel"},
            {"id": 5, "type": "message", "date": "2026-06-17T10:04:00", "from_id": "user100", "text": "   "},
        ],
    }


def test_parse_export():
    chat_id, name, msgs = parse_export(_export())
    assert chat_id == 555
    assert name == "Team"
    assert [m["tg_message_id"] for m in msgs] == [1, 2, 4]  # service + empty skipped
    m2 = next(m for m in msgs if m["tg_message_id"] == 2)
    assert m2["text"] == "Idea: cache it"
    assert m2["tg_user_id"] == 101
    m4 = next(m for m in msgs if m["tg_message_id"] == 4)
    assert m4["tg_user_id"] is None  # channel sender -> no user id


def test_import_messages_idempotent_and_optout(conn):
    chat_id = repo.upsert_chat(conn, 555, "Team")
    _, _, msgs = parse_export(_export())
    assert import_messages(conn, chat_id, msgs) == 3
    assert import_messages(conn, chat_id, msgs) == 0  # idempotent
    # opted-out user's future message is skipped
    repo.add_optout(conn, 100, chat_id=chat_id)
    extra = [{"tg_message_id": 9, "tg_user_id": 100, "text": "secret", "reply_to": None, "ts": "t"}]
    assert import_messages(conn, chat_id, extra) == 0


def test_import_export_file_binds_and_imports(conn, tmp_path):
    repo.create_project(conn, "team", "Team")
    path = tmp_path / "result.json"
    path.write_text(json.dumps(_export()), encoding="utf-8")
    res = import_export_file(conn, str(path), project_slug="team")
    assert res["imported"] == 3
    assert repo.is_chat_sanctioned(conn, res["chat_id"]) is True


def test_import_unknown_project_raises(conn, tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(_export()), encoding="utf-8")
    with pytest.raises(ValueError):
        import_export_file(conn, str(path), project_slug="missing")
