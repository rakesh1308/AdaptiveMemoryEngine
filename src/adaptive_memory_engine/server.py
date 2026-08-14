"""MCP server: stdio + streamable HTTP transport.

Built on the official `mcp` Python SDK. Exposes 12 tools that wrap the
MemoryEngine for any MCP-compatible client (Claude Desktop, Cline, etc.).
"""
from __future__ import annotations

import json
import logging
import os
import sys

import uvicorn

from .config import Config
from .engine import MemoryEngine
from .providers.factory import ProviderFactory

log = logging.getLogger(__name__)

SERVER_NAME = "adaptive-memory-engine"
SERVER_VERSION = "2.0.0"

# Module-level placeholder so build_http_app() can refer to it before
# _build_rest_tools() is called per-engine. Replaced per-request.
_REST_TOOL_FNS: dict[str, callable] = {}


# ---- result helpers ----

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

    @mcp.tool(
        name="backfill_graph",
        description=(
            "Re-extract concepts/relationships for memories missing from the "
            "knowledge graph. Use dry_run=true first to preview. "
            "Pass memory_ids to target specific keys; pass rebuild_all=true "
            "to re-extract every memory."
        ),
    )
    def backfill_graph(
        memory_ids: list[str] | None = None,
        dry_run: bool = False,
        rebuild_all: bool = False,
    ) -> str:
        result = engine.backfill_graph(
            memory_ids=memory_ids, dry_run=bool(dry_run), rebuild_all=bool(rebuild_all)
        )
        return json.dumps(result, indent=2, ensure_ascii=False)

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

    # ---- v2.1: version history ----

    @mcp.tool(
        name="get_memory_history",
        description="Get all prior versions of a memory (most recent first). Use restore_memory_version to revert.",
    )
    def get_memory_history(key: str, limit: int = 50) -> str:
        versions = engine.get_memory_history(key, limit=int(limit))
        if not versions:
            return f"No version history for '{key}'."
        lines = [f"=== {len(versions)} versions of '{key}' ===", ""]
        for v in versions:
            created = v.get("createdAt") or "unknown"
            content = (v.get("content") or "").replace("\n", " ")[:120]
            tags = ",".join(v.get("tags") or [])
            lines.append(f"[{v['version_id']}] v{v.get('version_num')} @ {created} tags={tags}")
            lines.append(f"  {content}{'...' if len(v.get('content','')) > 120 else ''}")
            lines.append("")
        return "\n".join(lines)

    @mcp.tool(
        name="restore_memory_version",
        description="Restore a memory to a prior state by version_id. The current state is itself snapshotted first so restore is reversible.",
    )
    def restore_memory_version(key: str, version_id: str) -> str:
        mem = engine.restore_memory_version(key, version_id)
        if not mem:
            return f"Version '{version_id}' not found for memory '{key}'."
        return f"Restored '{key}' to version {version_id} (now at v{mem['version']})."

    # ---- v2.2: memory suggestions ----

    @mcp.tool(
        name="list_suggestions",
        description="List memory suggestions (dedup / merge / stale / duplicate). Status defaults to 'open'.",
    )
    def list_suggestions(status: str = "open", limit: int = 50) -> str:
        items = engine.list_suggestions(status=status, limit=int(limit))
        if not items:
            return f"No {status} suggestions."
        lines = [f"=== {len(items)} {status} suggestions ===", ""]
        for s in items:
            lines.append(f"[{s['suggestion_id']}] {s['kind']}  targets={s.get('target_ids')}")
            lines.append(f"  {s.get('summary','')}")
            lines.append("")
        return "\n".join(lines)

    @mcp.tool(
        name="apply_suggestion",
        description="Apply a suggestion's payload (merges duplicates, updates tags, etc). Marks the suggestion as applied.",
    )
    def apply_suggestion(suggestion_id: str) -> str:
        result = engine.apply_suggestion(suggestion_id)
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool(
        name="dismiss_suggestion",
        description="Dismiss a suggestion without applying it.",
    )
    def dismiss_suggestion(suggestion_id: str) -> str:
        ok = engine.dismiss_suggestion(suggestion_id)
        return "Dismissed." if ok else "Not found or already resolved."

    @mcp.tool(
        name="run_suggestion_scan",
        description="Scan all memories for duplicates, tag-cluster overlaps, and stale entries. Persists new open suggestions.",
    )
    def run_suggestion_scan(max_new: int = 20) -> str:
        created = engine.run_suggestion_scan(max_new=int(max_new))
        if not created:
            return "No new suggestions found."
        return f"Created {len(created)} new suggestions. Use list_suggestions to review."

    # ---- v2.3: per-chat tag scoping ----

    @mcp.tool(
        name="set_active_tags",
        description="Scope the current chat to one or more tags. Subsequent search_memories / list_memories / ask will be filtered. chat_id is provided by TypingMind ({CHAT_ID}).",
    )
    def set_active_tags(tags: list[str], chat_id: str = "default") -> str:
        engine.set_chat_scope(chat_id, tags)
        return f"Chat '{chat_id}' scoped to {len(tags)} tag(s): {','.join(tags)}"

    @mcp.tool(
        name="clear_active_tags",
        description="Reset the chat's tag scope (back to global / all memories visible).",
    )
    def clear_active_tags(chat_id: str = "default") -> str:
        engine.clear_chat_scope(chat_id)
        return f"Chat '{chat_id}' scope cleared — global memory visible."

    # ---- v2.4: export formats ----

    @mcp.tool(
        name="export_memories",
        description="Export memories. Format: json (default), csv, or text (with AI-ready instructions prepended).",
    )
    def export_memories(format: str = "json", include_versions: bool = False) -> str:
        data = engine.export()
        memories = data.get("memories", [])
        if format == "csv":
            import csv, io
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "content", "tags", "importance", "createdAt", "updatedAt", "version", "source"])
            for m in memories:
                w.writerow([
                    m.get("id", ""),
                    (m.get("content") or "").replace("\n", " ").replace("\r", " "),
                    ";".join(m.get("tags") or []),
                    m.get("importance", ""),
                    m.get("createdAt", ""),
                    m.get("updatedAt", ""),
                    m.get("version", ""),
                    m.get("source", ""),
                ])
            return buf.getvalue()
        if format == "text":
            lines = [
                "# My Memory Export",
                "",
                "You are an AI assistant with access to the user's long-term memory.",
                "Use the following memories as context when relevant to the conversation.",
                "Memories are organized by tag. Be concise and recall facts by id when needed.",
                "",
                f"Total memories: {len(memories)}",
                f"Exported at: {data.get('exportedAt','')}",
                "",
                "---",
                "",
            ]
            grouped: dict[str, list[dict]] = {}
            for m in memories:
                tags = m.get("tags") or ["untagged"]
                for t in tags:
                    grouped.setdefault(t, []).append(m)
            for tag, ms in sorted(grouped.items()):
                lines.append(f"## {tag}")
                lines.append("")
                for m in ms:
                    lines.append(f"- [{m.get('id')}] (imp={m.get('importance')})")
                    lines.append(f"  {(m.get('content') or '').strip()}")
                    lines.append("")
            return "\n".join(lines)
        # default JSON
        if include_versions:
            for m in memories:
                m["versions"] = engine.get_memory_history(m["id"], limit=50)
        return json.dumps(data, indent=2, ensure_ascii=False)

    # ---- v2.5: bulk import with dedup ----

    @mcp.tool(
        name="import_memories",
        description="Bulk import memories from a JSON list. Each item: {id, content, tags?}. Dedups by content-hash and exact-id match.",
    )
    def import_memories(items: list[dict]) -> str:
        existing_ids = {m["id"] for m in engine.list_memories(limit=100_000)}
        existing_content = {(m.get("content") or "").strip().lower() for m in engine.list_memories(limit=100_000)}
        added, skipped_id, skipped_content = 0, 0, 0
        for item in items:
            mid = item.get("id")
            content = item.get("content", "")
            if not mid or not content:
                continue
            if mid in existing_ids:
                skipped_id += 1
                continue
            if content.strip().lower() in existing_content:
                skipped_content += 1
                continue
            tags = item.get("tags") or []
            engine.store_memory(mid, content, tags=tags, auto_tag=False, source="import")
            existing_ids.add(mid)
            existing_content.add(content.strip().lower())
            added += 1
        return f"Imported {added}. Skipped: {skipped_id} duplicate id, {skipped_content} duplicate content."

    # ---- v2.6: chat-history import (Pro feature) ----

    @mcp.tool(
        name="import_chat_export",
        description="Import an entire AI chat history export. Supports ChatGPT (conversations.json), Claude (conversations.json), and Gemini (takeout). Optional tag prefix applied to every imported memory.",
    )
    def import_chat_export(file_path: str, platform: str = "auto", tag_prefix: str = "imported") -> str:
        from pathlib import Path as _P
        p = _P(file_path)
        if not p.exists():
            return f"File not found: {file_path}"
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return f"Failed to read JSON: {e}"
        # Detect platform if auto
        if platform == "auto":
            if isinstance(raw, list) and raw and "mapping" in raw[0]:
                platform = "chatgpt"
            elif isinstance(raw, list) and raw and "chat_messages" in raw[0]:
                platform = "claude"
            else:
                platform = "unknown"
        items: list[dict] = []
        if platform == "chatgpt":
            for conv in raw:
                title = (conv.get("title") or "untitled")[:60].strip()
                mapping = conv.get("mapping") or {}
                # Walk in chronological order
                msgs = []
                for node in mapping.values():
                    m = node.get("message")
                    if not m:
                        continue
                    role = (m.get("author") or {}).get("role", "")
                    if role not in ("user", "assistant"):
                        continue
                    parts = m.get("content", {}).get("parts") or []
                    text = "\n".join(str(p) for p in parts if isinstance(p, str)).strip()
                    if text:
                        msgs.append((m.get("create_time") or 0, role, text))
                msgs.sort(key=lambda x: x[0])
                for i, (_t, role, text) in enumerate(msgs):
                    items.append({
                        "id": f"{tag_prefix}-{platform}-{conv.get('id','x')[:8]}-{i:03d}",
                        "content": f"[{title}] {role}: {text[:1500]}",
                        "tags": [tag_prefix, platform, "chat-history"],
                    })
        elif platform == "claude":
            for conv in raw:
                title = (conv.get("name") or conv.get("title") or "untitled")[:60].strip()
                for i, msg in enumerate(conv.get("chat_messages", []) or []):
                    role = msg.get("sender", "user")
                    text = (msg.get("text") or "").strip()
                    if text:
                        items.append({
                            "id": f"{tag_prefix}-{platform}-{conv.get('uuid','x')[:8]}-{i:03d}",
                            "content": f"[{title}] {role}: {text[:1500]}",
                            "tags": [tag_prefix, platform, "chat-history"],
                        })
        else:
            return f"Unsupported platform: {platform}. Supported: chatgpt, claude, auto."
        # Recursively import using the dedup-aware tool
        existing_ids = {m["id"] for m in engine.list_memories(limit=100_000)}
        existing_content = {(m.get("content") or "").strip().lower() for m in engine.list_memories(limit=100_000)}
        added, skipped = 0, 0
        for item in items:
            mid = item["id"]
            content = item["content"]
            if mid in existing_ids or content.strip().lower() in existing_content:
                skipped += 1
                continue
            engine.store_memory(mid, content, tags=item.get("tags", []), auto_tag=False, source="chat-import")
            existing_ids.add(mid)
            existing_content.add(content.strip().lower())
            added += 1
        return f"Imported {added} messages from {len(raw)} {platform} conversation(s). Skipped {skipped} duplicates."

    # ---- v2.7: single-memory summary (Smart Memory two-stage) ----

    @mcp.tool(
        name="summarize_memory",
        description="Return a 1-2 sentence summary of one memory. Cheaper than recalling the full content when you just need the gist.",
    )
    def summarize_memory(key: str) -> str:
        mem = engine.recall_memory(key)
        if not mem:
            return f"Not found: {key}"
        content = (mem.get("content") or "").strip()
        if not content:
            return f"Memory '{key}' is empty."
        if engine.intelligence_provider:
            try:
                return engine.intelligence_provider.synthesize(
                    content[:1500],
                    f"Summarize this memory in 1-2 sentences. Memory id: {key}.",
                    style="concise",
                )
            except Exception:  # noqa: BLE001
                pass
        # Fallback: truncate
        snippet = content[:200].replace("\n", " ")
        return f"[{key}] {snippet}{'...' if len(content) > 200 else ''}"


# ---- REST tool registry (used by /api/tools/{name}, HTTP-Action plugin) ----

def _build_rest_tools(engine: MemoryEngine) -> dict[str, callable]:
    """Return a flat {tool_name: callable(args...)} map for the REST mirror.
    Each callable accepts kwargs matching the MCP tool signature and returns
    a string (matching MCP tool-call semantics)."""
    return {
        "store_memory": lambda **kw: _mcp_store(engine, **kw),
        "get_memory": lambda **kw: _mcp_get(engine, **kw),
        "update_memory": lambda **kw: _mcp_update(engine, **kw),
        "delete_memory": lambda **kw: _mcp_delete(engine, **kw),
        "search": lambda **kw: _mcp_search(engine, **kw),
        "smart_search": lambda **kw: _mcp_search(engine, **kw),
        "list_memories": lambda **kw: _mcp_list(engine, **kw),
        "query_graph": lambda **kw: _mcp_query_graph(engine, **kw),
        "backfill_graph": lambda **kw: _mcp_backfill(engine, **kw),
        "get_stats": lambda **kw: _mcp_stats(engine, **kw),
        "backup": lambda **kw: _mcp_backup(engine, **kw),
        "ask": lambda **kw: _mcp_ask(engine, **kw),
        "summarize": lambda **kw: _mcp_summarize(engine, **kw),
        "get_provider_info": lambda **kw: _mcp_provider_info(engine, **kw),
        # v2.x additions
        "get_memory_history": lambda **kw: _mcp_history(engine, **kw),
        "restore_memory_version": lambda **kw: _mcp_restore(engine, **kw),
        "list_suggestions": lambda **kw: _mcp_list_suggestions(engine, **kw),
        "apply_suggestion": lambda **kw: _mcp_apply_suggestion(engine, **kw),
        "dismiss_suggestion": lambda **kw: _mcp_dismiss_suggestion(engine, **kw),
        "run_suggestion_scan": lambda **kw: _mcp_run_scan(engine, **kw),
        "set_active_tags": lambda **kw: _mcp_set_tags(engine, **kw),
        "clear_active_tags": lambda **kw: _mcp_clear_tags(engine, **kw),
        "export_memories": lambda **kw: _mcp_export(engine, **kw),
        "import_memories": lambda **kw: _mcp_import(engine, **kw),
        "import_chat_export": lambda **kw: _mcp_import_chat(engine, **kw),
        "summarize_memory": lambda **kw: _mcp_summarize_memory(engine, **kw),
    }


# ---- REST tool implementations (thin wrappers around engine methods) ----

def _mcp_store(engine, *, key, content, tags=None, tags_csv=None, auto_tag=False):
    # Accept tags as either list or comma-separated string (HTTP variant).
    if tags_csv and not tags:
        tags = [t.strip() for t in tags_csv.split(",") if t.strip()]
    mem = engine.store_memory(key, content, tags=tags, auto_tag=auto_tag, source="http-rest")
    return f"Stored memory '{mem['id']}' (importance={mem['importance']})."


def _mcp_get(engine, *, key):
    mem = engine.recall_memory(key)
    if not mem:
        return f"Not found: {key}"
    return json.dumps(mem, indent=2, ensure_ascii=False)


def _mcp_update(engine, *, key, content=None, tags=None, tags_csv=None, merge_tags=False):
    if tags_csv and not tags:
        tags = [t.strip() for t in tags_csv.split(",") if t.strip()]
    mem = engine.update_memory(key, content=content, tags=tags, merge_tags=merge_tags)
    if not mem:
        return f"Not found: {key}"
    return f"Updated '{mem['id']}'."


def _mcp_delete(engine, *, key):
    ok = engine.delete_memory(key)
    return "Deleted." if ok else f"Not found: {key}"


def _mcp_search(engine, *, query, limit=10):
    return _format_search(engine.search_memories(query, top_k=int(limit), mode="hybrid"))


def _mcp_list(engine, *, filter=None, limit=50, tag=None):
    return _format_list(engine.list_memories(filter_text=filter, tag=tag, limit=int(limit)))


def _mcp_query_graph(engine, *, concept=None, depth=1, find_path_to=None):
    return json.dumps(
        engine.query_graph(concept=concept, depth=int(depth), find_path_to=find_path_to),
        indent=2, ensure_ascii=False,
    )


def _mcp_backfill(engine, *, memory_ids=None, dry_run=False, rebuild_all=False):
    result = engine.backfill_graph(memory_ids=memory_ids, dry_run=bool(dry_run), rebuild_all=bool(rebuild_all))
    return json.dumps(result, indent=2, ensure_ascii=False)


def _mcp_stats(engine, **_):
    return json.dumps(engine.get_stats(), indent=2)


def _mcp_backup(engine, **_):
    return json.dumps(engine.create_snapshot(), indent=2)


def _mcp_ask(engine, *, question, context_limit=3):
    return engine.ask(question, context_limit=int(context_limit))


def _mcp_summarize(engine, *, query=None, keys=None, style="concise"):
    return engine.summarize(query=query, keys=keys, style=style)


def _mcp_provider_info(engine, **_):
    cfg = engine.embedding_provider.get_config()
    intel_cfg = engine.intelligence_provider.get_config() if engine.intelligence_provider else None
    return json.dumps(
        {"embedding_provider": cfg, "intelligence_provider": intel_cfg,
         "intelligence_available": engine.intelligence_provider is not None},
        indent=2,
    )


def _mcp_history(engine, *, key, limit=50):
    versions = engine.get_memory_history(key, limit=int(limit))
    if not versions:
        return f"No version history for '{key}'."
    lines = [f"=== {len(versions)} versions of '{key}' ===", ""]
    for v in versions:
        created = v.get("createdAt") or "unknown"
        content = (v.get("content") or "").replace("\n", " ")[:120]
        tags = ",".join(v.get("tags") or [])
        lines.append(f"[{v['version_id']}] v{v.get('version_num')} @ {created} tags={tags}")
        lines.append(f"  {content}{'...' if len(v.get('content','')) > 120 else ''}")
        lines.append("")
    return "\n".join(lines)


def _mcp_restore(engine, *, key, version_id):
    mem = engine.restore_memory_version(key, version_id)
    if not mem:
        return f"Version '{version_id}' not found for memory '{key}'."
    return f"Restored '{key}' to version {version_id} (now at v{mem['version']})."


def _mcp_list_suggestions(engine, *, status="open", limit=50):
    items = engine.list_suggestions(status=status, limit=int(limit))
    if not items:
        return f"No {status} suggestions."
    lines = [f"=== {len(items)} {status} suggestions ===", ""]
    for s in items:
        lines.append(f"[{s['suggestion_id']}] {s['kind']}  targets={s.get('target_ids')}")
        lines.append(f"  {s.get('summary','')}")
        lines.append("")
    return "\n".join(lines)


def _mcp_apply_suggestion(engine, *, suggestion_id):
    return json.dumps(engine.apply_suggestion(suggestion_id), indent=2, ensure_ascii=False)


def _mcp_dismiss_suggestion(engine, *, suggestion_id):
    ok = engine.dismiss_suggestion(suggestion_id)
    return "Dismissed." if ok else "Not found or already resolved."


def _mcp_run_scan(engine, *, max_new=20):
    created = engine.run_suggestion_scan(max_new=int(max_new))
    if not created:
        return "No new suggestions found."
    return f"Created {len(created)} new suggestions. Use list_suggestions to review."


def _mcp_set_tags(engine, *, tags=None, tags_csv=None, chat_id="default"):
    # HTTP variant passes tags as comma-separated string.
    if tags_csv and not tags:
        tags = [t.strip() for t in tags_csv.split(",") if t.strip()]
    elif not tags:
        tags = []
    engine.set_chat_scope(chat_id, tags)
    return f"Chat '{chat_id}' scoped to {len(tags)} tag(s): {','.join(tags)}"


def _mcp_clear_tags(engine, *, chat_id="default"):
    engine.clear_chat_scope(chat_id)
    return f"Chat '{chat_id}' scope cleared — global memory visible."


def _mcp_export(engine, *, format="json", include_versions=False):
    data = engine.export()
    memories = data.get("memories", [])
    if format == "csv":
        import csv, io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "content", "tags", "importance", "createdAt", "updatedAt", "version", "source"])
        for m in memories:
            w.writerow([
                m.get("id", ""),
                (m.get("content") or "").replace("\n", " ").replace("\r", " "),
                ";".join(m.get("tags") or []),
                m.get("importance", ""),
                m.get("createdAt", ""),
                m.get("updatedAt", ""),
                m.get("version", ""),
                m.get("source", ""),
            ])
        return buf.getvalue()
    if format == "text":
        lines = [
            "# My Memory Export", "",
            "You are an AI assistant with access to the user's long-term memory.",
            "Use the following memories as context when relevant to the conversation.",
            f"Total memories: {len(memories)}",
            f"Exported at: {data.get('exportedAt','')}", "", "---", "",
        ]
        grouped: dict[str, list[dict]] = {}
        for m in memories:
            tags = m.get("tags") or ["untagged"]
            for t in tags:
                grouped.setdefault(t, []).append(m)
        for tag, ms in sorted(grouped.items()):
            lines.append(f"## {tag}"); lines.append("")
            for m in ms:
                lines.append(f"- [{m.get('id')}] (imp={m.get('importance')})")
                lines.append(f"  {(m.get('content') or '').strip()}")
                lines.append("")
        return "\n".join(lines)
    if include_versions:
        for m in memories:
            m["versions"] = engine.get_memory_history(m["id"], limit=50)
    return json.dumps(data, indent=2, ensure_ascii=False)


def _mcp_import(engine, *, items=None, items_json=None):
    # HTTP variant passes items as a JSON string (TypingMind can't handle raw arrays).
    if items_json and not items:
        try:
            items = json.loads(items_json)
        except Exception as e:
            return f"Failed to parse items_json: {e}"
    items = items or []
    existing_ids = {m["id"] for m in engine.list_memories(limit=100_000)}
    existing_content = {(m.get("content") or "").strip().lower() for m in engine.list_memories(limit=100_000)}
    added, skipped_id, skipped_content = 0, 0, 0
    for item in items:
        mid = item.get("id"); content = item.get("content", "")
        if not mid or not content: continue
        if mid in existing_ids: skipped_id += 1; continue
        if content.strip().lower() in existing_content: skipped_content += 1; continue
        engine.store_memory(mid, content, tags=item.get("tags") or [], auto_tag=False, source="import")
        existing_ids.add(mid); existing_content.add(content.strip().lower()); added += 1
    return f"Imported {added}. Skipped: {skipped_id} duplicate id, {skipped_content} duplicate content."


def _mcp_import_chat(engine, *, file_path, platform="auto", tag_prefix="imported"):
    from pathlib import Path as _P
    p = _P(file_path)
    if not p.exists():
        return f"File not found: {file_path}"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return f"Failed to read JSON: {e}"
    if platform == "auto":
        if isinstance(raw, list) and raw and "mapping" in raw[0]: platform = "chatgpt"
        elif isinstance(raw, list) and raw and "chat_messages" in raw[0]: platform = "claude"
        else: platform = "unknown"
    items = []
    if platform == "chatgpt":
        for conv in raw:
            title = (conv.get("title") or "untitled")[:60].strip()
            msgs = []
            for node in (conv.get("mapping") or {}).values():
                m = node.get("message")
                if not m: continue
                role = (m.get("author") or {}).get("role", "")
                if role not in ("user", "assistant"): continue
                parts = m.get("content", {}).get("parts") or []
                text = "\n".join(str(p) for p in parts if isinstance(p, str)).strip()
                if text: msgs.append((m.get("create_time") or 0, role, text))
            msgs.sort(key=lambda x: x[0])
            for i, (_t, role, text) in enumerate(msgs):
                items.append({"id": f"{tag_prefix}-{platform}-{conv.get('id','x')[:8]}-{i:03d}",
                              "content": f"[{title}] {role}: {text[:1500]}",
                              "tags": [tag_prefix, platform, "chat-history"]})
    elif platform == "claude":
        for conv in raw:
            title = (conv.get("name") or conv.get("title") or "untitled")[:60].strip()
            for i, msg in enumerate(conv.get("chat_messages", []) or []):
                role = msg.get("sender", "user")
                text = (msg.get("text") or "").strip()
                if text:
                    items.append({"id": f"{tag_prefix}-{platform}-{conv.get('uuid','x')[:8]}-{i:03d}",
                                  "content": f"[{title}] {role}: {text[:1500]}",
                                  "tags": [tag_prefix, platform, "chat-history"]})
    else:
        return f"Unsupported platform: {platform}. Supported: chatgpt, claude, auto."
    existing_ids = {m["id"] for m in engine.list_memories(limit=100_000)}
    existing_content = {(m.get("content") or "").strip().lower() for m in engine.list_memories(limit=100_000)}
    added, skipped = 0, 0
    for item in items:
        if item["id"] in existing_ids or item["content"].strip().lower() in existing_content:
            skipped += 1; continue
        engine.store_memory(item["id"], item["content"], tags=item["tags"], auto_tag=False, source="chat-import")
        existing_ids.add(item["id"]); existing_content.add(item["content"].strip().lower()); added += 1
    return f"Imported {added} messages from {len(raw)} {platform} conversation(s). Skipped {skipped} duplicates."


def _mcp_summarize_memory(engine, *, key):
    mem = engine.recall_memory(key)
    if not mem: return f"Not found: {key}"
    content = (mem.get("content") or "").strip()
    if not content: return f"Memory '{key}' is empty."
    if engine.intelligence_provider:
        try:
            return engine.intelligence_provider.synthesize(
                content[:1500], f"Summarize this memory in 1-2 sentences. Memory id: {key}.", style="concise")
        except Exception: pass
    snippet = content[:200].replace("\n", " ")
    return f"[{key}] {snippet}{'...' if len(content) > 200 else ''}"


# ---- transports ----

def _build_mcp_server(engine: MemoryEngine):
    """Create an MCP server with all tools registered.

    Supports both the legacy `mcp.server.mcpserver.MCPServer` (pre-1.10)
    and the newer `mcp.server.fastmcp.FastMCP` (1.10+). The latter is
    what Zeabur's mcp>=1.0 install resolves to today.
    """
    # Detect which class is available. Newer SDKs only ship FastMCP.
    try:
        from mcp.server.fastmcp import FastMCP as _Server  # type: ignore
    except ImportError:
        from mcp.server.mcpserver import MCPServer as _Server  # type: ignore

    # Build kwargs compatible with both class shapes.
    try:
        mcp = _Server(name=SERVER_NAME, version=SERVER_VERSION)  # legacy
    except TypeError:
        mcp = _Server(name=SERVER_NAME)  # FastMCP
    _register_tools(mcp, engine)
    return mcp


def serve_stdio(engine: MemoryEngine) -> None:
    mcp = _build_mcp_server(engine)
    mcp.run(transport="stdio")


def build_http_app(engine: MemoryEngine):
    """Return a Starlette app exposing /mcp (streamable HTTP), /health, /."""
    mcp = _build_mcp_server(engine)
    # Disable DNS-rebinding protection so the MCP endpoint accepts
    # requests from arbitrary Host headers (e.g. behind a reverse proxy
    # on any PaaS like Zeabur). Different SDK versions expose this
    # either via a constructor kwarg or a streamable_http_app() kwarg.
    from mcp.server.streamable_http import TransportSecuritySettings
    try:
        base_app = mcp.streamable_http_app(
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
            ),
        )
    except TypeError:
        # FastMCP path — recreate with transport_security passed at ctor.
        try:
            from mcp.server.fastmcp import FastMCP as _FastMCP
            ts = TransportSecuritySettings(enable_dns_rebinding_protection=False)
            mcp2 = _FastMCP(name=SERVER_NAME, transport_security=ts)
            _register_tools(mcp2, engine)
            base_app = mcp2.streamable_http_app()
        except Exception:
            base_app = mcp.streamable_http_app()

    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def root(_request):
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

    async def health(_request):
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

    # ------------------------------------------------------------------------
    # REST mirror at /api/tools/{name} — used by the HTTP-Action variant of
    # the TypingMind plugin (no Node.js / npx required on the user side).
    # Each route accepts POST with JSON body {"arguments": {...}} and returns
    # {"result": "..."} just like MCP tools/call.
    # ------------------------------------------------------------------------
    from starlette.requests import Request as _Req
    from starlette.responses import JSONResponse as _JR

    async def call_tool(request: _Req) -> _JR:
        name = request.path_params["name"]
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        arguments = payload.get("arguments", {}) or {}
        # Look up via the per-engine registry we set on app.state at startup.
        tool_fn = getattr(request.app.state, "rest_tools", _REST_TOOL_FNS).get(name)
        if tool_fn is None:
            return _JR({"error": f"unknown_tool: {name}"}, status_code=404)
        try:
            result = tool_fn(**arguments) if isinstance(arguments, dict) else tool_fn(arguments)
            return _JR({"result": result})
        except TypeError as e:
            return _JR({"error": f"bad_arguments: {e}"}, status_code=400)
        except Exception as e:  # noqa: BLE001
            log.exception("REST tool %s failed", name)
            return _JR({"error": str(e)}, status_code=500)

    base_app.router.routes.append(
        Route("/api/tools/{name}", endpoint=call_tool, methods=["POST"])
    )

    # CORS — TypingMind's HTTP-Action plugin runs in the browser and calls
    # this server cross-origin. Allow any origin (the server is unauthenticated
    # by design for now; tighten via ALLOWED_ORIGINS env var when adding auth).
    from starlette.middleware.cors import CORSMiddleware
    # Register the per-engine tool registry so the REST handler can find tools.
    base_app.state.rest_tools = _build_rest_tools(engine)
    allowed = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
    cors = CORSMiddleware(
        app=base_app,
        allow_origins=allowed,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,
        max_age=600,
    )
    return cors


def serve_http(engine: MemoryEngine, host: str = "0.0.0.0", port: int = 3000) -> None:
    app = build_http_app(engine)
    uvicorn.run(app, host=host, port=port, log_level="info")


def serve() -> None:
    """Entrypoint for the `adaptive-memory-server` console script and Docker `CMD`."""
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