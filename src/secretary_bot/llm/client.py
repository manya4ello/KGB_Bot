"""LLM access via an OpenAI-compatible client (KTD8 / KTD8a).

Four roles share one client: triage, extraction, answering, embeddings.
Switching to OpenRouter is a base_url + key change (set in config). The
network-touching methods are thin; business logic (triage/extract/answer)
lives in the pipeline modules and is tested against the ``SupportsLLM``
protocol with a fake, so no test hits the network.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from ..config import Settings


@runtime_checkable
class SupportsLLM(Protocol):
    """Minimal surface the pipeline depends on (lets tests inject a fake)."""

    def complete_json(self, model: str, system: str, user: str) -> dict: ...
    def chat(self, model: str, system: str, user: str) -> str: ...
    def embed(self, texts: list[str], model: str) -> list[list[float]]: ...


class LLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        triage_model: str,
        extract_model: str,
        answer_model: str,
        embed_model: str,
    ) -> None:
        # Imported lazily so the package imports without the SDK present in
        # contexts that only use the protocol (and to keep import time low).
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.triage_model = triage_model
        self.extract_model = extract_model
        self.answer_model = answer_model
        self.embed_model = embed_model

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMClient":
        return cls(
            settings.openai_api_key,
            settings.openai_base_url,
            triage_model=settings.llm_triage_model,
            extract_model=settings.llm_extract_model,
            answer_model=settings.llm_answer_model,
            embed_model=settings.llm_embed_model,
        )

    def complete_json(self, model: str, system: str, user: str) -> dict:
        resp = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content or "{}")

    def chat(self, model: str, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        return resp.choices[0].message.content or ""

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        resp = self._client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]
