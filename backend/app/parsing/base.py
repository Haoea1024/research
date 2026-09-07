"""Application-owned parser types; no MinerU raw shape escapes this boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class ParserError(RuntimeError):
    code = "PARSER_ERROR"

    def __init__(self, message: str, *, details: str | None = None):
        super().__init__(message)
        self.details = details

    def persisted_message(self) -> str:
        return f"{self.code}: {self}" + (f"\n{self.details}" if self.details else "")


class ParserTimeoutError(ParserError):
    code = "PARSER_TIMEOUT"


class ParserProcessError(ParserError):
    code = "PARSER_PROCESS_FAILED"


class ParserOutputError(ParserError):
    code = "PARSER_OUTPUT_INVALID"


@dataclass(frozen=True)
class ParsedBlock:
    order_idx: int
    page: int
    bbox: tuple[float, float, float, float]
    type: str
    content_md: str | None
    confidence: float | None
    is_translatable: bool
    source_index: int
    source_type: str


@dataclass(frozen=True)
class ParsedFigure:
    index: int
    block_order_idx: int
    caption_order_idx: int | None
    image_path: str
    table_html: str | None
    caption_text: str | None
    caption_source_field: str | None
    diagnostics: tuple[str, ...] = ()


@dataclass
class ParseDiagnostics:
    raw_block_count: int = 0
    application_block_count: int = 0
    filtered_block_count: int = 0
    embedded_captions_without_bbox: int = 0
    paired_captions: int = 0
    formula_nontranslatable_count: int = 0
    issues: list[dict[str, Any]] = field(default_factory=list)
    command: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParseResult:
    parser: str
    parser_version: str
    blocks: tuple[ParsedBlock, ...]
    figures: tuple[ParsedFigure, ...]
    diagnostics: ParseDiagnostics
    raw_output_dir: Path


class Parser(Protocol):
    def parse(self, pdf_path: Path) -> ParseResult:
        """Parse one PDF or raise ParserError with persistable details."""
