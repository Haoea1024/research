"""Deterministic provider used only by unit and integration tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .base import ProviderBatchResult, ProviderItem, ProviderItemResult, TranslationProvider


class FakeTranslationProvider(TranslationProvider):
    name = "fake"
    model = "fake-translation"

    def __init__(
        self,
        transform: Callable[[ProviderItem], str | ProviderItemResult] | None = None,
        *,
        errors: Sequence[BaseException] = (),
    ) -> None:
        self.transform = transform or (lambda item: f"这是译文 {item.text}")
        self.errors = list(errors)
        self.calls: list[tuple[ProviderItem, ...]] = []

    async def translate(
        self,
        items: Sequence[ProviderItem],
        *,
        source_language: str,
        target_language: str,
        timeout_seconds: int,
    ) -> ProviderBatchResult:
        del source_language, target_language, timeout_seconds
        self.calls.append(tuple(items))
        if self.errors:
            raise self.errors.pop(0)
        results = []
        for item in items:
            value = self.transform(item)
            results.append(
                value
                if isinstance(value, ProviderItemResult)
                else ProviderItemResult(item_id=item.item_id, translated_text=value)
            )
        return ProviderBatchResult(items=tuple(results), request_id="fake-request")
