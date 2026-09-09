"""Vendor-neutral translation provider protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, Sequence


AvailabilityCode = Literal[
    "timeout",
    "rate_limited",
    "authentication",
    "quota_exhausted",
    "network",
    "server_error",
    "circuit_open",
]


class ProviderAvailabilityError(RuntimeError):
    def __init__(self, code: AvailabilityCode, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderItem:
    item_id: str
    text: str


@dataclass(frozen=True)
class ProviderItemResult:
    item_id: str
    translated_text: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ProviderUsage:
    billed_chars: int | None = None
    cost: float | None = None
    estimated_cost: float | None = None
    currency: str | None = None


@dataclass(frozen=True)
class ProviderBatchResult:
    items: tuple[ProviderItemResult, ...]
    request_id: str | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)


class TranslationProvider(Protocol):
    name: str
    model: str | None

    async def translate(
        self,
        items: Sequence[ProviderItem],
        *,
        source_language: str,
        target_language: str,
        timeout_seconds: int,
    ) -> ProviderBatchResult: ...
