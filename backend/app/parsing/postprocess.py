"""Normalize MinerU v1 content-list blocks into application-owned types."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .base import (
    ParseDiagnostics,
    ParsedBlock,
    ParsedFigure,
    ParserOutputError,
)


DISCARDED_TYPES = {
    "discarded",
    "discarded_block",
    "header",
    "footer",
    "page_header",
    "page_footer",
    "page_number",
}
FIGURE_TYPES = {"image", "chart"}
CAPTION_FIELDS = {
    "image": "image_caption",
    "chart": "chart_caption",
    "table": "table_caption",
}
FONT_RE = re.compile(r"(?:^|\b)(?:CM\w*|\w*Ital\w*|MS\w*)", re.IGNORECASE)
MATH_CHARS_RE = re.compile(r"[=+\-×÷∑∏∫√≤≥≈≠∞∂∇α-ωΑ-Ω]", re.UNICODE)


@dataclass
class _PendingBlock:
    key: str
    source_sort: tuple[int, int]
    page: int
    bbox: tuple[float, float, float, float]
    type: str
    content_md: str | None
    confidence: float | None
    is_translatable: bool
    source_index: int
    source_type: str


@dataclass
class _PendingFigure:
    block_key: str
    caption_key: str | None
    image_path: str
    table_html: str | None
    caption_text: str | None
    caption_source_field: str | None
    diagnostics: list[str]


def _bbox(value: Any, raw_index: int) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ParserOutputError(f"block {raw_index} has no four-number bbox")
    if not all(
        isinstance(item, (int, float))
        and not isinstance(item, bool)
        and math.isfinite(item)
        for item in value
    ):
        raise ParserOutputError(f"block {raw_index} has non-finite bbox values")
    x0, y0, x1, y1 = (float(item) for item in value)
    if x0 > x1 or y0 > y1:
        raise ParserOutputError(f"block {raw_index} has inverted bbox coordinates")
    if any(item < 0 or item > 1000 for item in (x0, y0, x1, y1)):
        raise ParserOutputError(
            f"block {raw_index} bbox is not normalized to the 0..1000 range"
        )
    return x0, y0, x1, y1


def _page(raw: dict[str, Any], raw_index: int) -> int:
    value = raw.get("page_idx")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ParserOutputError(f"block {raw_index} has invalid page_idx")
    return value


def _caption_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        joined = "\n".join(str(item).strip() for item in value if str(item).strip())
        return joined or None
    return None


def _content(raw: dict[str, Any], source_type: str, caption: str | None) -> str | None:
    if source_type == "list":
        items = raw.get("list_items") or []
        if isinstance(items, list):
            return "\n".join(str(item) for item in items)
    if source_type == "table":
        table = raw.get("table_body")
        parts = [part for part in (caption, table if isinstance(table, str) else None) if part]
        return "\n\n".join(parts) or None
    if source_type in FIGURE_TYPES:
        return caption
    for key in ("text", "content"):
        value = raw.get(key)
        if isinstance(value, str):
            return value
    return None


def _font_values(raw: dict[str, Any]) -> Iterable[str]:
    for key in ("font", "font_name", "font_names", "fonts"):
        value = raw.get(key)
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            yield from (str(item) for item in value)


def _looks_like_formula(raw: dict[str, Any], source_type: str, text: str | None) -> bool:
    if source_type in {"equation", "formula"}:
        return True
    if any(FONT_RE.search(value) for value in _font_values(raw)):
        return True
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    math_count = len(MATH_CHARS_RE.findall(compact))
    return math_count >= 2 and math_count / max(len(compact), 1) >= 0.15


def _app_type(raw: dict[str, Any], source_type: str) -> str:
    if source_type == "text":
        return "title" if raw.get("text_level") in {1, 2} else "text"
    if source_type in {"equation", "formula"}:
        return "formula"
    if source_type in FIGURE_TYPES:
        return "figure"
    if source_type == "table":
        return "table"
    if source_type == "caption":
        return "caption"
    return "text"


def _resolved_image(asset_root: Path | None, value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    path = Path(value)
    if asset_root and not path.is_absolute():
        return str((asset_root / path).resolve())
    return str(path)


def normalize_content_list(
    content: Any, *, asset_root: Path | None = None
) -> tuple[tuple[ParsedBlock, ...], tuple[ParsedFigure, ...], ParseDiagnostics]:
    if not isinstance(content, list) or not content:
        raise ParserOutputError("content list must be a non-empty list")

    diagnostics = ParseDiagnostics(raw_block_count=len(content))
    pending_blocks: list[_PendingBlock] = []
    pending_figures: list[_PendingFigure] = []

    for raw_index, raw in enumerate(content):
        if not isinstance(raw, dict):
            raise ParserOutputError(f"block {raw_index} is not an object")
        source_type = raw.get("type")
        if not isinstance(source_type, str) or not source_type:
            raise ParserOutputError(f"block {raw_index} has invalid type")
        if source_type in DISCARDED_TYPES:
            diagnostics.filtered_block_count += 1
            continue

        page = _page(raw, raw_index)
        bbox = _bbox(raw.get("bbox"), raw_index)
        caption_field = CAPTION_FIELDS.get(source_type)
        caption = _caption_text(raw.get(caption_field)) if caption_field else None
        content_md = _content(raw, source_type, caption)
        app_type = _app_type(raw, source_type)
        is_translatable = app_type not in {"formula", "figure", "table"}
        if _looks_like_formula(raw, source_type, content_md):
            is_translatable = False
        if app_type == "formula" or (app_type == "text" and not is_translatable):
            diagnostics.formula_nontranslatable_count += 1

        block_key = f"raw:{raw_index}"
        pending_blocks.append(
            _PendingBlock(
                key=block_key,
                source_sort=(raw_index, 0),
                page=page,
                bbox=bbox,
                type=app_type,
                content_md=content_md,
                confidence=raw.get("confidence")
                if isinstance(raw.get("confidence"), (int, float))
                else None,
                is_translatable=is_translatable,
                source_index=raw_index,
                source_type=source_type,
            )
        )

        if source_type not in FIGURE_TYPES | {"table"}:
            continue

        caption_key: str | None = None
        figure_diagnostics: list[str] = []
        if caption:
            candidate_bbox = raw.get("caption_bbox")
            if candidate_bbox is None and caption_field:
                candidate_bbox = raw.get(f"{caption_field}_bbox")
            if candidate_bbox is not None:
                caption_bbox = _bbox(candidate_bbox, raw_index)
                caption_key = f"raw:{raw_index}:caption"
                pending_blocks.append(
                    _PendingBlock(
                        key=caption_key,
                        source_sort=(raw_index, 1),
                        page=page,
                        bbox=caption_bbox,
                        type="caption",
                        content_md=caption,
                        confidence=None,
                        is_translatable=True,
                        source_index=raw_index,
                        source_type=caption_field or "caption",
                    )
                )
            else:
                diagnostics.embedded_captions_without_bbox += 1
                issue = {
                    "code": "CAPTION_WITHOUT_DISTINCT_BBOX",
                    "source_index": raw_index,
                    "source_type": source_type,
                    "source_field": caption_field,
                    "caption": caption,
                    "parent_bbox": list(bbox),
                }
                diagnostics.issues.append(issue)
                figure_diagnostics.append(issue["code"])

        pending_figures.append(
            _PendingFigure(
                block_key=block_key,
                caption_key=caption_key,
                image_path=_resolved_image(asset_root, raw.get("img_path")),
                table_html=raw.get("table_body")
                if isinstance(raw.get("table_body"), str)
                else None,
                caption_text=caption,
                caption_source_field=caption_field,
                diagnostics=figure_diagnostics,
            )
        )

    pending_blocks.sort(key=lambda block: block.source_sort)
    key_to_order = {block.key: index for index, block in enumerate(pending_blocks)}
    blocks = tuple(
        ParsedBlock(
            order_idx=order_idx,
            page=block.page,
            bbox=block.bbox,
            type=block.type,
            content_md=block.content_md,
            confidence=block.confidence,
            is_translatable=block.is_translatable,
            source_index=block.source_index,
            source_type=block.source_type,
        )
        for order_idx, block in enumerate(pending_blocks)
    )
    figures = tuple(
        ParsedFigure(
            index=index,
            block_order_idx=key_to_order[figure.block_key],
            caption_order_idx=key_to_order.get(figure.caption_key)
            if figure.caption_key
            else None,
            image_path=figure.image_path,
            table_html=figure.table_html,
            caption_text=figure.caption_text,
            caption_source_field=figure.caption_source_field,
            diagnostics=tuple(figure.diagnostics),
        )
        for index, figure in enumerate(pending_figures)
    )
    diagnostics.application_block_count = len(blocks)
    diagnostics.paired_captions = sum(
        figure.caption_order_idx is not None for figure in figures
    )
    return blocks, figures, diagnostics
