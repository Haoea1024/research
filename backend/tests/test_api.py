from __future__ import annotations

import sys
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import (
    DatabaseConfig,
    ParserConfig,
    Settings,
    StorageConfig,
)
from app.db import Database
from app.main import create_app
from app.parsing.base import ParserProcessError
from conftest import FakeParser


def _client(tmp_path: Path, parser: FakeParser, llm_client=None):
    settings = Settings(
        database=DatabaseConfig(path=tmp_path / "api.db"),
        parser=ParserConfig(command=sys.executable, output_dir=tmp_path / "parsed"),
        storage=StorageConfig(upload_dir=tmp_path / "uploads"),
    )
    database = Database(settings.database.path)
    app = create_app(
        settings=settings,
        database=database,
        parser=parser,
        llm_client=llm_client,
    )
    return TestClient(app), database


def test_upload_query_blocks_figures_and_health(tmp_path, parsed_result):
    parser = FakeParser(parsed_result)
    client, _ = _client(tmp_path, parser)
    with client:
        response = client.post(
            "/api/papers", files={"file": ("paper.pdf", b"%PDF-1.5\nfixture", "application/pdf")}
        )
        assert response.status_code == 202
        assert response.json()["status"] == "uploaded"
        paper_id = response.json()["paper_id"]
        assert client.get(f"/api/papers/{paper_id}").json()["status"] == "parsed"
        blocks = client.get(f"/api/papers/{paper_id}/blocks").json()
        figures = client.get(f"/api/papers/{paper_id}/figures").json()
        assert [block["order_idx"] for block in blocks] == list(range(6))
        assert len(figures) == 2
        assert figures[0]["caption_text"].startswith("Figure 1")
        assert figures[0]["caption_block_id"] is None
        assert figures[0]["diagnostics"] == ["CAPTION_WITHOUT_DISTINCT_BBOX"]
        assert figures[0]["image_url"].startswith("/api/figures/")
        assert "image_path" not in figures[0]
        assert figures[1]["caption_text"].startswith("Table 1")
        assert figures[1]["caption_block_id"].endswith(":4")
        assert client.get("/api/papers").json()[0]["id"] == paper_id
        health = client.get("/api/health").json()
        assert health["components"]["database"]["status"] == "ok"
        assert health["components"]["sqlite_vec"]["status"] == "ok"
        assert health["components"]["llm"]["status"] == "not_configured"


def test_upload_validation(tmp_path, parsed_result):
    client, _ = _client(tmp_path, FakeParser(parsed_result))
    with client:
        assert client.post(
            "/api/papers", files={"file": ("paper.txt", b"text", "text/plain")}
        ).status_code == 415
        assert client.post(
            "/api/papers", files={"file": ("paper.pdf", b"broken", "application/pdf")}
        ).status_code == 422


def test_pdf_endpoint_uses_database_path_without_exposing_it(tmp_path, parsed_result):
    parser = FakeParser(parsed_result)
    client, _ = _client(tmp_path, parser)
    payload = b"%PDF-1.5\nfixture-pdf"
    with client:
        response = client.post(
            "/api/papers",
            files={"file": ("secret-name.pdf", payload, "application/pdf")},
        )
        paper_id = response.json()["paper_id"]
        fetched = client.get(f"/api/papers/{paper_id}/pdf")
        assert fetched.status_code == 200
        assert fetched.content == payload
        assert fetched.headers["content-type"] == "application/pdf"
        assert fetched.headers["content-disposition"] == (
            f'inline; filename="{paper_id}.pdf"'
        )
        assert "pdf_path" not in client.get(f"/api/papers/{paper_id}").json()


def test_pdf_endpoint_reports_missing_database_file(tmp_path, parsed_result):
    client, database = _client(tmp_path, FakeParser(parsed_result))
    with client:
        missing = tmp_path / "missing.pdf"
        from app.models import Paper

        with database.session() as session:
            session.add(Paper(id="missing-file", pdf_path=str(missing), status="parsed"))
        response = client.get("/api/papers/missing-file/pdf")
        assert response.status_code == 404
        assert response.json()["detail"] == "paper PDF is missing from local storage"


def test_figure_image_endpoint_is_id_based_and_confined_to_parser_output(
    tmp_path, parsed_result
):
    client, database = _client(tmp_path, FakeParser(parsed_result))
    with client:
        upload = client.post(
            "/api/papers",
            files={"file": ("paper.pdf", b"%PDF-1.5\nfixture", "application/pdf")},
        )
        paper_id = upload.json()["paper_id"]
        figures = client.get(f"/api/papers/{paper_id}/figures").json()
        figure_id = figures[0]["id"]
        image = tmp_path / "parsed" / "paper" / "figure.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"fake-jpeg")

        from app.models import Figure

        with database.session() as session:
            session.get(Figure, figure_id).image_path = str(image)
        fetched = client.get(f"/api/figures/{figure_id}/image")
        assert fetched.status_code == 200
        assert fetched.content == b"fake-jpeg"
        assert fetched.headers["content-type"] == "image/jpeg"

        outside = tmp_path / "outside.jpg"
        outside.write_bytes(b"private")
        with database.session() as session:
            session.get(Figure, figure_id).image_path = str(outside)
        rejected = client.get(f"/api/figures/{figure_id}/image")
        assert rejected.status_code == 404
        assert rejected.content != b"private"


def test_failed_upload_can_retry_but_parsed_cannot(tmp_path, parsed_result):
    parser = FakeParser(error=ParserProcessError("failed", details="raw stderr"))
    client, _ = _client(tmp_path, parser)
    with client:
        response = client.post(
            "/api/papers", files={"file": ("paper.pdf", b"%PDF-1.5\nfixture", "application/pdf")}
        )
        paper_id = response.json()["paper_id"]
        detail = client.get(f"/api/papers/{paper_id}").json()
        assert detail["status"] == "parse_failed"
        assert "raw stderr" in detail["error"]

        parser.error = None
        parser.result = parsed_result
        retried = client.post(f"/api/papers/{paper_id}/retry")
        assert retried.status_code == 202
        assert retried.json()["status"] == "parsing"
        assert client.get(f"/api/papers/{paper_id}").json()["status"] == "parsed"
        conflict = client.post(f"/api/papers/{paper_id}/retry")
        assert conflict.status_code == 409
        assert "only parse_failed" in conflict.json()["detail"]


def test_missing_paper_is_404(tmp_path, parsed_result):
    client, _ = _client(tmp_path, FakeParser(parsed_result))
    with client:
        assert client.get("/api/papers/missing").status_code == 404
        assert client.get("/api/papers/missing/blocks").status_code == 404
        assert client.post("/api/papers/missing/retry").status_code == 404


def test_table_body_without_caption_is_not_reported_as_caption(
    tmp_path, content_list
):
    from app.parsing.base import ParseResult
    from app.parsing.postprocess import normalize_content_list

    table = next(block for block in content_list if block["type"] == "table")
    table.pop("table_caption", None)
    blocks, figures, diagnostics = normalize_content_list(content_list)
    result = ParseResult(
        parser="fake-mineru",
        parser_version="3.4.5",
        blocks=blocks,
        figures=figures,
        diagnostics=diagnostics,
        raw_output_dir=tmp_path,
    )
    client, _ = _client(tmp_path, FakeParser(result))
    with client:
        response = client.post(
            "/api/papers",
            files={"file": ("paper.pdf", b"%PDF-1.5\nfixture", "application/pdf")},
        )
        paper_id = response.json()["paper_id"]
        table_response = next(
            figure
            for figure in client.get(f"/api/papers/{paper_id}/figures").json()
            if figure["table_html"] == table["table_body"]
        )
        assert table_response["caption_text"] is None
        assert table_response["diagnostics"] == []


class _ApiFakeLLM:
    def __init__(self):
        self.calls: list[str] = []

    def model_for_task(self, task: str) -> str:
        return f"fake/{task}"

    def call(self, task: str, messages, **kwargs):
        del kwargs
        self.calls.append(task)
        if task == "glossary":
            payload = {"terms": [{"source": "network", "target": "网络"}]}
        else:
            prompt = messages[-1]["content"]
            marker = "Local blocks:\n" if "Local blocks:\n" in prompt else "Blocks:\n"
            blocks = json.loads(prompt.split(marker, 1)[1])
            payload = {
                "translations": [
                    {"block_id": block["block_id"], "zh_text": "这是通过接口生成的网络中文译文"}
                    for block in blocks
                    if not block["context_only"]
                ]
            }
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def test_s3_fake_translation_api_and_sse(tmp_path, parsed_result):
    llm = _ApiFakeLLM()
    client, _ = _client(tmp_path, FakeParser(parsed_result), llm)
    with client:
        upload = client.post(
            "/api/papers",
            files={"file": ("paper.pdf", b"%PDF-1.5\nfixture", "application/pdf")},
        )
        paper_id = upload.json()["paper_id"]
        blocks = client.get(f"/api/papers/{paper_id}/blocks").json()
        target_ids = [block["id"] for block in blocks if block["is_translatable"]][:2]
        started = client.post(
            f"/api/papers/{paper_id}/translate",
            json={"pages": [1], "block_ids": target_ids},
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = client.get(f"/api/papers/{paper_id}/translations").json()
            selected = [item for item in snapshot if item["block_id"] in target_ids]
            if selected and all(item["status"] == "done" for item in selected):
                break
            time.sleep(0.01)
        assert all(item["zh_text"] for item in selected)
        stream = client.get(
            f"/api/papers/{paper_id}/translate/stream",
            params={"run_id": run_id},
        )
        assert stream.status_code == 200
        assert "event: block" in stream.text
        assert "event: progress" in stream.text
        assert "event: finished" in stream.text
        glossary = client.get(f"/api/papers/{paper_id}/glossary").json()
        assert glossary == [{"source": "network", "target": "网络", "version": 1}]
        csv_response = client.get(
            f"/api/papers/{paper_id}/glossary", params={"format": "csv"}
        )
        assert csv_response.content.startswith(b"\xef\xbb\xbf")
        assert client.post(
            f"/api/papers/{paper_id}/viewport",
            json={"visible_block_ids": target_ids},
        ).status_code == 204


def test_s3_scope_rejects_foreign_block(tmp_path, parsed_result):
    client, _ = _client(tmp_path, FakeParser(parsed_result), _ApiFakeLLM())
    with client:
        upload = client.post(
            "/api/papers",
            files={"file": ("paper.pdf", b"%PDF-1.5\nfixture", "application/pdf")},
        )
        paper_id = upload.json()["paper_id"]
        response = client.post(
            f"/api/papers/{paper_id}/translate", json={"block_ids": ["foreign"]}
        )
        assert response.status_code == 422
