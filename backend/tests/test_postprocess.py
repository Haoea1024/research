from __future__ import annotations

import pytest

from app.parsing.base import ParserOutputError
from app.parsing.postprocess import normalize_content_list


def test_normalizes_types_order_caption_and_diagnostics(content_list, tmp_path):
    blocks, figures, diagnostics = normalize_content_list(
        content_list, asset_root=tmp_path
    )
    assert [block.order_idx for block in blocks] == list(range(len(blocks)))
    assert [block.type for block in blocks] == [
        "title",
        "text",
        "figure",
        "table",
        "caption",
        "formula",
    ]
    assert diagnostics.raw_block_count == 6
    assert diagnostics.application_block_count == 6
    assert diagnostics.filtered_block_count == 1
    assert diagnostics.embedded_captions_without_bbox == 1
    assert diagnostics.paired_captions == 1
    assert figures[0].caption_order_idx is None
    assert figures[0].caption_text.startswith("Figure 1")
    assert figures[0].diagnostics == ("CAPTION_WITHOUT_DISTINCT_BBOX",)
    assert figures[1].caption_order_idx == 4
    assert blocks[4].bbox == (120.0, 620.0, 880.0, 650.0)
    assert blocks[-1].is_translatable is False


@pytest.mark.parametrize(
    "bbox",
    ([1, 2, 3], [10, 20, 5, 30], [-1, 0, 10, 10], [0, 0, 1001, 10]),
)
def test_rejects_invalid_bbox(content_list, bbox):
    content_list[0]["bbox"] = bbox
    with pytest.raises(ParserOutputError):
        normalize_content_list(content_list)


def test_formula_heuristic_marks_math_text_nontranslatable():
    content = [
        {
            "type": "text",
            "text": "x+y=z",
            "bbox": [0, 0, 100, 100],
            "page_idx": 0,
        }
    ]
    blocks, _, diagnostics = normalize_content_list(content)
    assert blocks[0].is_translatable is False
    assert diagnostics.formula_nontranslatable_count == 1
