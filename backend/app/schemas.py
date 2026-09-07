"""S1 API response schemas."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaperResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str | None
    authors: str | None
    year: int | None
    status: str
    parser: str | None
    parser_version: str | None
    error: str | None
    created_at: str | None


class BlockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    paper_id: str
    order_idx: int
    page: int
    bbox: list[float]
    type: str
    content_md: str | None
    confidence: float | None
    is_translatable: bool

    @field_validator("bbox", mode="before")
    @classmethod
    def parse_bbox(cls, value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value


class FigureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    paper_id: str | None
    block_id: str | None
    caption_block_id: str | None
    image_path: str
    table_html: str | None
    caption_text: str | None = None
    diagnostics: list[str] = Field(default_factory=list)
    status: str | None
    error: str | None


class UploadResponse(BaseModel):
    paper_id: str
    status: str


class ErrorResponse(BaseModel):
    code: str
    message: str


class HealthResponse(BaseModel):
    status: str
    components: dict[str, Any]
