import pytest

from secretary_bot.pipeline.extract import extract_window


class FakeLLM:
    def __init__(self, response=None, raises=False):
        self.response = response
        self.raises = raises

    def complete_json(self, model, system, user):
        if self.raises:
            raise ValueError("bad json")
        return self.response

    def chat(self, model, system, user):  # pragma: no cover
        raise NotImplementedError

    def embed(self, texts, model):  # pragma: no cover
        raise NotImplementedError


def _window():
    return [{"tg_message_id": 5, "tg_user_id": 1, "text": "let's go with SQLite", "reply_to": None, "ts": "t"}]


def test_extracts_decision():
    llm = FakeLLM({"items": [
        {"type": "decision", "statement": "Use SQLite", "rationale": "simple", "participants": ["1"], "source_message_ids": [5], "confidence": 0.9}
    ]})
    items = extract_window(llm, "m", _window(), confidence_threshold=0.5)
    assert len(items) == 1
    assert items[0].type == "decision"
    assert items[0].source_message_ids == [5]


def test_multiple_types_kept():
    llm = FakeLLM({"items": [
        {"type": "idea", "statement": "Try caching", "confidence": 0.8},
        {"type": "argument", "statement": "It reduces latency", "confidence": 0.7},
    ]})
    items = extract_window(llm, "m", _window())
    assert {i.type for i in items} == {"idea", "argument"}


def test_invalid_type_dropped():
    llm = FakeLLM({"items": [{"type": "question", "statement": "what now?", "confidence": 0.9}]})
    assert extract_window(llm, "m", _window()) == []


def test_low_confidence_dropped():
    llm = FakeLLM({"items": [{"type": "decision", "statement": "X", "confidence": 0.2}]})
    assert extract_window(llm, "m", _window(), confidence_threshold=0.5) == []


def test_empty_statement_dropped():
    llm = FakeLLM({"items": [{"type": "idea", "statement": "  ", "confidence": 0.9}]})
    assert extract_window(llm, "m", _window()) == []


def test_malformed_payload_returns_empty():
    assert extract_window(FakeLLM({"items": "nope"}), "m", _window()) == []
    assert extract_window(FakeLLM({}), "m", _window()) == []


def test_llm_exception_returns_empty():
    assert extract_window(FakeLLM(raises=True), "m", _window()) == []
