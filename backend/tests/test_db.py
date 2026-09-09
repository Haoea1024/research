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
    "translation_provider_calls",
    "meta",
    "vec_blocks",
    "vec_figures",
}

EXPECTED_COLUMNS = {
    "papers": {"id", "title", "authors", "year", "pdf_path", "status", "parser", "parser_version", "error", "created_at"},
    "blocks": {"id", "paper_id", "order_idx", "page", "bbox", "type", "content_md", "confidence", "is_translatable"},
    "translations": {"block_id", "zh_text", "glossary_version", "model", "status", "error", "updated_at", "source_hash", "provider", "route", "validation_json"},
    "glossary_terms": {"paper_id", "source", "target", "version"},
    "figures": {"id", "paper_id", "block_id", "caption_block_id", "image_path", "vision_desc", "table_html", "model", "status", "error"},
    "messages": {"id", "paper_id", "role", "content", "anchors", "confidence", "created_at"},
    "report_sections": {"paper_id", "section", "content_md", "anchors", "summary", "dialog_aware", "model", "status"},
    "proposal_cards": {"paper_id", "idx", "kind", "card_json", "status", "model", "error"},
    "llm_calls": {"id", "task", "model", "tokens_in", "tokens_out", "cache_read_tokens", "cost", "latency_ms", "status", "error", "created_at", "run_id", "entity_ids", "route", "attempt", "provider"},
    "translation_provider_calls": {"id", "run_id", "entity_ids", "route", "provider", "model", "attempt", "status", "chars_in", "chars_out", "billed_chars", "cost", "estimated_cost", "currency", "latency_ms", "request_id", "error", "created_at"},
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
        "schema_version": "4",
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


def test_schema_v1_is_upgraded_with_translation_error_column(tmp_path):
    database = Database(tmp_path / "v1.db")
    database.initialize()
    with database.engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE translations RENAME TO translations_v2")
        connection.exec_driver_sql(
            "CREATE TABLE translations ("
            "block_id TEXT PRIMARY KEY, zh_text TEXT NOT NULL, "
            "glossary_version INTEGER NOT NULL, model TEXT NOT NULL, "
            "status TEXT NOT NULL, updated_at TEXT)"
        )
        connection.exec_driver_sql("DROP TABLE translations_v2")
        connection.exec_driver_sql(
            "UPDATE meta SET value='1' WHERE key='schema_version'"
        )

    database.initialize()

    assert {
        column["name"]
        for column in inspect(database.engine).get_columns("translations")
    } >= {"error"}
    assert database.health()["database"]["schema_version"] == "4"


def test_schema_v2_is_upgraded_with_llm_failure_audit_columns(tmp_path):
    database = Database(tmp_path / "v2.db")
    database.initialize()
    with database.engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE llm_calls RENAME TO llm_calls_v3")
        connection.exec_driver_sql(
            "CREATE TABLE llm_calls ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, model TEXT, "
            "tokens_in INTEGER, tokens_out INTEGER, cache_read_tokens INTEGER, "
            "cost FLOAT, latency_ms INTEGER, created_at TEXT)"
        )
        connection.exec_driver_sql("DROP TABLE llm_calls_v3")
        connection.exec_driver_sql(
            "UPDATE meta SET value='2' WHERE key='schema_version'"
        )

    database.initialize()

    columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("llm_calls")
    }
    assert {"status", "error"} <= columns
    assert database.health()["database"]["schema_version"] == "4"


def test_schema_v3_backfills_translation_source_hash(tmp_path):
    from app.models import Block, Translation
    from app.provenance import translation_source_hash

    database = Database(tmp_path / "v3.db")
    database.initialize()
    with database.session() as session:
        session.add(Paper(id="paper", pdf_path="paper.pdf", status="parsed"))
        session.add(Block(id="b0", paper_id="paper", order_idx=0, page=0, bbox="[0,0,1,1]", type="text", content_md="source", is_translatable=1))
        session.add(Translation(block_id="b0", zh_text="译文", glossary_version=1, model="old", status="done", source_hash=None))
    with database.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE meta SET value='3' WHERE key='schema_version'")

    database.initialize()

    with database.session() as session:
        assert session.get(Translation, "b0").source_hash == translation_source_hash("source")


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
