"""Guarded S3 live acceptance commands; never prints the configured API key."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from typing import Any, Literal

import litellm
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.config import load_settings
from app.db import Database
from app.llm import LLMClient, call_structured
from app.models import Block, GlossaryTerm, LLMCall, Paper, Translation
from app.translate.pipeline import TranslationManager


class SmokeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True]


class ObservedCompletion:
    def __init__(self) -> None:
        self.http_attempts = 0
        self.max_http_attempts: int | None = None
        self.max_estimated_cost_cny: float | None = None
        self.estimated_cost_cny = 0.0
        self.attempts: list[dict[str, object]] = []

    def __call__(self, **kwargs: Any) -> Any:
        if self.max_http_attempts is not None and self.http_attempts >= self.max_http_attempts:
            raise RuntimeError("LIVE_HTTP_ATTEMPT_LIMIT_REACHED")
        if (
            self.max_estimated_cost_cny is not None
            and self.estimated_cost_cny > self.max_estimated_cost_cny
        ):
            raise RuntimeError("LIVE_ESTIMATED_COST_LIMIT_REACHED")
        self.http_attempts += 1
        started = time.perf_counter()
        try:
            response = litellm.completion(**kwargs)
        except Exception as exc:
            self.attempts.append(
                {
                    "http_attempt": self.http_attempts,
                    "status": "timeout" if "timeout" in type(exc).__name__.casefold() else "error",
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "tokens_in": None,
                    "tokens_out": None,
                    "cache_read_tokens": None,
                    "visible_chinese_chars": None,
                }
            )
            raise
        usage = getattr(response, "usage", None) or {}
        tokens_in = _field(usage, "prompt_tokens")
        tokens_out = _field(usage, "completion_tokens")
        details = _field(usage, "prompt_tokens_details") or {}
        cache_tokens = _field(details, "cached_tokens") or 0
        content = _field(_field(_field(response, "choices")[0], "message"), "content")
        visible_chars = _visible_translation_chars(content)
        self.estimated_cost_cny += (
            (max((tokens_in or 0) - cache_tokens, 0) * 9)
            + (cache_tokens * 0.30)
            + ((tokens_out or 0) * 27)
        ) / 1_000_000
        self.attempts.append(
            {
                "http_attempt": self.http_attempts,
                "status": "success",
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cache_read_tokens": cache_tokens,
                "visible_chinese_chars": visible_chars,
            }
        )
        return response


class InstrumentedClient:
    def __init__(self, client: LLMClient, *, one_call_only: bool = False) -> None:
        self.client = client
        self.one_call_only = one_call_only
        self.task_calls: Counter[str] = Counter()
        self.structured_retries = 0
        self.drift_retries = 0
        self.allowed_tasks: set[str] | None = None

    def model_for_task(self, task: str) -> str:
        return self.client.model_for_task(task)

    def safe_error(self, error: BaseException) -> str:
        return self.client.safe_error(error)

    def call(self, task: str, messages, **kwargs):
        if self.allowed_tasks is not None and task not in self.allowed_tasks:
            raise RuntimeError(f"LIVE_TASK_NOT_AUTHORIZED: {task}")
        if self.one_call_only and sum(self.task_calls.values()) >= 1:
            raise RuntimeError("SMOKE_SECOND_NETWORK_CALL_BLOCKED")
        self.task_calls[task] += 1
        if any(
            isinstance(message.get("content"), str)
            and "The JSON failed schema validation" in message["content"]
            for message in messages
        ):
            self.structured_retries += 1
        first_content = messages[0].get("content", "") if messages else ""
        if isinstance(first_content, str) and first_content.startswith(
            "The previous Chinese translation failed"
        ):
            self.drift_retries += 1
        return self.client.call(task, messages, **kwargs)


def build_runtime(*, smoke: bool):
    settings = load_settings()
    if not os.getenv("PAPER_AGENT_API_KEY"):
        raise RuntimeError("PAPER_AGENT_API_KEY is not set")
    config = settings.llm.model_copy(deep=True)
    if smoke:
        config.retries = 0
        config.tasks["glossary"].max_tokens = 32
    database = Database(settings.database.path)
    database.initialize()
    completion = ObservedCompletion()
    client = LLMClient(
        config,
        completion=completion,
        session_factory=database.SessionLocal,
        sleeper=lambda _seconds: None,
    )
    return settings, database, completion, InstrumentedClient(
        client, one_call_only=smoke
    )


def latest_log_id(database: Database) -> int:
    with database.session() as session:
        return session.scalar(select(func.max(LLMCall.id))) or 0


def logs_after(database: Database, log_id: int) -> list[dict[str, object]]:
    with database.session() as session:
        rows = session.scalars(
            select(LLMCall).where(LLMCall.id > log_id).order_by(LLMCall.id)
        ).all()
        return [
            {
                "id": row.id,
                "task": row.task,
                "model": row.model,
                "tokens_in": row.tokens_in,
                "tokens_out": row.tokens_out,
                "cache_read_tokens": row.cache_read_tokens,
                "cost": row.cost,
                "latency_ms": row.latency_ms,
                "status": row.status,
                "error": row.error,
            }
            for row in rows
        ]


def smoke() -> int:
    _settings, database, completion, client = build_runtime(smoke=True)
    baseline = latest_log_id(database)
    result = call_structured(
        client,
        "glossary",
        SmokeResult,
        [
            {
                "role": "user",
                "content": 'Return exactly this JSON and nothing else: {"ok":true}',
            }
        ],
    )
    print(
        json.dumps(
            {
                "ok": result.ok,
                "http_attempts": completion.http_attempts,
                "structured_retries": client.structured_retries,
                "logs": logs_after(database, baseline),
            },
            ensure_ascii=False,
        )
    )
    return 0


async def page_one() -> int:
    settings, database, completion, client = build_runtime(smoke=False)
    completion.max_http_attempts = 10
    completion.max_estimated_cost_cny = 2.0
    client.allowed_tasks = {"translate"}
    with database.session() as session:
        paper = session.scalars(
            select(Paper).where(Paper.status == "parsed").order_by(Paper.created_at.desc())
        ).first()
        if paper is None:
            raise RuntimeError("parsed paper not found")
        page_blocks = session.scalars(
            select(Block)
            .where(Block.paper_id == paper.id, Block.page == 0)
            .order_by(Block.order_idx)
        ).all()
        selected_ids = [block.id for block in page_blocks if block.is_translatable]
        skipped = Counter(
            block.type for block in page_blocks if not block.is_translatable
        )
        paper_id = paper.id
    if len(selected_ids) != 17:
        raise RuntimeError(f"page 1 scope changed: expected 17, got {len(selected_ids)}")

    baseline = latest_log_id(database)
    manager = TranslationManager(
        database.SessionLocal,
        client,
        settings.translation,
        glossary_config=settings.glossary,
    )
    await manager.start()
    try:
        run = await manager.submit(paper_id, pages=[1])
        if run.target_ids != set(selected_ids):
            raise RuntimeError("page 1 scope identity mismatch")
        async with asyncio.timeout(900):
            async for event in manager.stream(run.id):
                if event.event == "finished":
                    break
        first_counts = dict(client.task_calls)
        first_http_attempts = completion.http_attempts
        with database.session() as session:
            rows = session.scalars(
                select(Translation).where(Translation.block_id.in_(selected_ids))
            ).all()
            statuses = Counter(row.status for row in rows)
            returned_ids = {row.block_id for row in rows}
            glossary_count = session.scalar(
                select(func.count()).select_from(GlossaryTerm).where(
                    GlossaryTerm.paper_id == paper_id
                )
            )
        if returned_ids != set(selected_ids):
            raise RuntimeError("persisted translation IDs do not match page 1 targets")
        cache_model_delta = None
        cache_http_delta = None
        if statuses.get("done", 0) == len(selected_ids):
            cached_run = await manager.submit(paper_id, pages=[1])
            if not cached_run.finished or set(cached_run.states.values()) != {"done"}:
                raise RuntimeError("second page 1 run did not finish entirely from cache")
            cache_model_delta = sum(client.task_calls.values()) - sum(first_counts.values())
            cache_http_delta = completion.http_attempts - first_http_attempts
            if cache_model_delta or cache_http_delta:
                raise RuntimeError(
                    "CACHE_IDEMPOTENCY_FAILED: second request created a model call"
                )
    finally:
        await manager.close()

    print(
        json.dumps(
            {
                "paper_id": paper_id,
                "pages": [1],
                "selected": len(selected_ids),
                "skipped": dict(skipped),
                "statuses": dict(statuses),
                "glossary_terms": glossary_count,
                "task_calls": first_counts,
                "http_attempts": first_http_attempts,
                "structured_retries": client.structured_retries,
                "drift_retries": client.drift_retries,
                "normal_translate_calls": first_counts.get("translate", 0)
                - client.structured_retries
                - client.drift_retries,
                "transport_retries": first_http_attempts
                - first_counts.get("translate", 0),
                "estimated_cost_cny": completion.estimated_cost_cny,
                "attempts": completion.attempts,
                "second_request_new_model_calls": cache_model_delta,
                "second_request_new_http_attempts": cache_http_delta,
                "logs": logs_after(database, baseline),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _visible_translation_chars(content: Any) -> int | None:
    if not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
        translations = payload.get("translations", [])
        return sum(len(item.get("zh_text", "")) for item in translations)
    except (TypeError, ValueError, AttributeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("smoke", "page-one"))
    args = parser.parse_args()
    try:
        return smoke() if args.command == "smoke" else asyncio.run(page_one())
    except Exception as exc:
        try:
            _settings, _database, _completion, client = build_runtime(smoke=True)
            safe_error = client.safe_error(exc)
        except Exception:
            safe_error = f"{type(exc).__name__}: live acceptance failed"
        print(json.dumps({"ok": False, "error": safe_error}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
