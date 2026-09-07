from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Database
from app.models import Paper


EXPECTED_TABLES = {
    "papers",
    "blocks",
    "translations",
    "glossary_terms",
    "figures",
    "messages",
    "report_sections",
    "proposal_cards",
    "llm_calls",
    "meta",
    "vec_blocks",
    "vec_figures",
}

EXPECTED_COLUMNS = {
    "papers": {"id", "title", "authors", "year", "pdf_path", "status", "parser", "parser_version", "error", "created_at"},
    "blocks": {"id", "paper_id", "order_idx", "page", "bbox", "type", "content_md", "confidence", "is_translatable"},
    "translations": {"block_id", "zh_text", "glossary_version", "model", "status", "updated_at"},
    "glossary_terms": {"paper_id", "source", "target", "version"},
    "figures": {"id", "paper_id", "block_id", "caption_block_id", "image_path", "vision_desc", "table_html", "model", "status", "error"},
    "messages": {"id", "paper_id", "role", "content", "anchors", "confidence", "created_at"},
    "report_sections": {"paper_id", "section", "content_md", "anchors", "summary", "dialog_aware", "model", "status"},
    "proposal_cards": {"paper_id", "idx", "kind", "card_json", "status", "model", "error"},
    "llm_calls": {"id", "task", "model", "tokens_in", "tokens_out", "cache_read_tokens", "cost", "latency_ms", "created_at"},
    "meta": {"key", "value"},
}


def test_schema_is_complete_idempotent_and_healthy(database):
    database.initialize()
    tables = set(inspect(database.engine).get_table_names())
    assert EXPECTED_TABLES <= tables
    for table, expected in EXPECTED_COLUMNS.items():
        assert {column["name"] for column in inspect(database.engine).get_columns(table)} == expected
    health = database.health()
    assert health["database"] == {
        "status": "ok",
        "journal_mode": "wal",
        "foreign_keys": True,
        "schema_version": "1",
    }
    assert health["sqlite_vec"]["status"] == "ok"
    assert health["sqlite_vec"]["version"] == "v0.1.6"


def test_vector_tables_have_partition_keys(database):
    with database.engine.connect() as connection:
        definitions = dict(
            connection.execute(
                text(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE name IN ('vec_blocks', 'vec_figures')"
                )
            ).all()
        )
    assert "paper_id TEXT partition key" in definitions["vec_blocks"]
    assert "paper_id TEXT partition key" in definitions["vec_figures"]


def test_orphaned_parsing_is_recovered(database):
    with database.session() as session:
        session.add(
            Paper(
                id="orphan",
                pdf_path="paper.pdf",
                status="parsing",
                created_at="now",
            )
        )
    assert database.recover_orphaned_parses() == 1
    with database.session() as session:
        paper = session.get(Paper, "orphan")
        assert paper.status == "parse_failed"
        assert paper.error.startswith("ORPHANED_PARSE:")


def test_vector_schema_failure_does_not_block_ordinary_schema(monkeypatch, tmp_path):
    monkeypatch.setattr("app.db.VECTOR_DDL", ("INVALID VECTOR DDL",))
    database = Database(tmp_path / "degraded.db")
    database.initialize()
    assert "papers" in inspect(database.engine).get_table_names()
    health = database.health()
    assert health["database"]["status"] == "ok"
    assert health["sqlite_vec"]["status"] == "failed"
    assert "vector schema initialization failed" in health["sqlite_vec"]["error"]


def test_vector_extension_load_failure_does_not_block_ordinary_schema(
    monkeypatch, tmp_path
):
    def broken_load(_connection):
        raise OSError("raw extension load failure")

    monkeypatch.setattr("sqlite_vec.load", broken_load)
    database = Database(tmp_path / "no-extension.db")
    database.initialize()
    assert "papers" in inspect(database.engine).get_table_names()
    health = database.health()
    assert health["database"]["status"] == "ok"
    assert health["sqlite_vec"]["status"] == "failed"
    assert "raw extension load failure" in health["sqlite_vec"]["error"]
