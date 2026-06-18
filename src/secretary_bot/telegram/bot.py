"""aiogram wiring (U2 + U4 + runextract). Thin layer over the logic modules.

Command handlers (opt-out, admin) are registered before the broad group
message handler so they win dispatch; ingest catches everything else.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message

from ..config import Settings
from ..db import repositories as repo
from ..logging import get_logger
from ..qa.answer import answer_question
from . import access, admin, ingest
from .commands import help_text

log = get_logger(__name__)

_JOINED_STATUSES = {"member", "administrator", "creator"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_chat_id(conn: sqlite3.Connection, tg_chat_id: int, is_private: bool) -> int | None:
    if is_private:
        return None
    chat = repo.get_chat_by_tg(conn, tg_chat_id)
    return int(chat["id"]) if chat else None


def _make_member_check(bot: Bot):
    async def check(tg_chat_id: int, user_id: int) -> bool:
        try:
            m = await bot.get_chat_member(tg_chat_id, user_id)
        except Exception:
            return False
        if m.status in ("creator", "administrator", "member"):
            return True
        if m.status == "restricted":
            return bool(getattr(m, "is_member", False))
        return False

    return check


def build_dispatcher(
    conn: sqlite3.Connection,
    settings: Settings,
    llm=None,
    scheduler=None,
    bot_username: str | None = None,
) -> Dispatcher:
    router = Router()

    @router.my_chat_member()
    async def on_my_chat_member(event: ChatMemberUpdated, bot: Bot) -> None:
        if event.new_chat_member.status in _JOINED_STATUSES:
            ingest.register_chat(conn, event.chat.id, event.chat.title, ts=_now_iso())
            log.info("Added to chat %s (%s)", event.chat.id, event.chat.title)
            try:
                await bot.send_message(event.chat.id, ingest.ANNOUNCE_TEXT)
            except Exception:  # pragma: no cover - network/permission issues
                log.warning("Could not post announce in chat %s", event.chat.id)

    @router.message(Command("optout"))
    async def cmd_optout(message: Message) -> None:
        if not message.from_user:
            return
        chat_id = _db_chat_id(conn, message.chat.id, message.chat.type == "private")
        ingest.opt_out(conn, message.from_user.id, chat_id=chat_id, ts=_now_iso())
        scope = "во всех чатах" if chat_id is None else "в этом чате"
        await message.reply(f"Готово — ваши сообщения {scope} больше не учитываются. Вернуть: /optin")

    @router.message(Command("optin"))
    async def cmd_optin(message: Message) -> None:
        if not message.from_user:
            return
        chat_id = _db_chat_id(conn, message.chat.id, message.chat.type == "private")
        ingest.opt_in(conn, message.from_user.id, chat_id=chat_id)
        await message.reply("Готово — ваши сообщения снова учитываются.")

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        is_admin = bool(message.from_user) and repo.is_admin(conn, message.from_user.id)
        await message.reply(help_text(is_admin))

    # Admin commands (and /runextract) — registered before the group catch-all.
    run_extract = None
    if scheduler is not None:

        async def run_extract() -> str:  # noqa: A001 - intentional local callback
            reports = await scheduler.run_due(force=True)
            processed = [r for r in reports if not r.skipped]
            total = sum(r.items_added for r in reports)
            merged = sum(r.items_merged for r in reports)
            return (
                f"Готово. Чатов: {len(processed)}, новых элементов: {total}, объединено: {merged}."
            )

    admin.register(router, conn, settings, run_extract)

    @router.message(F.chat.type == "private", F.text)
    async def on_private_query(message: Message, bot: Bot) -> None:
        text = message.text or ""
        if text.startswith("/"):
            return  # commands are handled by their own handlers
        user = message.from_user
        if not user or not access.is_allowed(conn, user.id) or llm is None:
            return  # non-whitelisted users are ignored entirely (KTD6)
        if access.is_superadmin(settings, user.id):
            projects = access.all_project_ids(conn)  # super-admin sees everything
        else:
            projects = await access.accessible_projects(
                conn, _make_member_check(bot), user.id, ttl_seconds=settings.membership_ttl_seconds
            )
        res = answer_question(conn, llm, settings, query=text, project_ids=projects)
        await message.reply(res["answer"])

    if bot_username:
        mention = f"@{bot_username}"

        @router.message(F.chat.type.in_({"group", "supergroup"}), F.text.contains(mention))
        async def on_mention(message: Message) -> None:
            user = message.from_user
            if not user or not access.is_allowed(conn, user.id) or llm is None:
                return
            pid = access.project_for_tg_chat(conn, message.chat.id)
            if pid is None:
                return  # chat not bound to a project
            query = (message.text or "").replace(mention, " ").strip()
            res = answer_question(conn, llm, settings, query=query, project_ids={pid})
            await message.reply(res["answer"])

    @router.message(F.chat.type.in_({"group", "supergroup"}))
    async def on_group_message(message: Message) -> None:
        ingest.handle_incoming(
            conn,
            tg_chat_id=message.chat.id,
            chat_title=message.chat.title,
            tg_message_id=message.message_id,
            tg_user_id=message.from_user.id if message.from_user else None,
            username=message.from_user.username if message.from_user else None,
            text=message.text or message.caption,
            reply_to=message.reply_to_message.message_id if message.reply_to_message else None,
            ts=message.date.isoformat() if message.date else _now_iso(),
        )

    dp = Dispatcher()
    dp.include_router(router)
    return dp
