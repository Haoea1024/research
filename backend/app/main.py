"""FastAPI application factory for S1."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.health import build_health_router
from .api.papers import build_papers_router
from .api.translations import build_translation_router
from .config import Settings, load_settings
from .db import Database
from .parsing.base import Parser
from .parsing.mineru_client import MinerUCLIParser
from .llm import LLMClient
from .services.papers import PaperService
from .translate.pipeline import TranslationManager


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    parser: Parser | None = None,
    llm_client: LLMClient | None = None,
    translation_manager: TranslationManager | None = None,
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
    llm_client = llm_client or LLMClient(
        settings.llm, session_factory=database.SessionLocal
    )
    translation_manager = translation_manager or TranslationManager(
        database.SessionLocal,
        llm_client,
        settings.translation,
        glossary_config=settings.glossary,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        database.initialize()
        recovered = database.recover_orphaned_parses()
        _app.state.recovered_orphaned_parses = recovered
        await translation_manager.start()
        try:
            yield
        finally:
            await translation_manager.close()

    app = FastAPI(title="Paper Reading Agent", version="0.3.0-s3", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.paper_service = service
    app.state.translation_manager = translation_manager
    app.include_router(build_health_router(database, settings))
    app.include_router(build_papers_router(service, settings.storage.upload_dir))
    app.include_router(build_translation_router(translation_manager))
    return app


app = create_app()
