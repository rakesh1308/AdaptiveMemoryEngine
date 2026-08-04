# 🧠 AdaptiveMemoryEngine

**Semantic memory for AI assistants. Pluggable, private, and MCP-native.**

[![Python](https://img.shields.io/badge/python-≥3.11-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-green)](https://modelcontextprotocol.io/)
[![Deploy on Zeabur](https://img.shields.io/badge/Deploy-Zeabur-7B61FF)](https://zeabur.com)

AdaptiveMemoryEngine is an intelligent memory system that remembers everything you tell it. Unlike simple note-taking apps, it uses **semantic embeddings** to understand the meaning of your content, enabling intelligent search and AI-powered insights.

> **Python port** (v2.0) — same data format, same MCP surface, same Zeabur deployment story as the original Node.js version. Existing `memories.db` and `knowledge-graph.json` keep working without migration.

---

## ☁️ Deploy to Zeabur (One-Click)

1. **Push this repo to GitHub** and connect it to Zeabur.
2. **Set your AI provider key** in Zeabur's Variables tab:
   - `OPENAI_API_KEY` (recommended) — or `GEMINI_API_KEY`, or set `PROVIDER_TYPE=ollama`
3. **Wait for the build**. Zeabur auto-detects Python via `pyproject.toml`, builds the image, and starts the server.
4. **Add a persistent Volume** mounted at `/data` so memories survive restarts.
5. Connect any MCP client to `https://<your-app>.zeabur.app/mcp`.

`PORT` is auto-injected by Zeabur → transport switches to HTTP automatically.

### Health & info endpoints

- `GET https://<your-app>.zeabur.app/health` — `{status, memories, concepts, embeddings, provider}`
- `GET https://<your-app>.zeabur.app/` — server info + stats
- `POST https://<your-app>.zeabur.app/mcp` — MCP JSON-RPC

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| **Semantic Search** | Find memories by meaning, not just keywords. Ask "machine learning" and find "neural networks" content. |
| **Knowledge Graph** | Automatically builds relationships between concepts in your memories. |
| **AI-Powered** | Optional AI features for auto-tagging, Q&A, and summarization. |
| **Privacy-First** | Run completely offline with local AI models (Ollama). |
| **MCP Native** | Works with Claude Desktop, Cline, and any MCP-compatible tool. |
| **Multi-Provider** | OpenAI, Google Gemini, Anthropic, or local Ollama. |

---

## 🚀 Quick Start

### Prerequisites

- **Python ≥ 3.11** (3.12 recommended for Zeabur)
- An embedding provider — one of:
  - [OpenAI](https://platform.openai.com/api-keys) (recommended)
  - [Google AI Studio](https://aistudio.google.com/app/apikey)
  - [Ollama](https://ollama.com) for 100% local/offline use

### Installation

```bash
git clone https://github.com/rakesh1308/AdaptiveMemoryEngine.git
cd AdaptiveMemoryEngine
pip install -e .
cp .env.example .env
# edit .env and add your API key
```

### Usage

#### Option 1 — MCP server for Claude Desktop, Cline, etc.

Add to your MCP settings:

```json
{
  "mcpServers": {
    "memory": {
      "command": "python",
      "args": ["-m", "adaptive_memory_engine", "serve"],
      "env": {
        "OPENAI_API_KEY": "sk-your-key-here",
        "PROVIDER_TYPE": "openai"
      }
    }
  }
}
```

Then ask Claude:
- "Remember that I prefer TypeScript for new projects"
- "What do I know about distributed systems?"
- "Summarize my notes on machine learning"

#### Option 2 — CLI

```bash
# Set your API key
export OPENAI_API_KEY="sk-your-key-here"

# Import files
python -m adaptive_memory_engine import ./notes.md --tag work
python -m adaptive_memory_engine import ./docs -r --tag documentation

# Search
python -m adaptive_memory_engine search "javascript async patterns"

# Ask AI
python -m adaptive_memory_engine ask "what projects have I documented?"

# Query knowledge graph
python -m adaptive_memory_engine graph "machine learning"
```

---

## 🛠 MCP Tools (13 tools, identical to v1)

When connected via MCP, clients can use:

| Tool | Description |
|------|-------------|
| `store_memory` | Save content with automatic embeddings and optional AI auto-tagging |
| `get_memory` | Retrieve a memory by key |
| `update_memory` | Update memory content and/or tags (supports `merge_tags`) |
| `delete_memory` | Delete a memory by key |
| `search` | Hybrid semantic + keyword search |
| `smart_search` | Alias for `search` (kept for back-compat) |
| `list_memories` | List memories, optionally filtered |
| `ask` | RAG-style Q&A over your memories |
| `summarize` | Summarize memories on a topic (or by key list) |
| `query_graph` | Query the knowledge graph (related concepts / path-finding) |
| `get_stats` | Engine + provider statistics |
| `backup` | Create a JSON snapshot |
| `get_provider_info` | Show current AI provider configuration |

---

## 📁 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              MCP Server (stdio / Streamable HTTP)           │
│                  FastAPI  +  uvicorn                        │
├─────────────────────────────────────────────────────────────┤
│                      MemoryEngine                           │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐    │
│  │  SQLite     │  │  VectorStore │  │  KnowledgeGraph │    │
│  │  + FTS5     │  │  (cosine)    │  │  (concepts)     │    │
│  └─────────────┘  └──────────────┘  └─────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│              Pluggable Provider Layer                       │
│   OpenAI ◄──► Ollama ◄──► Gemini ◄──► Anthropic            │
└─────────────────────────────────────────────────────────────┘
```

Embeddings are **mandatory** (every memory is semantically indexed). Intelligence (AI features like `ask`, `summarize`, auto-tagging) is **optional** — the engine degrades gracefully to keyword results when no intelligence provider is available.

---

## ⚙️ Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROVIDER_TYPE` | ✅ | `openai` | `openai`, `ollama`, `gemini`, `anthropic` |
| `OPENAI_API_KEY` | If OpenAI | — | OpenAI API key |
| `OPENAI_EMBEDDING_MODEL` | ❌ | `text-embedding-3-small` | |
| `OPENAI_CHAT_MODEL` | ❌ | `gpt-4o-mini` | |
| `OLLAMA_HOST` | If Ollama | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_EMBEDDING_MODEL` | ❌ | `nomic-embed-text` | |
| `OLLAMA_CHAT_MODEL` | ❌ | `llama3.2` | |
| `GEMINI_API_KEY` | If Gemini | — | Google AI API key |
| `ANTHROPIC_API_KEY` | If Anthropic | — | Anthropic API key (chat-only) |
| `INTELLIGENCE_PROVIDER` | ❌ | same as embeddings | Separate provider for AI features |
| `DATA_DIR` | ❌ | `./data` (local) / `/data` (PaaS) | Data directory |
| `TRANSPORT` | ❌ | auto (`http` on PaaS) | `stdio` or `http` |
| `PORT` | ❌ | `3000` | PaaS injects this |

---

## 📦 CLI Commands

```bash
python -m adaptive_memory_engine import <path> [-r] [--tag tag1,tag2]
python -m adaptive_memory_engine list [filter]
python -m adaptive_memory_engine search <query>
python -m adaptive_memory_engine get <id>
python -m adaptive_memory_engine delete <id>
python -m adaptive_memory_engine stats
python -m adaptive_memory_engine export [file]
python -m adaptive_memory_engine snapshot
python -m adaptive_memory_engine graph <concept>
python -m adaptive_memory_engine ask <question>
python -m adaptive_memory_engine provider
python -m adaptive_memory_engine serve         # start MCP server
python -m adaptive_memory_engine help
```

---

## 🔄 Migrating from v1 (Node.js) → v2 (Python)

**Nothing required** — the SQLite schema (`memories`, `embeddings`, `access_log`, FTS5 virtual table) and `knowledge-graph.json` shape are byte-compatible. Existing deployments keep their data.

If you already have a running Node version:

1. Pull the new Python code (Zeabur auto-deploys on push).
2. Verify with `curl https://<your-app>.zeabur.app/health`.
3. Reconnect your MCP clients to the same URL.

---

## 🧪 Testing

A minimal smoke test:

```bash
python -c "from adaptive_memory_engine.engine import MemoryEngine; \
           from adaptive_memory_engine.providers.factory import ProviderFactory; \
           from adaptive_memory_engine.config import Config; \
           cfg = Config.load(); \
           emb, _ = ProviderFactory.create(cfg); \
           eng = MemoryEngine(embedding_provider=emb, data_dir=cfg.data_dir); \
           eng.initialize(); \
           print('Loaded', len(eng._memories), 'memories')"
```

---

## 🤝 Contributing

Contributions welcome. Areas of interest:
- Additional AI providers
- Additional vector stores (FAISS, Qdrant, pgvector)
- Performance optimizations (HNSW, ANN)
- Documentation improvements

---

## 📄 License

MIT © Rakesh Sonawane

---

## 🔗 Links

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Ollama](https://ollama.com/)
- [OpenAI](https://platform.openai.com/)
- [Google AI Studio](https://aistudio.google.com/)