"""ID-based access to parser-produced figure and table crops."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..services.papers import PaperNotFoundError, PaperService


_ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def build_figures_router(service: PaperService, parser_output_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/api/figures", tags=["figures"])
    output_root = parser_output_dir.resolve()

    @router.get("/{figure_id}/image", response_class=FileResponse)
    def get_figure_image(figure_id: str) -> FileResponse:
        try:
            figure = service.get_figure(figure_id)
        except PaperNotFoundError as exc:
            raise HTTPException(status_code=404, detail="figure image not found") from exc

        image_path = Path(figure.image_path).resolve() if figure.image_path else None
        if (
            image_path is None
            or image_path.suffix.lower() not in _ALLOWED_IMAGE_SUFFIXES
            or not image_path.is_relative_to(output_root)
            or not image_path.is_file()
        ):
            raise HTTPException(status_code=404, detail="figure image not found")

        media_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        return FileResponse(
            image_path,
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f'inline; filename="{figure.id}{image_path.suffix.lower()}"'
                )
            },
        )

    return router
