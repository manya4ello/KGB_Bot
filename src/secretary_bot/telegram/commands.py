"""Bot command registry + Telegram command-menu setup (setMyCommands).

Public commands show to everyone (default scope); the full admin set shows only
in the admin's private chat (BotCommandScopeChat for ADMIN_USER_ID). The same
registry feeds /help.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from ..config import Settings
from ..logging import get_logger

log = get_logger(__name__)

# (command, short description for the menu, usage shown in /help)
# Available to any whitelisted user (feeding data + querying).
PUBLIC: list[tuple[str, str, str]] = [
    ("help", "Справка и как пользоваться", "/help"),
    ("optout", "Не учитывать мои сообщения", "/optout"),
    ("optin", "Снова учитывать мои сообщения", "/optin"),
    ("note", "Заметка/файл в проект", "/note <slug> <текст> (или приложите файл с подписью)"),
    ("import", "Импорт истории чата", "/import <slug> (приложить .json-экспорт)"),
]

ADMIN: list[tuple[str, str, str]] = PUBLIC + [
    ("newproject", "Создать проект", "/newproject <slug> <название>"),
    ("bindchat", "Привязать чат к проекту", "/bindchat <slug> [chat_id]"),
    ("whitelist_add", "Добавить в whitelist", "/whitelist_add <user_id> [admin] [имя/описание]"),
    ("whitelist_remove", "Убрать из whitelist", "/whitelist_remove <user_id>"),
    ("whitelist", "Показать whitelist", "/whitelist"),
    ("grant", "Выдать доступ к проекту", "/grant <slug> <user_id>"),
    ("runextract", "Запустить извлечение знаний", "/runextract"),
    ("status", "Статус бота", "/status"),
]


def bot_commands(admin: bool) -> list[BotCommand]:
    rows = ADMIN if admin else PUBLIC
    return [BotCommand(command=cmd, description=desc) for cmd, desc, _ in rows]


_INTRO = (
    "🤖 Я веду базу знаний команды: читаю сообщения рабочих чатов, извлекаю из "
    "обсуждений идеи, решения и аргументы и отвечаю на вопросы по ним — со ссылками "
    "на источники."
)

_HOW_TO_ASK = (
    "❓ Как спросить:\n"
    "• в личке — просто напишите вопрос, отвечу по проектам, к которым у вас есть доступ;\n"
    "• в чате — упомяните меня (@…) с вопросом, отвечу по проекту этого чата.\n"
    "Если в базе нет ответа — честно скажу «по этому в базе ничего нет», без выдумок."
)

_OPTOUT = "🔕 Приватность: /optout — не учитывать ваши сообщения, /optin — вернуть."

_CONCEPTS = (
    "📚 Понятия:\n"
    "• Чат — Telegram-группа, куда меня добавили.\n"
    "• Проект — единица знаний; к нему привязывают один или несколько чатов. "
    "Доступ — по проекту: кто состоит хотя бы в одном чате проекта (или кому выдан доступ) "
    "видит знания всего проекта.\n"
    "• slug — короткий идентификатор проекта: латиница в нижнем регистре, без пробелов "
    "(напр. marketing, product-team). У проекта есть человеческое название («Маркетинг Q3») "
    "и slug-ключ для команд; в репозитории проект лежит в projects/<slug>/."
)

_SETUP = (
    "🛠 Настройка (для админов):\n"
    "1) Создать проект: /newproject <slug> <название>\n"
    "   пример: /newproject marketing Маркетинг Q3\n"
    "2) Привязать чат к проекту — выполнить прямо в нужном чате: /bindchat <slug>\n"
    "   (после этого я начинаю собирать сообщения; до привязки — игнорирую чат)\n"
    "3) Дать команде пообщаться, затем извлечь знания: /runextract\n"
    "Доступ выдаётся автоматически участникам чатов проекта; вручную — /grant <slug> <user_id>."
)

_FEED = (
    "📥 Загрузить данные в проект (доступно всем из белого списка):\n"
    "• История чата: /import <slug> и приложите .json-экспорт "
    "(Telegram Desktop → Экспорт истории → формат JSON).\n"
    "• Заметка/документ: /note <slug> <текст> или приложите файл "
    "(.txt/.md/.pdf/.docx) с подписью /note <slug>.\n"
    "Проект (slug) должен уже существовать — создаёт его админ."
)


def _commands_block(rows: list[tuple[str, str, str]]) -> str:
    return "Команды:\n" + "\n".join(f"{usage} — {desc}" for _, desc, usage in rows)


def help_text(admin: bool) -> str:
    if admin:
        sections = [_INTRO, _CONCEPTS, _SETUP, _FEED, _HOW_TO_ASK, _OPTOUT, _commands_block(ADMIN)]
    else:
        sections = [_INTRO, _FEED, _HOW_TO_ASK, _OPTOUT, _commands_block(PUBLIC)]
    return "\n\n".join(sections)


async def set_bot_commands(bot: Bot, settings: Settings) -> None:
    """Register the command menu (setMyCommands) with scopes."""
    await bot.set_my_commands(bot_commands(admin=False), scope=BotCommandScopeDefault())
    if settings.admin_user_id:
        await bot.set_my_commands(
            bot_commands(admin=True),
            scope=BotCommandScopeChat(chat_id=settings.admin_user_id),
        )
    log.info("Bot command menu registered")
