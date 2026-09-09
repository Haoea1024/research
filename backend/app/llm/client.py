"""Task-routed LiteLLM wrapper with bounded retry and cost logging."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Sequence

from sqlalchemy.orm import Session, sessionmaker

from ..config import LLMConfig
from ..models import LLMCall


class LLMError(RuntimeError):
    pass


class UnknownTaskError(LLMError):
    pass


class LLMNotConfiguredError(LLMError):
    pass


class LLMCallError(LLMError):
    pass


@dataclass(frozen=True)
class LLMCallContext:
    run_id: str | None = None
    entity_ids: tuple[str, ...] = ()
    route: str | None = None


class LLMClient:
    def __init__(
        self,
        config: LLMConfig,
        *,
        completion: Callable[..., Any] | None = None,
        session_factory: sessionmaker[Session] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if completion is None:
            from litellm import completion as litellm_completion

            completion = litellm_completion
        self.config = config
        self.completion = completion
        self.session_factory = session_factory
        self.sleeper = sleeper

    def model_for_task(self, task: str) -> str:
        route = self.config.tasks.get(task)
        if route is None:
            raise UnknownTaskError(f"unknown LLM task: {task}")
        if route.provider not in self.config.providers:
            raise LLMNotConfiguredError(
                f"provider {route.provider!r} for task {task!r} is not configured"
            )
        return route.model if "/" in route.model else f"{route.provider}/{route.model}"

    def provider_for_task(self, task: str) -> str:
        route = self.config.tasks.get(task)
        if route is None:
            raise UnknownTaskError(f"unknown LLM task: {task}")
        return route.provider

    def safe_error(self, error: BaseException) -> str:
        secrets = [
            os.getenv(provider.api_key_env, "")
            for provider in self.config.providers.values()
        ]
        return f"{type(error).__name__}: {redact_sensitive_text(repr(error), secrets)}"

    def call(
        self,
        task: str,
        messages: Sequence[dict[str, Any]],
        *,
        images: Sequence[str] | None = None,
        stream: bool = False,
        audit_context: LLMCallContext | None = None,
    ) -> Any:
        route = self.config.tasks.get(task)
        if route is None:
            raise UnknownTaskError(f"unknown LLM task: {task}")
        provider = self.config.providers.get(route.provider)
        if provider is None:
            raise LLMNotConfiguredError(
                f"provider {route.provider!r} for task {task!r} is not configured"
            )
        api_key = os.getenv(provider.api_key_env)
        if not api_key:
            raise LLMNotConfiguredError(
                f"environment variable {provider.api_key_env!r} is not set"
            )

        model = self.model_for_task(task)
        timeout_seconds = route.timeout_seconds or self.config.timeout_seconds
        retries = route.retries if route.retries is not None else self.config.retries
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _messages_with_images(messages, images),
            "api_key": api_key,
            "timeout": timeout_seconds,
            # LiteLLM/OpenAI defaults may retry internally. Keep retries solely
            # in this audited wrapper so one configured attempt is one request.
            "num_retries": 0,
            "stream": stream,
        }
        if provider.base_url:
            kwargs["api_base"] = provider.base_url
        if route.max_tokens:
            kwargs["max_tokens"] = route.max_tokens
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            started = time.perf_counter()
            try:
                response = self.completion(**kwargs)
            except Exception as exc:
                last_error = exc
                latency_ms = round((time.perf_counter() - started) * 1000)
                self._log_failure(
                    task, model, route.provider, exc, latency_ms, attempt + 1, audit_context
                )
                if attempt < retries:
                    self.sleeper(2**attempt)
                    continue
                break
            latency_ms = round((time.perf_counter() - started) * 1000)
            try:
                self._log_success(
                    task, model, route.provider, response, latency_ms, attempt + 1, audit_context
                )
            except Exception as exc:
                raise LLMCallError(
                    f"LLM task {task!r} succeeded but llm_calls logging failed: {exc!r}"
                ) from exc
            return response
        safe_error = redact_sensitive_text(repr(last_error), [api_key])
        raise LLMCallError(
            f"LLM task {task!r} failed after {retries + 1} attempts: "
            f"{safe_error}"
        ) from last_error

    def _log_success(
        self,
        task: str,
        model: str,
        provider: str,
        response: Any,
        latency_ms: int,
        attempt: int,
        context: LLMCallContext | None,
    ) -> None:
        if self.session_factory is None:
            return
        usage = _value(response, "usage") or {}
        hidden = _value(response, "_hidden_params") or {}
        record = LLMCall(
            task=task,
            model=model,
            tokens_in=_int_value(usage, "prompt_tokens", "input_tokens"),
            tokens_out=_int_value(usage, "completion_tokens", "output_tokens"),
            cache_read_tokens=_cache_read_tokens(usage),
            cost=_float_value(hidden, "response_cost", "cost"),
            latency_ms=latency_ms,
            status="success",
            error=None,
            created_at=datetime.now(UTC).isoformat(),
            run_id=context.run_id if context else None,
            entity_ids=json.dumps(context.entity_ids) if context and context.entity_ids else None,
            route=context.route if context else None,
            attempt=attempt,
            provider=provider,
        )
        self._write_log(record)

    def _log_failure(
        self,
        task: str,
        model: str,
        provider: str,
        error: BaseException,
        latency_ms: int,
        attempt: int,
        context: LLMCallContext | None,
    ) -> None:
        if self.session_factory is None:
            return
        safe_error = self.safe_error(error)
        record = LLMCall(
            task=task,
            model=model,
            tokens_in=None,
            tokens_out=None,
            cache_read_tokens=None,
            cost=None,
            latency_ms=latency_ms,
            status="timeout" if _is_timeout(error) else "error",
            error=safe_error,
            created_at=datetime.now(UTC).isoformat(),
            run_id=context.run_id if context else None,
            entity_ids=json.dumps(context.entity_ids) if context and context.entity_ids else None,
            route=context.route if context else None,
            attempt=attempt,
            provider=provider,
        )
        self._write_log(record)

    def _write_log(self, record: LLMCall) -> None:
        if self.session_factory is None:
            return
        session = self.session_factory()
        try:
            session.add(record)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def response_text(response: Any) -> str:
    choices = _value(response, "choices")
    if not choices:
        raise LLMCallError("LLM response has no choices")
    message = _value(choices[0], "message")
    content = _value(message, "content")
    if not isinstance(content, str):
        raise LLMCallError("LLM response content is not text")
    return content


def _messages_with_images(
    messages: Sequence[dict[str, Any]], images: Sequence[str] | None
) -> list[dict[str, Any]]:
    """Attach OpenAI-compatible image parts to the final user message."""
    result = [dict(message) for message in messages]
    if not images:
        return result
    user_index = next(
        (index for index in range(len(result) - 1, -1, -1)
         if result[index].get("role") == "user"),
        None,
    )
    if user_index is None:
        raise LLMCallError("images require at least one user message")
    content = result[user_index].get("content", "")
    if isinstance(content, str):
        parts: list[dict[str, Any]] = [{"type": "text", "text": content}]
    elif isinstance(content, list):
        parts = list(content)
    else:
        raise LLMCallError("user message content must be text or a content-part list")
    parts.extend(
        {"type": "image_url", "image_url": {"url": image}}
        for image in images
    )
    result[user_index]["content"] = parts
    return result


def _value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _int_value(value: Any, *keys: str) -> int | None:
    for key in keys:
        found = _value(value, key)
        if isinstance(found, int):
            return found
    return None


def _float_value(value: Any, *keys: str) -> float | None:
    for key in keys:
        found = _value(value, key)
        if isinstance(found, (int, float)):
            return float(found)
    return None


def _cache_read_tokens(usage: Any) -> int | None:
    direct = _int_value(usage, "cache_read_input_tokens", "cache_read_tokens")
    if direct is not None:
        return direct
    prompt_details = _value(usage, "prompt_tokens_details")
    return _int_value(prompt_details, "cached_tokens") if prompt_details else None


_AUTHORIZATION = re.compile(
    r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;\"']+"
)
_KEY_VALUE = re.compile(
    r"(?i)((?:api[_-]?key|token)\s*[:=]\s*)[^\s,;\"']+"
)


def redact_sensitive_text(value: str, secrets: Sequence[str] = ()) -> str:
    """Remove configured secrets and common auth fields from persisted errors."""

    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _AUTHORIZATION.sub(r"\1[REDACTED]", redacted)
    return _KEY_VALUE.sub(r"\1[REDACTED]", redacted)


def _is_timeout(error: BaseException) -> bool:
    value = f"{type(error).__name__} {error}".casefold()
    return "timeout" in value or "timed out" in value
