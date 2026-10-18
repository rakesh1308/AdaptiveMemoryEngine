# Adaptive Memory

**Private, local memory for your coding agents. Free and open source. No cloud, no API key.**

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

Check it works: `adaptive-memory stats` should print a JSON summary.

Prefer not to install anything globally? With [uv](https://docs.astral.sh/uv/), point your agent at
`uvx adaptive-memory` instead of `adaptive-memory`.

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

If your agent can't find the `adaptive-memory` command, use the full Python path instead:
`"command": "python", "args": ["-m", "adaptive_memory"]`.

### Teach your agent when to use it (optional but recommended)

Copy `skill/adaptive-memory/SKILL.md` into your agent's skills folder, for example
`~/.claude/skills/adaptive-memory/SKILL.md` for Claude Code. It tells the agent when to
search, what to store, and what never to store.

### Try it

Restart your agent, then say: *"Remember that we use PostgreSQL for the main database."*
In a later session ask: *"Which database do we use?"*

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

## How good is the search?

`study/eval_embeddings.py` scores retrieval on 20 memories, 20 paraphrased questions
(no shared wording, e.g. "who signs off schema changes?" for "Priya approves all database
migrations") and 10 exact-term queries. Top-1 accuracy:

| Embedding model (all run locally) | Paraphrase | Exact terms |
|---|---|---|
| `BAAI/bge-small-en-v1.5` (default, 130 MB) | 85-90% | 100% |
| `sentence-transformers/all-MiniLM-L6-v2` | 90% | 100% |
| `BAAI/bge-base-en-v1.5` | 90% | 100% |
| Keyword search only | 45% | n/a |

Set `OPENAI_API_KEY` and rerun the script to add OpenAI `text-embedding-3-small` to the table.
The set is small, so treat the numbers as a sanity check, not a benchmark.
Switch models with `ADAPTIVE_MEMORY_MODEL`; memories are re-embedded automatically.

## Is SQLite enough? (Do I need Postgres?)

Yes for this use. Search keeps all vectors in memory and compares them with one matrix
multiply. Measured median search time (384-dim vectors, 8-word memories):

| Memories | Search time | Database size |
|---|---|---|
| 1,000 | 2 ms | < 1 MB |
| 10,000 | 20 ms | 22 MB |
| 50,000 | 130 ms | 111 MB |
| 100,000 | 260 ms | 221 MB |

A coding agent writes hundreds or low thousands of memories. Postgres + pgvector only
pays off with millions of memories or many users sharing one server.

## Works where

Agents that run on your machine and can start a local process: Claude Code, Cursor, Windsurf,
Cline, VS Code Copilot, Zed, Claude Desktop. It does **not** work in the claude.ai website or
phone apps, which can't reach a process on your computer.

## Privacy

Memories never leave your device. The only network call is the one-time model download from
Hugging Face. Do not store passwords or API keys in memory.

## License

Apache License 2.0. See [LICENSE](LICENSE).
