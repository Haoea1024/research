from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import FallbackGuardConfig, TranslationConfig, TranslationProviderConfig
from app.models import Block, GlossaryTerm, Paper, Translation, TranslationProviderCall
from app.provenance import translation_source_hash
from app.translate.glossary import GlossaryService
from app.translate.content import translation_skip_reason
from app.translate.language import chinese_character_ratio, translation_language_ratio
from app.translate.pipeline import TranslationManager, TranslationScopeError
from app.translate.benchmark import run_candidate_benchmark
from app.translate.protection import TermDirective, protect_text
from app.translate.providers import FakeTranslationProvider, ProviderAvailabilityError, ProviderItemResult


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

    def call(self, task: str, messages: list[dict], **kwargs):
        del kwargs
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
            source_number = item["content"].rsplit(" ", 1)[-1]
            value = "English only" if self.always_drift or (self.drift and attempts == 0) else f"这是残差中文译文 {source_number}"
            translations.append({"block_id": item["block_id"], "zh_text": value})
        return response({"translations": translations})


class PartialFailureLLM(FakeLLM):
    def __init__(self) -> None:
        super().__init__()
        self.translate_calls = 0

    def call(self, task: str, messages: list[dict], **kwargs):
        del kwargs
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
                        "zh_text": f"有效残差中文译文 {item['content'].rsplit(' ', 1)[-1]}" if index == 0 else "",
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


def test_reference_lists_and_truncated_parser_fragments_are_skipped() -> None:
    def block(content: str) -> Block:
        return Block(
            id="parser-anomaly",
            paper_id="paper",
            order_idx=0,
            page=0,
            bbox="[0,0,1,1]",
            type="text",
            content_md=content,
            is_translatable=1,
        )

    references = "\n".join(f"[{index}] Author. Paper title." for index in range(1, 8))
    assert translation_skip_reason(block(references)) == "REFERENCE_LIST"
    assert translation_skip_reason(
        block("50-layer ResNet: We replace each 2-layer block in the")
    ) == "MALFORMED_FRAGMENT"
    assert translation_skip_reason(block("A complete sentence ends normally.")) is None


@pytest.mark.parametrize(
    ("source", "translated"),
    [
        ("4.1. ImageNet Classification", "4.1. ImageNet 分类"),
        ("PASCAL VOC", "PASCAL VOC"),
        ("ResNet", "ResNet"),
        ("CIFAR-10", "CIFAR-10"),
    ],
)
def test_title_language_check_allows_preserved_standard_proper_nouns(
    source: str, translated: str
) -> None:
    block = Block(
        id="title",
        paper_id="paper",
        order_idx=0,
        page=0,
        bbox="[0,0,1,1]",
        type="title",
        content_md=source,
        is_translatable=1,
    )
    assert translation_language_ratio(block, translated) >= 0.4


def test_title_language_check_does_not_accept_untranslated_ordinary_words() -> None:
    block = Block(
        id="title",
        paper_id="paper",
        order_idx=0,
        page=0,
        bbox="[0,0,1,1]",
        type="title",
        content_md="4.1. ImageNet Classification",
        is_translatable=1,
    )
    assert translation_language_ratio(block, "4.1. ImageNet Classification") < 0.4
    assert translation_language_ratio(block, "ImageNet") < 0.4


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
                "source_hash": None,
                "provider": None,
                "route": None,
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
        assert valid.zh_text == "有效残差中文译文 0"
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
                source_hash=translation_source_hash("residual source 0"),
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


def test_new_skip_guard_overrides_historical_failed_row_without_deleting_it(database) -> None:
    paper, _ = seed(database)
    with database.session() as session:
        session.get(Block, "b0").content_md = (
            "50-layer ResNet: We replace each 2-layer block in the"
        )
        session.add(
            Translation(
                block_id="b0",
                zh_text="",
                glossary_version=1,
                model="fake/old",
                status="failed",
                error="historical timeout",
            )
        )
    manager = TranslationManager(database.SessionLocal, FakeLLM(), TranslationConfig())

    visible = {item["block_id"]: item for item in manager.translations(paper.id)}
    assert visible["b0"]["status"] == "skipped"
    assert visible["b0"]["skip_reason"] == "MALFORMED_FRAGMENT"
    with database.session() as session:
        assert session.get(Translation, "b0").status == "failed"


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


def hybrid_config(*, retries: int = 0, max_fallback_blocks: int | None = None) -> TranslationConfig:
    return TranslationConfig(
        strategy="hybrid",
        bulk_provider="fake",
        providers={
            "fake": TranslationProviderConfig(
                type="fake", model="fake-translation", retries=retries
            )
        },
        fallback=FallbackGuardConfig(max_blocks=max_fallback_blocks),
    )


def valid_provider_text(item) -> str:
    return item.text.replace("residual source", "残差内容")


def seed_glossary(database, paper_id: str) -> None:
    with database.session() as session:
        session.add(
            GlossaryTerm(
                paper_id=paper_id, source="residual", target="残差", version=1
            )
        )


def test_hybrid_bulk_success_uses_zero_llm_calls(database) -> None:
    paper, _ = seed(database)
    seed_glossary(database, paper.id)
    llm = FakeLLM()
    provider = FakeTranslationProvider(valid_provider_text)
    manager = TranslationManager(
        database.SessionLocal,
        llm,
        hybrid_config(),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0", "b1"])
        await wait_finished(run)
        await manager.close()
        assert run.states == {"b0": "done", "b1": "done"}

    asyncio.run(scenario())
    assert llm.calls == []
    assert len(provider.calls) == 1
    with database.session() as session:
        rows = session.scalars(select(Translation).order_by(Translation.block_id)).all()
        assert {row.route for row in rows} == {"bulk"}
        audit = session.scalars(select(TranslationProviderCall)).one()
        assert audit.status == "success"
        assert audit.attempt == 1


def test_hybrid_quality_failure_falls_back_only_failed_block(database) -> None:
    paper, _ = seed(database)
    seed_glossary(database, paper.id)
    llm = FakeLLM()

    def transform(item):
        if item.item_id == "b1":
            return ProviderItemResult(item_id="b1", translated_text="")
        return valid_provider_text(item)

    provider = FakeTranslationProvider(transform)
    manager = TranslationManager(
        database.SessionLocal,
        llm,
        hybrid_config(max_fallback_blocks=1),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0", "b1"])
        await wait_finished(run)
        await manager.close()
        assert run.states == {"b0": "done", "b1": "done"}

    asyncio.run(scenario())
    assert [task for task, _ in llm.calls] == ["translate"]
    with database.session() as session:
        assert session.get(Translation, "b0").route == "bulk"
        assert session.get(Translation, "b1").route == "fallback"


def test_hybrid_quality_failure_preserves_valid_sibling_without_fallback(database) -> None:
    paper, _ = seed(database)
    seed_glossary(database, paper.id)

    def transform(item):
        if item.item_id == "b1":
            return ProviderItemResult(item_id="b1", translated_text="")
        return valid_provider_text(item)

    provider = FakeTranslationProvider(transform)
    llm = FakeLLM()
    manager = TranslationManager(
        database.SessionLocal,
        llm,
        hybrid_config(max_fallback_blocks=0),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0", "b1"])
        await wait_finished(run)
        await manager.close()
        assert run.states == {"b0": "done", "b1": "failed"}

    asyncio.run(scenario())
    assert llm.calls == []
    with database.session() as session:
        assert session.get(Translation, "b0").route == "bulk"
        failed = session.get(Translation, "b1")
        assert failed.status == "failed"
        assert "FALLBACK_GUARD_EXHAUSTED" in failed.error


def test_hybrid_quality_fallback_is_disabled_until_budget_is_configured(database) -> None:
    paper, _ = seed(database, 1)
    seed_glossary(database, paper.id)
    provider = FakeTranslationProvider(
        lambda item: ProviderItemResult(item_id=item.item_id, translated_text="")
    )
    llm = FakeLLM()
    manager = TranslationManager(
        database.SessionLocal,
        llm,
        hybrid_config(),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0"])
        await wait_finished(run)
        await manager.close()
        assert run.states == {"b0": "failed"}

    asyncio.run(scenario())
    assert llm.calls == []


@pytest.mark.parametrize("code", ["timeout", "rate_limited", "server_error"])
def test_hybrid_availability_failure_never_causes_pro_fallback_storm(database, code) -> None:
    paper, _ = seed(database)
    seed_glossary(database, paper.id)
    llm = FakeLLM()
    provider = FakeTranslationProvider(
        errors=[
            ProviderAvailabilityError(code, "provider unavailable", retryable=True),
            ProviderAvailabilityError(code, "provider unavailable", retryable=True),
        ]
    )
    manager = TranslationManager(
        database.SessionLocal,
        llm,
        hybrid_config(retries=1),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0", "b1", "b2", "b3"])
        await wait_finished(run)
        await manager.close()
        assert run.status == "failed"
        assert run.error_code == "TRANSLATION_PROVIDER_UNAVAILABLE"
        assert set(run.states.values()) == {"pending"}

    asyncio.run(scenario())
    assert len(provider.calls) == 2
    assert llm.calls == []
    with database.session() as session:
        assert session.scalars(select(Translation)).all() == []
        assert len(session.scalars(select(TranslationProviderCall)).all()) == 2


def test_provider_circuit_rejects_followup_run_without_http_attempt(database) -> None:
    paper, _ = seed(database)
    seed_glossary(database, paper.id)
    provider = FakeTranslationProvider(
        errors=[ProviderAvailabilityError("network", "offline", retryable=True)]
    )
    manager = TranslationManager(
        database.SessionLocal,
        FakeLLM(),
        hybrid_config(),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        first = await manager.submit(paper.id, block_ids=["b0"])
        await wait_finished(first)
        second = await manager.submit(paper.id, block_ids=["b1"])
        await wait_finished(second)
        await manager.close()
        assert first.error_code == "TRANSLATION_PROVIDER_UNAVAILABLE"
        assert second.error_code == "TRANSLATION_PROVIDER_UNAVAILABLE"

    asyncio.run(scenario())
    assert len(provider.calls) == 1
    with database.session() as session:
        assert len(session.scalars(select(TranslationProviderCall)).all()) == 1


def test_provider_token_protection_round_trip_and_damage_detection() -> None:
    source = (
        r"Use $\\mathcal{H}(x)$ [12] from https://example.com and a@example.com"
        "<sup>1</sup>."
    )
    protected = protect_text(source, request_scope="ABCDEF12")
    assert len(protected.tokens) == 5
    restored, errors = protected.restore("中文：" + protected.text)
    assert errors == ()
    assert restored == "中文：" + source

    missing, errors = protected.restore(protected.text.replace(protected.tokens[0].placeholder, ""))
    assert missing is None and "count=0" in errors[0]
    duplicate, errors = protected.restore(protected.text + protected.tokens[0].placeholder)
    assert duplicate is None and "count=2" in errors[0]
    unknown, errors = protected.restore(protected.text + "__PA_DEADBEEF_9999__")
    assert unknown is None and any("unknown" in error for error in errors)


def test_glossary_term_policies_are_distinct() -> None:
    protected = protect_text(
        "ResNet uses Residual Learning and ImageNet",
        request_scope="1234ABCD",
        terms=[
            TermDirective("ResNet", "ResNet", "preserve_literal"),
            TermDirective("Residual Learning", "残差学习", "force_target"),
            TermDirective("ImageNet", "ImageNet", "validate_only"),
        ],
    )
    assert len(protected.tokens) == 2
    restored, errors = protected.restore(protected.text)
    assert errors == ()
    assert restored == "ResNet uses 残差学习 and ImageNet"
    assert "ImageNet" in protected.text


def test_hybrid_explicit_retranslate_bypasses_bulk_provider(database) -> None:
    paper, _ = seed(database)
    seed_glossary(database, paper.id)
    provider = FakeTranslationProvider(valid_provider_text)
    llm = FakeLLM()
    manager = TranslationManager(
        database.SessionLocal,
        llm,
        hybrid_config(),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        run = await manager.retranslate("b0")
        await wait_finished(run)
        await manager.close()
        assert run.states == {"b0": "done"}

    asyncio.run(scenario())
    assert provider.calls == []
    assert [task for task, _ in llm.calls] == ["translate"]


def test_hybrid_existing_done_and_failed_are_terminal_cache(database) -> None:
    paper, _ = seed(database)
    source_hash = translation_source_hash("residual source 0")
    with database.session() as session:
        session.add_all([
            Translation(block_id="b0", zh_text="已有译文", glossary_version=1, model="old", status="done", source_hash=source_hash),
            Translation(block_id="b1", zh_text="", glossary_version=1, model="old", status="failed", source_hash=translation_source_hash("residual source 1")),
        ])
    provider = FakeTranslationProvider(valid_provider_text)
    manager = TranslationManager(
        database.SessionLocal,
        FakeLLM(),
        hybrid_config(),
        translation_provider=provider,
    )

    async def scenario():
        run = await manager.submit(paper.id, block_ids=["b0", "b1"])
        assert run.finished
        assert run.states == {"b0": "done", "b1": "failed"}

    asyncio.run(scenario())
    assert provider.calls == []


def test_source_hash_change_invalidates_terminal_cache(database) -> None:
    paper, _ = seed(database, 1)
    seed_glossary(database, paper.id)
    with database.session() as session:
        session.add(
            Translation(
                block_id="b0",
                zh_text="旧译文",
                glossary_version=1,
                model="old",
                status="done",
                source_hash=translation_source_hash("different source"),
            )
        )
    provider = FakeTranslationProvider(valid_provider_text)
    manager = TranslationManager(
        database.SessionLocal,
        FakeLLM(),
        hybrid_config(),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0"])
        await wait_finished(run)
        await manager.close()
        assert run.states == {"b0": "done"}

    asyncio.run(scenario())
    assert len(provider.calls) == 1
    with database.session() as session:
        row = session.get(Translation, "b0")
        assert row.zh_text != "旧译文"
        assert row.source_hash == translation_source_hash("residual source 0")


def test_default_llm_strategy_does_not_invoke_injected_provider(database) -> None:
    paper, _ = seed(database, 1)
    provider = FakeTranslationProvider(valid_provider_text)
    llm = FakeLLM()
    manager = TranslationManager(
        database.SessionLocal,
        llm,
        TranslationConfig(),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        run = await manager.submit(paper.id, block_ids=["b0"])
        await wait_finished(run)
        await manager.close()

    asyncio.run(scenario())
    assert provider.calls == []
    assert [task for task, _ in llm.calls] == ["glossary", "translate"]


def test_hybrid_overlapping_runs_share_one_provider_work_item(database) -> None:
    paper, _ = seed(database)
    seed_glossary(database, paper.id)
    provider = FakeTranslationProvider(valid_provider_text)
    manager = TranslationManager(
        database.SessionLocal,
        FakeLLM(),
        hybrid_config(),
        translation_provider=provider,
    )

    async def scenario():
        await manager.start()
        first, second = await asyncio.gather(
            manager.submit(paper.id, block_ids=["b0", "b1"]),
            manager.submit(paper.id, block_ids=["b0", "b1"]),
        )
        await wait_finished(first)
        await wait_finished(second)
        await manager.close()

    asyncio.run(scenario())
    assert len(provider.calls) == 1


def test_benchmark_candidate_is_read_only(database) -> None:
    _, blocks = seed(database, 1)
    baseline = Translation(
        block_id="b0",
        zh_text="现有基线",
        glossary_version=1,
        model="pro",
        status="done",
        source_hash=translation_source_hash(blocks[0].content_md),
    )
    with database.session() as session:
        session.add(baseline)
    provider = FakeTranslationProvider(valid_provider_text)

    artifact = asyncio.run(
        run_candidate_benchmark(
            provider,
            blocks,
            {"b0": baseline},
            threshold=0.4,
            timeout_seconds=10,
            terms_by_block={"b0": [TermDirective("residual", "残差")]},
        )
    )
    assert artifact.candidates[0].baseline_zh == "现有基线"
    assert artifact.candidates[0].candidate_zh != "现有基线"
    with database.session() as session:
        assert session.get(Translation, "b0").zh_text == "现有基线"
