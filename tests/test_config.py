import pytest
from pydantic import ValidationError

from secretary_bot.config import Settings


def test_loads_with_required_fields():
    s = Settings(_env_file=None, telegram_bot_token="tok", openai_api_key="key")
    assert s.telegram_bot_token == "tok"
    assert s.openai_api_key == "key"
    # sane defaults
    assert s.openai_base_url.startswith("https://")
    assert s.llm_embed_model
    assert 0 < s.dup_similarity_threshold <= 1


def test_missing_required_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "from-env")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("EXTRACT_MESSAGE_THRESHOLD", "7")
    s = Settings(_env_file=None)
    assert s.telegram_bot_token == "from-env"
    assert s.extract_message_threshold == 7
