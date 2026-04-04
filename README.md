# AdaptiveMemoryEngine

An intelligent memory system with **mandatory semantic embeddings**, optional AI enhancement, and native MCP support.

## Philosophy

- **Embeddings are required**: Every memory is semantically indexed. No fallback to keyword-only search.
- **Intelligence is optional**: Auto-tagging, natural language answers, and AI-enhanced knowledge graphs require a generative model, but the core system works with embeddings alone.
- **SQLite only**: Single, reliable storage backend. No JSONL fallback, no migration scripts.
- **MCP-native**: Built on the official Model Context Protocol SDK. Works locally via `stdio` or remotely via `SSE`.

## Quick Start

```bash
git clone https://github.com/yourusername/AdaptiveMemoryEngine.git
cd AdaptiveMemoryEngine
npm install
```

Create a `.env` file:

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY
```

Run the MCP server (stdio mode for Claude Desktop, Cline, etc.):

```bash
npm start
```

Or run in SSE mode for remote deployment:

```bash
TRANSPORT=sse PORT=3000 npm start
```

## Requirements

| Feature | Requirement | Notes |
|---------|-------------|-------|
| Store memory | ✅ Embedding model | `text-embedding-3-small` or compatible |
| Semantic search | ✅ Embedding model | Always works |
| Hybrid search | ✅ Embedding model | Combines semantic + keyword |
| Knowledge graph | ✅ Base system | Regex extraction always works |
| AI-enhanced graph | ⚠️ Intelligence model | `gpt-4o-mini` or compatible |
| Auto-tagging | ⚠️ Intelligence model | Generates tags if no tags provided |
| Ask | ⚠️ Intelligence model | Natural language answers |
| Summarize | ⚠️ Intelligence model | AI-generated summaries |

## MCP Tools

### Core Tools

- `store_memory` - Save content with tags and embeddings
- `get_memory` - Retrieve by key
- `update_memory` - Update content/tags
- `delete_memory` - Remove a memory
- `search` - Hybrid semantic + keyword search
- `list_memories` - List all memories
- `query_graph` - Explore concept relationships
- `get_stats` - System overview
- `backup` - Create JSON snapshot

### AI-Enhanced Tools

- `smart_search` - Alias for `search` (embeddings are mandatory)
- `ask` - Question answering over memories
- `summarize` - Summarize memories by query or keys

## CLI Usage

```bash
# Import files
node cli.js import notes.md --tag work

# Search
node cli.js search "distributed systems"

# Get memory
node cli.js get meeting_notes_jan15

# Query knowledge graph
node cli.js graph "machine learning"

# Show stats
node cli.js stats

# Create backup
node cli.js snapshot
```

## Deployment Modes

### stdio (Default)
For local AI assistants. The host spawns the process directly.

```json
{
  "mcpServers": {
    "memory": {
      "command": "node",
      "args": ["/path/to/AdaptiveMemoryEngine/server.js"],
      "env": {
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

### SSE
For server deployment. Exposes an HTTP+SSE endpoint.

```bash
TRANSPORT=sse PORT=3000 node server.js
```

Endpoints:
- `GET /mcp` - SSE stream
- `POST /messages?sessionId=...` - Message endpoint
- `GET /health` - Health check

## Architecture

```
┌─────────────────────────────────────────┐
│  MCP Server (stdio / SSE)               │
├─────────────────────────────────────────┤
│  MemoryEngine                           │
│  ├── SQLiteBackend (storage)            │
│  ├── VectorStore (embeddings)           │
│  ├── KnowledgeGraph (concepts)          │
│  └── MemoryLifecycle (importance/decay) │
├─────────────────────────────────────────┤
│  embeddingProvider (required)           │
│  intelligenceProvider (optional)        │
└─────────────────────────────────────────┘
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | ✅ Yes | — | API key for embeddings |
| `OPENAI_EMBEDDING_MODEL` | ❌ No | `text-embedding-3-small` | Embedding model |
| `OPENAI_CHAT_MODEL` | ❌ No | `gpt-4o-mini` | Intelligence model |
| `DATA_DIR` | ❌ No | `./data` | Data directory |
| `TRANSPORT` | ❌ No | `stdio` | `stdio` or `sse` |
| `PORT` | ❌ No | `3000` | Port for SSE mode |

## License

MIT
