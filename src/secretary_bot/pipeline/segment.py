"""Conversation segmentation (U6, KTD3).

The unit of extraction is a coherent *window* of conversation, not a single
message. Windows are split on time gaps but kept together across reply chains.

Messages are mappings with keys: ``tg_message_id``, ``tg_user_id``,
``text``, ``reply_to``, ``ts`` (ISO-8601 string or None). sqlite3.Row works.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

DEFAULT_TIME_GAP_SECONDS = 1800  # 30 min

# Delimiters that fence untrusted chat content inside LLM prompts (anti-injection).
UNTRUSTED_OPEN = "<<<UNTRUSTED_CHAT_CONTENT>>>"
UNTRUSTED_CLOSE = "<<<END_UNTRUSTED_CHAT_CONTENT>>>"

Window = list[Mapping[str, Any]]


def _parse_ts(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts))
    except ValueError:
        return None


def segment_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    time_gap_seconds: int = DEFAULT_TIME_GAP_SECONDS,
) -> list[Window]:
    """Split an ordered message list into conversation windows.

    A new window starts when the time gap to the previous message exceeds
    ``time_gap_seconds`` AND the message is not a reply into the current window.
    """
    windows: list[Window] = []
    current: Window = []
    current_ids: set[int] = set()
    prev_ts: datetime | None = None

    for m in messages:
        ts = _parse_ts(m["ts"])
        reply_to = m["reply_to"]
        gap_break = (
            prev_ts is not None
            and ts is not None
            and (ts - prev_ts).total_seconds() > time_gap_seconds
        )
        reply_links = reply_to is not None and reply_to in current_ids

        if current and gap_break and not reply_links:
            windows.append(current)
            current = []
            current_ids = set()

        current.append(m)
        current_ids.add(m["tg_message_id"])
        if ts is not None:
            prev_ts = ts

    if current:
        windows.append(current)
    return windows


def render_window(window: Window) -> str:
    """Render a window as a delimited, untrusted-content block for the LLM.

    The fences let the system prompt instruct the model to treat everything
    between them as data, never as instructions (anti prompt-injection).
    """
    lines = []
    for m in window:
        who = m["tg_user_id"] if m["tg_user_id"] is not None else "?"
        text = (m["text"] or "").replace("\n", " ").strip()
        lines.append(f"[{m['tg_message_id']}] user {who}: {text}")
    body = "\n".join(lines)
    return f"{UNTRUSTED_OPEN}\n{body}\n{UNTRUSTED_CLOSE}"
