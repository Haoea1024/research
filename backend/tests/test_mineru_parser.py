from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.parsing.base import ParserOutputError, ParserProcessError, ParserTimeoutError
from app.parsing.mineru_client import MinerUCLIParser


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.5\nfixture")
    return path


def test_cli_parser_reads_generated_content(monkeypatch, tmp_path, content_list):
    def fake_run(command, **kwargs):
        output = Path(command[command.index("-o") + 1]) / "paper" / "auto"
        output.mkdir(parents=True)
        (output / "paper_content_list.json").write_text(
            json.dumps(content_list), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("app.parsing.mineru_client.subprocess.run", fake_run)
    parser = MinerUCLIParser(output_root=tmp_path / "out")
    result = parser.parse(_pdf(tmp_path))
    assert result.parser == "mineru-cli"
    assert len(result.blocks) == 6
    assert result.diagnostics.command["exit_code"] == 0
    assert (result.raw_output_dir / "parse_diagnostics.json").exists()


def test_cli_parser_preserves_process_error_and_oom(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.parsing.mineru_client.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=137, stdout="", stderr="RuntimeError: out of memory"
        ),
    )
    parser = MinerUCLIParser(output_root=tmp_path / "out")
    with pytest.raises(ParserProcessError) as error:
        parser.parse(_pdf(tmp_path))
    assert "code 137" in str(error.value)
    assert "OOM suspected" in str(error.value)
    assert "out of memory" in error.value.details


def test_cli_parser_timeout(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=480, stderr="slow")

    monkeypatch.setattr("app.parsing.mineru_client.subprocess.run", timeout)
    parser = MinerUCLIParser(output_root=tmp_path / "out")
    with pytest.raises(ParserTimeoutError) as error:
        parser.parse(_pdf(tmp_path))
    assert "480 seconds" in str(error.value)


def test_cli_parser_requires_exactly_one_output(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.parsing.mineru_client.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    parser = MinerUCLIParser(output_root=tmp_path / "out")
    with pytest.raises(ParserOutputError, match="found 0"):
        parser.parse(_pdf(tmp_path))


def test_cli_parser_rejects_non_pdf(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_text("not a pdf", encoding="utf-8")
    parser = MinerUCLIParser(output_root=tmp_path / "out")
    with pytest.raises(ParserOutputError, match="not a PDF"):
        parser.parse(path)
