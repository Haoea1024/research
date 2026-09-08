"""Language-drift checks for translated blocks."""

from __future__ import annotations

import re

from .content import strip_language_check_noise


_LATEX_COMMAND = re.compile(r"\\[A-Za-z]+(?:\s*\{[^{}]*\})?")


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
