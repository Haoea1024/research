"""Paper upload, status, PDF, block, figure, and retry endpoints."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from ..schemas import BlockResponse, FigureResponse, PaperResponse, UploadResponse
from ..services.papers import (
    PaperNotFoundError,
    PaperService,
    PaperStateConflictError,
)


def build_papers_router(service: PaperService, upload_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/api/papers", tags=["papers"])

    @router.post("", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
    def upload_paper(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
    ) -> UploadResponse:
        filename = Path(file.filename or "").name
        if Path(filename).suffix.lower() != ".pdf":
            raise HTTPException(status_code=415, detail="only PDF uploads are accepted")
        first = file.file.read(5)
        if first != b"%PDF-":
            raise HTTPException(status_code=422, detail="uploaded file is not a valid PDF")
        upload_dir.mkdir(parents=True, exist_ok=True)
        destination = upload_dir / f"upload-{uuid4().hex}.pdf"
        try:
            with destination.open("wb") as output:
                output.write(first)
                while chunk := file.file.read(1024 * 1024):
                    output.write(chunk)
            paper = service.create_paper(destination, title=Path(filename).stem or None)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        background_tasks.add_task(service.parse_uploaded, paper.id)
        return UploadResponse(paper_id=paper.id, status="uploaded")

    @router.get("", response_model=list[PaperResponse])
    def list_papers() -> list[PaperResponse]:
        return [PaperResponse.model_validate(paper) for paper in service.list_papers()]

    @router.get("/{paper_id}", response_model=PaperResponse)
    def get_paper(paper_id: str) -> PaperResponse:
        try:
            return PaperResponse.model_validate(service.get_paper(paper_id))
        except PaperNotFoundError as exc:
            raise HTTPException(status_code=404, detail="paper not found") from exc

    @router.get("/{paper_id}/pdf", response_class=FileResponse)
    def get_paper_pdf(paper_id: str) -> FileResponse:
        try:
            paper = service.get_paper(paper_id)
        except PaperNotFoundError as exc:
            raise HTTPException(status_code=404, detail="paper not found") from exc
        pdf_path = Path(paper.pdf_path)
        if not pdf_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="paper PDF is missing from local storage",
            )
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{paper.id}.pdf"',
            },
        )

    @router.get("/{paper_id}/blocks", response_model=list[BlockResponse])
    def get_blocks(paper_id: str) -> list[BlockResponse]:
        try:
            return [BlockResponse.model_validate(block) for block in service.list_blocks(paper_id)]
        except PaperNotFoundError as exc:
            raise HTTPException(status_code=404, detail="paper not found") from exc

    @router.get("/{paper_id}/figures", response_model=list[FigureResponse])
    def get_figures(paper_id: str) -> list[FigureResponse]:
        try:
            figures = service.list_figures(paper_id)
            blocks = {block.id: block for block in service.list_blocks(paper_id)}
            result = []
            for figure in figures:
                parent = blocks.get(figure.block_id)
                caption = blocks.get(figure.caption_block_id) if figure.caption_block_id else None
                caption_text = caption.content_md if caption else (parent.content_md if parent else None)
                if figure.table_html and caption_text:
                    suffix = f"\n\n{figure.table_html}"
                    if caption_text == figure.table_html:
                        caption_text = None
                    elif caption_text.endswith(suffix):
                        caption_text = caption_text[: -len(suffix)] or None
                diagnostics = []
                if caption_text and figure.caption_block_id is None:
                    diagnostics.append("CAPTION_WITHOUT_DISTINCT_BBOX")
                result.append(
                    FigureResponse(
                        id=figure.id,
                        paper_id=figure.paper_id,
                        block_id=figure.block_id,
                        caption_block_id=figure.caption_block_id,
                        image_url=f"/api/figures/{figure.id}/image"
                        if figure.image_path
                        else None,
                        table_html=figure.table_html,
                        caption_text=caption_text,
                        diagnostics=diagnostics,
                        status=figure.status,
                        error=figure.error,
                    )
                )
            return result
        except PaperNotFoundError as exc:
            raise HTTPException(status_code=404, detail="paper not found") from exc

    @router.post("/{paper_id}/retry", response_model=UploadResponse, status_code=202)
    def retry_paper(
        paper_id: str, background_tasks: BackgroundTasks
    ) -> UploadResponse:
        try:
            service.claim_retry(paper_id)
        except PaperNotFoundError as exc:
            raise HTTPException(status_code=404, detail="paper not found") from exc
        except PaperStateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        background_tasks.add_task(service.parse_claimed_retry, paper_id)
        return UploadResponse(paper_id=paper_id, status="parsing")

    return router
