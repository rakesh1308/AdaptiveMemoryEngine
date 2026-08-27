# AdaptiveMemoryEngine

A production-hardened, single-tenant RAG memory service for ChatGPT and other MCP-compatible AI clients.

AdaptiveMemoryEngine stores durable memories, indexes them with full-text and semantic search, builds a lightweight knowledge graph, and exposes the workflow through MCP and REST. It is an MS-study RAG project demonstrating the separation between an AI model's reasoning and an external, auditable memory system.

## What ChatGPT intelligence does

ChatGPT is the reasoning and orchestration layer; it is not the database.

- It interprets user intent and decides when to call a memory tool.
- It turns natural language into structured MCP tool arguments.
- For `ask` and `summarize`, the configured chat model synthesizes an answer from retrieved context.
- It can suggest tags and concise summaries.
- It does not directly persist memory, execute retrieval, or silently train on stored data.

AdaptiveMemoryEngine owns durable storage, chunking, embeddings, PostgreSQL full-text search, pgvector hybrid ranking, lifecycle scoring, version history, graph maintenance, backups, and access control. Because MCP is model-neutral, ChatGPT can be replaced by Claude, Gemini, a local Ollama model, or another compatible client without migrating the database.

| Layer | Responsibility |
|---|---|
| ChatGPT / AI client | Intent recognition, reasoning, tool selection, final response |
| Intelligence provider | Optional tagging, summarization, and grounded synthesis |
| Embedding provider | Converts chunks and queries into vectors; does not generate answers |
| AdaptiveMemoryEngine | Ingestion, retrieval, ranking, persistence, history, graph, policies, tools |
| PostgreSQL + pgvector | Transactional source of truth, text index, vectors, and normalized graph |

## Architecture

```mermaid
flowchart LR
    User[User] --> Client[ChatGPT or MCP client]
    Client -->|structured tool call| Gateway[MCP / authenticated REST]
    Gateway --> Engine[MemoryEngine]

    subgraph Retrieval[Deterministic retrieval plane]
        Engine --> Chunker[Chunking]
        Engine --> FTS[PostgreSQL tsvector + GIN]
        Engine --> Vectors[pgvector + HNSW]
        Engine --> Graph[Knowledge graph]
        Engine --> History[Versions and lifecycle]
    end

    Engine -->|embed chunks and queries| Embedder[Embedding provider]
    Engine -->|retrieved context + question| LLM[Chat intelligence]
    LLM -->|grounded synthesis| Engine
    Engine --> Gateway --> Client --> User
    Postgres[(PostgreSQL + pgvector)] <--> Engine
```

### RAG request path

```mermaid
sequenceDiagram
    participant U as User
    participant C as ChatGPT / client
    participant A as AdaptiveMemoryEngine
    participant E as Embedding API
    participant D as PostgreSQL + pgvector
    participant L as Chat intelligence

    U->>C: Ask a question
    C->>A: ask(question, context_limit)
    A->>D: PostgreSQL keyword retrieval
    A->>E: Embed question
    E-->>A: Query vector
    A->>D: Semantic search + hybrid ranking
    D-->>A: Top-k memory context
    A->>L: Untrusted context + guarded task + question
    L-->>A: Grounded answer
    A-->>C: Answer or deterministic fallback
    C-->>U: Final response
```

### Ingestion path

1. Validate the memory key, content size, and tags.
2. Snapshot the current version when updating an existing memory.
3. Upsert authoritative text and metadata in PostgreSQL.
4. Split content into bounded semantic chunks.
5. Generate embeddings with the configured embedding model.
6. Replace the memory's chunks and vectors transactionally.
7. Update normalized graph concepts, relationships, and evidence.
8. Publish the application event.

Original text is never reconstructed from a vector. Full-text indexes, vectors,
and graph links are derived state that can be rebuilt from authoritative memory
text and metadata.

### Retrieval behavior

Hybrid retrieval runs lexical and semantic branches, de-duplicates their
candidates, and batch-fetches the winning memories. Ranking retains a 70%
semantic and 30% lexical weighting. If query embedding fails, retrieval degrades
to PostgreSQL keyword search. If answer synthesis fails, `ask` returns
deterministic evidence excerpts instead of inventing an answer.

### PostgreSQL data model

| Relation | Purpose |
|---|---|
| `memories` | Authoritative text, tags, importance, lifecycle data, and generated `tsvector` |
| `chunks` | Persistent chunk text, content hash, embedding model, and pgvector value |
| `embeddings` | Compatibility-level memory embedding |
| `memory_versions` | Reversible edit history |
| `access_log` | Usage and lifecycle evidence |
| `memory_suggestions` | Human-review quality workflow |
| `graph_concepts` | Normalized knowledge-graph nodes |
| `graph_concept_memories` | Concept-to-memory provenance |
| `graph_relationships` | Typed knowledge-graph edges |
| `graph_relationship_evidence` | Edge-to-memory provenance |
| `migration_runs` | Idempotent import status, counts, and audit metadata |

The embedding dimension is fixed by the PostgreSQL schema. Moving to a model
with a different dimension requires a fresh database and complete re-embedding.

### Reliability, security, and trade-offs

- Psycopg connection pools are bounded and health-checked.
- PostgreSQL foreign keys and cascades protect relational consistency.
- Chunk vectors survive restarts and are shared across application workers.
- Semantic winners are batch-fetched to prevent N+1 database queries.
- Provider requests use bounded retries, timeouts, and safe server-side logging.
- Bearer authentication, Host/CORS allowlists, request limits, and import-path containment protect HTTP deployments when configured.
- Retrieved memories are explicitly treated as untrusted model input.
- PostgreSQL plus pgvector provides one transactional backup boundary; HNSW gains speed by trading a small amount of exact recall.
- Graph traversal uses an in-process read model for API compatibility. Very large graphs should move to database-native recursive queries.
- The service is single-tenant; per-user authorization and tenant isolation are outside the current scope.

## Key capabilities

- Hybrid PostgreSQL full-text and pgvector cosine retrieval
- Persistent chunk embeddings with an HNSW approximate-nearest-neighbour index
- OpenAI, Gemini, Ollama, or Anthropic intelligence; Anthropic uses an embedding fallback
- Version history, restore, suggestions, tag scopes, export, import, and backup
- Normalized PostgreSQL knowledge-graph persistence
- Bounded provider retries for transient transport, rate-limit, and 5xx failures
- PostgreSQL connection pooling, transactions, and batched memory fetches
- Bearer auth, CORS/Host allowlists, DNS-rebinding protection, and request limits
- Generic external errors with detailed server-side logging
- Deterministic retrieval fallback when chat intelligence is unavailable

## Quick start

Requirements: Python 3.11+ and an embedding provider. OpenAI is the default.

```bash
git clone https://github.com/rakesh1308/AdaptiveMemoryEngine.git
cd AdaptiveMemoryEngine
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`, then start the local stdio server:

```bash
adaptive-memory-server
```

Example stdio MCP configuration:

```json
{
  "mcpServers": {
    "adaptive-memory": {
      "command": "python",
      "args": ["-m", "adaptive_memory_engine.server"],
      "env": {"OPENAI_API_KEY": "YOUR_KEY"}
    }
  }
}
```

## Production HTTP deployment

Minimum variables for an OpenAI-backed PostgreSQL deployment:

```bash
TRANSPORT=http
PORT=3000
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://user:password@postgres:5432/postgres
PROVIDER_TYPE=openai
OPENAI_API_KEY=<provider-key>
```

Then run `adaptive-memory-server`.

Optional HTTP hardening:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"

AUTH_TOKEN=<generated-value>
ALLOWED_ORIGINS=https://your-client.example
ALLOWED_HOSTS=memory.example.com
```

When `ALLOWED_HOSTS` is absent, reverse-proxy Host validation is disabled so
dynamic PaaS hostnames such as Zeabur work without additional configuration.
When it is set, unlisted hosts receive HTTP 421. Public deployments should use
the optional security controls whenever the client supports them.

Endpoints:

- `POST /mcp` - streamable HTTP MCP
- `POST /api/tools/{name}` - REST tool mirror
- `GET /health` - readiness check backed by a database read
- `GET /` - non-secret service metadata

When `AUTH_TOKEN` is configured, protected endpoints require `Authorization: Bearer <AUTH_TOKEN>`. The TypingMind plugin forwards its `authToken` setting. Public deployment without `AUTH_TOKEN` is logged as unsafe.

Chat imports are restricted to `IMPORT_ROOT` (default `DATA_DIR/imports`) and 50 MB. Copy an export there before calling `import_chat_export`; other server paths are rejected.

### Docker

```bash
docker build -t adaptive-memory-engine:3.0.0 .
docker run --rm -p 3000:3000 \
  -e TRANSPORT=http -e PORT=3000 \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e STORAGE_BACKEND=postgres -e DATABASE_URL="$DATABASE_URL" \
  -e AUTH_TOKEN="$AUTH_TOKEN" \
  -e ALLOWED_ORIGINS=https://your-client.example \
  -e ALLOWED_HOSTS=localhost:3000 \
  -v ame-data:/data adaptive-memory-engine:3.0.0
```

The image runs as UID 10001 and includes a health check. Use one writable persistent volume per service instance.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PROVIDER_TYPE` | `openai` | `openai`, `ollama`, `gemini`, or `anthropic` embeddings |
| `INTELLIGENCE_PROVIDER` | provider type | Optional independent chat provider |
| `OPENAI_API_KEY` | none | OpenAI credential |
| `OPENAI_BASE_URL` | OpenAI v1 | OpenAI-compatible endpoint |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | Chat model |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama endpoint |
| `GEMINI_API_KEY` | none | Gemini credential |
| `ANTHROPIC_API_KEY` | none | Anthropic credential; embeddings need fallback |
| `DATA_DIR` | `./data` or `/data` on PaaS | Persistent state |
| `STORAGE_BACKEND` | auto | `postgres` when `DATABASE_URL` is present; `sqlite` is legacy/local compatibility |
| `DATABASE_URL` | none | PostgreSQL 18 + pgvector connection URL |
| `DATABASE_POOL_MIN` / `MAX` | `1` / `10` | Bounded PostgreSQL connection pool |
| `TRANSPORT` | auto | `stdio` or `http` |
| `PORT` | `3000` | HTTP port, validated to 1-65535 |
| `AUTH_TOKEN` | none | Bearer token for MCP and REST tools |
| `ALLOWED_ORIGINS` | none | Optional comma-separated browser-origin allowlist |
| `ALLOWED_HOSTS` | none | Optional comma-separated Host allowlist; enables strict proxy Host validation when set |
| `IMPORT_ROOT` | `DATA_DIR/imports` | Only directory readable by chat import |

## Tool surface

The server has 26 implementations, including the `smart_search` compatibility alias.

| Area | Tools |
|---|---|
| CRUD and retrieval | `store_memory`, `get_memory`, `update_memory`, `delete_memory`, `search`, `smart_search`, `list_memories` |
| RAG intelligence | `ask`, `summarize`, `summarize_memory`, `get_provider_info` |
| Graph/maintenance | `query_graph`, `backfill_graph`, `get_stats`, `backup` |
| History/quality | `get_memory_history`, `restore_memory_version`, `list_suggestions`, `apply_suggestion`, `dismiss_suggestion`, `run_suggestion_scan` |
| Scope/portability | `set_active_tags`, `clear_active_tags`, `export_memories`, `import_memories`, `import_chat_export` |

## Verification

```bash
python -m pytest -q
ruff check src tests/conftest.py tests/test_*.py
mypy src
python tests/smoke_v2.py
python tests/all_tools_smoke.py
python tests/pre_deploy.py
```

Coverage includes validation, PostgreSQL restart persistence, pgvector retrieval, concurrency, legacy SQLite recovery, stale-index cleanup, recency, HTTP security, retries, CRUD, history, suggestions, import/export, RAG fallbacks, and the full tool surface.

## Scope and limitations

Production-oriented here means a personal or research deployment, not multi-tenant SaaS.

- PostgreSQL is the production backend; the legacy SQLite backend remains for local compatibility and migration only.
- HNSW retrieval trades a small amount of exact recall for substantially better large-corpus latency.
- Auth is one shared token; per-user authorization and tenant isolation are not implemented.
- Provider APIs receive text needed for embedding/synthesis. Use Ollama for local-only processing.
- Memory is marked untrusted in the RAG task, but model prompt-injection risk cannot be eliminated.
- JSON snapshots are portable exports; operators should also maintain tested PostgreSQL backups.

## Project structure

```text
src/adaptive_memory_engine/
  server.py              MCP and authenticated REST transports
  engine.py              RAG orchestration and consistency boundary
  storage/               PostgreSQL/pgvector production and legacy SQLite migration storage
  migration.py           Recover, import, backfill, checksum, and validate backups
  providers/             OpenAI, Anthropic, Gemini, Ollama, retry policy
  knowledge_graph.py     Concept graph and atomic persistence
  chunking.py            Chunk strategies and process-local chunk state
  lifecycle.py           Importance and access scoring
tests/                    Unit, integration, regression, and smoke coverage
docs/typingmind-setup.md  TypingMind MCP client setup
docs/zeabur-deploy.md     Zeabur deployment guide
```

## License

MIT (c) Rakesh Sonawane
