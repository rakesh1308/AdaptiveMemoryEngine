"""MCP server: stdio + streamable HTTP. Mirrors server.js 1:1.

Uses the official `mcp` Python SDK. FastMCP for HTTP transport (handles
streamable HTTP + session management internally).
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

import uvicorn
from fastapi import FastAPI

from .config import Config
from .engine import MemoryEngine
from .providers.factory import ProviderFactory

log = logging.getLogger(__name__)

SERVER_NAME = "adaptive-memory-engine"
SERVER_VERSION = "2.0.0"


# ---- result helpers ----

def _text(s: str) -> dict:
    return {"type": "text", "text": s}


def _format_search(results: list[dict]) -> str:
    if not results:
        return "No results."
    lines = [f"=== {len(results)} results ===", ""]
    for r in results:
        m = r["memory"]
        snippet = (m.get("content") or "").replace("\n", " ")[:300]
        lines.append(f"[{m['id']}] score={r['score']:.3f}")
        lines.append(f"  {snippet}{'...' if len(m.get('content','')) > 300 else ''}")
        lines.append("")
    return "\n".join(lines)


def _format_list(items: list[dict]) -> str:
    if not items:
        return "No memories."
    lines = [f"=== {len(items)} memories ==="]
    for m in items:
        snippet = (m.get("content") or "").replace("\n", " ")[:100]
        tags = m.get("tags") or []
        lines.append(f"[{m['id']}] imp={m.get('importance')} tags={','.join(tags)}")
        lines.append(f"  {snippet}...")
    return "\n".join(lines)


# ---- tool registration ----

def _register_tools(mcp, engine: MemoryEngine) -> None:
    """Register all 13 MCP tools. Names + behavior match the Node version."""

    @mcp.tool(
        name="store_memory",
        description="Save content with automatic embeddings and optional AI auto-tagging.",
    )
    def store_memory(key: str, content: str, tags: list[str] | None = None, auto_tag: bool = False) -> str:
        mem = engine.store_memory(key, content, tags=tags, auto_tag=auto_tag, source="mcp")
        return f"Stored memory '{mem['id']}' (importance={mem['importance']})."

    @mcp.tool(name="get_memory", description="Retrieve a memory by key.")
    def get_memory(key: str) -> str:
        mem = engine.recall_memory(key)
        if not mem:
            return f"Not found: {key}"
        return json.dumps(mem, indent=2, ensure_ascii=False)

    @mcp.tool(
        name="update_memory",
        description="Update memory content and/or tags. Set merge_tags=true to union with existing tags.",
    )
    def update_memory(
        key: str,
        content: str | None = None,
        tags: list[str] | None = None,
        merge_tags: bool = False,
    ) -> str:
        mem = engine.update_memory(key, content=content, tags=tags, merge_tags=merge_tags)
        if not mem:
            return f"Not found: {key}"
        return f"Updated '{mem['id']}'."

    @mcp.tool(name="delete_memory", description="Delete a memory by key.")
    def delete_memory(key: str) -> str:
        ok = engine.delete_memory(key)
        return "Deleted." if ok else f"Not found: {key}"

    @mcp.tool(name="search", description="Hybrid semantic + keyword search across memories.")
    def search(query: str, limit: int = 10) -> str:
        results = engine.search_memories(query, top_k=int(limit), mode="hybrid")
        return _format_search(results)

    @mcp.tool(name="smart_search", description="Alias for search (kept for backward compatibility).")
    def smart_search(query: str, limit: int = 10) -> str:
        results = engine.search_memories(query, top_k=int(limit), mode="hybrid")
        return _format_search(results)

    @mcp.tool(name="list_memories", description="List memories, optionally filtered by text or tag.")
    def list_memories(filter: str | None = None, limit: int = 50, tag: str | None = None) -> str:
        items = engine.list_memories(filter_text=filter, tag=tag, limit=int(limit))
        return _format_list(items)

    @mcp.tool(name="query_graph", description="Query the knowledge graph: related concepts or path-finding.")
    def query_graph(concept: str | None = None, depth: int = 1, find_path_to: str | None = None) -> str:
        return json.dumps(
            engine.query_graph(concept=concept, depth=int(depth), find_path_to=find_path_to),
            indent=2,
            ensure_ascii=False,
        )

    @mcp.tool(name="get_stats", description="Show system statistics.")
    def get_stats() -> str:
        return json.dumps(engine.get_stats(), indent=2)

    @mcp.tool(name="backup", description="Create a JSON snapshot of the current state.")
    def backup() -> str:
        info = engine.create_snapshot()
        return json.dumps(info, indent=2)

    @mcp.tool(name="ask", description="Ask a question using retrieved memories as context (RAG-style).")
    def ask(question: str, context_limit: int = 3) -> str:
        return engine.ask(question, context_limit=int(context_limit))

    @mcp.tool(name="summarize", description="Summarize memories matching a query, or specific keys.")
    def summarize(
        query: str | None = None,
        keys: list[str] | None = None,
        style: str = "concise",
    ) -> str:
        return engine.summarize(query=query, keys=keys, style=style)

    @mcp.tool(name="get_provider_info", description="Show the current AI provider configuration.")
    def get_provider_info() -> str:
        cfg = engine.embedding_provider.get_config()
        intel_cfg = engine.intelligence_provider.get_config() if engine.intelligence_provider else None
        return json.dumps(
            {
                "embedding_provider": cfg,
                "intelligence_provider": intel_cfg,
                "intelligence_available": engine.intelligence_provider is not None,
            },
            indent=2,
        )


# ---- transports ----

def _build_mcp_server(engine: MemoryEngine):
    """Create an MCP server with all tools registered."""
    from mcp.server.mcpserver import MCPServer
    mcp = MCPServer(name=SERVER_NAME, version=SERVER_VERSION)
    _register_tools(mcp, engine)
    return mcp


def serve_stdio(engine: MemoryEngine) -> None:
    mcp = _build_mcp_server(engine)
    mcp.run(transport="stdio")


def build_http_app(engine: MemoryEngine):
    """Return a Starlette app exposing /mcp (streamable HTTP), /health, /."""
    mcp = _build_mcp_server(engine)
    base_app = mcp.streamable_http_app()

    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def root(request):
        cfg = Config.load()
        s = engine.get_stats()
        return JSONResponse({
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "description": "Semantic memory for AI assistants.",
            "transport": cfg.transport,
            "mcp_endpoint": "/mcp",
            "health_endpoint": "/health",
            "provider": cfg.provider_type,
            "intelligence_provider": cfg.intelligence_provider or cfg.provider_type,
            "stats": {"memories": s.get("total", 0), "concepts": s.get("concepts", 0)},
        })

    async def health(request):
        s = engine.get_stats()
        return JSONResponse({
            "status": "ok",
            "engineReady": True,
            "memories": s.get("total", 0),
            "concepts": s.get("concepts", 0),
            "embeddings": s.get("withEmbeddings", 0),
            "provider": engine.embedding_provider.get_config(),
        })

    # Add / and /health routes to the existing Starlette app
    base_app.router.routes.insert(0, Route("/", endpoint=root, methods=["GET"]))
    base_app.router.routes.insert(1, Route("/health", endpoint=health, methods=["GET"]))
    return base_app


def serve_http(engine: MemoryEngine, host: str = "0.0.0.0", port: int = 3000) -> None:
    app = build_http_app(engine)
    uvicorn.run(app, host=host, port=port, log_level="info")


def serve() -> None:
    """Entrypoint for `adaptive-memory serve` / Procfile."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = Config.load()
    cfg.ensure_data_dir()
    emb, intel = ProviderFactory.create(cfg)
    engine = MemoryEngine(
        embedding_provider=emb,
        intelligence_provider=intel,
        data_dir=cfg.data_dir,
    )
    engine.initialize()
    log.info("Engine ready: %d memories", len(engine._memories))
    if cfg.transport == "http":
        log.info("Starting HTTP MCP server on 0.0.0.0:%d", cfg.port)
        serve_http(engine, port=cfg.port)
    else:
        log.info("Starting stdio MCP server")
        serve_stdio(engine)


if __name__ == "__main__":
    serve()