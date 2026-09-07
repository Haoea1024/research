"""FastAPI application factory for S1."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.health import build_health_router
from .api.papers import build_papers_router
from .config import Settings, load_settings
from .db import Database
from .parsing.base import Parser
from .parsing.mineru_client import MinerUCLIParser
from .services.papers import PaperService


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    parser: Parser | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    database = database or Database(settings.database.path)
    parser = parser or MinerUCLIParser(
        command=settings.parser.command,
        backend=settings.parser.backend,
        timeout_seconds=settings.parser.timeout_seconds,
        output_root=settings.parser.output_dir,
    )
    service = PaperService(database.SessionLocal, parser)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        database.initialize()
        recovered = database.recover_orphaned_parses()
        _app.state.recovered_orphaned_parses = recovered
        yield

    app = FastAPI(title="Paper Reading Agent", version="0.1.0-s1", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.paper_service = service
    app.include_router(build_health_router(database, settings))
    app.include_router(build_papers_router(service, settings.storage.upload_dir))
    return app


app = create_app()
