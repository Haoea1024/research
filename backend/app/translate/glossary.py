"""Structured glossary generation, persistence, matching, and CSV export."""

from __future__ import annotations

import asyncio
import csv
import io
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..llm import LLMClient, call_structured
from ..llm.schemas import GlossaryResult
from ..llm.templating import PromptRenderer
from ..models import Block, GlossaryTerm, Paper


@dataclass(frozen=True)
class GlossaryValue:
    source: str
    target: str
    version: int


@dataclass(frozen=True)
class GlossarySource:
    text: str
    entries: tuple[str, ...]


_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\b")
_PROPER_NAME = re.compile(r"\b(?:[A-Z][A-Za-z0-9-]+\s+){1,3}[A-Z][A-Za-z0-9-]+\b")
_DOMAIN_TERM = re.compile(
    r"\b(?:[A-Za-z][A-Za-z0-9-]*\s+){0,3}"
    r"(?:network|networks|learning|mapping|connections?|blocks?|datasets?|"
    r"models?|modules?|architectures?|layers?)\b",
    re.IGNORECASE,
)
_COMMON_ACRONYMS = {"A", "AN", "AND", "AS", "AT", "BY", "FOR", "IN", "OF", "ON", "OR", "THE", "TO"}


class GlossaryService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        llm: LLMClient,
        *,
        source_char_limit: int = 14_000,
        renderer: PromptRenderer | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.llm = llm
        self.source_char_limit = source_char_limit
        self.renderer = renderer or PromptRenderer()
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def ensure(self, paper: Paper, blocks: list[Block]) -> list[GlossaryValue]:
        existing = self.latest(paper.id)
        if existing:
            return existing
        lock = await self._paper_lock(paper.id)
        async with lock:
            existing = self.latest(paper.id)
            if existing:
                return existing
            prompt = self.renderer.render(
                "glossary.md",
                paper_title=paper.title or "Untitled paper",
                source_text=self.build_source(paper, blocks).text,
            )
            result = await asyncio.to_thread(
                call_structured,
                self.llm,
                "glossary",
                GlossaryResult,
                [{"role": "user", "content": prompt}],
            )
            values = [
                GlossaryValue(term.source, term.target, 1)
                for term in result.terms
            ]
            with self.session_factory.begin() as session:
                session.add_all(
                    GlossaryTerm(
                        paper_id=paper.id,
                        source=value.source,
                        target=value.target,
                        version=value.version,
                    )
                    for value in values
                )
            return values

    def latest(self, paper_id: str) -> list[GlossaryValue]:
        with self.session_factory() as session:
            version = session.scalar(
                select(func.max(GlossaryTerm.version)).where(
                    GlossaryTerm.paper_id == paper_id
                )
            )
            if version is None:
                return []
            terms = session.scalars(
                select(GlossaryTerm)
                .where(
                    GlossaryTerm.paper_id == paper_id,
                    GlossaryTerm.version == version,
                )
                .order_by(GlossaryTerm.source)
            ).all()
            return [
                GlossaryValue(term.source, term.target or "", term.version)
                for term in terms
                if term.target
            ]

    def matching_subset(
        self, terms: list[GlossaryValue], text: str
    ) -> list[GlossaryValue]:
        folded = text.casefold()
        return sorted(
            (term for term in terms if term.source.casefold() in folded),
            key=lambda term: (-len(term.source), term.source.casefold()),
        )

    def csv_bytes(self, paper_id: str) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["source", "target", "version"])
        for term in self.latest(paper_id):
            writer.writerow([term.source, term.target, term.version])
        return output.getvalue().encode("utf-8-sig")

    async def _paper_lock(self, paper_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(paper_id, asyncio.Lock())

    def build_source(self, paper: Paper, blocks: list[Block]) -> GlossarySource:
        """Build a stable, boundary-truncated terminology candidate document."""

        ordered = sorted(blocks, key=lambda block: block.order_idx)
        entries: list[str] = []
        self._append_unique(entries, f"[paper-title] {paper.title or 'Untitled paper'}")

        in_abstract = False
        for block in ordered:
            content = (block.content_md or "").strip()
            if not content:
                continue
            if block.type == "title":
                self._append_unique(entries, f"[heading:{block.order_idx}] {content}")
                in_abstract = content.strip("# .").casefold() == "abstract"
                continue
            if in_abstract:
                self._append_unique(entries, f"[abstract:{block.order_idx}] {content}")

        all_text = "\n".join(
            (block.content_md or "").strip() for block in ordered if block.content_md
        )
        counts: Counter[str] = Counter()
        canonical: dict[str, str] = {}
        for pattern in (_ACRONYM, _PROPER_NAME, _DOMAIN_TERM):
            for match in pattern.finditer(all_text):
                term = " ".join(match.group(0).split()).strip(".,:;()[]{}")
                if len(term) < 2 or term.upper() in _COMMON_ACRONYMS:
                    continue
                key = term.casefold()
                counts[key] += 1
                canonical.setdefault(key, term)
        candidates = [
            (canonical[key], count)
            for key, count in counts.items()
            if count >= 2 or _ACRONYM.fullmatch(canonical[key]) is not None
        ]
        for term, count in sorted(candidates, key=lambda item: (-item[1], item[0].casefold(), item[0])):
            self._append_unique(entries, f"[candidate] {term} (frequency={count})")

        accepted: list[str] = []
        length = 0
        for entry in entries:
            addition = len(entry) + (2 if accepted else 0)
            if length + addition > self.source_char_limit:
                continue
            accepted.append(entry)
            length += addition
        return GlossarySource(text="\n\n".join(accepted), entries=tuple(accepted))

    @staticmethod
    def _append_unique(entries: list[str], entry: str) -> None:
        if entry not in entries:
            entries.append(entry)
