# 🧠 AdaptiveMemoryEngine

**Semantic memory for AI assistants. Pluggable, private, and MCP-native.**

[![Node Version](https://img.shields.io/badge/node-%3E%3D22.0.0-brightgreen)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AdaptiveMemoryEngine is an intelligent memory system that remembers everything you tell it. Unlike simple note-taking apps, it uses **semantic embeddings** to understand the meaning of your content, enabling intelligent search and AI-powered insights.

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| **Semantic Search** | Find memories by meaning, not just keywords. Ask "machine learning" and find "neural networks" content. |
| **Knowledge Graph** | Automatically builds relationships between concepts in your memories. |
| **AI-Powered** | Optional AI features for auto-tagging, Q&A, and summarization. |
| **Privacy-First** | Run completely offline with local AI models (Ollama). Your data never leaves your machine. |
| **MCP Native** | Works with Claude Desktop, Cline, and other MCP-compatible tools. |
| **Multi-Provider** | Use OpenAI, Google Gemini, Anthropic, or local Ollama — your choice. |

---

## 🚀 Quick Start

### Prerequisites

- **Node.js ≥ 22.0.0** (for built-in SQLite support)
- An embedding provider — one of:
  - [OpenAI](https://platform.openai.com/api-keys) (recommended)
  - [Google AI Studio](https://aistudio.google.com/app/apikey)
  - [Ollama](https://ollama.com) for 100% local/offline use

### Installation

```bash
# Clone the repository
git clone https://github.com/rakesh1308/AdaptiveMemoryEngine.git
cd AdaptiveMemoryEngine

# Install dependencies
npm install

# Configure your environment
cp .env.example .env
# Edit .env and add your API key
```

### Usage

#### Option 1: MCP Server (for Claude Desktop, Cline)

Add to your MCP settings:

**Windows:**
```json
{
  "mcpServers": {
    "memory": {
      "command": "cmd",
      "args": [
        "/c",
        "cd C:\\path\\to\\AdaptiveMemoryEngine && node server.js"
      ],
      "env": {
        "OPENAI_API_KEY": "sk-your-key-here",
        "PROVIDER_TYPE": "openai"
      }
    }
  }
}
```

**macOS/Linux:**
```json
{
  "mcpServers": {
    "memory": {
      "command": "bash",
      "args": [
        "-c",
        "cd /path/to/AdaptiveMemoryEngine && node server.js"
      ],
      "env": {
        "OPENAI_API_KEY": "sk-your-key-here",
        "PROVIDER_TYPE": "openai"
      }
    }
  }
}
```

> **Note:** The `cd` command ensures Claude uses the same data directory as the CLI. Without it, Claude would create a separate data folder.

Then ask Claude:
- "Remember that I prefer TypeScript for new projects"
- "What do I know about distributed systems?"
- "Summarize my notes on machine learning"

#### Option 2: CLI

```bash
# Set your API key
export OPENAI_API_KEY="sk-your-key-here"  # Linux/Mac
# or
set OPENAI_API_KEY=sk-your-key-here       # Windows

# Import files
node cli.js import ./notes.md --tag work
node cli.js import ./docs -r --tag documentation

# Search your memories
node cli.js search "javascript async patterns"

# Ask AI about your memories
node cli.js ask "what projects have I documented?"

# Query knowledge graph
node cli.js graph "machine learning"
```

---

## 📁 Data Sharing Between CLI and MCP

**Yes, CLI and Claude share the same memories!**

Both CLI and MCP server use the same `DATA_DIR` (default: `./data`). Memories you import via CLI are immediately available to Claude, and vice versa.

```
CLI Import ──┐
             ├──►  ./data/memories.db  ◄──┬──► Claude (MCP)
MCP Store ───┘                            │
                 ./data/knowledge-graph.json
```

**Example workflow:**
```bash
# 1. Import documents via CLI
node cli.js import ./project-docs --tag myproject

# 2. Ask Claude about them (in Claude Desktop)
# "What documentation do I have for myproject?"

# 3. Claude finds and uses the memories you just imported
```

---

## 🔌 Provider Configuration

Choose your AI provider based on your needs:

### OpenAI (Recommended)
Best balance of quality and speed.

```bash
# .env
PROVIDER_TYPE=openai
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_CHAT_MODEL=gpt-4o-mini
```

### Ollama (Local & Private)
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

### Google Gemini (Free Tier)
Generous free tier. Strong multilingual support.

```bash
# .env
PROVIDER_TYPE=gemini
GEMINI_API_KEY=your-key
```

### Mixed Providers
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

## 📖 CLI Commands

```bash
node cli.js import <file-or-directory> [-r] [--tag tag1,tag2]  # Import files
node cli.js list [filter]                                       # List all memories
node cli.js search <query>                                      # Semantic + keyword search
node cli.js get <id>                                            # Get memory by ID
node cli.js delete <id>                                         # Delete a memory
node cli.js stats                                               # Show statistics
node cli.js export [file]                                       # Export memories to JSON
node cli.js snapshot                                            # Create backup snapshot
node cli.js graph <concept>                                     # Query knowledge graph
node cli.js ask <question>                                      # Ask AI about your memories
node cli.js provider                                            # Show provider configuration
```

### Supported File Types

| Category | Extensions |
|----------|------------|
| **Documents** | `.md` `.mdx` `.txt` `.pdf` `.rst` `.adoc` `.tex` `.csv` `.tsv` `.log` |
| **Code** | `.js` `.ts` `.jsx` `.tsx` `.py` `.java` `.go` `.rs` `.c` `.cpp` `.h` `.cs` `.rb` `.php` `.swift` `.kt` `.scala` `.r` `.sql` `.sh` `.bash` `.ps1` `.vue` `.svelte` `.html` `.css` `.scss` and more |
| **Config** | `.json` `.yaml` `.yml` `.xml` `.ini` `.conf` `.env` `Dockerfile` `Makefile` `.gitignore` |

---

## 🛠️ MCP Tools (for AI Assistants)

When connected via MCP, Claude can use these tools:

| Tool | Description |
|------|-------------|
| `store_memory` | Save content with automatic embeddings and optional AI auto-tagging |
| `get_memory` | Retrieve a memory by key |
| `update_memory` | Update memory content and/or tags |
| `delete_memory` | Delete a memory |
| `search` | Semantic + keyword hybrid search |
| `list_memories` | List all memories, optionally filtered by tag |
| `ask` | Ask questions about your memories (AI answers if intelligence model is available) |
| `summarize` | Summarize memories on a topic (AI summary if intelligence model is available) |
| `query_graph` | Explore concept relationships in the knowledge graph |
| `get_stats` | Show system statistics |
| `backup` | Create a JSON snapshot |
| `get_provider_info` | Show current AI provider configuration |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server (stdio/HTTP)                  │
│                         or                                  │
│                        CLI Tool                             │
├─────────────────────────────────────────────────────────────┤
│                      MemoryEngine                           │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐    │
│  │  SQLite     │  │  VectorStore │  │  KnowledgeGraph │    │
│  │  (storage)  │  │  (embeddings)│  │  (concepts)     │    │
│  └─────────────┘  └──────────────┘  └─────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│              Pluggable Provider Layer                       │
│   OpenAI ◄──► Ollama ◄──► Gemini ◄──► Anthropic            │
└─────────────────────────────────────────────────────────────┘
```

**Design principle:** Embeddings are **mandatory** (every memory is semantically indexed). Intelligence (AI features like `ask`, `summarize`, auto-tagging) is **optional** — the system degrades gracefully to keyword-based results when no intelligence provider is available.

---

## ⚙️ Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROVIDER_TYPE` | ✅ | `openai` | Provider: `openai`, `ollama`, `gemini` |
| `OPENAI_API_KEY` | If OpenAI | — | OpenAI API key |
| `OLLAMA_HOST` | If Ollama | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_EMBEDDING_MODEL` | If Ollama | `nomic-embed-text` | Ollama embedding model |
| `OLLAMA_CHAT_MODEL` | If Ollama | `llama3.2` | Ollama chat model |
| `GEMINI_API_KEY` | If Gemini | — | Google AI API key |
| `ANTHROPIC_API_KEY` | If Anthropic | — | Anthropic API key |
| `INTELLIGENCE_PROVIDER` | ❌ | Same as embeddings | Separate provider for AI features |
| `DATA_DIR` | ❌ | `./data` | Data directory |
| `TRANSPORT` | ❌ | `stdio` | `stdio` or `http` |
| `PORT` | ❌ | `3000` | Port for HTTP mode |

---

## 🧪 Testing

```bash
# Verify setup
node cli.js provider

# Quick test
node cli.js import ./README.md --tag test
node cli.js search "semantic memory"
node cli.js stats
```

---

## 🤝 Contributing

Contributions welcome! Areas of interest:
- Additional AI providers
- Additional storage backends
- Performance optimizations
- Documentation improvements

---

## 📄 License

MIT © Rakesh Sonawane

---

## 🔗 Links

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Ollama](https://ollama.com/)
- [OpenAI](https://platform.openai.com/)
- [Google AI Studio](https://aistudio.google.com/)
