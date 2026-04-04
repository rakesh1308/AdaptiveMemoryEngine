# 🧠 AdaptiveMemoryEngine

**Semantic memory for AI assistants. Pluggable, private, and MCP-native.**

[![Node Version](https://img.shields.io/badge/node-%3E%3D22.0.0-brightgreen)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AdaptiveMemoryEngine is an intelligent memory system with **mandatory semantic embeddings**, a **knowledge graph**, and **native MCP support**. Unlike other memory systems, it requires embeddings (no keyword-only fallback) and lets you choose any AI provider—including local models via Ollama.

---

## ✨ Philosophy

| Principle | Implementation |
|-----------|---------------|
| **Embeddings are mandatory** | Every memory is semantically indexed. No keyword-only search fallback. |
| **Intelligence is optional** | Auto-tagging, Q&A, and summaries use AI only when configured. |
| **Provider-agnostic** | Use OpenAI, Google Gemini, local Ollama, or mix providers. |
| **Privacy-first** | Run completely offline with Ollama. Your data never leaves your machine. |
| **MCP-native** | Built on the official Model Context Protocol. Works with Claude, Cline, etc. |

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/yourusername/AdaptiveMemoryEngine.git
cd AdaptiveMemoryEngine
npm install
```

### Configure

```bash
cp .env.example .env
# Edit .env with your preferred provider (see Provider Options below)
```

### Run

```bash
# MCP server (stdio mode for Claude Desktop, Cline)
npm start

# Or SSE mode for remote access
TRANSPORT=sse PORT=3000 npm start

# CLI for file imports and management
node cli.js import ./my-notes.md
node cli.js search "machine learning"
```

---

## 🔌 Provider Options

AdaptiveMemoryEngine supports multiple AI providers. Choose based on your priorities:

### Option 1: OpenAI (Recommended)
Best balance of quality and speed.

```bash
# .env
PROVIDER_TYPE=openai
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_CHAT_MODEL=gpt-4o-mini
```

### Option 2: Ollama (Local & Private)
100% offline. No API costs. Your data stays local.

```bash
# 1. Install Ollama: https://ollama.com
# 2. Pull models
ollama pull nomic-embed-text
ollama pull llama3.2

# 3. Configure
# .env
PROVIDER_TYPE=ollama
OLLAMA_HOST=http://localhost:11434
```

### Option 3: Google Gemini (Free Tier)
Generous free tier. Strong multilingual support.

```bash
# .env
PROVIDER_TYPE=gemini
GEMINI_API_KEY=your-key  # Get from https://aistudio.google.com/app/apikey
```

### Option 4: Mixed Providers
Use different providers for embeddings vs. intelligence.

```bash
# OpenAI embeddings + Anthropic intelligence
# .env
PROVIDER_TYPE=openai
OPENAI_API_KEY=sk-...
INTELLIGENCE_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 📖 Usage

### As MCP Server (Claude Desktop, Cline)

Add to your MCP settings:

```json
{
  "mcpServers": {
    "memory": {
      "command": "node",
      "args": ["/path/to/AdaptiveMemoryEngine/server.js"],
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "PROVIDER_TYPE": "openai"
      }
    }
  }
}
```

Then ask Claude:
- "Store this: Machine learning is a subset of AI..."
- "Search my memories for distributed systems"
- "What do I know about Kubernetes?"

### CLI

```bash
# Import files
node cli.js import ./notes.md --tag work
node cli.js import ./docs -r --tag documentation

# Search
node cli.js search "javascript async patterns"

# Ask AI about your memories
node cli.js ask "summarize what I know about React"

# Knowledge graph
node cli.js graph "machine learning"

# Show provider config
node cli.js provider
```

### Programmatic (NPM Module)

```javascript
import { MemoryEngine, OllamaProvider } from 'adaptive-memory-engine';

const engine = new MemoryEngine({
  dataDir: './data',
  embeddingProvider: new OllamaProvider({
    embeddingModel: 'nomic-embed-text',
    chatModel: 'llama3.2'
  })
});

await engine.initialize();

// Store memory
await engine.storeMemory('ml_basics', `
  Machine learning enables computers to learn from data
  without being explicitly programmed.
`, { tags: ['ai', 'ml'] });

// Search
const results = await engine.searchMemories('learning algorithms', {
  topK: 5,
  mode: 'hybrid'
});

// Query knowledge graph
const related = engine.knowledgeGraph.getRelatedConcepts('machine learning', 2);
```

---

## 🛠️ MCP Tools

| Tool | Description | Requires Intelligence |
|------|-------------|----------------------|
| `store_memory` | Save content with embeddings & auto-tags | Optional |
| `get_memory` | Retrieve by key | No |
| `update_memory` | Update content/tags | No |
| `delete_memory` | Remove a memory | No |
| `search` | Hybrid semantic + keyword search | No |
| `list_memories` | List/filter memories | No |
| `query_graph` | Explore concept relationships | No |
| `ask` | Natural language Q&A over memories | Yes |
| `summarize` | AI-generated summaries | Yes |
| `backup` | Create JSON snapshot | No |
| `get_provider_info` | Show AI provider config | No |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server (stdio/SSE)                   │
├─────────────────────────────────────────────────────────────┤
│                      MemoryEngine                           │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐    │
│  │  SQLite     │  │  VectorStore │  │  KnowledgeGraph │    │
│  │  (storage)  │  │  (embeddings)│  │  (concepts)     │    │
│  └─────────────┘  └──────────────┘  └─────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│              Pluggable Provider Layer                       │
│   OpenAI ◄──► Ollama ◄──► Gemini ◄──► Anthropic            │
│   (embeddings + intelligence)                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🆚 Comparison with Alternatives

| Feature | AdaptiveMemoryEngine | basic-memory | mem0 | Other MCP Memory |
|---------|---------------------|--------------|------|------------------|
| **Embeddings** | ✅ Mandatory | ✅ Yes | ✅ Yes | ⚠️ Optional/No |
| **Local/Offline** | ✅ Ollama | ❌ No | ❌ No | Rare |
| **Provider Choice** | ✅ Any (OpenAI, Gemini, Ollama, mix) | ❌ OpenAI only | ❌ Proprietary | Usually OpenAI |
| **Knowledge Graph** | ✅ Built-in | ❌ No | ❌ No | Rare |
| **MCP Native** | ✅ Yes | ✅ Yes | ❌ No | Varies |
| **Storage** | ✅ SQLite | ❌ JSONL | ☁️ Cloud | Varies |
| **Hybrid Search** | ✅ Semantic + Keyword | ✅ Yes | ✅ Yes | Varies |
| **Auto-tagging** | ✅ AI-generated | ✅ Yes | ✅ Yes | Varies |
| **Privacy** | ✅ 100% offline possible | ❌ Cloud | ❌ Cloud | Varies |

### Why AdaptiveMemoryEngine?

vs **basic-memory**:
- ✅ **Pluggable providers** — Use Ollama, Gemini, or mix providers
- ✅ **Knowledge graph** — Concept relationships, not just search
- ✅ **SQLite storage** — Reliable, queryable, no corruption issues
- ✅ **100% offline capable** — Run locally with Ollama

vs **mem0**:
- ✅ **Local-first** — Your data stays on your machine
- ✅ **MCP-native** — Works directly with Claude, Cline
- ✅ **No cloud dependency** — No accounts, no quotas, no outages
- ✅ **Open source** — Full control and transparency

vs **Custom JSON/memory MCPs**:
- ✅ **Mandatory embeddings** — Every memory is semantically indexed
- ✅ **Intelligence optional** — Core works without AI, enhanced with AI
- ✅ **Production-ready** — Transaction support, backups, lifecycle management

---

## ⚙️ Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROVIDER_TYPE` | ❌ | `openai` | Provider: `openai`, `ollama`, `gemini` |
| `OPENAI_API_KEY` | If OpenAI | — | OpenAI API key |
| `OLLAMA_HOST` | If Ollama | `http://localhost:11434` | Ollama server URL |
| `GEMINI_API_KEY` | If Gemini | — | Google AI API key |
| `INTELLIGENCE_PROVIDER` | ❌ | Same as embeddings | Separate provider for AI features |
| `DATA_DIR` | ❌ | `./data` | Data directory |
| `TRANSPORT` | ❌ | `stdio` | `stdio` or `sse` |
| `PORT` | ❌ | `3000` | Port for SSE mode |

---

## 🧪 Testing

```bash
# Verify syntax
node --check server.js
node --check cli.js

# Test with different providers
PROVIDER_TYPE=ollama node cli.js stats
PROVIDER_TYPE=gemini GEMINI_API_KEY=... node cli.js search "test"
```

---

## 📝 Requirements

- **Node.js ≥ 22.0.0** (for built-in `node:sqlite`)
- One of:
  - OpenAI API key, OR
  - Ollama installed locally, OR
  - Google Gemini API key

---

## 🤝 Contributing

Contributions welcome! Areas of interest:
- Additional AI providers (Cohere, Mistral, etc.)
- Additional storage backends
- Performance optimizations
- Documentation improvements

---

## 📄 License

MIT © AdaptiveMemoryEngine Contributors

---

## 🔗 Links

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Ollama](https://ollama.com/)
- [OpenAI](https://platform.openai.com/)
- [Google AI Studio](https://aistudio.google.com/)
