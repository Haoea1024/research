"""S1 health endpoint without external paid calls."""

from __future__ import annotations

import os
import shutil
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

from ..config import Settings
from ..db import Database
from ..schemas import HealthResponse


def build_health_router(database: Database, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        components = database.health()
        parser_path = shutil.which(settings.parser.command)
        try:
            parser_version = version("mineru")
        except PackageNotFoundError:
            parser_version = None
        components["parser"] = {
            "status": "ok" if parser_path else "failed",
            "command": settings.parser.command,
            "resolved_path": parser_path,
            "version": parser_version,
            "error": None if parser_path else "MinerU command was not found on PATH",
        }
        configured_tasks = []
        missing_keys = []
        for task, route in settings.llm.tasks.items():
            provider = settings.llm.providers.get(route.provider)
            if provider and os.getenv(provider.api_key_env):
                configured_tasks.append(task)
            else:
                missing_keys.append(task)
        components["llm"] = {
            "status": "ok" if configured_tasks else "not_configured",
            "configured_tasks": configured_tasks,
            "unavailable_tasks": missing_keys,
        }
        overall = "ok"
        if components["database"]["status"] != "ok" or components["parser"]["status"] != "ok":
            overall = "degraded"
        if components["sqlite_vec"]["status"] != "ok":
            overall = "degraded"
        return HealthResponse(status=overall, components=components)

    return router
