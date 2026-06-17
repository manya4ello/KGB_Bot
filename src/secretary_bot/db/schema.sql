-- SQLite schema (idempotent). Mirrors the ERD in docs/plans/.
-- SQLite is the source of truth for rebuilding the vector index (KTD4).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    slug  TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_chat_id INTEGER NOT NULL UNIQUE,
    title      TEXT,
    joined_at  TEXT
);

-- A chat belongs to at most one project (one chat = one project, default).
CREATE TABLE IF NOT EXISTS project_chats (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chat_id    INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, chat_id),
    UNIQUE (chat_id)
);

CREATE TABLE IF NOT EXISTS users (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER NOT NULL UNIQUE,
    username  TEXT
);

CREATE TABLE IF NOT EXISTS whitelist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER NOT NULL UNIQUE,
    is_admin   INTEGER NOT NULL DEFAULT 0,
    note       TEXT
);

-- Per-user / per-chat opt-out (B5). chat_id NULL = global opt-out for the user.
CREATE TABLE IF NOT EXISTS optouts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER NOT NULL,
    chat_id    INTEGER,
    ts         TEXT,
    UNIQUE (tg_user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    tg_message_id INTEGER NOT NULL,
    tg_user_id    INTEGER,
    text          TEXT,
    reply_to      INTEGER,
    ts            TEXT,
    processed     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (chat_id, tg_message_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_processed ON messages (chat_id, processed);

-- Membership cache (KTD6). source: 'observed' | 'checked' | 'manual'.
CREATE TABLE IF NOT EXISTS memberships (
    chat_id    INTEGER NOT NULL,
    tg_user_id INTEGER NOT NULL,
    is_member  INTEGER NOT NULL DEFAULT 1,
    checked_at TEXT,
    source     TEXT,
    PRIMARY KEY (chat_id, tg_user_id)
);

-- Admin-granted project access (KTD6 fallback).
CREATE TABLE IF NOT EXISTS project_grants (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    tg_user_id INTEGER NOT NULL,
    granted_by INTEGER,
    ts         TEXT,
    PRIMARY KEY (project_id, tg_user_id)
);

-- type: idea | decision | argument (v1). status: active | superseded.
CREATE TABLE IF NOT EXISTS knowledge_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type          TEXT NOT NULL,
    statement     TEXT NOT NULL,
    rationale     TEXT,
    participants  TEXT,
    confidence    REAL,
    status        TEXT NOT NULL DEFAULT 'active',
    superseded_by INTEGER REFERENCES knowledge_items(id),
    content_hash  TEXT,
    created_at    TEXT,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_project_status ON knowledge_items (project_id, status);

CREATE TABLE IF NOT EXISTS item_sources (
    item_id    INTEGER NOT NULL REFERENCES knowledge_items(id) ON DELETE CASCADE,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, message_id)
);

-- Derived vector index (U10). Embeddings stored as JSON; rebuildable from
-- knowledge_items (KTD4). Cosine search is done in Python (small scale).
CREATE TABLE IF NOT EXISTS item_vectors (
    item_id    INTEGER PRIMARY KEY REFERENCES knowledge_items(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL,
    vector     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_item_vectors_project ON item_vectors (project_id, status);
