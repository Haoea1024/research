#!/usr/bin/env python
"""Validate a MinerU v1 content_list.json for the S0 parsing spike."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any


CAPTION_FIELDS = ("image_caption", "chart_caption", "table_caption")
FIGURE_TYPES = {"image", "chart"}


def _nonempty_caption(block: dict[str, Any]) -> bool:
    for field in CAPTION_FIELDS:
        value = block.get(field)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return True
    return False


def validate(content: Any) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if not isinstance(content, list) or not content:
        return ["top level must be a non-empty list"], {}

    type_counts: Counter[str] = Counter()
    pages: set[int] = set()
    previous_page = -1
    figure_count = table_count = caption_count = 0

    for order_idx, block in enumerate(content):
        prefix = f"block[{order_idx}]"
        if not isinstance(block, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        block_type = block.get("type")
        if not isinstance(block_type, str) or not block_type.strip():
            errors.append(f"{prefix}: type must be a non-empty string")
        else:
            type_counts[block_type] += 1
            figure_count += block_type in FIGURE_TYPES
            table_count += block_type == "table"

        page_idx = block.get("page_idx")
        if not isinstance(page_idx, int) or isinstance(page_idx, bool) or page_idx < 0:
            errors.append(f"{prefix}: page_idx must be a non-negative integer")
        else:
            pages.add(page_idx)
            if page_idx < previous_page:
                errors.append(
                    f"{prefix}: page_idx {page_idx} is before previous page {previous_page}"
                )
            previous_page = page_idx

        bbox = block.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            errors.append(f"{prefix}: bbox must contain exactly four numbers")
        elif not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in bbox
        ):
            errors.append(f"{prefix}: bbox values must be finite numbers")
        else:
            x0, y0, x1, y1 = bbox
            if x0 > x1 or y0 > y1:
                errors.append(f"{prefix}: bbox coordinates are not ordered")
            if any(value < 0 or value > 1000 for value in bbox):
                errors.append(f"{prefix}: bbox values must be within 0..1000")

        caption_count += _nonempty_caption(block)

    if not figure_count:
        errors.append("content must include at least one image or chart block")
    if not table_count:
        errors.append("content must include at least one table block")
    if not caption_count:
        errors.append("content must include at least one non-empty caption")
    if pages and pages != set(range(max(pages) + 1)):
        errors.append("page_idx values must form a continuous sequence starting at 0")

    summary = {
        "blocks": len(content),
        "pages": len(pages),
        "page_indices": sorted(pages),
        "order_idx": {"first": 0, "last": len(content) - 1, "continuous": True},
        "types": dict(sorted(type_counts.items())),
        "figures": figure_count,
        "tables": table_count,
        "captioned_blocks": caption_count,
    }
    return errors, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content_list", type=Path, help="MinerU *_content_list.json")
    args = parser.parse_args()

    try:
        content = json.loads(args.content_list.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read {args.content_list}: {exc}", file=sys.stderr)
        return 1

    errors, summary = validate(content)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if summary:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
