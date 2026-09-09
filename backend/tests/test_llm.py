from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.config import LLMConfig, ProviderConfig, TaskRoute
from app.llm.client import (
    LLMCallContext,
    LLMCallError,
    LLMClient,
    LLMNotConfiguredError,
    UnknownTaskError,
    redact_sensitive_text,
)
from app.llm.structured import StructuredOutputError, call_structured
from app.llm.schemas import translation_result_schema
from app.models import LLMCall


class Answer(BaseModel):
    value: int


def _config() -> LLMConfig:
    return LLMConfig(
        providers={"fake": ProviderConfig(api_key_env="TEST_LLM_KEY")},
        tasks={"test": TaskRoute(provider="fake", model="model", max_tokens=10)},
    )


def _response(content: str):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        "_hidden_params": {"response_cost": 0.01},
    }


def test_unknown_task_and_missing_key(monkeypatch):
    client = LLMClient(_config(), completion=lambda **kwargs: _response("{}"))
    with pytest.raises(UnknownTaskError):
        client.call("missing", [])
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    with pytest.raises(LLMNotConfiguredError):
        client.call("test", [])


def test_retry_once_and_log_success(monkeypatch, database):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TimeoutError("raw timeout")
        return _response('{"value": 7}')

    client = LLMClient(
        _config(),
        completion=completion,
        session_factory=database.SessionLocal,
        sleeper=lambda _: None,
    )
    response = client.call("test", [{"role": "user", "content": "x"}])
    assert len(calls) == 2
    assert calls[0]["timeout"] == 60
    assert calls[0]["num_retries"] == 0
    assert calls[0]["model"] == "fake/model"
    assert response["choices"][0]["message"]["content"] == '{"value": 7}'
    with database.session() as session:
        records = session.scalars(select(LLMCall).order_by(LLMCall.id)).all()
        assert len(records) == 2
        failed, record = records
        assert failed.status == "timeout"
        assert "raw timeout" in failed.error
        assert failed.tokens_in is None
        assert record.task == "test"
        assert record.status == "success"
        assert record.tokens_in == 3
        assert record.tokens_out == 2
        assert record.cost == 0.01


def test_llm_audit_records_business_context(monkeypatch, database):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    client = LLMClient(
        _config(),
        completion=lambda **kwargs: _response('{"value": 7}'),
        session_factory=database.SessionLocal,
    )
    client.call(
        "test",
        [{"role": "user", "content": "x"}],
        audit_context=LLMCallContext(
            run_id="run-1", entity_ids=("b1", "b2"), route="fallback"
        ),
    )
    with database.session() as session:
        record = session.scalars(select(LLMCall)).one()
        assert record.run_id == "run-1"
        assert record.entity_ids == '["b1", "b2"]'
        assert record.route == "fallback"
        assert record.attempt == 1
        assert record.provider == "fake"


def test_task_route_overrides_timeout_and_retry(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        raise TimeoutError("stop")

    config = _config()
    config.tasks["glossary"] = TaskRoute(
        provider="fake", model="model", timeout_seconds=180, retries=0
    )
    config.tasks["translate"] = TaskRoute(
        provider="fake", model="model", timeout_seconds=60, retries=1
    )
    client = LLMClient(config, completion=completion, sleeper=lambda _: None)
    with pytest.raises(LLMCallError):
        client.call("glossary", [])
    with pytest.raises(LLMCallError):
        client.call("translate", [])
    assert len(calls) == 3
    assert calls[0]["timeout"] == 180
    assert [call["timeout"] for call in calls[1:]] == [60, 60]
    assert all(call["num_retries"] == 0 for call in calls)


def test_failed_attempt_is_persisted_with_redacted_error(monkeypatch, database):
    monkeypatch.setenv("TEST_LLM_KEY", "private-test-key")

    def completion(**kwargs):
        raise RuntimeError(
            "Authorization: Bearer private-test-key api_key=private-test-key"
        )

    config = _config()
    config.retries = 0
    client = LLMClient(
        config, completion=completion, session_factory=database.SessionLocal
    )
    with pytest.raises(LLMCallError):
        client.call("test", [])
    with database.session() as session:
        record = session.scalars(select(LLMCall)).one()
        assert record.status == "error"
        assert record.tokens_in is None
        assert record.tokens_out is None
        assert record.cost is None
        assert "private-test-key" not in record.error
        assert "[REDACTED]" in record.error


def test_logs_openai_nested_cached_tokens(monkeypatch, database):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    payload = _response('{"value": 7}')
    payload["usage"]["prompt_tokens_details"] = {"cached_tokens": 2}
    client = LLMClient(
        _config(), completion=lambda **kwargs: payload, session_factory=database.SessionLocal
    )
    client.call("test", [])
    with database.session() as session:
        assert session.scalars(select(LLMCall)).one().cache_read_tokens == 2


def test_transport_error_keeps_raw_cause(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    client = LLMClient(
        _config(),
        completion=lambda **kwargs: (_ for _ in ()).throw(ValueError("raw failure")),
        sleeper=lambda _: None,
    )
    with pytest.raises(LLMCallError, match="raw failure") as error:
        client.call("test", [])
    assert isinstance(error.value.__cause__, ValueError)


def test_sensitive_auth_values_are_redacted() -> None:
    raw = "Authorization: Bearer secret-value api_key=second-secret token=third-secret"
    safe = redact_sensitive_text(raw, ["secret-value"])
    assert "secret-value" not in safe
    assert "second-secret" not in safe
    assert "third-secret" not in safe
    assert safe.count("[REDACTED]") == 3


def test_images_are_attached_to_last_user_message(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return _response("ok")

    client = LLMClient(_config(), completion=completion)
    client.call(
        "test",
        [{"role": "user", "content": "inspect"}],
        images=["data:image/png;base64,AAAA"],
    )
    assert "images" not in calls[0]
    assert calls[0]["messages"][0]["content"] == [
        {"type": "text", "text": "inspect"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,AAAA"},
        },
    ]


def test_logging_failure_does_not_repeat_successful_paid_call(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return _response('{"value": 7}')

    def broken_session_factory():
        raise RuntimeError("database unavailable")

    client = LLMClient(
        _config(),
        completion=completion,
        session_factory=broken_session_factory,
        sleeper=lambda _: None,
    )
    with pytest.raises(LLMCallError, match="logging failed"):
        client.call("test", [])
    assert len(calls) == 1


def test_structured_validation_retries_once(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    responses = iter([_response('{"value":"bad"}'), _response('{"value":9}')])
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return next(responses)

    client = LLMClient(_config(), completion=completion)
    answer = call_structured(client, "test", Answer, [])
    assert answer.value == 9
    assert len(calls) == 2
    assert "Validation errors" in calls[1]["messages"][-1]["content"]


def test_structured_validation_fails_explicitly(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    client = LLMClient(_config(), completion=lambda **kwargs: _response("{}"))
    with pytest.raises(StructuredOutputError, match="failed validation twice"):
        call_structured(client, "test", Answer, [])


def test_translation_identity_is_part_of_structured_retry(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "not-a-real-key")
    responses = iter(
        [
            _response('{"translations":[{"block_id":"wrong","zh_text":"错误"}]}'),
            _response('{"translations":[{"block_id":"b1","zh_text":"正确"}]}'),
        ]
    )
    client = LLMClient(_config(), completion=lambda **kwargs: next(responses))
    result = call_structured(
        client,
        "test",
        translation_result_schema({"b1"}),
        [{"role": "user", "content": "translate"}],
    )
    assert result.translations[0].block_id == "b1"
