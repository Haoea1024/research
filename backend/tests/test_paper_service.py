from __future__ import annotations

from pathlib import Path

import pytest

from app.parsing.base import ParserProcessError
from app.services.papers import PaperService, PaperStateConflictError
from conftest import FakeParser


def test_successful_state_machine_and_persistence(database, parsed_result, tmp_path):
    parser = FakeParser(parsed_result)
    service = PaperService(database.SessionLocal, parser)
    paper = service.create_paper(tmp_path / "paper.pdf")
    assert paper.status == "uploaded"
    service.parse_uploaded(paper.id)
    saved = service.get_paper(paper.id)
    assert saved.status == "parsed"
    assert saved.parser == "fake-mineru"
    assert [block.order_idx for block in service.list_blocks(paper.id)] == list(range(6))
    assert len(service.list_figures(paper.id)) == 2


def test_failure_preserves_raw_error_and_retry_rules(database, parsed_result, tmp_path):
    parser = FakeParser(error=ParserProcessError("boom", details="raw stderr"))
    service = PaperService(database.SessionLocal, parser)
    paper = service.create_paper(tmp_path / "paper.pdf")
    service.parse_uploaded(paper.id)
    failed = service.get_paper(paper.id)
    assert failed.status == "parse_failed"
    assert "PARSER_PROCESS_FAILED: boom" in failed.error
    assert "raw stderr" in failed.error

    service.claim_retry(paper.id)
    assert service.get_paper(paper.id).status == "parsing"
    with pytest.raises(PaperStateConflictError):
        service.claim_retry(paper.id)
    parser.error = None
    parser.result = parsed_result
    service.parse_claimed_retry(paper.id)
    assert service.get_paper(paper.id).status == "parsed"
    with pytest.raises(PaperStateConflictError):
        service.claim_retry(paper.id)
