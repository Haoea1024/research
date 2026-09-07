"""MinerU 3.x CLI subprocess implementation of the Parser protocol."""

from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .base import (
    ParseResult,
    ParserOutputError,
    ParserProcessError,
    ParserTimeoutError,
)
from .postprocess import normalize_content_list


OOM_RE = re.compile(
    r"out of memory|cuda.*memory|cannot allocate memory|memoryerror|std::bad_alloc",
    re.IGNORECASE,
)


class MinerUCLIParser:
    def __init__(
        self,
        *,
        command: str = "mineru",
        backend: str = "pipeline",
        timeout_seconds: int = 480,
        output_root: Path,
    ):
        self.command = command
        self.backend = backend
        self.timeout_seconds = timeout_seconds
        self.output_root = output_root

    def parse(self, pdf_path: Path) -> ParseResult:
        pdf_path = pdf_path.resolve()
        if not pdf_path.is_file():
            raise ParserOutputError(f"PDF does not exist: {pdf_path}")
        if pdf_path.read_bytes()[:5] != b"%PDF-":
            raise ParserOutputError(f"file is not a PDF: {pdf_path}")

        run_dir = (self.output_root / uuid.uuid4().hex).resolve()
        run_dir.mkdir(parents=True, exist_ok=False)
        command = [
            self.command,
            "-p",
            str(pdf_path),
            "-o",
            str(run_dir),
            "-b",
            self.backend,
        ]
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ParserTimeoutError(
                f"MinerU exceeded {self.timeout_seconds} seconds",
                details=f"stdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}",
            ) from exc
        except OSError as exc:
            raise ParserProcessError(
                f"failed to start MinerU command {self.command!r}", details=repr(exc)
            ) from exc

        elapsed = time.perf_counter() - started
        combined = f"{completed.stdout}\n{completed.stderr}"
        if completed.returncode != 0:
            diagnosis = "OOM suspected. " if OOM_RE.search(combined) else ""
            raise ParserProcessError(
                f"MinerU exited with code {completed.returncode}; {diagnosis}".rstrip(),
                details=combined,
            )

        candidates = [
            path
            for path in run_dir.rglob("*_content_list.json")
            if not path.name.endswith("_content_list_v2.json")
        ]
        if len(candidates) != 1:
            raise ParserOutputError(
                f"expected one MinerU content list, found {len(candidates)}",
                details="\n".join(str(path) for path in candidates),
            )
        content_path = candidates[0]
        try:
            content = json.loads(content_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ParserOutputError(
                f"cannot read MinerU output {content_path}", details=repr(exc)
            ) from exc

        blocks, figures, diagnostics = normalize_content_list(
            content, asset_root=content_path.parent
        )
        diagnostics.command = {
            "argv": command,
            "exit_code": completed.returncode,
            "elapsed_seconds": round(elapsed, 3),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "content_list": str(content_path),
        }
        diagnostics_path = run_dir / "parse_diagnostics.json"
        diagnostics_path.write_text(
            json.dumps(diagnostics.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            parser_version = version("mineru")
        except PackageNotFoundError:
            parser_version = "unknown"
        return ParseResult(
            parser="mineru-cli",
            parser_version=parser_version,
            blocks=blocks,
            figures=figures,
            diagnostics=diagnostics,
            raw_output_dir=run_dir,
        )
