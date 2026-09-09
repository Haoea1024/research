"""Paper persistence and parsing state machine."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from ..models import Block, Figure, Paper
from ..parsing.base import ParseResult, Parser


class PaperNotFoundError(LookupError):
    pass


class PaperStateConflictError(RuntimeError):
    pass


class PaperService:
    def __init__(
        self, session_factory: sessionmaker[Session], parser: Parser
    ) -> None:
        self.session_factory = session_factory
        self.parser = parser

    def create_paper(self, pdf_path: Path, *, title: str | None = None) -> Paper:
        paper = Paper(
            id=str(uuid4()),
            title=title,
            authors=None,
            year=None,
            pdf_path=str(pdf_path.resolve()),
            status="uploaded",
            parser=None,
            parser_version=None,
            error=None,
            created_at=datetime.now(UTC).isoformat(),
        )
        with self._session() as session:
            session.add(paper)
        return paper

    def get_paper(self, paper_id: str) -> Paper:
        with self._session() as session:
            paper = session.get(Paper, paper_id)
            if paper is None:
                raise PaperNotFoundError(paper_id)
            session.expunge(paper)
            return paper

    def list_papers(self) -> list[Paper]:
        with self._session() as session:
            papers = list(
                session.scalars(select(Paper).order_by(Paper.created_at.desc())).all()
            )
            for paper in papers:
                session.expunge(paper)
            return papers

    def list_blocks(self, paper_id: str) -> list[Block]:
        self.get_paper(paper_id)
        with self._session() as session:
            blocks = list(
                session.scalars(
                    select(Block)
                    .where(Block.paper_id == paper_id)
                    .order_by(Block.order_idx)
                ).all()
            )
            for block in blocks:
                session.expunge(block)
            return blocks

    def list_figures(self, paper_id: str) -> list[Figure]:
        self.get_paper(paper_id)
        with self._session() as session:
            figures = list(
                session.scalars(
                    select(Figure)
                    .join(Block, Figure.block_id == Block.id)
                    .where(Figure.paper_id == paper_id)
                    .order_by(Block.order_idx)
                ).all()
            )
            for figure in figures:
                session.expunge(figure)
            return figures

    def get_figure(self, figure_id: str) -> Figure:
        with self._session() as session:
            figure = session.get(Figure, figure_id)
            if figure is None:
                raise PaperNotFoundError(figure_id)
            session.expunge(figure)
            return figure

    def parse_uploaded(self, paper_id: str) -> None:
        if not self._transition(paper_id, "uploaded", "parsing"):
            return
        self._run_parser(paper_id)

    def claim_retry(self, paper_id: str) -> None:
        paper = self.get_paper(paper_id)
        if paper.status != "parse_failed":
            raise PaperStateConflictError(
                f"paper {paper_id} is {paper.status}; only parse_failed can be retried"
            )
        if not self._transition(paper_id, "parse_failed", "parsing"):
            raise PaperStateConflictError(f"paper {paper_id} retry was claimed concurrently")

    def parse_claimed_retry(self, paper_id: str) -> None:
        paper = self.get_paper(paper_id)
        if paper.status != "parsing":
            return
        self._run_parser(paper_id)

    def _run_parser(self, paper_id: str) -> None:
        paper = self.get_paper(paper_id)
        try:
            result = self.parser.parse(Path(paper.pdf_path))
            self._persist_result(paper_id, result)
        except Exception as exc:
            message = (
                exc.persisted_message()
                if hasattr(exc, "persisted_message")
                else f"{type(exc).__name__}: {exc}"
            )
            with self._session() as session:
                session.execute(
                    update(Paper)
                    .where(Paper.id == paper_id)
                    .values(status="parse_failed", error=message)
                )

    def _persist_result(self, paper_id: str, result: ParseResult) -> None:
        with self._session() as session:
            session.execute(delete(Figure).where(Figure.paper_id == paper_id))
            session.execute(delete(Block).where(Block.paper_id == paper_id))
            block_ids: dict[int, str] = {}
            for parsed in result.blocks:
                block_id = f"{paper_id}:{parsed.order_idx}"
                block_ids[parsed.order_idx] = block_id
                session.add(
                    Block(
                        id=block_id,
                        paper_id=paper_id,
                        order_idx=parsed.order_idx,
                        page=parsed.page,
                        bbox=json.dumps(parsed.bbox),
                        type=parsed.type,
                        content_md=parsed.content_md,
                        confidence=parsed.confidence,
                        is_translatable=int(parsed.is_translatable),
                    )
                )
            for parsed in result.figures:
                session.add(
                    Figure(
                        id=f"{paper_id}:figure:{parsed.index}",
                        paper_id=paper_id,
                        block_id=block_ids[parsed.block_order_idx],
                        caption_block_id=block_ids.get(parsed.caption_order_idx)
                        if parsed.caption_order_idx is not None
                        else None,
                        image_path=parsed.image_path,
                        vision_desc=None,
                        table_html=parsed.table_html,
                        model=None,
                        status="pending",
                        error=None,
                    )
                )
            updated = session.execute(
                update(Paper)
                .where(Paper.id == paper_id, Paper.status == "parsing")
                .values(
                    status="parsed",
                    parser=result.parser,
                    parser_version=result.parser_version,
                    error=None,
                )
            )
            if updated.rowcount != 1:
                raise PaperStateConflictError(
                    f"paper {paper_id} left parsing state before result persistence"
                )

    def _transition(self, paper_id: str, expected: str, target: str) -> bool:
        with self._session() as session:
            paper = session.get(Paper, paper_id)
            if paper is None:
                raise PaperNotFoundError(paper_id)
            result = session.execute(
                update(Paper)
                .where(Paper.id == paper_id, Paper.status == expected)
                .values(status=target, error=None)
            )
            return result.rowcount == 1

    def _session(self):
        return _SessionScope(self.session_factory)


class _SessionScope:
    def __init__(self, factory: sessionmaker[Session]):
        self.factory = factory
        self.session: Session | None = None

    def __enter__(self) -> Session:
        self.session = self.factory()
        return self.session

    def __exit__(self, exc_type, exc, traceback) -> None:
        assert self.session is not None
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
