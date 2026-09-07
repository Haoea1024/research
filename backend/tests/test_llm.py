from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.config import LLMConfig, ProviderConfig, TaskRoute
from app.llm.client import LLMCallError, LLMClient, LLMNotConfiguredError, UnknownTaskError
from app.llm.structured import StructuredOutputError, call_structured
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
    assert calls[0]["model"] == "fake/model"
    assert response["choices"][0]["message"]["content"] == '{"value": 7}'
    with database.session() as session:
        record = session.scalars(select(LLMCall)).one()
        assert record.task == "test"
        assert record.tokens_in == 3
        assert record.tokens_out == 2
        assert record.cost == 0.01


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
