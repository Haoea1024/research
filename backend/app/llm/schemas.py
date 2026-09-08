"""Strict structured-output schemas used by S3 translation tasks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GlossaryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)

    @field_validator("source", "target")
    @classmethod
    def strip_term(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("glossary values must not be blank")
        return stripped


class GlossaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terms: list[GlossaryEntry] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_sources(self) -> "GlossaryResult":
        normalized = [term.source.casefold() for term in self.terms]
        if len(normalized) != len(set(normalized)):
            raise ValueError("glossary source terms must be unique")
        return self


class TranslationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1)
    zh_text: str = Field(min_length=1)

    @field_validator("block_id", "zh_text")
    @classmethod
    def strip_translation(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("translation fields must not be blank")
        return stripped


class TranslationBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translations: list[TranslationEntry] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_block_ids(self) -> "TranslationBatchResult":
        block_ids = [item.block_id for item in self.translations]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("translation block ids must be unique")
        return self


def translation_result_schema(expected_ids: set[str]) -> type[TranslationBatchResult]:
    """Create a Pydantic schema whose validation includes exact target identity."""

    expected = frozenset(expected_ids)

    class ExpectedTranslationResult(TranslationBatchResult):
        @model_validator(mode="after")
        def exact_target_ids(self) -> "ExpectedTranslationResult":
            actual = {item.block_id for item in self.translations}
            if actual != expected or len(self.translations) != len(expected):
                raise ValueError(
                    "translation output IDs must exactly equal targets; "
                    f"expected={sorted(expected)!r}, actual={sorted(actual)!r}"
                )
            return self

    return ExpectedTranslationResult
