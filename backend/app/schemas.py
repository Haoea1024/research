"""S1 API response schemas."""

from __future__ import annotations

import json
from typing import Any, Literal

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


TranslationStatus = Literal[
    "pending", "queued", "translating", "done", "failed", "skipped"
]


class GlossaryTermResponse(BaseModel):
    source: str
    target: str
    version: int


class TranslationResponse(BaseModel):
    block_id: str
    status: TranslationStatus
    zh_text: str | None = None
    error: str | None = None
    model: str | None = None
    glossary_version: int | None = None
    updated_at: str | None = None
    cached: bool = False
    retranslate_failed: bool = False
    skip_reason: str | None = None


class TranslateRequest(BaseModel):
    pages: list[int] | None = None
    block_ids: list[str] | None = None


class TranslateRunResponse(BaseModel):
    run_id: str
    paper_id: str
    total: int
    states: dict[str, TranslationStatus]


class ViewportRequest(BaseModel):
    visible_block_ids: list[str]
