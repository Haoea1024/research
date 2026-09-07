from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db import Database
from app.parsing.base import ParseResult
from app.parsing.postprocess import normalize_content_list


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def content_list() -> list[dict]:
    return json.loads((FIXTURES / "mineru_content_list.json").read_text(encoding="utf-8"))


@pytest.fixture
def parsed_result(content_list, tmp_path: Path) -> ParseResult:
    asset_root = tmp_path / "assets"
    blocks, figures, diagnostics = normalize_content_list(
        content_list, asset_root=asset_root
    )
    return ParseResult(
        parser="fake-mineru",
        parser_version="3.4.5",
        blocks=blocks,
        figures=figures,
        diagnostics=diagnostics,
        raw_output_dir=tmp_path,
    )


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "app.db")
    db.initialize()
    return db


class FakeParser:
    def __init__(self, result: ParseResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[Path] = []

    def parse(self, pdf_path: Path) -> ParseResult:
        self.calls.append(pdf_path)
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result
