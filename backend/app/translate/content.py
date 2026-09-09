"""Translation eligibility and language-check text normalization."""

from __future__ import annotations

import html
import re

from ..models import Block


_HTML_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+\s*@\s*[\w.-]+\.[A-Za-z]{2,}")
_ARXIV_META = re.compile(
    r"^arxiv:\S+\s+\[[^]]+]\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{4}[.]?$",
    re.IGNORECASE,
)
_LETTERS = re.compile(r"[A-Za-z\u4e00-\u9fff]")
_REFERENCE_ENTRY = re.compile(r"(?:^|\n)\s*\[\d+\]\s+")
_TRAILING_CONTINUATION = re.compile(
    r"\b(?:a|an|and|as|at|by|for|from|in|of|on|or|the|to|with)\s*$",
    re.IGNORECASE,
)


def translation_skip_reason(block: Block) -> str | None:
    source = (block.content_md or "").strip()
    if not source:
        return "EMPTY_CONTENT"
    visible = html.unescape(_HTML_TAG.sub(" ", source)).strip()
    if not visible:
        return "HTML_ONLY_METADATA"
    if _ARXIV_META.fullmatch(visible):
        return "DOCUMENT_METADATA"
    if len(_REFERENCE_ENTRY.findall(visible)) >= 5:
        return "REFERENCE_LIST"
    if (
        block.type == "text"
        and 30 <= len(visible) <= 180
        and len(visible.split()) >= 7
        and not re.search(r"[.!?;:\u3002\uff01\uff1f\uff1b]\s*$", visible)
        and _TRAILING_CONTINUATION.search(visible)
    ):
        return "MALFORMED_FRAGMENT"

    urls = _URL.findall(visible)
    emails = _EMAIL.findall(visible)
    remainder = _URL.sub(" ", visible)
    remainder = _EMAIL.sub(" ", remainder)
    meaningful_letters = len(_LETTERS.findall(remainder))
    if urls and meaningful_letters <= 8:
        return "URL_METADATA"
    if emails and meaningful_letters <= 40 and not re.search(r"[.!?。！？]", remainder):
        return "CONTACT_METADATA"
    return None


def strip_language_check_noise(text: str) -> str:
    value = html.unescape(_HTML_TAG.sub(" ", text))
    value = _URL.sub(" ", value)
    return _EMAIL.sub(" ", value)
