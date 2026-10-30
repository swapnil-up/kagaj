"""Tests for the shared Gemini structured-JSON client (no network)."""

import json

import pytest

from kagaj_core.llm import (
    GeminiClient,
    GeminiError,
    QuotaError,
    classify_error,
    output_token_budget,
)


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        import copy
        self.calls.append((url, copy.deepcopy(kwargs)))
        return self.responses.pop(0)


def _success(payload):
    return FakeResponse(200, {
        "candidates": [{
            "content": {"parts": [{"text": json.dumps(payload)}]},
            "finishReason": "STOP",
        }],
        "usageMetadata": {"candidatesTokenCount": 10},
    })


def test_structured_returns_parsed_json():
    session = FakeSession([_success({"ok": True})])
    client = GeminiClient(api_key="key", session=session)
    assert client.structured("prompt") == {"ok": True}
    assert session.calls[0][0].endswith("gemini-2.5-flash-lite:generateContent")


def test_structured_retries_transient_status():
    sleeps = []
    session = FakeSession([FakeResponse(503, text="busy"), _success({"n": 1})])
    client = GeminiClient(api_key="key", session=session, sleep=sleeps.append)
    assert client.structured("prompt") == {"n": 1}
    assert sleeps == [5.0]


def test_quota_is_raised_when_retries_are_disabled():
    session = FakeSession([FakeResponse(429, text="quota exhausted")])
    client = GeminiClient(api_key="key", session=session,
                          retry_on_quota=False)
    with pytest.raises(QuotaError):
        client.structured("prompt")


def test_truncated_json_grows_the_budget():
    truncated = FakeResponse(200, {
        "candidates": [{
            "content": {"parts": [{"text": '{"a":'}]},
            "finishReason": "MAX_TOKENS",
        }],
        "usageMetadata": {"candidatesTokenCount": 100},
    })
    session = FakeSession([truncated, _success({"a": 1})])
    client = GeminiClient(api_key="key", session=session,
                          max_output_tokens=10000, sleep=lambda _: None)
    assert client.structured("prompt", budget=1000) == {"a": 1}
    first = session.calls[0][1]["json"]["generationConfig"]["maxOutputTokens"]
    second = session.calls[1][1]["json"]["generationConfig"]["maxOutputTokens"]
    assert first == 1000
    assert second > first


def test_missing_api_key_is_an_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(GeminiError):
        GeminiClient(session=FakeSession([])).structured("prompt")


def test_error_classification_and_budget():
    assert classify_error("rate limit hit") == "rpm"
    assert classify_error("RESOURCE_EXHAUSTED") == "rpd"
    assert classify_error("bad request") == "other"
    assert output_token_budget("x" * 100) == 8192
    assert output_token_budget("x" * 200000) == 65536


def _embedding(values):
    return FakeResponse(200, {"embedding": {"values": values}})


def test_embed_returns_values():
    session = FakeSession([_embedding([0.1, 0.2, 0.3])])
    client = GeminiClient(api_key="key", session=session)
    assert client.embed("hello", model="gemini-embedding-001") == [0.1, 0.2, 0.3]
    url, kwargs = session.calls[0]
    assert url.endswith("gemini-embedding-001:embedContent")
    assert kwargs["json"]["outputDimensionality"] == 768


def test_embed_many_pauses_and_reports_quota():
    session = FakeSession([_embedding([1.0]), FakeResponse(
        429, text="quota exhausted")])
    sleeps = []
    client = GeminiClient(api_key="key", session=session, sleep=sleeps.append)
    with pytest.raises(QuotaError):
        client.embed_many(["a", "b"])
    assert sleeps == []


def test_generate_text_returns_candidate_text():
    session = FakeSession([FakeResponse(200, {
        "candidates": [{"content": {"parts": [{"text": "hello"}]}}]})])
    client = GeminiClient(api_key="key", session=session)
    assert client.generate_text("prompt") == "hello"


def test_generate_text_reports_quota():
    session = FakeSession([FakeResponse(429, text="quota exhausted")])
    client = GeminiClient(api_key="key", session=session,
                          retry_on_quota=False)
    with pytest.raises(QuotaError):
        client.generate_text("prompt")
