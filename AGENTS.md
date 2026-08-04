# AGENTS.md — AdaptiveMemoryEngine (Python v2)

## What this is

A semantic memory MCP server. Stores user-supplied content as **embeddings + SQLite + knowledge graph**. Exposes 13 MCP tools. Runs on Zeabur.

**Python 3.11+ port** of the original Node.js v1. **Schema and data files are byte-compatible** with v1 — existing `data/memories.db` and `data/knowledge-graph.json` work without migration.

## Repo layout

```
AdaptiveMemoryEngine/
├── src/adaptive_memory_engine/   # The package
│   ├── __init__.py              # Public exports
│   ├── __main__.py              # `python -m adaptive_memory_engine`
│   ├── cli.py                   # CLI dispatcher
│   ├── server.py                # MCP server (stdio + HTTP)
│   ├── engine.py                # MemoryEngine orchestrator
│   ├── config.py                # env / .env loader
│   ├── events.py                # EventBus + MemoryEvents
│   ├── chunking.py              # ChunkStore + strategies
│   ├── knowledge_graph.py       # Concept graph
│   ├── lifecycle.py             # Importance / Decay / Consolidation
│   ├── providers/               # OpenAI / Ollama / Gemini / Anthropic
│   └── storage/                 # SQLiteBackend + VectorStore
├── data/                        # Live state (gitignored, mounted as /data on Zeabur)
├── seed-data/                   # First-boot seed for Zeabur
├── pyproject.toml
├── Dockerfile                   # Zeabur image
├── nixpacks.toml                # Zeabur build plan
├── Procfile
└── README.md
```

## Build / run / test

```bash
# install
pip install -e .

# CLI
python -m adaptive_memory_engine stats
python -m adaptive_memory_engine search "python async"
python -m adaptive_memory_engine serve     # stdio MCP

# HTTP MCP (auto when PORT is set)
PORT=3000 python -m adaptive_memory_engine serve
# then POST to http://localhost:3000/mcp
```

## Critical data contracts (do not break)

- **`data/memories.db`** — SQLite schema with tables `memories`, `embeddings`, `access_log`, virtual table `memories_fts` (FTS5, external content). PRAGMAs: `journal_mode=DELETE`, `synchronous=NORMAL`, `locking_mode=NORMAL`. Embedding BLOB = Float32 little-endian raw bytes.
- **`data/knowledge-graph.json`** — `{concepts: [[id, node], ...], relationships: [...], conceptIndex: [[id, [memoryId, ...]], ...], savedAt}`. Concept id normalization = `lowercase → non-alphanum → '_' → trim '_'`.
- **13 MCP tools** with exact names + input schemas (see `server.py:_register_tools`).

## Deployment

Zeabur auto-detects Python from `pyproject.toml`. `PORT` env var auto-switches to HTTP transport and `DATA_DIR=/data`. Seed data is copied on first boot if `/data/memories.db` is missing (Dockerfile entrypoint).

## Simplified vs Node v1

Dropped (intentionally — half-built or never persisted):
- `TransactionManager` (WAL was write-only, no real rollback)
- `ArchiveManager` (in-memory only, lost on restart)
- `EventBus` middleware / history / replay
- `HealthMonitor` Prometheus metrics
- `setInterval` timers in `MemoryLifecycle`

Kept: `MemoryEngine`, `VectorStore`, `ChunkStore`, `KnowledgeGraph`, `MemoryLifecycle` (without archive), 4 providers, all CLI commands, all 13 MCP tools.

## When adding code

- All logging must go to **stderr** (stdio MCP keeps stdout clean).
- All datetimes use `now_iso()` from `events.py` to match the Node version's ISO format.
- Embedding vectors persist as **little-endian float32** (`struct.pack(f"<{n}f", ...)`).
- New MCP tools go in `server.py:_register_tools`.

## Regression test

Run the comprehensive local test suite before pushing:

```bash
python tests/pre_deploy.py
```

Should report `40 passed, 0 failed`. Covers: schema byte-compat, FTS5 search, embedding load, knowledge graph (incl. legacy `[id, node]` relationship format), engine CRUD, semantic/keyword/hybrid search, full MCP HTTP round-trip (initialize → list tools → call tools), all CLI commands, stdio MCP, and chunking strategies.