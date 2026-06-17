import re

from aiogram.types import BotCommand

from secretary_bot.telegram.commands import ADMIN, PUBLIC, bot_commands, help_text


def test_admin_includes_public_commands():
    public = {c for c, _, _ in PUBLIC}
    admin = {c for c, _, _ in ADMIN}
    assert public <= admin
    assert "newproject" in admin and "newproject" not in public


def test_command_names_are_valid_for_telegram():
    for c, _, _ in ADMIN:
        assert re.fullmatch(r"[a-z0-9_]{1,32}", c), c


def test_bot_commands_returns_valid_objects():
    cmds = bot_commands(admin=True)
    assert all(isinstance(x, BotCommand) for x in cmds)
    assert any(x.command == "runextract" for x in cmds)
    assert all(1 <= len(x.description) <= 256 for x in cmds)


def test_help_text_respects_scope():
    assert "newproject" in help_text(True)
    assert "newproject" not in help_text(False)
    assert "/optout" in help_text(False)


def test_help_text_includes_guidance():
    admin = help_text(True)
    assert "slug" in admin  # concept explained
    assert "Проект" in admin and "Настройка" in admin
    assert "Как спросить" in help_text(False)  # users learn how to query


def test_help_text_within_telegram_limit():
    assert len(help_text(True)) <= 4096
    assert len(help_text(False)) <= 4096
