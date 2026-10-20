"""Turning what the API returns into text a model can read."""

from __future__ import annotations

import base64
import html
import io
import re

from pypdf import PdfReader

_BLOCK_TAGS = re.compile(r"<\s*(?:br|/p|/div|/li|/h[1-6]|/tr)\s*/?>", re.IGNORECASE)
_LIST_ITEM = re.compile(r"<\s*li[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def html_to_text(markup: str | None) -> str:
    """The subsidy overview arrives as styled HTML; keep its line structure, drop the rest."""
    if not markup:
        return ""
    text = _BLOCK_TAGS.sub("\n", markup)
    text = _LIST_ITEM.sub("・", text)
    text = html.unescape(_ANY_TAG.sub("", text))
    lines = (line.strip() for line in text.splitlines())
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


class UnsupportedAttachment(Exception):
    """An attachment whose format this server cannot turn into text."""


def attachment_text(name: str, data_base64: str) -> str:
    """The readable text of an attachment: PDF pages, or plain text files as they are."""
    data = base64.b64decode(data_base64 or "")
    lowered = name.lower()
    if lowered.endswith(".pdf") or data.startswith(b"%PDF"):
        reader = PdfReader(io.BytesIO(data))
        pages = [
            f"--- page {number} ---\n{(page.extract_text() or '').strip()}"
            for number, page in enumerate(reader.pages, start=1)
        ]
        return "\n\n".join(pages)
    if lowered.endswith((".txt", ".csv")):
        for encoding in ("utf-8-sig", "cp932"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
    raise UnsupportedAttachment(name)
