from __future__ import annotations

import httpx

from adaptive_memory_engine.providers import http as provider_http
from adaptive_memory_engine.providers.gemini_provider import GeminiProvider
from adaptive_memory_engine.providers.openai_provider import OpenAIProvider


def test_retry_recovers_from_transient_status(monkeypatch):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        status = 503 if attempts < 3 else 200
        return httpx.Response(status, request=request)

    monkeypatch.setattr(provider_http.time, "sleep", lambda _delay: None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = provider_http.request_with_retry(client, "GET", "https://provider.test")

    assert response.status_code == 200
    assert attempts == 3


def test_retry_does_not_repeat_permanent_client_error(monkeypatch):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, request=request)

    monkeypatch.setattr(provider_http.time, "sleep", lambda _delay: None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = provider_http.request_with_retry(client, "GET", "https://provider.test")

    assert response.status_code == 400
    assert attempts == 1


def test_gemini_uses_header_auth_and_current_stable_defaults():
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, request=request, json={"embedding": {"values": [0.0] * 768}})

    provider = GeminiProvider("gemini-secret")
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        assert len(provider.embed("hello")) == 768
        assert captured is not None
        assert captured.headers["x-goog-api-key"] == "gemini-secret"
        assert "gemini-secret" not in str(captured.url)
        assert provider.embedding_model == "gemini-embedding-001"
        assert provider.chat_model == "gemini-2.5-flash"
    finally:
        provider.close()


def test_openai_json_object_query_expansion(monkeypatch):
    provider = OpenAIProvider("test-key")
    monkeypatch.setattr(provider, "_chat", lambda *_args, **_kwargs: '{"queries":["a","b"]}')
    try:
        assert provider.expand_query("original") == ["a", "b"]
    finally:
        provider.close()
