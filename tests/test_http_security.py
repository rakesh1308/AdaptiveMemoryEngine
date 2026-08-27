from __future__ import annotations

import httpx
import pytest

from adaptive_memory_engine.server import build_http_app


@pytest.mark.asyncio
async def test_mcp_accepts_proxy_host_when_allowlist_is_unset(engine, monkeypatch):
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    app = build_http_app(engine)
    transport = httpx.ASGITransport(app=app)
    base_app = app.app.app

    async with base_app.router.lifespan_context(base_app), httpx.AsyncClient(
        transport=transport, base_url="https://memory.example.zeabur.app"
    ) as client:
        response = await client.post(
            "/mcp",
            headers={"accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_mcp_rejects_proxy_host_when_allowlist_is_configured(engine, monkeypatch):
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ALLOWED_HOSTS", "approved.example")
    app = build_http_app(engine)
    transport = httpx.ASGITransport(app=app)
    base_app = app.app.app

    async with base_app.router.lifespan_context(base_app), httpx.AsyncClient(
        transport=transport, base_url="https://unapproved.example"
    ) as client:
        response = await client.post("/mcp", json={})
        assert response.status_code == 421


@pytest.mark.asyncio
async def test_rest_requires_configured_bearer_token(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_TOKEN", "test-token-with-sufficient-entropy")
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://client.example")
    monkeypatch.setenv("IMPORT_ROOT", str(tmp_path / "imports"))
    app = build_http_app(engine)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthorized = await client.post(
            "/api/tools/store_memory",
            json={"arguments": {"key": "secure", "content": "secret memory"}},
        )
        assert unauthorized.status_code == 401

        authorized = await client.post(
            "/api/tools/store_memory",
            headers={"Authorization": "Bearer test-token-with-sufficient-entropy"},
            json={"arguments": {"key": "secure", "content": "secret memory"}},
        )
        assert authorized.status_code == 200
        assert engine.sqlite.get("secure") is not None


@pytest.mark.asyncio
async def test_rest_rejects_bad_payload_and_hides_internal_errors(engine, monkeypatch):
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")
    app = build_http_app(engine)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        bad_json = await client.post(
            "/api/tools/store_memory",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
        assert bad_json.status_code == 400

        internal = await client.post(
            "/api/tools/store_memory",
            json={"arguments": {"key": "empty", "content": ""}},
        )
        assert internal.status_code == 500
        assert internal.json() == {"error": "internal_server_error"}
