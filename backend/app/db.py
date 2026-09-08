"""SQLite engine, idempotent schema initialization, and sqlite-vec health."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base, Meta


SCHEMA_VERSION = "3"
VECTOR_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_blocks USING vec0("
    "block_id TEXT PRIMARY KEY, paper_id TEXT partition key, embedding float[1024])",
    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_figures USING vec0("
    "figure_id TEXT PRIMARY KEY, paper_id TEXT partition key, embedding float[1024])",
)


@dataclass
class ComponentHealth:
    status: str
    error: str | None = None
    version: str | None = None


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else None
        self.vector_health = ComponentHealth(status="unknown")
        self.vector_schema_error: str | None = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{self.path.as_posix()}"
            kwargs = {"connect_args": {"check_same_thread": False}}
        else:
            url = "sqlite://"
            kwargs = {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
        self.engine: Engine = create_engine(url, future=True, **kwargs)
        self._register_connect_hooks()
        self.SessionLocal = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=Session
        )

    def _register_connect_hooks(self) -> None:
        @event.listens_for(self.engine, "connect")
        def configure_connection(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
            try:
                import sqlite_vec

                dbapi_connection.enable_load_extension(True)
                sqlite_vec.load(dbapi_connection)
                version = dbapi_connection.execute("SELECT vec_version()").fetchone()[0]
                self.vector_health = ComponentHealth(status="ok", version=version)
            except Exception as exc:  # health must preserve the extension's raw error
                self.vector_health = ComponentHealth(status="failed", error=repr(exc))

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            current = connection.execute(
                text("SELECT value FROM meta WHERE key='schema_version'")
            ).scalar_one_or_none()
            if current not in (None, "1", "2", SCHEMA_VERSION):
                raise RuntimeError(
                    f"unsupported schema version {current}; expected 1, 2, or {SCHEMA_VERSION}"
                )
            translation_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(translations)"
                ).all()
            }
            if "error" not in translation_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE translations ADD COLUMN error TEXT"
                )
            llm_call_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(llm_calls)"
                ).all()
            }
            if "status" not in llm_call_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE llm_calls ADD COLUMN status TEXT"
                )
            if "error" not in llm_call_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE llm_calls ADD COLUMN error TEXT"
                )
            connection.exec_driver_sql(
                "UPDATE llm_calls SET status='success' WHERE status IS NULL"
            )
            if current is None:
                connection.execute(
                    text("INSERT INTO meta(key, value) VALUES ('schema_version', :version)"),
                    {"version": SCHEMA_VERSION},
                )
            elif current in ("1", "2"):
                connection.execute(
                    text(
                        "UPDATE meta SET value=:version WHERE key='schema_version'"
                    ),
                    {"version": SCHEMA_VERSION},
                )
        if self.vector_health.status == "ok":
            self.vector_schema_error = None
            try:
                with self.engine.begin() as connection:
                    for statement in VECTOR_DDL:
                        connection.exec_driver_sql(statement)
            except Exception as exc:
                self.vector_schema_error = repr(exc)
                # Vector search is post-S1. Ordinary tables and APIs remain usable.
                self.vector_health = ComponentHealth(
                    status="failed", error=f"vector schema initialization failed: {exc!r}"
                )

    @contextmanager
    def session(self) -> Iterator[Session]:
        db_session = self.SessionLocal()
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise
        finally:
            db_session.close()

    def health(self) -> dict[str, object]:
        with self.engine.connect() as connection:
            wal = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            connection.exec_driver_sql("SELECT 1").scalar_one()
        vector_health = asdict(self.vector_health)
        if self.vector_schema_error:
            vector_health = {
                "status": "failed",
                "error": f"vector schema initialization failed: {self.vector_schema_error}",
                "version": self.vector_health.version,
            }
        return {
            "database": {
                "status": "ok",
                "journal_mode": wal,
                "foreign_keys": bool(foreign_keys),
                "schema_version": SCHEMA_VERSION,
            },
            "sqlite_vec": vector_health,
        }

    def recover_orphaned_parses(self) -> int:
        with self.engine.begin() as connection:
            result = connection.exec_driver_sql(
                "UPDATE papers SET status='parse_failed', "
                "error='ORPHANED_PARSE: application restarted while parsing' "
                "WHERE status='parsing'"
            )
            return result.rowcount
