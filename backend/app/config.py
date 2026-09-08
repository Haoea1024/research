"""Application configuration loaded from YAML, with secrets kept in env vars."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DatabaseConfig(BaseModel):
    path: Path = Path("data/app.db")


class ParserConfig(BaseModel):
    command: str = "mineru"
    backend: str = "pipeline"
    timeout_seconds: int = Field(default=480, ge=1)
    output_dir: Path = Path("data/parsed")


class StorageConfig(BaseModel):
    upload_dir: Path = Path("data/uploads")


class ProviderConfig(BaseModel):
    api_key_env: str
    base_url: str | None = None


class TaskRoute(BaseModel):
    provider: str
    model: str
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1)
    retries: int | None = Field(default=None, ge=0, le=1)


class LLMConfig(BaseModel):
    timeout_seconds: int = Field(default=60, ge=1)
    retries: int = Field(default=1, ge=0, le=1)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    tasks: dict[str, TaskRoute] = Field(default_factory=dict)


class TranslationConfig(BaseModel):
    batch_size: int = Field(default=4, ge=3, le=5)
    next_screen_blocks: int = Field(default=12, ge=1)
    chinese_ratio_threshold: float = Field(default=0.4, gt=0, le=1)
    event_buffer_size: int = Field(default=256, ge=16)


class GlossaryConfig(BaseModel):
    max_source_chars: int = Field(default=14_000, ge=1_000)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAPER_AGENT_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    parser: ParserConfig = Field(default_factory=ParserConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    glossary: GlossaryConfig = Field(default_factory=GlossaryConfig)
    translation: TranslationConfig = Field(default_factory=TranslationConfig)

    def resolve_paths(self, root: Path = PROJECT_ROOT) -> "Settings":
        copy = self.model_copy(deep=True)
        for owner, field in (
            (copy.database, "path"),
            (copy.parser, "output_dir"),
            (copy.storage, "upload_dir"),
        ):
            value = getattr(owner, field)
            if not value.is_absolute():
                setattr(owner, field, (root / value).resolve())
        return copy


def load_settings(path: Path | None = None) -> Settings:
    config_path = path or PROJECT_ROOT / "config.yaml"
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    data: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if loaded is not None and not isinstance(loaded, dict):
            raise ValueError(f"configuration root must be an object: {config_path}")
        data = loaded or {}
    return Settings(**data).resolve_paths(PROJECT_ROOT)
