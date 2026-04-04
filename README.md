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
| **Multi-Provider** | Use OpenAI, Google Gemini, or local Ollama - your choice. |

---

## 🚀 Quick Start

### Prerequisites

- **Node.js ≥ 22.0.0** (for built-in SQLite support)
- An API key from one of:
  - [OpenAI](https://platform.openai.com/api-keys) (recommended)
  - [Google AI Studio](https://aistudio.google.com/app/apikey)
  - Or install [Ollama](https://ollama.com) for local/offline use

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/AdaptiveMemoryEngine.git
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

```json
{
  "mcpServers": {
    "memory": {
      "command": "node",
      "args": ["/path/to/AdaptiveMemoryEngine/server.js"],
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
             ├──►  ./data/memories.db  ◄──├──► Claude (MCP)
MCP Store ───┘         ↑                    │
                       └────────────────────┘
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
# File import (supports 50+ file types!)
node cli.js import <file-or-directory> [-r] [--tag tag1,tag2]

# Search memories
node cli.js search <query>

# Ask AI about your memories
node cli.js ask <question>

# List all memories
node cli.js list [filter]

# Get specific memory
node cli.js get <id>

# Query knowledge graph
node cli.js graph <concept>

# Show statistics
node cli.js stats

# Create backup
node cli.js snapshot

# Show provider configuration
node cli.js provider
```

### Supported File Types

| Category | Extensions |
|----------|------------|
| **Documents** | `.md` `.mdx` `.txt` `.pdf` `.rst` `.csv` `.log` |
| **Code** | `.js` `.ts` `.py` `.java` `.go` `.rs` `.cpp` `.rb` `.swift` `.kt` and 30+ more |
| **Config** | `.json` `.yaml` `.xml` `.env` `.tf` `Dockerfile` `Makefile` |

---

## 🛠️ MCP Tools (for AI Assistants)

When connected via MCP, Claude can use these tools:

| Tool | Description |
|------|-------------|
| `store_memory` | Save content with automatic embeddings & tags |
| `get_memory` | Retrieve a memory by key |
| `search` | Semantic + keyword hybrid search |
| `ask` | Ask questions about your memories (AI answers) |
| `summarize` | Summarize memories on a topic |
| `query_graph` | Explore concept relationships |
| `backup` | Create JSON snapshot |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server (stdio/SSE)                   │
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

MIT © AdaptiveMemoryEngine Contributors

---

## 🔗 Links

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Ollama](https://ollama.com/)
- [OpenAI](https://platform.openai.com/)
- [Google AI Studio](https://aistudio.google.com/)
