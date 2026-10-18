"""Optional remote mode: the same tools over streamable HTTP, behind a bearer token.

The token is mandatory. Put the server behind HTTPS (a reverse proxy or your host's TLS)
before exposing it to the internet.
"""

from __future__ import annotations

import hmac
import inspect
import os
import sys

from .server import build_server
from .store import MemoryStore

MIN_TOKEN_LENGTH = 24


class BearerAuth:
    """Pure ASGI middleware: every request needs `Authorization: Bearer <token>`."""

    def __init__(self, app, token: str) -> None:
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] == "/health":
            return await self._reply(send, 200, b"ok")
        headers = dict(scope["headers"])
        supplied = headers.get(b"authorization", b"")
        expected = b"Bearer " + self.token
        if not hmac.compare_digest(supplied, expected):
            return await self._reply(send, 401, b"unauthorized")
        await self.app(scope, receive, send)

    @staticmethod
    async def _reply(send, status: int, body: bytes) -> None:
        await send(
            {"type": "http.response.start", "status": status,
             "headers": [(b"content-type", b"text/plain")]}
        )
        await send({"type": "http.response.body", "body": body})


def build_app(store: MemoryStore | None, token: str):
    """ASGI app serving MCP at /mcp. Host-header checks are off because the token protects it."""
    from mcp.server.transport_security import TransportSecuritySettings

    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    mcp = build_server(store)
    if "transport_security" in inspect.signature(mcp.streamable_http_app).parameters:
        app = mcp.streamable_http_app(transport_security=security)  # mcp 2.x
    else:
        mcp = build_server(store, transport_security=security)  # mcp 1.x
        app = mcp.streamable_http_app()
    return BearerAuth(app, token)


def main(argv: list[str]) -> None:
    import uvicorn

    host, port = "127.0.0.1", 8000
    for i, arg in enumerate(argv):
        if arg == "--host":
            host = argv[i + 1]
        elif arg == "--port":
            port = int(argv[i + 1])
    token = os.environ.get("ADAPTIVE_MEMORY_TOKEN", "")
    if len(token) < MIN_TOKEN_LENGTH:
        sys.exit(
            "Set ADAPTIVE_MEMORY_TOKEN to a secret of at least 24 characters. Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    print(f"Serving MCP at http://{host}:{port}/mcp  (send 'Authorization: Bearer <token>')")
    uvicorn.run(build_app(MemoryStore(), token), host=host, port=port, log_level="warning")
