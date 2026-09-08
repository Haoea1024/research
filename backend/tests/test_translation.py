from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import TranslationConfig
from app.models import Block, GlossaryTerm, Paper, Translation
from app.translate.glossary import GlossaryService
from app.translate.content import translation_skip_reason
from app.translate.language import chinese_character_ratio
from app.translate.pipeline import TranslationManager, TranslationScopeError


class FakeLLM:
    def __init__(self, *, drift: bool = False, always_drift: bool = False, fail_translate: bool = False, fail_glossary: bool = False, delay: float = 0):
        self.calls: list[tuple[str, list[dict]]] = []
        self.drift = drift
        self.always_drift = always_drift
        self.fail_translate = fail_translate
        self.fail_glossary = fail_glossary
        self.delay = delay
        self._translate_attempts: dict[str, int] = {}
        self._lock = threading.Lock()

    def model_for_task(self, task: str) -> str:
        return f"fake/{task}"

    def call(self, task: str, messages: list[dict]):
        with self._lock:
            self.calls.append((task, messages))
        if self.delay:
            time.sleep(self.delay)
        if task == "glossary":
            if self.fail_glossary:
                raise TimeoutError("fake glossary timeout")
            return response({"terms": [{"source": "residual", "target": "残差"}]})
        if self.fail_translate:
            raise RuntimeError("fake provider failure")
        prompt = messages[-1]["content"]
        marker = "Local blocks:\n" if "Local blocks:\n" in prompt else "Blocks:\n"
        blocks = json.loads(prompt.split(marker, 1)[1])
        targets = [item for item in blocks if not item["context_only"]]
        translations = []
        for item in targets:
            attempts = self._translate_attempts.get(item["block_id"], 0)
            self._translate_attempts[item["block_id"]] = attempts + 1
            value = "English only" if self.always_drift or (self.drift and attempts == 0) else f"这是中文译文 {item['block_id']}"
            translations.append({"block_id": item["block_id"], "zh_text": value})
        return response({"translations": translations})


class PartialFailureLLM(FakeLLM):
    def __init__(self) -> None:
        super().__init__()
        self.translate_calls = 0

    def call(self, task: str, messages: list[dict]):
        if task == "glossary":
            return super().call(task, messages)
        self.calls.append((task, messages))
        self.translate_calls += 1
        original = next(
            message["content"]
            for message in messages
            if isinstance(message.get("content"), str)
            and "Local blocks:\n" in message["content"]
        )
        blocks = json.loads(original.split("Local blocks:\n", 1)[1])
        targets = [item for item in blocks if not item["context_only"]]
        if self.translate_calls == 1:
            payload = {
                "translations": [
                    {
                        "block_id": item["block_id"],
                        "zh_text": "有效中文译文" if index == 0 else "",
                    }
                    for index, item in enumerate(targets)
                ]
            }
        else:
            payload = {
                "translations": [
                    {"block_id": targets[-1]["block_id"], "zh_text": ""}
                ]
            }
        return response(payload)


def response(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def seed(database, count: int = 7) -> tuple[Paper, list[Block]]:
    paper = Paper(
        id="paper-1",
        title="Residual Networks",
        pdf_path=str(Path("fake.pdf").resolve()),
        status="parsed",
    )
    blocks = [
        Block(
            id=f"b{index}",
            paper_id=paper.id,
            order_idx=index,
            page=index // 3,
            bbox="[0, 0, 10, 10]",
            type="formula" if index == 5 else "text",
            content_md=f"residual source {index}",
            is_translatable=0 if index == 5 else 1,
        )
        for index in range(count)
    ]
    with database.session() as session:
        session.add(paper)
        session.add_all(blocks)
    return paper, blocks


async def wait_finished(run, timeout: float = 3) -> None:
    async with asyncio.timeout(timeout):
        while not run.finished:
            await asyncio.sleep(0.01)


def test_chinese_ratio_ignores_noise() -> None:
    assert chinese_character_ratio(r"中文 123, \\alpha") == 1
    assert chinese_character_ratio("English 123") == 0
    assert chinese_character_ratio("译文 https://example.com/a/very/long/path") == 1
    assert chinese_character_ratio("联系 test@example.com 获取资料") == 1


def test_empty_and_metadata_blocks_have_explicit_skip_reasons() -> None:
    def block(content: str) -> Block:
        return Block(
            id="skip",
            paper_id="paper",
            order_idx=0,
            page=0,
            bbox="[0,0,1,1]",
            type="text",
            content_md=content,
            is_translatable=1,
        )

    assert translation_skip_reason(block("   ")) == "EMPTY_CONTENT"
    assert translation_skip_reason(block("<div><br></div>")) == "HTML_ONLY_METADATA"
    assert translation_skip_reason(block("<sup>1</sup> https://example.com/path")) == "URL_METADATA"
    assert translation_skip_reason(block("name@example.com")) == "CONTACT_METADATA"
    assert translation_skip_reason(block("正文中参见 https://example.com 获取完整结果。")) is None


def test_glossary_double_checked_lock_and_csv(database) -> None:
    paper, blocks = seed(database)
    llm = FakeLLM(delay=0.05)
    service = GlossaryService(database.SessionLocal, llm)

    async def scenario():
        first, second = await asyncio.gather(
            service.ensure(paper, blocks), service.ensure(paper, blocks)
        )
        assert first == second

    asyncio.run(scenario())
    assert [task for task, _ in llm.calls] == ["glossary"]
    csv_data = service.csv_bytes(paper.id)
    assert csv_data.startswith(b"\xef\xbb\xbf")
    assert "source,target,version" in csv_data.decode("utf-8-sig")


def test_glossary_candidate_source_is_focused_stable_and_boundary_limited(database) -> None:
    paper, blocks = seed(database)
    paper.title = "Deep Residual Learning"
    blocks[0].type = "title"
    blocks[0].content_md = "Deep Residual Learning for Image Recognition"
    blocks[1].type = "title"
    blocks[1].content_md = "Abstract"
    blocks[2].content_md = "A Residual Network improves a CNN model."
    blocks[3].content_md = "The Residual Network makes optimization easier for CNN systems."
    blocks[4].type = "title"
    blocks[4].content_md = "1. Introduction"
    service = GlossaryService(database.SessionLocal, FakeLLM(), source_char_limit=14_000)

    first = service.build_source(paper, blocks)
    second = service.build_source(paper, list(reversed(blocks)))
    assert first == second
    assert "[paper-title] Deep Residual Learning" in first.text
    assert "[abstract:2]" in first.text
    assert "[heading:4] 1. Introduction" in first.text
    assert "Residual Network" in first.text
    assert "CNN" in first.text

    limited = GlossaryService(database.SessionLocal, FakeLLM(), source_char_limit=180)
    truncated = limited.build_source(paper, blocks)
    assert len(truncated.text) <= 180
    assert truncated.text == "\n\n".join(truncated.entries)
    assert truncated == limited.build_source(paper, blocks)


def test_batch_overlap_cache_and_sse(database) -> None:
    paper, _ = seed(database)
    llm = FakeLLM(delay=0.05)
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig(batch_size=4))

    async def scenario():
        await manager.start()
        run_a = await manager.submit(paper.id, block_ids=["b0", "b1", "b2", "b3"])
        run_b = await manager.submit(paper.id, block_ids=["b0", "b1", "b2", "b3"])
        await wait_finished(run_a)
        await wait_finished(run_b)
        events = []
        async for event in manager.stream(run_b.id):
            events.append(event.event)
        cached = await manager.submit(paper.id, block_ids=["b0", "b1"])
        assert cached.finished
        await manager.close()
        assert "finished" in events
        assert all(state == "done" for state in run_a.states.values())

    asyncio.run(scenario())
    tasks = [task for task, _ in llm.calls]
    assert tasks.count("glossary") == 1
    assert tasks.count("translate") == 1
    translate_prompt = next(messages[-1]["content"] for task, messages in llm.calls if task == "translate")
    local = json.loads(translate_prompt.split("Local blocks:\n", 1)[1])
    assert [item["block_id"] for item in local if not item["context_only"]] == [
        "b0", "b1", "b2", "b3"
    ]
    assert local[-1]["block_id"] == "b4"
    assert local[-1]["context_only"] is True


def test_one_glossary_preparation_serves_multiple_batches(database) -> None:
    paper, _ = seed(database, 6)
    llm = FakeLLM()
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig(batch_size=4))

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id)
        await wait_finished(run)
        await manager.close()

    asyncio.run(scenario())
    tasks = [task for task, _ in llm.calls]
    assert tasks.count("glossary") == 1
    assert tasks.count("translate") == 2


def test_empty_block_is_skipped_without_translation_row(database) -> None:
    paper, blocks = seed(database)
    with database.session() as session:
        session.get(Block, blocks[0].id).content_md = "  "
    llm = FakeLLM()
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig())

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0", "b1"])
        await wait_finished(run)
        await manager.close()
        assert run.states == {"b0": "skipped", "b1": "done"}
        skipped_event = next(
            event
            for event in run.events
            if event.event == "block" and event.data.get("block_id") == "b0"
        )
        assert skipped_event.data == {
            "block_id": "b0",
            "status": "skipped",
            "zh_text": None,
            "error": None,
            "model": None,
            "glossary_version": None,
            "updated_at": None,
            "cached": False,
            "skip_reason": "EMPTY_CONTENT",
        }
        assert any(
            event.event == "progress" and event.data.get("skipped") == 1
            for event in run.events
        )

    asyncio.run(scenario())
    with database.session() as session:
        assert session.get(Translation, "b0") is None
    translate_prompt = next(
        messages[-1]["content"] for task, messages in llm.calls if task == "translate"
    )
    payload = json.loads(translate_prompt.split("Local blocks:\n", 1)[1])
    assert [item["block_id"] for item in payload if not item["context_only"]] == ["b1"]


def test_url_contact_and_document_metadata_never_enter_queue(database) -> None:
    paper, blocks = seed(database, 4)
    contents = {
        "b0": "<sup>1</sup> https://example.com/dataset",
        "b1": "arXiv:1512.03385v1 [cs.CV] 10 Dec 2015",
        "b2": "author@example.com",
        "b3": "A normal technical paragraph about residual learning.",
    }
    with database.session() as session:
        for block_id, content in contents.items():
            session.get(Block, block_id).content_md = content
    llm = FakeLLM()
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig())

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id)
        await wait_finished(run)
        await manager.close()
        assert run.states == {
            "b0": "skipped",
            "b1": "skipped",
            "b2": "skipped",
            "b3": "done",
        }

    asyncio.run(scenario())
    with database.session() as session:
        assert session.scalars(select(Translation)).all()[0].block_id == "b3"


def test_partial_batch_failure_commits_valid_sibling_only(database) -> None:
    paper, _ = seed(database)
    llm = PartialFailureLLM()
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig())

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0", "b1"])
        await wait_finished(run)
        await manager.close()
        assert run.states == {"b0": "done", "b1": "failed"}

    asyncio.run(scenario())
    assert llm.translate_calls == 2
    with database.session() as session:
        valid = session.get(Translation, "b0")
        invalid = session.get(Translation, "b1")
        assert valid.status == "done"
        assert valid.zh_text == "有效中文译文"
        assert valid.error is None
        assert invalid.status == "failed"
        assert invalid.zh_text == ""
        assert invalid.error.startswith("STRUCTURED_OUTPUT_INVALID:")


def test_failed_cache_requires_explicit_retranslate(database) -> None:
    paper, _ = seed(database)
    with database.session() as session:
        session.add(
            Translation(
                block_id="b0",
                zh_text="",
                glossary_version=1,
                model="fake/old",
                status="failed",
                error="old failure",
            )
        )
    llm = FakeLLM()
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig())

    async def scenario():
        cached = await manager.submit(paper.id, block_ids=["b0"])
        assert cached.finished
        assert cached.states == {"b0": "failed"}
        assert list(cached.events)[0].data["cached"] is True
        assert llm.calls == []

        await manager.start()
        retried = await manager.retranslate("b0")
        await wait_finished(retried)
        await manager.close()
        assert retried.states == {"b0": "done"}

    asyncio.run(scenario())
    assert [task for task, _ in llm.calls] == ["translate"]
    with database.session() as session:
        assert session.get(Translation, "b0").status == "done"


def test_glossary_failure_fails_run_without_block_rows_or_translate_calls(database) -> None:
    paper, _ = seed(database)
    llm = FakeLLM(fail_glossary=True)
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig())

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0", "b1", "b2", "b3"])
        await wait_finished(run)
        await manager.close()
        assert run.status == "failed"
        assert set(run.states.values()) == {"pending"}
        assert [event.event for event in run.events][-2:] == ["error", "finished"]
        error = list(run.events)[-2].data
        assert error["block_id"] is None
        assert error["code"] == "GLOSSARY_PREPARATION_FAILED"
        assert error["retryable"] is True

    asyncio.run(scenario())
    assert [task for task, _ in llm.calls] == ["glossary"]
    with database.session() as session:
        assert session.scalars(select(Translation)).all() == []


def test_existing_glossary_skips_glossary_llm_call(database) -> None:
    paper, _ = seed(database)
    with database.session() as session:
        session.add(
            GlossaryTerm(
                paper_id=paper.id, source="residual", target="残差", version=1
            )
        )
    llm = FakeLLM()
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig())

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0"])
        await wait_finished(run)
        await manager.close()

    asyncio.run(scenario())
    assert [task for task, _ in llm.calls] == ["translate"]


def test_pages_are_one_based_intersect_ids_and_reject_foreign(database) -> None:
    paper, _ = seed(database)
    manager = TranslationManager(database.SessionLocal, FakeLLM(), TranslationConfig())

    async def scenario():
        run = await manager.submit(paper.id, pages=[2], block_ids=["b2", "b3", "b4"])
        assert run.target_ids == {"b3", "b4"}
        with pytest.raises(TranslationScopeError):
            await manager.submit(paper.id, block_ids=["foreign"])
        with pytest.raises(TranslationScopeError):
            await manager.submit(paper.id, pages=[0])

    asyncio.run(scenario())


def test_viewport_lazy_priority_selects_visible_then_next(database) -> None:
    paper, _ = seed(database, 12)
    manager = TranslationManager(database.SessionLocal, FakeLLM(), TranslationConfig(batch_size=4))

    async def scenario():
        await manager.submit(paper.id)
        await manager.prioritize_viewport(paper.id, ["b7"])
        batch = await manager._take_batch()
        assert batch[0].block.id == "b7"
        assert batch[0].priority == 0

    asyncio.run(scenario())


def test_language_drift_retries_only_failed_block(database) -> None:
    paper, _ = seed(database)
    llm = FakeLLM(drift=True)
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig())

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0", "b1"])
        await wait_finished(run)
        await manager.close()
        assert run.states == {"b0": "done", "b1": "done"}

    asyncio.run(scenario())
    assert [task for task, _ in llm.calls].count("translate") == 3


def test_second_language_drift_is_persisted_as_failed(database) -> None:
    paper, _ = seed(database)
    manager = TranslationManager(
        database.SessionLocal, FakeLLM(always_drift=True), TranslationConfig()
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0"])
        await wait_finished(run)
        await manager.close()
        assert run.states["b0"] == "failed"

    asyncio.run(scenario())
    with database.session() as session:
        row = session.get(Translation, "b0")
        assert row.zh_text == ""
        assert row.status == "failed"
        assert row.error.startswith("LANGUAGE_DRIFT:")


def test_first_provider_failure_persists_raw_diagnostic(database) -> None:
    paper, _ = seed(database)
    manager = TranslationManager(
        database.SessionLocal, FakeLLM(fail_translate=True), TranslationConfig()
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0"])
        await wait_finished(run)
        await manager.close()

    asyncio.run(scenario())
    with database.session() as session:
        row = session.get(Translation, "b0")
        assert row.status == "failed"
        assert row.zh_text == ""
        assert "fake provider failure" in row.error


def test_sse_disconnect_does_not_cancel_work_and_reconnect_snapshots(database) -> None:
    paper, _ = seed(database)
    manager = TranslationManager(
        database.SessionLocal, FakeLLM(delay=0.05), TranslationConfig()
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0"])
        stream = manager.stream(run.id)
        first = await anext(stream)
        assert first.event == "block"
        await stream.aclose()
        await wait_finished(run)
        reconnected = []
        async for event in manager.stream(run.id):
            reconnected.append(event.event)
        await manager.close()
        assert reconnected[-1] == "finished"
        assert "block" in reconnected

    asyncio.run(scenario())


def test_failed_retranslate_preserves_previous_success(database) -> None:
    paper, _ = seed(database)
    with database.session() as session:
        session.add(
            Translation(
                block_id="b0",
                zh_text="旧的成功译文",
                glossary_version=1,
                model="fake/old",
                status="done",
            )
        )
    llm = FakeLLM(fail_translate=True)
    manager = TranslationManager(database.SessionLocal, llm, TranslationConfig())

    async def scenario():
        await manager.start()
        run = await manager.retranslate("b0")
        await wait_finished(run)
        await manager.close()
        assert any(event.event == "error" for event in run.events)

    asyncio.run(scenario())
    with database.session() as session:
        row = session.get(Translation, "b0")
        assert row.status == "done"
        assert row.zh_text == "旧的成功译文"
        assert row.error is None
    assert "glossary" not in [task for task, _ in llm.calls]
