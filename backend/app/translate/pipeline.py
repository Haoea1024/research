"""In-memory S3 scheduler with SQLite-backed translation results."""

from __future__ import annotations

import asyncio
import heapq
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import AsyncIterator, Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import GlossaryConfig, TranslationConfig
from ..llm import LLMCallContext, LLMClient, call_structured
from ..llm.partial import PartialTranslationResult, call_partial_translations
from ..llm.schemas import translation_result_schema
from ..llm.templating import PromptRenderer
from ..models import Block, Paper, Translation
from ..provenance import translation_source_hash
from .glossary import GlossaryService, GlossaryValue
from .content import translation_skip_reason
from .language import translation_language_ratio
from .protection import ProtectedText, TermDirective, protect_text
from .providers import ProviderAvailabilityError, ProviderItem, TranslationProvider
from .routing import TranslationRouter
from .validation import FinalValidation, validate_final_translation, validation_json


class TranslationNotFoundError(LookupError):
    pass


class TranslationScopeError(ValueError):
    pass


class TranslationStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    id: int
    event: str
    data: dict[str, object]


@dataclass
class RunState:
    id: str
    paper_id: str
    target_ids: set[str]
    states: dict[str, str]
    events: deque[Event]
    sequence: int = 0
    finished: bool = False
    status: str = "preparing_glossary"
    error: str | None = None
    error_code: str | None = None
    subscribers: set[asyncio.Queue[Event]] = field(default_factory=set)


@dataclass
class WorkItem:
    block: Block
    priority: int
    generation: int
    subscribers: set[str] = field(default_factory=set)
    state: str = "queued"
    retranslate: bool = False
    had_success: bool = False


@dataclass(frozen=True)
class RoutedTranslation:
    text: str
    provider: str
    model: str
    route: str
    validation: FinalValidation


class TranslationManager:
    """One worker, a lazy-invalidated heap, and fan-out to overlapping runs."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        llm: LLMClient,
        config: TranslationConfig,
        *,
        glossary_config: GlossaryConfig | None = None,
        renderer: PromptRenderer | None = None,
        translation_provider: TranslationProvider | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.llm = llm
        self.config = config
        self.renderer = renderer or PromptRenderer()
        self.glossary = GlossaryService(
            session_factory,
            llm,
            source_char_limit=(glossary_config or GlossaryConfig()).max_source_chars,
            renderer=self.renderer,
        )
        self.router = TranslationRouter(
            config,
            provider=translation_provider,
            session_factory=session_factory,
        )
        self._condition = asyncio.Condition()
        self._heap: list[tuple[int, int, int, int, str]] = []
        self._works: dict[str, WorkItem] = {}
        self._priority_overrides: dict[str, int] = {}
        self._runs: dict[str, RunState] = {}
        self._serial = 0
        self._worker: asyncio.Task[None] | None = None
        self._preparations: set[asyncio.Task[None]] = set()
        self._closed = False

    async def start(self) -> None:
        if self._worker is None:
            self._closed = False
            self._worker = asyncio.create_task(self._worker_loop())

    async def close(self) -> None:
        self._closed = True
        preparations = list(self._preparations)
        for task in preparations:
            task.cancel()
        if preparations:
            await asyncio.gather(*preparations, return_exceptions=True)
        async with self._condition:
            self._condition.notify_all()
        if self._worker is not None:
            await self._worker
            self._worker = None

    def glossary_values(self, paper_id: str) -> list[GlossaryValue]:
        self._paper(paper_id)
        return self.glossary.latest(paper_id)

    def glossary_csv(self, paper_id: str) -> bytes:
        self._paper(paper_id)
        return self.glossary.csv_bytes(paper_id)

    def translations(self, paper_id: str) -> list[dict[str, object]]:
        blocks = self._blocks(paper_id, translatable_only=True)
        with self.session_factory() as session:
            rows = {
                row.block_id: row
                for row in session.scalars(
                    select(Translation).where(
                        Translation.block_id.in_([block.id for block in blocks])
                    )
                ).all()
            }
        result = []
        for block in blocks:
            row = rows.get(block.id)
            work = self._works.get(block.id)
            skip_reason = translation_skip_reason(block)
            if skip_reason:
                result.append(
                    self._translation_dict(
                        block.id, "skipped", skip_reason=skip_reason
                    )
                )
                continue
            status = (
                work.state
                if work and work.state in {"queued", "translating"}
                else (row.status if row else "pending")
            )
            result.append(self._translation_dict(block.id, status, row))
        return result

    async def submit(
        self,
        paper_id: str,
        *,
        pages: list[int] | None = None,
        block_ids: list[str] | None = None,
        priority: int | None = None,
    ) -> RunState:
        paper = self._paper(paper_id)
        if paper.status != "parsed":
            raise TranslationStateError(
                f"paper {paper_id} is {paper.status}; only parsed papers can be translated"
            )
        blocks = self._scope(paper_id, pages, block_ids)
        run = RunState(
            id=str(uuid4()),
            paper_id=paper_id,
            target_ids={block.id for block in blocks},
            states={},
            events=deque(maxlen=self.config.event_buffer_size),
        )
        self._runs[run.id] = run
        rows = self._translation_rows(run.target_ids)
        normal_priority = priority if priority is not None else (2 if pages or block_ids else 3)
        pending: list[Block] = []
        for block in blocks:
            row = rows.get(block.id)
            skip_reason = translation_skip_reason(block)
            if skip_reason:
                run.states[block.id] = "skipped"
                self._emit(
                    run,
                    "block",
                    self._translation_dict(
                        block.id, "skipped", skip_reason=skip_reason
                    ),
                )
            elif self._is_cached(row, block):
                run.states[block.id] = row.status
                self._emit(
                    run,
                    "block",
                    self._translation_dict(block.id, row.status, row, cached=True),
                )
            else:
                run.states[block.id] = "pending"
                pending.append(block)
        self._progress(run)
        if pending:
            task = asyncio.create_task(
                self._prepare_run(run, paper, pending, normal_priority)
            )
            self._preparations.add(task)
            task.add_done_callback(self._preparations.discard)
        else:
            self._finish_if_complete(run)
        return run

    async def _prepare_run(
        self,
        run: RunState,
        paper: Paper,
        pending: list[Block],
        priority: int,
    ) -> None:
        try:
            all_blocks = self._blocks(paper.id, translatable_only=False)
            await self.glossary.ensure(paper, all_blocks)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_glossary_preparation(run, self._safe_error(exc))
            return

        run.status = "running"
        rows = self._translation_rows(block.id for block in pending)
        async with self._condition:
            for block in pending:
                row = rows.get(block.id)
                if self._is_cached(row, block):
                    run.states[block.id] = row.status
                    self._emit(
                        run,
                        "block",
                        self._translation_dict(block.id, row.status, row, cached=True),
                    )
                    continue
                work = self._works.get(block.id)
                if work and work.state in {"queued", "translating"}:
                    work.subscribers.add(run.id)
                    run.states[block.id] = work.state
                else:
                    work = WorkItem(
                        block=block,
                        priority=min(priority, self._priority_overrides.pop(block.id, priority)),
                        generation=0,
                    )
                    work.subscribers.add(run.id)
                    self._works[block.id] = work
                    run.states[block.id] = "queued"
                    self._push(work)
            self._condition.notify_all()
        self._progress(run)
        self._finish_if_complete(run)

    def _fail_glossary_preparation(self, run: RunState, error: str) -> None:
        run.status = "failed"
        run.error = error
        run.error_code = "GLOSSARY_PREPARATION_FAILED"
        payload: dict[str, object] = {
            "run_id": run.id,
            "block_id": None,
            "code": "GLOSSARY_PREPARATION_FAILED",
            "retryable": True,
            "error": error,
        }
        self._emit(run, "error", payload)
        run.finished = True
        self._emit(run, "finished", self._progress_data(run))

    async def retranslate(self, block_id: str) -> RunState:
        block = self._block(block_id)
        if not block.is_translatable:
            raise TranslationScopeError(f"block {block_id} is not translatable")
        skip_reason = translation_skip_reason(block)
        if skip_reason:
            raise TranslationScopeError(
                f"block {block_id} is skipped: {skip_reason}"
            )
        paper = self._paper(block.paper_id)
        if paper.status != "parsed":
            raise TranslationStateError(f"paper {paper.id} is not parsed")
        run = RunState(
            id=str(uuid4()),
            paper_id=paper.id,
            target_ids={block.id},
            states={block.id: "queued"},
            events=deque(maxlen=self.config.event_buffer_size),
            status="running",
        )
        self._runs[run.id] = run
        row = self._translation_rows({block.id}).get(block.id)
        async with self._condition:
            work = self._works.get(block.id)
            if work and work.state in {"queued", "translating"}:
                work.subscribers.add(run.id)
            else:
                work = WorkItem(
                    block=block,
                    priority=-1,
                    generation=0,
                    subscribers={run.id},
                    retranslate=True,
                    had_success=bool(row and row.status == "done"),
                )
                self._works[block.id] = work
                self._push(work)
            self._condition.notify_all()
        self._progress(run)
        return run

    async def prioritize_viewport(self, paper_id: str, visible_block_ids: list[str]) -> None:
        blocks = self._blocks(paper_id, translatable_only=False)
        by_id = {block.id: block for block in blocks}
        if any(block_id not in by_id for block_id in visible_block_ids):
            raise TranslationScopeError("visible_block_ids contains a block from another paper")
        visible = [by_id[block_id] for block_id in visible_block_ids]
        maximum = max((block.order_idx for block in visible), default=-1)
        following = [
            block for block in blocks
            if block.is_translatable
            and translation_skip_reason(block) is None
            and block.order_idx > maximum
        ][: self.config.next_screen_blocks]
        priorities = {
            block.id: 0
            for block in visible
            if block.is_translatable and translation_skip_reason(block) is None
        }
        priorities.update({block.id: 1 for block in following})
        async with self._condition:
            for block_id, priority in priorities.items():
                work = self._works.get(block_id)
                if work and work.state == "queued" and priority < work.priority:
                    work.priority = priority
                    work.generation += 1
                    self._push(work)
                elif work is None:
                    previous = self._priority_overrides.get(block_id, priority)
                    self._priority_overrides[block_id] = min(previous, priority)
            self._condition.notify_all()

    async def stream(self, run_id: str, last_event_id: int | None = None) -> AsyncIterator[Event]:
        run = self._runs.get(run_id)
        if run is None:
            raise TranslationNotFoundError(run_id)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        subscribed = not run.finished
        if subscribed:
            # Register before yielding the snapshot so completion cannot fall into
            # the snapshot/subscription gap.
            run.subscribers.add(queue)
        replay = [event for event in run.events if last_event_id is not None and event.id > last_event_id]
        try:
            if last_event_id is None or (last_event_id and not replay):
                for item in self._run_snapshot(run):
                    yield item
            else:
                for event in replay:
                    yield event
            if not subscribed:
                return
            while True:
                event = await queue.get()
                yield event
                if event.event == "finished":
                    return
        finally:
            run.subscribers.discard(queue)

    def run(self, run_id: str) -> RunState:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise TranslationNotFoundError(run_id) from exc

    async def _worker_loop(self) -> None:
        while True:
            batch = await self._take_batch()
            if not batch:
                if self._closed:
                    return
                continue
            await self._process_batch(batch)

    async def _take_batch(self) -> list[WorkItem]:
        async with self._condition:
            while not self._heap and not self._closed:
                await self._condition.wait()
            if self._closed and not self._heap:
                return []
            first: WorkItem | None = None
            while self._heap:
                priority, _order, generation, _serial, block_id = heapq.heappop(self._heap)
                candidate = self._works.get(block_id)
                if candidate and candidate.state == "queued" and candidate.generation == generation and candidate.priority == priority:
                    first = candidate
                    break
            if first is None:
                return []
            batch_limit = self.config.batch_size
            if self.router.uses_hybrid and self.config.bulk_provider:
                provider_config = self.config.providers.get(self.config.bulk_provider)
                if provider_config is not None:
                    batch_limit = min(batch_limit, provider_config.max_batch_size)
            candidates = sorted(
                (
                    work for work in self._works.values()
                    if work.state == "queued"
                    and work.block.paper_id == first.block.paper_id
                    and work.retranslate == first.retranslate
                    and work.priority == first.priority
                    and abs(work.block.order_idx - first.block.order_idx) <= batch_limit
                ),
                key=lambda work: (abs(work.block.order_idx - first.block.order_idx), work.block.order_idx),
            )
            selected = [first]
            for candidate in candidates:
                if candidate is first or len(selected) >= batch_limit:
                    continue
                orders = [item.block.order_idx for item in selected] + [candidate.block.order_idx]
                if max(orders) - min(orders) <= batch_limit - 1:
                    selected.append(candidate)
            selected.sort(key=lambda work: work.block.order_idx)
            for work in selected:
                work.state = "translating"
                for run_id in work.subscribers:
                    run = self._runs.get(run_id)
                    if run:
                        run.states[work.block.id] = "translating"
                        self._emit(run, "block", {"block_id": work.block.id, "status": "translating"})
            return selected

    async def _process_batch(self, batch: list[WorkItem]) -> None:
        paper = self._paper(batch[0].block.paper_id)
        blocks = self._blocks(paper.id, translatable_only=False)
        glossary = self.glossary.latest(paper.id)
        run_id = sorted(batch[0].subscribers)[0] if batch[0].subscribers else "unattached"
        if self.router.uses_hybrid and not batch[0].retranslate:
            try:
                values, errors = await self._call_provider_batch(
                    batch, glossary, run_id=run_id
                )
            except ProviderAvailabilityError as exc:
                await self._fail_provider_availability(batch, exc)
                return
            for work in batch:
                routed = values.get(work.block.id)
                if routed is None:
                    fallback_runs = [
                        (subscriber, len(self._runs[subscriber].target_ids))
                        for subscriber in sorted(work.subscribers)
                        if subscriber in self._runs
                    ]
                    if not self.router.reserve_quality_fallbacks(fallback_runs):
                        await self._complete_failure(
                            work,
                            "FALLBACK_GUARD_EXHAUSTED: "
                            + errors.get(work.block.id, "provider candidate rejected"),
                        )
                        continue
                    try:
                        routed = await self._call_llm_single(
                            paper,
                            blocks,
                            work,
                            glossary,
                            run_id=run_id,
                            route="fallback",
                            rejected=errors.get(work.block.id, "provider candidate rejected"),
                        )
                    except Exception as exc:
                        await self._complete_failure(
                            work, f"FALLBACK_ERROR: {self._safe_error(exc)}"
                        )
                        continue
                await self._complete_success(
                    work,
                    routed.text,
                    glossary[0].version if glossary else 1,
                    provider=routed.provider,
                    model=routed.model,
                    route=routed.route,
                    validation=routed.validation,
                )
            return
        try:
            # Glossary preparation is a run-level gate. Workers only consume the
            # persisted glossary and can never trigger generation per batch.
            result = await self._call_llm_batch(
                paper, blocks, batch, glossary, run_id=run_id
            )
        except Exception as exc:
            await self._fail_batch(batch, self._safe_error(exc))
            return
        for work in batch:
            if work.block.id not in result.values:
                await self._complete_failure(
                    work,
                    "STRUCTURED_OUTPUT_INVALID: "
                    + result.errors.get(work.block.id, "missing valid output"),
                )
                continue
            text = result.values[work.block.id]
            validation = self._validate(work.block, text, glossary)
            if not validation.valid:
                try:
                    routed = await self._call_llm_single(
                        paper,
                        blocks,
                        work,
                        glossary,
                        run_id=run_id,
                        route="explicit_retranslate" if work.retranslate else "llm_validation_retry",
                        rejected=", ".join(validation.errors),
                    )
                except Exception as exc:
                    await self._complete_failure(
                        work, f"VALIDATION_RETRY_ERROR: {self._safe_error(exc)}"
                    )
                    continue
            else:
                routed = RoutedTranslation(
                    text=text,
                    provider=self._llm_provider(),
                    model=self.llm.model_for_task("translate"),
                    route="explicit_retranslate" if work.retranslate else "llm",
                    validation=validation,
                )
            if not routed.validation.valid:
                prefix = (
                    "LANGUAGE_DRIFT: "
                    if "LANGUAGE_DRIFT" in routed.validation.errors
                    else "FINAL_VALIDATION: "
                )
                await self._complete_failure(
                    work, prefix + ", ".join(routed.validation.errors)
                )
            else:
                await self._complete_success(
                    work,
                    routed.text,
                    glossary[0].version if glossary else 1,
                    provider=routed.provider,
                    model=routed.model,
                    route=routed.route,
                    validation=routed.validation,
                )

    async def _call_llm_batch(
        self,
        paper: Paper,
        all_blocks: list[Block],
        batch: list[WorkItem],
        glossary: list[GlossaryValue],
        *,
        run_id: str,
    ) -> PartialTranslationResult:
        targets = [work.block for work in batch]
        local = self._local_blocks(all_blocks, targets)
        target_ids = {block.id for block in targets}
        text = "\n".join(block.content_md or "" for block in local)
        subset = self.glossary.matching_subset(glossary, text)
        prompt = self.renderer.render(
            "translate.md",
            paper_title=paper.title or "Untitled paper",
            glossary_json=json.dumps([term.__dict__ for term in subset], ensure_ascii=False),
            blocks_json=self._blocks_json(local, target_ids),
        )
        return await asyncio.to_thread(
            call_partial_translations,
            self.llm,
            "translate",
            target_ids,
            [{"role": "user", "content": prompt}],
            audit_context=LLMCallContext(
                run_id=run_id,
                entity_ids=tuple(sorted(target_ids)),
                route="explicit_retranslate" if batch[0].retranslate else "llm",
            ),
        )

    async def _call_provider_batch(
        self,
        batch: list[WorkItem],
        glossary: list[GlossaryValue],
        *,
        run_id: str,
    ) -> tuple[dict[str, RoutedTranslation], dict[str, str]]:
        protected: dict[str, ProtectedText] = {}
        items: list[ProviderItem] = []
        for work in batch:
            terms = self._term_directives(glossary, work.block.content_md or "")
            encoded = protect_text(
                work.block.content_md or "",
                request_scope=f"{run_id}-{work.block.id}",
                terms=terms,
            )
            protected[work.block.id] = encoded
            items.append(ProviderItem(work.block.id, encoded.text))
        response = await self.router.bulk(items, run_id=run_id)
        by_id: dict[str, object] = {}
        duplicate_ids: set[str] = set()
        expected = {work.block.id for work in batch}
        for item in response.result.items:
            if item.item_id not in expected:
                continue
            if item.item_id in by_id:
                duplicate_ids.add(item.item_id)
            by_id[item.item_id] = item
        values: dict[str, RoutedTranslation] = {}
        errors: dict[str, str] = {}
        for work in batch:
            block_id = work.block.id
            if block_id in duplicate_ids:
                errors[block_id] = "BATCH_MAPPING_DUPLICATE"
                continue
            item = by_id.get(block_id)
            if item is None:
                errors[block_id] = "BATCH_MAPPING_MISSING"
                continue
            if item.error or not item.translated_text:
                errors[block_id] = f"PROVIDER_CANDIDATE_ERROR: {item.error or 'empty output'}"
                continue
            restored, restore_errors = protected[block_id].restore(item.translated_text)
            if restore_errors or restored is None:
                errors[block_id] = "PLACEHOLDER_INTEGRITY: " + "; ".join(restore_errors)
                continue
            validation = self._validate(work.block, restored, glossary)
            if not validation.valid:
                errors[block_id] = "FINAL_VALIDATION: " + ", ".join(validation.errors)
                continue
            values[block_id] = RoutedTranslation(
                text=restored,
                provider=self.router.provider.name,
                model=self.router.provider.model or "unversioned",
                route="bulk",
                validation=validation,
            )
        return values, errors

    def _term_directives(
        self, glossary: list[GlossaryValue], source: str
    ) -> list[TermDirective]:
        folded = source.casefold()
        result = []
        seen: set[str] = set()
        for term in glossary:
            if term.source.casefold() not in folded:
                continue
            policy = self.config.term_policies.get(
                term.source,
                self.config.term_policies.get(term.source.casefold(), "validate_only"),
            )
            result.append(TermDirective(term.source, term.target, policy))
            seen.add(term.source.casefold())
        for source_term, policy in self.config.term_policies.items():
            if source_term.casefold() in seen or source_term.casefold() not in folded:
                continue
            result.append(TermDirective(source_term, source_term, policy))
        return result

    def _validate(
        self, block: Block, translated: str, glossary: list[GlossaryValue]
    ) -> FinalValidation:
        return validate_final_translation(
            block,
            translated,
            threshold=self.config.chinese_ratio_threshold,
            terms=self._term_directives(glossary, block.content_md or ""),
        )

    async def _fail_provider_availability(
        self, batch: list[WorkItem], error: ProviderAvailabilityError
    ) -> None:
        run_ids = {
            run_id
            for work in batch
            for run_id in work.subscribers
            if run_id in self._runs
        }
        async with self._condition:
            for run_id in run_ids:
                run = self._runs[run_id]
                run.status = "failed"
                run.error_code = "TRANSLATION_PROVIDER_UNAVAILABLE"
                run.error = self._safe_error(error)
                for block_id, state in list(run.states.items()):
                    if state in {"queued", "translating"}:
                        run.states[block_id] = "pending"
                self._emit(
                    run,
                    "error",
                    {
                        "run_id": run.id,
                        "block_id": None,
                        "code": run.error_code,
                        "retryable": error.retryable,
                        "error": run.error,
                    },
                )
                run.finished = True
                self._emit(run, "finished", self._progress_data(run))
            for block_id, work in list(self._works.items()):
                work.subscribers.difference_update(run_ids)
                if not work.subscribers:
                    self._works.pop(block_id, None)
            self._condition.notify_all()

    async def _call_llm_single(
        self,
        paper: Paper,
        all_blocks: list[Block],
        work: WorkItem,
        glossary: list[GlossaryValue],
        *,
        run_id: str,
        route: str,
        rejected: str,
    ) -> RoutedTranslation:
        local = self._local_blocks(all_blocks, [work.block])
        subset = self.glossary.matching_subset(
            glossary, "\n".join(block.content_md or "" for block in local)
        )
        prompt = self.renderer.render(
            "retranslate.md",
            paper_title=paper.title or "Untitled paper",
            chinese_ratio="not-applicable",
            rejected_text=rejected,
            glossary_json=json.dumps([term.__dict__ for term in subset], ensure_ascii=False),
            blocks_json=self._blocks_json(local, {work.block.id}),
        )
        result = await asyncio.to_thread(
            call_structured,
            self.llm,
            "translate",
            translation_result_schema({work.block.id}),
            [{"role": "user", "content": prompt}],
            audit_context=LLMCallContext(
                run_id=run_id,
                entity_ids=(work.block.id,),
                route=route,
            ),
        )
        text = result.translations[0].zh_text
        validation = self._validate(work.block, text, glossary)
        return RoutedTranslation(
            text=text,
            provider=self._llm_provider(),
            model=self.llm.model_for_task("translate"),
            route=route,
            validation=validation,
        )

    async def _complete_success(
        self,
        work: WorkItem,
        text_value: str,
        glossary_version: int,
        *,
        provider: str,
        model: str,
        route: str,
        validation: FinalValidation,
    ) -> None:
        with self.session_factory.begin() as session:
            row = session.get(Translation, work.block.id)
            values = dict(
                zh_text=text_value,
                glossary_version=glossary_version,
                model=model,
                status="done",
                error=None,
                updated_at=datetime.now(UTC).isoformat(),
                source_hash=translation_source_hash(work.block.content_md),
                provider=provider,
                route=route,
                validation_json=json.dumps(validation_json(validation), ensure_ascii=False),
            )
            if row is None:
                session.add(Translation(block_id=work.block.id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        await self._terminal(work, "done", zh_text=text_value)

    async def _complete_failure(self, work: WorkItem, error: str) -> None:
        if not work.had_success:
            model = self._safe_model()
            with self.session_factory.begin() as session:
                row = session.get(Translation, work.block.id)
                values = dict(
                    zh_text="",
                    glossary_version=1,
                    model=model,
                    status="failed",
                    error=error,
                    updated_at=datetime.now(UTC).isoformat(),
                    source_hash=translation_source_hash(work.block.content_md),
                    provider=self._llm_provider() if work.retranslate else (
                        self.router.provider.name if self.router.uses_hybrid and self.router.provider else "llm"
                    ),
                    route="explicit_retranslate" if work.retranslate else (
                        "fallback" if self.router.uses_hybrid else "llm"
                    ),
                    validation_json=None,
                )
                if row is None:
                    session.add(Translation(block_id=work.block.id, **values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
        await self._terminal(work, "done" if work.had_success else "failed", error=error, retranslate_failed=work.had_success)

    async def _fail_batch(self, batch: list[WorkItem], error: str) -> None:
        for work in batch:
            await self._complete_failure(work, error)

    async def _terminal(self, work: WorkItem, status: str, **extra: object) -> None:
        work.state = status
        for run_id in list(work.subscribers):
            run = self._runs.get(run_id)
            if run is None:
                continue
            run.states[work.block.id] = status
            payload: dict[str, object] = {"block_id": work.block.id, "status": status, **extra}
            self._emit(run, "block", payload)
            if extra.get("error"):
                self._emit(run, "error", payload)
            self._progress(run)
            self._finish_if_complete(run)
        self._works.pop(work.block.id, None)

    def _finish_if_complete(self, run: RunState) -> None:
        if not run.finished and all(
            run.states.get(block_id) in {"done", "failed", "skipped"}
            for block_id in run.target_ids
        ):
            run.status = "success"
            run.finished = True
            self._emit(run, "finished", self._progress_data(run))

    def _progress(self, run: RunState) -> None:
        self._emit(run, "progress", self._progress_data(run))

    def _progress_data(self, run: RunState) -> dict[str, object]:
        counts = {
            state: list(run.states.values()).count(state)
            for state in (
                "pending",
                "queued",
                "translating",
                "done",
                "failed",
                "skipped",
            )
        }
        return {
            "run_id": run.id,
            "status": run.status,
            "total": len(run.target_ids),
            **counts,
        }

    def _emit(self, run: RunState, event_type: str, data: dict[str, object]) -> Event:
        run.sequence += 1
        event = Event(run.sequence, event_type, data)
        run.events.append(event)
        for queue in list(run.subscribers):
            queue.put_nowait(event)
        return event

    def _run_snapshot(self, run: RunState) -> list[Event]:
        events: list[Event] = []
        rows = self._translation_rows(run.target_ids)
        for block_id in sorted(run.target_ids):
            row = rows.get(block_id)
            status = run.states.get(block_id, row.status if row else "pending")
            events.append(Event(0, "block", self._translation_dict(block_id, status, row)))
        events.append(Event(0, "progress", self._progress_data(run)))
        if run.finished:
            if run.status == "failed" and run.error:
                events.append(
                    Event(
                        0,
                        "error",
                        {
                            "run_id": run.id,
                            "block_id": None,
                            "code": run.error_code or "TRANSLATION_RUN_FAILED",
                            "retryable": True,
                            "error": run.error,
                        },
                    )
                )
            events.append(Event(0, "finished", self._progress_data(run)))
        return events

    def _push(self, work: WorkItem) -> None:
        self._serial += 1
        heapq.heappush(self._heap, (work.priority, work.block.order_idx, work.generation, self._serial, work.block.id))

    def _scope(self, paper_id: str, pages: list[int] | None, block_ids: list[str] | None) -> list[Block]:
        all_blocks = self._blocks(paper_id, translatable_only=False)
        if pages is not None and any(page < 1 for page in pages):
            raise TranslationScopeError("pages are 1-based and must be positive")
        by_id = {block.id: block for block in all_blocks}
        if block_ids is not None:
            unknown = [block_id for block_id in block_ids if block_id not in by_id]
            if unknown:
                raise TranslationScopeError(f"block_ids contains blocks outside paper: {unknown!r}")
        page_set = set(pages) if pages is not None else None
        id_set = set(block_ids) if block_ids is not None else None
        return [
            block for block in all_blocks
            if block.is_translatable
            and (page_set is None or block.page + 1 in page_set)
            and (id_set is None or block.id in id_set)
        ]

    def _paper(self, paper_id: str) -> Paper:
        with self.session_factory() as session:
            paper = session.get(Paper, paper_id)
            if paper is None:
                raise TranslationNotFoundError(paper_id)
            session.expunge(paper)
            return paper

    def _block(self, block_id: str) -> Block:
        with self.session_factory() as session:
            block = session.get(Block, block_id)
            if block is None:
                raise TranslationNotFoundError(block_id)
            session.expunge(block)
            return block

    def _blocks(self, paper_id: str, *, translatable_only: bool) -> list[Block]:
        self._paper(paper_id)
        with self.session_factory() as session:
            query = select(Block).where(Block.paper_id == paper_id)
            if translatable_only:
                query = query.where(Block.is_translatable == 1)
            blocks = list(session.scalars(query.order_by(Block.order_idx)).all())
            for block in blocks:
                session.expunge(block)
            return blocks

    def _translation_rows(self, block_ids: Iterable[str]) -> dict[str, Translation]:
        ids = list(block_ids)
        if not ids:
            return {}
        with self.session_factory() as session:
            rows = list(session.scalars(select(Translation).where(Translation.block_id.in_(ids))).all())
            for row in rows:
                session.expunge(row)
            return {row.block_id: row for row in rows}

    @staticmethod
    def _is_cached(row: Translation | None, block: Block) -> bool:
        return bool(
            row is not None
            and row.status in {"done", "failed"}
            and row.source_hash == translation_source_hash(block.content_md)
        )

    def _local_blocks(self, all_blocks: list[Block], targets: list[Block]) -> list[Block]:
        indexes = {block.id: index for index, block in enumerate(all_blocks)}
        positions = sorted(indexes[block.id] for block in targets)
        start = max(0, positions[0] - 1)
        end = min(len(all_blocks), positions[-1] + 2)
        return all_blocks[start:end]

    @staticmethod
    def _blocks_json(blocks: list[Block], target_ids: set[str]) -> str:
        return json.dumps(
            [
                {
                    "block_id": block.id,
                    "order_idx": block.order_idx,
                    "type": block.type,
                    "content": block.content_md or "",
                    "context_only": block.id not in target_ids,
                }
                for block in blocks
                if block.id in target_ids or translation_skip_reason(block) is None
            ],
            ensure_ascii=False,
        )

    @staticmethod
    def _translation_dict(
        block_id: str,
        status: str,
        row: Translation | None = None,
        *,
        cached: bool = False,
        skip_reason: str | None = None,
    ) -> dict[str, object]:
        return {
            "block_id": block_id,
            "status": status,
            "zh_text": row.zh_text if row and row.status == "done" else None,
            "error": row.error if row else None,
            "model": row.model if row else None,
            "glossary_version": row.glossary_version if row else None,
            "updated_at": row.updated_at if row else None,
            "cached": cached,
            "skip_reason": skip_reason,
            "source_hash": row.source_hash if row else None,
            "provider": row.provider if row else None,
            "route": row.route if row else None,
        }

    def _safe_model(self) -> str:
        try:
            return self.llm.model_for_task("translate")
        except Exception:
            return "unconfigured"

    def _llm_provider(self) -> str:
        resolver = getattr(self.llm, "provider_for_task", None)
        if callable(resolver):
            try:
                return resolver("translate")
            except Exception:
                pass
        model = self._safe_model()
        return model.split("/", 1)[0] if "/" in model else "llm"

    def _safe_error(self, error: BaseException) -> str:
        sanitizer = getattr(self.llm, "safe_error", None)
        if callable(sanitizer):
            return sanitizer(error)
        return f"{type(error).__name__}: {error!r}"
