"""Admin commands (U4): projects, chat binding, whitelist, grants, runextract.

Pure logic functions (testable without aiogram) plus a ``register`` helper that
wires them onto an aiogram router. Commands run in private chat and require an
admin (whitelist.is_admin), except ``/bindchat`` which may run inside the target
group. Non-admins are ignored silently.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..config import Settings
from ..db import repositories as repo
from ..documents import decode_text_file, extract_text  # noqa: F401 (re-export)
from ..logging import get_logger
from ..pipeline.import_export import import_export_file
from ..pipeline.segment import DEFAULT_TIME_GAP_SECONDS

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


MAX_DOC_BYTES = 20_000_000  # 20 MB — Telegram Bot API download ceiling
NOTE_CHUNK_CHARS = 4000  # split long notes/files into chunks of ~this size
_NOTE_CHUNK_GAP = DEFAULT_TIME_GAP_SECONDS + 60  # stagger ts so each chunk is its own window


def _chunk_text(text: str, max_chars: int = NOTE_CHUNK_CHARS) -> list[str]:
    """Split text into chunks <= max_chars, preferring paragraph boundaries."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        if current and len(current) + 2 + len(para) > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
        while len(current) > max_chars:  # a single oversized paragraph
            chunks.append(current[:max_chars])
            current = current[max_chars:]
    if current:
        chunks.append(current)
    return chunks


def _staggered_ts(ts: str | None, i: int) -> str | None:
    """Timestamp for chunk i, spaced past the window gap so chunks don't merge."""
    if i == 0:
        return ts
    base: datetime | None = None
    if ts:
        try:
            base = datetime.fromisoformat(ts)
        except ValueError:
            base = None
    if base is None:
        base = datetime.now(timezone.utc)
    return (base + timedelta(seconds=i * _NOTE_CHUNK_GAP)).isoformat()


# --------------------------------------------------------------------------- #
# Pure logic
# --------------------------------------------------------------------------- #


def create_project(conn: sqlite3.Connection, slug: str, title: str) -> int:
    return repo.create_project(conn, slug, title)


def bind_chat(
    conn: sqlite3.Connection, tg_chat_id: int, slug: str, title: str | None = None
) -> tuple[int, int]:
    project = repo.get_project_by_slug(conn, slug)
    if project is None:
        raise ValueError(f"project '{slug}' not found")
    chat_id = repo.upsert_chat(conn, tg_chat_id, title)
    repo.bind_chat_to_project(conn, int(project["id"]), chat_id)
    return int(project["id"]), chat_id


def whitelist_add(
    conn: sqlite3.Connection,
    tg_user_id: int,
    is_admin: bool = False,
    note: str | None = None,
) -> None:
    repo.add_to_whitelist(conn, tg_user_id, is_admin, note)


def whitelist_remove(conn: sqlite3.Connection, tg_user_id: int) -> None:
    repo.remove_from_whitelist(conn, tg_user_id)


# Synthetic chat id base for per-project notes (well above real Telegram ids).
NOTE_CHAT_BASE = 7_000_000_000_000


def add_note(
    conn: sqlite3.Connection,
    slug: str,
    text: str,
    *,
    author_id: int | None = None,
    ts: str | None = None,
) -> int | None:
    """Add a free-form note to a project via a synthetic per-project notes chat.

    The note flows through the normal pipeline on the next /runextract.
    """
    project = repo.get_project_by_slug(conn, slug)
    if project is None:
        raise ValueError(f"project '{slug}' not found")
    pid = int(project["id"])
    chat_id = repo.upsert_chat(conn, NOTE_CHAT_BASE + pid, f"[notes] {project['title']}")
    repo.bind_chat_to_project(conn, pid, chat_id)
    base_id = repo.next_synthetic_message_id(conn, chat_id)
    last_id = None
    for i, chunk in enumerate(_chunk_text(text)):
        last_id = repo.add_message(
            conn,
            chat_id=chat_id,
            tg_message_id=base_id + i,
            tg_user_id=author_id,
            text=chunk,
            reply_to=None,
            ts=_staggered_ts(ts, i),
        )
    return last_id


def grant(
    conn: sqlite3.Connection, slug: str, tg_user_id: int, by: int | None = None
) -> int:
    project = repo.get_project_by_slug(conn, slug)
    if project is None:
        raise ValueError(f"project '{slug}' not found")
    repo.grant_project(conn, int(project["id"]), tg_user_id, by, _now_iso())
    return int(project["id"])


def status(conn: sqlite3.Connection) -> dict[str, int]:
    def count(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    return {
        "projects": count("SELECT COUNT(*) FROM projects"),
        "chats_bound": count("SELECT COUNT(*) FROM project_chats"),
        "whitelist": count("SELECT COUNT(*) FROM whitelist"),
        "messages": count("SELECT COUNT(*) FROM messages"),
        "messages_unprocessed": count("SELECT COUNT(*) FROM messages WHERE processed = 0"),
        "knowledge_items": count("SELECT COUNT(*) FROM knowledge_items WHERE status = 'active'"),
    }


def bootstrap_admin(conn: sqlite3.Connection, admin_user_id: int | None) -> None:
    """Seed the first admin from config (U14) so the bot is operable on deploy."""
    if admin_user_id:
        repo.add_to_whitelist(conn, int(admin_user_id), is_admin=True, note="bootstrap")
        log.info("Bootstrapped admin %s", admin_user_id)


# --------------------------------------------------------------------------- #
# aiogram handlers
# --------------------------------------------------------------------------- #

RunExtractCb = Callable[[], Awaitable[str]]


def register(
    router: Router,
    conn: sqlite3.Connection,
    settings: Settings,
    run_extract: RunExtractCb | None = None,
) -> None:
    def _is_admin(message: Message) -> bool:
        return bool(message.from_user) and repo.is_admin(conn, message.from_user.id)

    def _private(message: Message) -> bool:
        return message.chat.type == "private"

    @router.message(Command("newproject"))
    async def cmd_newproject(message: Message, command: CommandObject) -> None:
        if not (_private(message) and _is_admin(message)):
            return
        args = (command.args or "").split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Использование: /newproject <slug> <название>")
            return
        slug, title = args[0], args[1]
        create_project(conn, slug, title)
        await message.reply(f"Проект `{slug}` создан.")

    @router.message(Command("bindchat"))
    async def cmd_bindchat(message: Message, command: CommandObject) -> None:
        # Allowed in the target group (admin) or in private with an explicit chat id.
        if not _is_admin(message):
            return
        parts = (command.args or "").split()
        if not parts:
            await message.reply("Использование: /bindchat <slug> [chat_id]")
            return
        slug = parts[0]
        if len(parts) >= 2:
            tg_chat_id = int(parts[1])
            title = None
        elif not _private(message):
            tg_chat_id = message.chat.id
            title = message.chat.title
        else:
            await message.reply("В личке укажите chat_id: /bindchat <slug> <chat_id>")
            return
        try:
            bind_chat(conn, tg_chat_id, slug, title)
        except ValueError as exc:
            await message.reply(str(exc))
            return
        await message.reply(f"Чат {tg_chat_id} привязан к проекту `{slug}`. Сбор включён.")

    @router.message(Command("whitelist_add"))
    async def cmd_wl_add(message: Message, command: CommandObject) -> None:
        if not (_private(message) and _is_admin(message)):
            return
        parts = (command.args or "").split()
        if not parts:
            await message.reply("Использование: /whitelist_add <user_id> [admin] [имя/описание]")
            return
        rest = parts[1:]
        is_admin_flag = bool(rest) and rest[0].lower() == "admin"
        if is_admin_flag:
            rest = rest[1:]
        note = " ".join(rest) or None
        whitelist_add(conn, int(parts[0]), is_admin_flag, note)
        tag = " (admin)" if is_admin_flag else ""
        label = f" — {note}" if note else ""
        await message.reply(f"Добавлен в whitelist: {parts[0]}{label}{tag}")

    @router.message(Command("whitelist_remove"))
    async def cmd_wl_remove(message: Message, command: CommandObject) -> None:
        if not (_private(message) and _is_admin(message)):
            return
        if not command.args:
            await message.reply("Использование: /whitelist_remove <user_id>")
            return
        whitelist_remove(conn, int(command.args.split()[0]))
        await message.reply("Удалён из whitelist.")

    @router.message(Command("whitelist"))
    async def cmd_wl_list(message: Message) -> None:
        if not (_private(message) and _is_admin(message)):
            return
        rows = repo.list_whitelist(conn)
        if not rows:
            await message.reply("Whitelist пуст.")
            return
        lines = []
        for r in rows:
            tag = " (admin)" if r["is_admin"] else ""
            note = f" — {r['note']}" if r["note"] else ""
            lines.append(f"{r['tg_user_id']}{note}{tag}")
        await message.reply("Whitelist:\n" + "\n".join(lines))

    @router.message(Command("grant"))
    async def cmd_grant(message: Message, command: CommandObject) -> None:
        if not (_private(message) and _is_admin(message)):
            return
        parts = (command.args or "").split()
        if len(parts) < 2:
            await message.reply("Использование: /grant <slug> <user_id>")
            return
        try:
            grant(conn, parts[0], int(parts[1]), by=message.from_user.id)
        except ValueError as exc:
            await message.reply(str(exc))
            return
        await message.reply(f"Доступ к проекту `{parts[0]}` выдан пользователю {parts[1]}.")

    @router.message(Command("note"), ~F.document)
    async def cmd_note(message: Message, command: CommandObject) -> None:
        if not (_private(message) and _is_admin(message)):
            return
        args = (command.args or "").split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Использование: /note <slug> <текст заметки>")
            return
        try:
            add_note(conn, args[0], args[1], author_id=message.from_user.id, ts=_now_iso())
        except ValueError as exc:
            await message.reply(str(exc))
            return
        await message.reply(f"Заметка добавлена в проект `{args[0]}`. Будет учтена при /runextract.")

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        if not (_private(message) and _is_admin(message)):
            return
        s = status(conn)
        lines = "\n".join(f"{k}: {v}" for k, v in s.items())
        await message.reply(f"Статус:\n{lines}")

    @router.message(Command("runextract"))
    async def cmd_runextract(message: Message) -> None:
        if not (_private(message) and _is_admin(message)):
            return
        if run_extract is None:
            await message.reply("Извлечение недоступно (LLM/KB не сконфигурированы).")
            return
        await message.reply("Запускаю извлечение…")
        summary = await run_extract()
        await message.reply(summary)

    async def _do_import(message: Message, slug: str, path: str) -> None:
        try:
            res = import_export_file(conn, path, project_slug=slug)
        except Exception as exc:  # bad json / unknown project / io
            await message.reply(f"Ошибка импорта: {exc}")
            return
        await message.reply(
            f"Импортировано {res['imported']} из {res['total']} сообщений "
            f"в проект `{slug}`. Запустите /runextract."
        )

    @router.message(Command("import"), ~F.document)
    async def cmd_import(message: Message, command: CommandObject) -> None:
        if not (_private(message) and _is_admin(message)):
            return
        args = (command.args or "").split()
        if len(args) < 2:
            await message.reply(
                "Пришлите .json-экспорт чата с подписью `/import <slug>`, "
                "либо `/import <slug> <путь на сервере>`."
            )
            return
        await _do_import(message, args[0], args[1])

    @router.message(F.document)
    async def on_document(message: Message, bot) -> None:
        # File sent in private with a command caption:
        #   /import <slug>  — Telegram JSON export
        #   /note   <slug>  — text file (.txt/.md/...) added to the project
        if not (_private(message) and _is_admin(message)):
            return
        parts = (message.caption or "").strip().split()
        if not parts or parts[0].lower() not in ("/import", "/note"):
            return
        if len(parts) < 2:
            await message.reply(f"Подпись к файлу: {parts[0]} <slug>")
            return
        cmd, slug = parts[0].lower(), parts[1]
        if message.document.file_size and message.document.file_size > MAX_DOC_BYTES:
            await message.reply(f"Файл слишком большой (макс. {MAX_DOC_BYTES // 1_000_000} МБ).")
            return
        dest = f"/tmp/kgb_{message.document.file_unique_id}"
        try:
            try:
                await bot.download(message.document, destination=dest)
            except Exception:
                await message.reply("Не удалось скачать файл (для Bot API лимит ~20 МБ).")
                return
            if cmd == "/import":
                await _do_import(message, slug, dest)
                return
            with open(dest, "rb") as fh:
                raw = fh.read()
            try:
                text = extract_text(message.document.file_name or "", raw).strip()
            except ValueError as exc:
                await message.reply(f"Не удалось прочитать файл: {exc}")
                return
            if not text:
                await message.reply("Файл пустой.")
                return
            try:
                add_note(conn, slug, text, author_id=message.from_user.id, ts=_now_iso())
            except ValueError as exc:
                await message.reply(str(exc))
                return
            await message.reply(
                f"Файл загружен в проект `{slug}` ({len(text)} символов). Запустите /runextract."
            )
        finally:
            try:
                os.remove(dest)
            except OSError:
                pass
