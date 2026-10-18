import json

import pytest
from starlette.testclient import TestClient

from adaptive_memory.http import build_app
from adaptive_memory.store import MemoryStore
from tests.test_store import FakeEmbedder

TOKEN = "t" * 32
INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
               "clientInfo": {"name": "test", "version": "0"}},
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def client(tmp_path):
    app = build_app(MemoryStore(tmp_path / "m.db", FakeEmbedder()), TOKEN)
    with TestClient(app, base_url="http://memory.example.com") as c:
        yield c


def test_rejects_missing_and_wrong_token(client):
    assert client.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
    bad = {**HEADERS, "Authorization": "Bearer nope"}
    assert client.post("/mcp", json=INIT, headers=bad).status_code == 401


def test_health_is_open(client):
    assert client.get("/health").text == "ok"


def test_valid_token_initializes_mcp(client):
    r = client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert "adaptive-memory" in r.text
