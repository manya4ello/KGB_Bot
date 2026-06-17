"""Extract text from uploaded files (text, PDF, DOCX) for /note.

PDF and DOCX parsing use optional libraries imported lazily, so the package
imports fine without them; a missing library yields a clear user-facing error.
"""

from __future__ import annotations

import io


def decode_text_file(raw: bytes) -> str:
    """Decode bytes as text (UTF-8 or CP1251). Reject binaries."""
    if b"\x00" in raw[:4096]:
        raise ValueError("похоже на бинарный файл, не текст")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("не удалось декодировать как текст (UTF-8/CP1251)")


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ValueError("поддержка PDF не установлена на сервере") from exc
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _docx_text(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise ValueError("поддержка DOCX не установлена на сервере") from exc
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text(filename: str, data: bytes) -> str:
    """Extract text from an uploaded file based on its extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if ext == "pdf":
        return _pdf_text(data)
    if ext == "docx":
        return _docx_text(data)
    if ext == "doc":
        raise ValueError("старый формат .doc не поддерживается — сохраните как .docx или .txt")
    return decode_text_file(data)
