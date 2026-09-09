"""Language-drift checks for translated blocks."""

from __future__ import annotations

import re

from ..models import Block
from .content import strip_language_check_noise


_LATEX_COMMAND = re.compile(r"\\[A-Za-z]+(?:\s*\{[^{}]*\})?")
_LATIN_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z0-9-]*\b")


def chinese_character_ratio(text: str) -> float:
    """Return CJK / (CJK + Latin) after ignoring markup and non-letters."""
    cleaned = strip_language_check_noise(_LATEX_COMMAND.sub("", text))
    chinese = sum("\u4e00" <= char <= "\u9fff" for char in cleaned)
    latin = sum(
        ("a" <= char.lower() <= "z")
        for char in cleaned
    )
    denominator = chinese + latin
    return chinese / denominator if denominator else 0.0


def protected_proper_nouns(source: str) -> list[str]:
    """Return stable technical/proper-name tokens that may remain in English."""
    tokens: list[str] = []
    for match in _LATIN_TOKEN.finditer(source):
        token = match.group(0)
        letters = "".join(char for char in token if char.isalpha())
        if not letters:
            continue
        is_acronym = len(letters) >= 2 and letters.isupper()
        has_internal_capital = any(char.isupper() for char in letters[1:])
        has_number_or_hyphen = any(char.isdigit() for char in token) or "-" in token
        if is_acronym or has_internal_capital or has_number_or_hyphen:
            tokens.append(token)
    return sorted(set(tokens), key=lambda value: (-len(value), value.casefold()))


def translation_language_ratio(block: Block, translated: str) -> float:
    """Score Chinese output without penalizing preserved standard proper nouns.

    This is deliberately narrower than lowering the global threshold: only
    technical tokens present in both source and output are excluded.
    """
    source = block.content_md or ""
    cleaned = translated
    protected = protected_proper_nouns(source)
    preserved = 0
    for token in protected:
        pattern = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(token)}(?![A-Za-z0-9-])", re.IGNORECASE)
        cleaned, count = pattern.subn(" ", cleaned)
        preserved += count
    ratio = chinese_character_ratio(cleaned)
    remaining_letters = re.findall(r"[A-Za-z\u4e00-\u9fff]", strip_language_check_noise(_LATEX_COMMAND.sub("", cleaned)))
    source_latin_count = len(re.findall(r"[A-Za-z]", source))
    protected_latin_count = sum(
        len(re.findall(r"[A-Za-z]", token)) for token in protected
    )
    proper_noun_share = protected_latin_count / max(1, source_latin_count)
    if not remaining_letters and preserved and proper_noun_share >= 0.6:
        return 1.0
    return ratio
