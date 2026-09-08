"""S3 glossary, translation scheduling, and SSE endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from ..schemas import (
    GlossaryTermResponse,
    TranslateRequest,
    TranslateRunResponse,
    TranslationResponse,
    ViewportRequest,
)
from ..translate.pipeline import (
    TranslationManager,
    TranslationNotFoundError,
    TranslationScopeError,
    TranslationStateError,
)


def build_translation_router(manager: TranslationManager) -> APIRouter:
    router = APIRouter(tags=["translations"])

    @router.get("/api/papers/{paper_id}/glossary")
    def get_glossary(
        paper_id: str,
        format: str = Query(default="json", pattern="^(json|csv)$"),
    ):
        try:
            if format == "csv":
                return Response(
                    manager.glossary_csv(paper_id),
                    media_type="text/csv; charset=utf-8",
                    headers={
                        "Content-Disposition": f'attachment; filename="{paper_id}-glossary.csv"'
                    },
                )
            return [
                GlossaryTermResponse(source=item.source, target=item.target, version=item.version)
                for item in manager.glossary_values(paper_id)
            ]
        except TranslationNotFoundError as exc:
            raise HTTPException(status_code=404, detail="paper not found") from exc

    @router.get(
        "/api/papers/{paper_id}/translations",
        response_model=list[TranslationResponse],
    )
    def get_translations(paper_id: str):
        try:
            return manager.translations(paper_id)
        except TranslationNotFoundError as exc:
            raise HTTPException(status_code=404, detail="paper not found") from exc

    @router.post(
        "/api/papers/{paper_id}/translate",
        response_model=TranslateRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def translate(paper_id: str, body: TranslateRequest):
        try:
            run = await manager.submit(
                paper_id, pages=body.pages, block_ids=body.block_ids
            )
            return _run_response(run)
        except TranslationNotFoundError as exc:
            raise HTTPException(status_code=404, detail="paper not found") from exc
        except TranslationScopeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except TranslationStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/api/papers/{paper_id}/translate/stream")
    async def translate_stream(
        paper_id: str,
        request: Request,
        run_id: str,
        last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        try:
            run = manager.run(run_id)
            if run.paper_id != paper_id:
                raise TranslationScopeError("run does not belong to paper")
            last_event_id = int(last_event_id_header) if last_event_id_header else None
        except TranslationNotFoundError as exc:
            raise HTTPException(status_code=404, detail="translation run not found") from exc
        except (TranslationScopeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        async def generate():
            async for event in manager.stream(run_id, last_event_id):
                if await request.is_disconnected():
                    break
                yield {
                    "id": str(event.id),
                    "event": event.event,
                    "data": json.dumps(event.data, ensure_ascii=False),
                }

        return EventSourceResponse(generate())

    @router.post("/api/papers/{paper_id}/viewport", status_code=204)
    async def viewport(paper_id: str, body: ViewportRequest) -> Response:
        try:
            await manager.prioritize_viewport(paper_id, body.visible_block_ids)
            return Response(status_code=204)
        except TranslationNotFoundError as exc:
            raise HTTPException(status_code=404, detail="paper not found") from exc
        except TranslationScopeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post(
        "/api/blocks/{block_id}/retranslate",
        response_model=TranslateRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retranslate(block_id: str):
        try:
            return _run_response(await manager.retranslate(block_id))
        except TranslationNotFoundError as exc:
            raise HTTPException(status_code=404, detail="block not found") from exc
        except TranslationScopeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except TranslationStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router


def _run_response(run) -> TranslateRunResponse:
    return TranslateRunResponse(
        run_id=run.id,
        paper_id=run.paper_id,
        total=len(run.target_ids),
        states=run.states,
    )
