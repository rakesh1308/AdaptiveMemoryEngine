# Adaptive Memory

**Private, local memory for your coding agents. Pay once. No subscription, no cloud.**

Adaptive Memory is an MCP server that gives Claude Code, Cursor, Windsurf, Cline and other
local agents a long-term memory. Memories live in one SQLite file on your machine. Search is
semantic (by meaning) plus keyword, using a small embedding model that runs locally.
No API key, no account, no server, no Docker.

## Install

Requires Python 3.10+.

```bash
pip install adaptive-memory
adaptive-memory warmup   # optional: downloads the ~130 MB embedding model now, once
```

### Claude Code

```bash
claude mcp add adaptive-memory -- adaptive-memory
```

### Cursor / Windsurf / Cline / Claude Desktop

Add to your MCP config:

```json
{
  "mcpServers": {
    "adaptive-memory": { "command": "adaptive-memory" }
  }
}
```

Then install the included skill (`skill/adaptive-memory/SKILL.md`) so your agent knows
when to remember and when to search.

## Tools

| Tool | What it does |
|---|---|
| `store_memory(key, content, tags?)` | Save or overwrite one fact |
| `get_memory(key)` | Read one memory |
| `search(query, limit?)` | Find memories by meaning and keywords |
| `list_memories(tag?, limit?)` | Recent memories |
| `delete_memory(key)` | Remove a memory |
| `get_stats()` | Count, model, database path |
| `export_memories()` | Full JSON backup |

## Where your data lives

| | Default | Override |
|---|---|---|
| Database | `~/.adaptive-memory/memory.db` | `ADAPTIVE_MEMORY_DB` |
| Model cache | `~/.adaptive-memory/models/` | `ADAPTIVE_MEMORY_HOME` |
| Embedding model | `BAAI/bge-small-en-v1.5` | `ADAPTIVE_MEMORY_MODEL` |

Use a different `ADAPTIVE_MEMORY_DB` per project if you want separate memories.
To back up, copy the database file or run `adaptive-memory export > backup.json`.

## How it works

- One SQLite file with an FTS5 keyword index and stored vectors.
- Search merges keyword and semantic rankings. If the embedding model can't load, it falls
  back to keyword search and says so.
- Changing the embedding model re-embeds your memories automatically. Nothing is lost.
- Brute-force vector search is fast up to tens of thousands of memories, which is far more
  than a coding agent will write.

## Works where

Agents that run on your machine and can start a local process: Claude Code, Cursor, Windsurf,
Cline, VS Code Copilot, Zed, Claude Desktop. It does **not** work in the claude.ai website or
phone apps, which can't reach a process on your computer.

## Privacy

Memories never leave your device. The only network call is the one-time model download from
Hugging Face. Do not store passwords or API keys in memory.

## Previous version

Version 3.x (OpenAI + Postgres) is preserved under the `v3.0.0-legacy` tag and remains MIT.

## License

See [LICENSE](LICENSE).
