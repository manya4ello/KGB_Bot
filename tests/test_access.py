from datetime import datetime, timezone

from secretary_bot.db import repositories as repo
from secretary_bot.db.database import init_db
from secretary_bot.telegram import access


def _conn():
    return init_db(":memory:")


def _project_with_chat(conn, slug="p", tg_chat_id=100):
    pid = repo.create_project(conn, slug, slug.upper())
    chat_id = repo.upsert_chat(conn, tg_chat_id, "C")
    repo.bind_chat_to_project(conn, pid, chat_id)
    return pid, chat_id


def test_is_allowed_uses_whitelist():
    conn = _conn()
    assert access.is_allowed(conn, 7) is False
    repo.add_to_whitelist(conn, 7)
    assert access.is_allowed(conn, 7) is True


def test_project_for_tg_chat():
    conn = _conn()
    pid, _ = _project_with_chat(conn)
    assert access.project_for_tg_chat(conn, 100) == pid
    assert access.project_for_tg_chat(conn, 999) is None


async def test_membership_grants_project():
    conn = _conn()
    pid, _ = _project_with_chat(conn)

    async def check(c, u):
        return (c, u) == (100, 7)

    assert await access.accessible_projects(conn, check, 7) == {pid}


async def test_non_member_excluded():
    conn = _conn()
    _project_with_chat(conn)

    async def check(c, u):
        return False

    assert await access.accessible_projects(conn, check, 7) == set()


async def test_grant_opens_project_without_membership():
    conn = _conn()
    pid, _ = _project_with_chat(conn)
    repo.grant_project(conn, pid, 7)

    async def check(c, u):
        return False

    assert await access.accessible_projects(conn, check, 7) == {pid}


async def test_short_circuit_across_chats():
    conn = _conn()
    pid = repo.create_project(conn, "p", "P")
    c1 = repo.upsert_chat(conn, 100, "C1")
    c2 = repo.upsert_chat(conn, 200, "C2")
    repo.bind_chat_to_project(conn, pid, c1)
    repo.bind_chat_to_project(conn, pid, c2)

    async def check(c, u):
        return c == 200  # member only in the second chat

    assert await access.accessible_projects(conn, check, 7) == {pid}


async def test_fresh_cache_skips_check():
    conn = _conn()
    pid, chat_id = _project_with_chat(conn)
    now = datetime(2026, 6, 17, tzinfo=timezone.utc)
    repo.record_membership(conn, chat_id, 7, is_member=True, source="checked", checked_at=now.isoformat())
    calls = []

    async def check(c, u):
        calls.append(1)
        return False

    res = await access.accessible_projects(conn, check, 7, ttl_seconds=3600, now=now)
    assert res == {pid}
    assert calls == []  # served from cache, no API call
