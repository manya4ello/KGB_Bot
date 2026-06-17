from secretary_bot.db.database import apply_schema, connect, init_db

EXPECTED_TABLES = {
    "projects",
    "chats",
    "project_chats",
    "users",
    "whitelist",
    "optouts",
    "messages",
    "memberships",
    "project_grants",
    "knowledge_items",
    "item_sources",
}


def _tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_init_creates_all_tables():
    conn = init_db(":memory:")
    assert EXPECTED_TABLES <= _tables(conn)


def test_apply_schema_is_idempotent():
    conn = connect(":memory:")
    apply_schema(conn)
    apply_schema(conn)  # must not raise on existing tables
    assert "messages" in _tables(conn)


def test_migration_adds_whitelist_note_column():
    conn = connect(":memory:")
    # Simulate an old DB whose whitelist table predates the `note` column.
    conn.executescript(
        "CREATE TABLE whitelist (id INTEGER PRIMARY KEY, tg_user_id INTEGER UNIQUE, is_admin INTEGER DEFAULT 0);"
    )
    conn.commit()
    apply_schema(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(whitelist)").fetchall()]
    assert "note" in cols


def test_file_db_creates_parent_dirs(tmp_path):
    db = tmp_path / "nested" / "dir" / "secretary.db"
    conn = init_db(str(db))
    assert db.exists()
    assert "knowledge_items" in _tables(conn)
