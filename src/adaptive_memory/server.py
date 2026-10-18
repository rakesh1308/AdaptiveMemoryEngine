"""MCP server (stdio). Seven tools, no configuration required."""

from __future__ import annotations

import json

from .store import MemoryStore

NAME = "adaptive-memory"


def _fmt(m: dict, full: bool = True) -> str:
    tags = f"  [{', '.join(m['tags'])}]" if m["tags"] else ""
    head = f"{m['key']}{tags}  (updated {m['updated_at']})"
    return f"{head}\n{m['content']}" if full else head


def register_tools(mcp, store: MemoryStore) -> None:
    @mcp.tool(
        name="store_memory",
        description=(
            "Save or overwrite one fact. Use a short slash-style key (e.g. 'project/db-choice'). "
            "One fact per memory. Never store secrets, passwords or API keys."
        ),
    )
    def store_memory(key: str, content: str, tags: list[str] | None = None) -> str:
        r = store.store(key, content, tags)
        return f"{'Updated' if r['updated'] else 'Stored'} '{r['key']}'."

    @mcp.tool(name="get_memory", description="Read one memory by its exact key.")
    def get_memory(key: str) -> str:
        m = store.get(key)
        return _fmt(m) if m else f"No memory with key '{key}'."

    @mcp.tool(
        name="search",
        description="Find memories by meaning and keywords. Use this before answering questions about past decisions or preferences.",
    )
    def search(query: str, limit: int = 5) -> str:
        results, mode = store.search(query, max(1, min(limit, 25)))
        if not results:
            return "No matching memories."
        body = "\n\n".join(_fmt(m) for m in results)
        note = "" if mode == "hybrid" else "\n\n(keyword-only: embeddings unavailable)"
        return body + note

    @mcp.tool(name="list_memories", description="List recent memories, optionally by tag.")
    def list_memories(tag: str | None = None, limit: int = 50) -> str:
        items = store.list(tag, max(1, min(limit, 200)))
        return "\n".join(_fmt(m, full=False) for m in items) or "No memories yet."

    @mcp.tool(name="delete_memory", description="Delete a memory by key.")
    def delete_memory(key: str) -> str:
        return f"Deleted '{key}'." if store.delete(key) else f"No memory with key '{key}'."

    @mcp.tool(name="get_stats", description="Memory count, embedding model and database path.")
    def get_stats() -> str:
        return json.dumps(store.stats(), indent=2)

    @mcp.tool(name="export_memories", description="Export every memory as JSON (backup).")
    def export_memories() -> str:
        return json.dumps(store.export(), indent=2)


def build_server(store: MemoryStore | None = None):
    try:
        from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x
    except ImportError:
        from mcp.server.mcpserver import MCPServer as Server  # mcp 2.x
    mcp = Server(name=NAME)
    register_tools(mcp, store or MemoryStore())
    return mcp


def main() -> None:
    build_server().run(transport="stdio")
