"""Shared final validation for LLM and non-LLM translation candidates."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from ..models import Block
from .language import protected_proper_nouns, translation_language_ratio
from .protection import TermDirective, literal_fragments


@dataclass(frozen=True)
class FinalValidation:
    valid: bool
    errors: tuple[str, ...]
    language_ratio: float


_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*(?:%|×)?")


def validate_final_translation(
    block: Block,
    translated: str,
    *,
    threshold: float,
    terms: Iterable[TermDirective] = (),
) -> FinalValidation:
    errors: list[str] = []
    value = translated.strip()
    if not value:
        return FinalValidation(False, ("EMPTY_TRANSLATION",), 0.0)
    source = block.content_md or ""
    source_numbers = Counter(_NUMBER.findall(source))
    output_numbers = Counter(_NUMBER.findall(value))
    if source_numbers != output_numbers:
        errors.append("NUMERIC_INTEGRITY")
    for kind, fragment in literal_fragments(source):
        if fragment not in value:
            errors.append(f"CONTENT_INTEGRITY:{kind}")

    source_letters = len(re.findall(r"[A-Za-z\u4e00-\u9fff]", source))
    output_letters = len(re.findall(r"[A-Za-z\u4e00-\u9fff]", value))
    if source_letters >= 20 and output_letters < max(2, round(source_letters * 0.08)):
        errors.append("CONTENT_OMISSION")
    if source_letters >= 20 and output_letters > source_letters * 4:
        errors.append("CONTENT_ADDITION")

    folded_source = source.casefold()
    folded_output = value.casefold()
    directives = list(terms)
    for term in directives:
        if term.source.casefold() not in folded_source:
            continue
        expected = term.source if term.policy == "preserve_literal" else term.target
        if expected and expected.casefold() not in folded_output:
            errors.append(f"TERMINOLOGY:{term.source}")

    glossary_sources = {term.source.casefold() for term in directives}
    for noun in protected_proper_nouns(source):
        if noun.casefold() in glossary_sources:
            continue
        if noun.casefold() not in folded_output:
            errors.append(f"PROPER_NOUN:{noun}")

    ratio = translation_language_ratio(block, value)
    if ratio < threshold:
        errors.append("LANGUAGE_DRIFT")
    return FinalValidation(not errors, tuple(dict.fromkeys(errors)), ratio)


def validation_json(result: FinalValidation) -> dict[str, object]:
    return {
        "valid": result.valid,
        "errors": list(result.errors),
        "language_ratio": result.language_ratio,
    }
