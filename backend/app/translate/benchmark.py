"""Read-only benchmark seam; candidate results never touch production translations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Sequence

from ..models import Block, Translation
from .protection import TermDirective, protect_text
from .providers import ProviderItem, TranslationProvider
from .validation import validate_final_translation


@dataclass(frozen=True)
class BenchmarkCase:
    block_id: str
    source: str
    baseline_zh: str | None


@dataclass(frozen=True)
class BenchmarkCandidate:
    block_id: str
    source: str
    baseline_zh: str | None
    candidate_zh: str | None
    valid: bool
    errors: tuple[str, ...]
    language_ratio: float


@dataclass(frozen=True)
class BenchmarkArtifact:
    provider: str
    model: str | None
    candidates: tuple[BenchmarkCandidate, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def build_cases(
    blocks: Sequence[Block], rows: dict[str, Translation]
) -> tuple[BenchmarkCase, ...]:
    return tuple(
        BenchmarkCase(
            block_id=block.id,
            source=block.content_md or "",
            baseline_zh=(rows[block.id].zh_text if block.id in rows and rows[block.id].status == "done" else None),
        )
        for block in blocks
    )


async def run_candidate_benchmark(
    provider: TranslationProvider,
    blocks: Sequence[Block],
    rows: dict[str, Translation],
    *,
    threshold: float,
    timeout_seconds: int,
    terms_by_block: dict[str, Sequence[TermDirective]] | None = None,
) -> BenchmarkArtifact:
    """Return a serializable artifact without accepting a Session or writing DB state."""

    cases = build_cases(blocks, rows)
    protected = {
        case.block_id: protect_text(
            case.source,
            request_scope=f"benchmark-{case.block_id}",
            terms=(terms_by_block or {}).get(case.block_id, ()),
        )
        for case in cases
    }
    result = await provider.translate(
        [ProviderItem(case.block_id, protected[case.block_id].text) for case in cases],
        source_language="en",
        target_language="zh",
        timeout_seconds=timeout_seconds,
    )
    returned = {item.item_id: item for item in result.items}
    by_id = {block.id: block for block in blocks}
    candidates = []
    for case in cases:
        item = returned.get(case.block_id)
        restored = None
        errors: tuple[str, ...] = ("BATCH_MAPPING_MISSING",)
        ratio = 0.0
        if item and item.translated_text:
            restored, restore_errors = protected[case.block_id].restore(item.translated_text)
            errors = restore_errors
            if restored is not None and not errors:
                final = validate_final_translation(
                    by_id[case.block_id],
                    restored,
                    threshold=threshold,
                    terms=(terms_by_block or {}).get(case.block_id, ()),
                )
                errors = final.errors
                ratio = final.language_ratio
        candidates.append(
            BenchmarkCandidate(
                block_id=case.block_id,
                source=case.source,
                baseline_zh=case.baseline_zh,
                candidate_zh=restored,
                valid=not errors,
                errors=errors,
                language_ratio=ratio,
            )
        )
    return BenchmarkArtifact(provider.name, provider.model, tuple(candidates))
