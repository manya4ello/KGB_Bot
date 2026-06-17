"""Entrypoint: run the bot (polling)."""

from __future__ import annotations

import asyncio

from aiogram import Bot

from .config import get_settings
from .db.database import init_db
from .knowledge.storage import GitKB
from .llm.client import LLMClient
from .logging import get_logger, setup_logging
from .pipeline.scheduler import Scheduler
from .telegram.admin import bootstrap_admin
from .telegram.bot import build_dispatcher
from .telegram.commands import set_bot_commands

log = get_logger(__name__)


async def _amain() -> None:
    setup_logging()
    settings = get_settings()
    conn = init_db(settings.db_path)
    bootstrap_admin(conn, settings.admin_user_id)

    llm = LLMClient.from_settings(settings)
    kb = GitKB(
        settings.kb_local_path,
        settings.kb_repo_url,
        deploy_key_path=settings.kb_repo_deploy_key_path,
    )
    scheduler = Scheduler(conn, llm, settings, kb)

    bot = Bot(settings.telegram_bot_token)
    me = await bot.get_me()
    dp = build_dispatcher(conn, settings, llm=llm, scheduler=scheduler, bot_username=me.username)
    await set_bot_commands(bot, settings)
    asyncio.create_task(scheduler.loop())
    log.info("Starting polling as @%s (scan every %ss)", me.username, settings.scan_interval_seconds)
    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
