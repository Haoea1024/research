"""Per-block validation for translation batches with one bounded correction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from pydantic import ValidationError

from .client import LLMCallContext, LLMClient, response_text
from .schemas import TranslationEntry


@dataclass(frozen=True)
class PartialTranslationResult:
    values: dict[str, str]
    errors: dict[str, str]
    correction_attempted: bool


def call_partial_translations(
    client: LLMClient,
    task: str,
    expected_ids: set[str],
    messages: Sequence[dict[str, Any]],
    *,
    audit_context: LLMCallContext | None = None,
) -> PartialTranslationResult:
    response = client.call(task, messages, audit_context=audit_context)
    raw_text = response_text(response)
    values, errors = _validate_translation_payload(raw_text, expected_ids)
    invalid_ids = expected_ids - values.keys()
    if not invalid_ids:
        return PartialTranslationResult(values, {}, False)

    correction_messages = list(messages)
    correction_messages.extend(
        [
            {"role": "assistant", "content": raw_text},
            {
                "role": "user",
                "content": (
                    "The JSON failed per-block schema validation. Return corrected JSON only "
                    "for exactly these block IDs, with a non-blank zh_text for every ID: "
                    f"{json.dumps(sorted(invalid_ids))}. Validation errors: "
                    f"{json.dumps(errors, ensure_ascii=False)}"
                ),
            },
        ]
    )
    try:
        corrected_response = client.call(
            task, correction_messages, audit_context=audit_context
        )
        corrected_text = response_text(corrected_response)
        corrected, corrected_errors = _validate_translation_payload(
            corrected_text, invalid_ids
        )
    except Exception as exc:
        safe_error = _safe_error(client, exc)
        corrected = {}
        corrected_errors = {block_id: safe_error for block_id in invalid_ids}

    values.update(corrected)
    remaining = {
        block_id: corrected_errors.get(block_id, errors.get(block_id, "missing output"))
        for block_id in expected_ids - values.keys()
    }
    return PartialTranslationResult(values, remaining, True)


def _validate_translation_payload(
    raw_text: str, expected_ids: set[str]
) -> tuple[dict[str, str], dict[str, str]]:
    values: dict[str, str] = {}
    errors: dict[str, str] = {}
    seen: set[str] = set()
    try:
        payload = json.loads(raw_text)
        items = payload.get("translations") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ValueError("translations must be a list")
    except (json.JSONDecodeError, ValueError) as exc:
        return {}, {block_id: f"invalid JSON payload: {exc}" for block_id in expected_ids}

    for item in items:
        block_id = item.get("block_id") if isinstance(item, dict) else None
        if not isinstance(block_id, str) or block_id not in expected_ids:
            continue
        if block_id in seen:
            values.pop(block_id, None)
            errors[block_id] = "duplicate block_id"
            continue
        seen.add(block_id)
        try:
            entry = TranslationEntry.model_validate(item)
        except ValidationError as exc:
            errors[block_id] = exc.errors(include_url=False)[0]["msg"]
        else:
            values[block_id] = entry.zh_text
            errors.pop(block_id, None)

    for block_id in expected_ids - seen:
        errors[block_id] = "missing block_id"
    return values, errors


def _safe_error(client: LLMClient, error: BaseException) -> str:
    sanitizer = getattr(client, "safe_error", None)
    return sanitizer(error) if callable(sanitizer) else f"{type(error).__name__}: {error!r}"
