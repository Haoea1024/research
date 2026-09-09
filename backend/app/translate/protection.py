"""Provider-safe token protection and deterministic restoration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal


TermPolicy = Literal["preserve_literal", "force_target", "validate_only"]


@dataclass(frozen=True)
class TermDirective:
    source: str
    target: str
    policy: TermPolicy = "validate_only"


@dataclass(frozen=True)
class ProtectedToken:
    placeholder: str
    original: str
    replacement: str
    kind: str


@dataclass(frozen=True)
class ProtectedText:
    text: str
    tokens: tuple[ProtectedToken, ...]
    prefix: str

    def restore(self, translated: str) -> tuple[str | None, tuple[str, ...]]:
        errors: list[str] = []
        known = {token.placeholder for token in self.tokens}
        found = _PLACEHOLDER.findall(translated)
        for token in self.tokens:
            count = translated.count(token.placeholder)
            if count != 1:
                errors.append(f"placeholder {token.placeholder} count={count}, expected=1")
        unknown = sorted(set(found) - known)
        if unknown:
            errors.append(f"unknown placeholders: {unknown!r}")
        if errors:
            return None, tuple(errors)
        restored = translated
        for token in self.tokens:
            restored = restored.replace(token.placeholder, token.replacement)
        if _PLACEHOLDER.search(restored):
            return None, ("placeholder residue after restore",)
        return restored, ()


_PLACEHOLDER = re.compile(r"__PA_[A-F0-9]{8}_\d{4}__")
_LITERAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("display_latex", re.compile(r"\$\$.*?\$\$|\\\[.*?\\\]", re.DOTALL)),
    ("inline_latex", re.compile(r"(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)|\\\(.*?\\\)", re.DOTALL)),
    ("safe_sup", re.compile(r"<sup>[^<>]*</sup>", re.IGNORECASE)),
    ("url", re.compile(r"(?:https?://|www\.)[^\s<]+", re.IGNORECASE)),
    ("email", re.compile(r"[\w.+-]+\s*@\s*[\w.-]+\.[A-Za-z]{2,}")),
    (
        "numeric_citation",
        re.compile(r"\[(?:\d+(?:\s*[-–—]\s*\d+)?)(?:\s*,\s*\d+(?:\s*[-–—]\s*\d+)?)*\]"),
    ),
    ("author_year_citation", re.compile(r"\([A-Z][A-Za-z-]+(?:\s+et\s+al\.)?,\s*\d{4}[a-z]?\)")),
)


def literal_fragments(source: str) -> tuple[tuple[str, str], ...]:
    found: list[tuple[int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for kind, pattern in _LITERAL_PATTERNS:
        for match in pattern.finditer(source):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            occupied.append((match.start(), match.end()))
            found.append((match.start(), kind, match.group(0)))
    return tuple((kind, value) for _, kind, value in sorted(found))


def protect_text(
    source: str,
    *,
    request_scope: str,
    terms: Iterable[TermDirective] = (),
) -> ProtectedText:
    prefix = re.sub(r"[^A-F0-9]", "", request_scope.upper())[:8].ljust(8, "0")
    spans: list[tuple[int, int, str, str, str]] = []
    for kind, pattern in _LITERAL_PATTERNS:
        for match in pattern.finditer(source):
            spans.append((match.start(), match.end(), kind, match.group(0), match.group(0)))
    for term in sorted(terms, key=lambda item: (-len(item.source), item.source.casefold())):
        if term.policy == "validate_only" or not term.source:
            continue
        replacement = term.target if term.policy == "force_target" else term.source
        pattern = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(term.source)}(?![A-Za-z0-9-])", re.IGNORECASE)
        for match in pattern.finditer(source):
            spans.append((match.start(), match.end(), f"term:{term.policy}", match.group(0), replacement))
    selected: list[tuple[int, int, str, str, str]] = []
    for span in sorted(spans, key=lambda item: (item[0], -(item[1] - item[0]), item[2])):
        if any(span[0] < current[1] and span[1] > current[0] for current in selected):
            continue
        selected.append(span)
    selected.sort()
    parts: list[str] = []
    tokens: list[ProtectedToken] = []
    cursor = 0
    for index, (start, end, kind, original, replacement) in enumerate(selected, 1):
        placeholder = f"__PA_{prefix}_{index:04d}__"
        parts.extend((source[cursor:start], placeholder))
        tokens.append(ProtectedToken(placeholder, original, replacement, kind))
        cursor = end
    parts.append(source[cursor:])
    return ProtectedText("".join(parts), tuple(tokens), prefix)
