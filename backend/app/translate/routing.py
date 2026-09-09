"""Hybrid routing for bulk translation providers and paid LLM fallback."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy.orm import Session, sessionmaker

from ..config import TranslationConfig, TranslationProviderConfig
from ..llm.client import redact_sensitive_text
from ..models import TranslationProviderCall
from .providers import (
    ProviderAvailabilityError,
    ProviderBatchResult,
    ProviderItem,
    TranslationProvider,
)


@dataclass(frozen=True)
class ProviderRouteResult:
    result: ProviderBatchResult
    attempt_count: int


class TranslationRouter:
    def __init__(
        self,
        config: TranslationConfig,
        *,
        provider: TranslationProvider | None = None,
        session_factory: sessionmaker[Session] | None = None,
        sleeper=asyncio.sleep,
    ) -> None:
        self.config = config
        self.provider = provider
        self.session_factory = session_factory
        self.sleeper = sleeper
        self._fallback_counts: dict[str, int] = {}
        self._fallback_costs: dict[str, float] = {}
        self._circuit_open_until = 0.0

    @property
    def uses_hybrid(self) -> bool:
        return self.config.strategy == "hybrid"

    def provider_config(self) -> TranslationProviderConfig:
        name = self.config.bulk_provider
        if not name or name not in self.config.providers:
            raise ProviderAvailabilityError(
                "authentication",
                "hybrid translation provider is not configured",
                retryable=False,
            )
        if self.provider is None or self.provider.name != name:
            raise ProviderAvailabilityError(
                "authentication",
                f"translation provider adapter {name!r} is not available",
                retryable=False,
            )
        return self.config.providers[name]

    async def bulk(
        self,
        items: Sequence[ProviderItem],
        *,
        run_id: str,
    ) -> ProviderRouteResult:
        provider_config = self.provider_config()
        assert self.provider is not None
        if time.monotonic() < self._circuit_open_until:
            raise ProviderAvailabilityError(
                "circuit_open",
                "translation provider circuit is open after an availability failure",
                retryable=True,
            )
        last_error: ProviderAvailabilityError | None = None
        for attempt in range(1, provider_config.retries + 2):
            started = time.perf_counter()
            try:
                async with asyncio.timeout(provider_config.timeout_seconds):
                    result = await self.provider.translate(
                        items,
                        source_language="en",
                        target_language="zh",
                        timeout_seconds=provider_config.timeout_seconds,
                    )
            except TimeoutError as exc:
                last_error = ProviderAvailabilityError(
                    "timeout", "translation provider timed out", retryable=True
                )
                latency_ms = round((time.perf_counter() - started) * 1000)
                self._audit_failure(
                    run_id, items, provider_config, attempt, last_error, latency_ms
                )
                if attempt <= provider_config.retries:
                    await self.sleeper(2 ** (attempt - 1))
                    continue
                self._circuit_open_until = (
                    time.monotonic() + provider_config.circuit_reset_seconds
                )
                raise last_error from exc
            except ProviderAvailabilityError as exc:
                last_error = exc
                latency_ms = round((time.perf_counter() - started) * 1000)
                self._audit_failure(run_id, items, provider_config, attempt, exc, latency_ms)
                if exc.retryable and attempt <= provider_config.retries:
                    await self.sleeper(2 ** (attempt - 1))
                    continue
                self._circuit_open_until = (
                    time.monotonic() + provider_config.circuit_reset_seconds
                )
                raise
            latency_ms = round((time.perf_counter() - started) * 1000)
            self._audit_success(run_id, items, provider_config, attempt, result, latency_ms)
            return ProviderRouteResult(result=result, attempt_count=attempt)
        assert last_error is not None
        raise last_error

    def reserve_quality_fallbacks(
        self, runs: Sequence[tuple[str, int]]
    ) -> bool:
        guard = self.config.fallback
        if (
            guard.max_blocks is None
            and guard.max_ratio is None
            and guard.estimated_cost_limit is None
        ):
            return False
        for run_id, run_total in runs:
            next_count = self._fallback_counts.get(run_id, 0) + 1
            if guard.max_blocks is not None and next_count > guard.max_blocks:
                return False
            if guard.max_ratio is not None and next_count / max(1, run_total) > guard.max_ratio:
                return False
            if guard.estimated_cost_limit is not None:
                estimate = guard.estimated_cost_per_block
                if estimate is None:
                    return False
                if (
                    self._fallback_costs.get(run_id, 0.0) + estimate
                    > guard.estimated_cost_limit
                ):
                    return False
        for run_id, _ in runs:
            self._fallback_counts[run_id] = self._fallback_counts.get(run_id, 0) + 1
            if guard.estimated_cost_per_block is not None:
                self._fallback_costs[run_id] = (
                    self._fallback_costs.get(run_id, 0.0)
                    + guard.estimated_cost_per_block
                )
        return True

    def _audit_success(self, run_id, items, config, attempt, result, latency_ms) -> None:
        self._write_audit(
            TranslationProviderCall(
                run_id=run_id,
                entity_ids=json.dumps([item.item_id for item in items]),
                route="bulk",
                provider=self.provider.name if self.provider else None,
                model=self.provider.model if self.provider else config.model,
                attempt=attempt,
                status="success",
                chars_in=sum(len(item.text) for item in items),
                chars_out=sum(len(item.translated_text or "") for item in result.items),
                billed_chars=result.usage.billed_chars,
                cost=result.usage.cost,
                estimated_cost=result.usage.estimated_cost,
                currency=result.usage.currency,
                latency_ms=latency_ms,
                request_id=result.request_id,
                error=None,
                created_at=datetime.now(UTC).isoformat(),
            )
        )

    def _audit_failure(self, run_id, items, config, attempt, error, latency_ms) -> None:
        secrets = []
        if config.api_key_env:
            secrets.append(os.getenv(config.api_key_env, ""))
        self._write_audit(
            TranslationProviderCall(
                run_id=run_id,
                entity_ids=json.dumps([item.item_id for item in items]),
                route="bulk",
                provider=self.provider.name if self.provider else self.config.bulk_provider,
                model=self.provider.model if self.provider else config.model,
                attempt=attempt,
                status=error.code,
                chars_in=sum(len(item.text) for item in items),
                chars_out=None,
                billed_chars=None,
                cost=None,
                estimated_cost=None,
                currency=None,
                latency_ms=latency_ms,
                request_id=None,
                error=redact_sensitive_text(f"{type(error).__name__}: {error}", secrets),
                created_at=datetime.now(UTC).isoformat(),
            )
        )

    def _write_audit(self, record: TranslationProviderCall) -> None:
        if self.session_factory is None:
            return
        with self.session_factory.begin() as session:
            session.add(record)
