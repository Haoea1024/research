"""Pydantic-validated structured output with one validation retry."""

from __future__ import annotations

from typing import Any, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from .client import LLMClient, response_text


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    pass


def call_structured(
    client: LLMClient,
    task: str,
    schema: type[SchemaT],
    messages: Sequence[dict[str, Any]],
) -> SchemaT:
    current_messages = list(messages)
    last_error: ValidationError | None = None
    for validation_attempt in range(2):
        response = client.call(task, current_messages)
        raw_text = response_text(response)
        try:
            return schema.model_validate_json(raw_text)
        except ValidationError as exc:
            last_error = exc
            if validation_attempt == 0:
                current_messages.extend(
                    [
                        {"role": "assistant", "content": raw_text},
                        {
                            "role": "user",
                            "content": (
                                "The JSON failed schema validation. Return corrected JSON only. "
                                f"Validation errors: {exc.json()}"
                            ),
                        },
                    ]
                )
    raise StructuredOutputError(
        f"structured output for task {task!r} failed validation twice: {last_error}"
    ) from last_error
