# TypingMind Plugin — Install Guide

Make every AI in TypingMind remember you, with **Adaptive Memory Engine** running on your own server.

> Replaces MemoryPlugin.com ($300/yr) with a free, self-hosted equivalent.
> **No Node.js required** — uses TypingMind's native HTTP Action plugin type.

---

## Prerequisites

Pick **one**:

### Option A — Local (free, single-machine)

- Python 3.11+
- An OpenAI API key (or Anthropic / Gemini / Ollama)
- Adaptive Memory Engine running on your laptop

### Option B — Hosted (free, cross-device)

- Adaptive Memory Engine deployed on [Zeabur](https://zeabur.com) or any VPS
- The public URL (e.g. `https://adaptive-memory.zeabur.app`)

---

## 1. Get the engine running

### Option A — Local

```bash
git clone https://github.com/rakesh1308/AdaptiveMemoryEngine.git
cd AdaptiveMemoryEngine
pip install -e .

cp .env.example .env
# edit .env: set OPENAI_API_KEY=sk-...

export TRANSPORT=http
export PORT=3000
adaptive-memory-server
```

You should see:

```
Engine ready: 0 memories
Starting HTTP MCP server on 0.0.0.0:3000
```

Verify with: `curl http://localhost:3000/health` → `{"status":"ok",...}`

### Option B — Hosted on Zeabur

See [`zeabur-deploy.md`](./zeabur-deploy.md). Once deployed, your MCP URL is `https://<your-app>.zeabur.app`.

---

## 2. Install the TypingMind plugin (HTTP variant)

**No Node.js required.** The plugin uses TypingMind's native HTTP Action type — works on any browser, any device.

1. Open **TypingMind** → click **Plugins** in the sidebar → **Add Plugin**
2. Choose **"Import from JSON / link"**
3. Paste one of these:

   **Option 1 — GitHub repo URL** (TypingMind fetches `plugin.json` automatically):
   ```
   https://github.com/rakesh1308/AdaptiveMemoryEngine
   ```

   **Option 2 — direct JSON URL**:
   ```
   https://raw.githubusercontent.com/rakesh1308/AdaptiveMemoryEngine/main/plugin.json
   ```

   **Option 3 — paste JSON** (works always):
   Open the URL above in your browser, copy all the JSON, then choose **Import via JSON file** in TypingMind.

4. Click **Install**.

---

## 3. Configure the plugin

1. Open the plugin's **Settings** tab.
2. Set **MCP Server URL**:
   - Local: `http://localhost:3000`
   - Zeabur: `https://<your-app>.zeabur.app`
3. Set **Auth Token** to the server's `AUTH_TOKEN`. It may be blank only for
   trusted local development; all remote deployments must use a token.
4. Click **Save** and **restart TypingMind** so the plugin loads cleanly.

---

## 4. Test it

Open a **new chat** in TypingMind. Try:

> *"Remember that I prefer dark roast coffee and I'm allergic to peanuts."*

The AI should call `store_memory` and reply with something like:

> *"Got it. Saved to memory."*

Now open a **fresh chat** and ask:

> *"What do you know about my dietary preferences?"*

The AI should call `search_memories` + `ask_memory` and recall both facts.

---

## 5. Daily-use patterns

### Auto-recall (the AI decides)

By default the plugin's system prompt instructs the AI to call `search_memories` whenever a question might relate to past context. You don't need to do anything.

### Explicit save

Just say *"remember..."* or *"note that..."* and the AI calls `store_memory`.

### Buckets via tag scoping

For a sensitive or project-specific chat:

> *"For this chat, only remember/recall things tagged 'work' and 'client-x'."*

The AI calls `set_active_tags(["work","client-x"])`. The chat now only sees memories with those tags.

To reset:

> *"Clear the tag scope."*

### Version history & restore

> *"Show me the version history for memory 'project-stack'."*

> *"Restore that memory to version 9f8e7d6c."*

### Dedup / suggestions

> *"Run a suggestion scan."*

> *"List open suggestions."*

> *"Apply suggestion abc123."*

### Bulk export

> *"Export all my memories as CSV."*

Or for a portable text file you can paste into any AI:

> *"Export as text."*

### Import past ChatGPT / Claude history

1. Export your data from ChatGPT (`Settings → Data controls → Export`) or Claude (`Settings → Privacy → Export data`).
2. Unzip and find `conversations.json`.
3. In TypingMind:

> *"Import chat history from /Users/you/Downloads/chatgpt-export/conversations.json with tag prefix 'gpt'."*

The AI calls `import_chat_export` and indexes the entire archive, tagged so you can scope or filter later.

---

## 6. What ships in this plugin

| Tool | What it does |
|---|---|
| `store_memory` | Save a fact, optionally auto-tag |
| `search_memories` | Hybrid semantic + keyword search |
| `ask_memory` | RAG: question + retrieved memories → answer |
| `get_memory` | Fetch one memory by id |
| `list_memories` | List all, filter by text/tag |
| `delete_memory` | Remove one |
| `set_active_tags` / `clear_active_tags` | Per-chat bucket scoping |
| `get_memory_history` | All prior versions of a memory |
| `restore_memory_version` | Revert to a prior version (itself reversible) |
| `list_suggestions` / `apply_suggestion` / `dismiss_suggestion` | Dedup inbox |
| `run_suggestion_scan` | Trigger a new dedup/stale scan |
| `export_memories` | JSON / CSV / text-with-AI-instructions |
| `import_memories` | Bulk import with dedup |
| `import_chat_export` | Import ChatGPT/Claude/Gemini export files |
| `summarize_memory` | 1-2 sentence summary of one memory |
| `summarize` | Summarize a query-matching set |
| `query_graph` | Knowledge graph queries |
| `get_stats` | Engine stats |
| `backup` | Full JSON snapshot |

22 tools. Zero subscription.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| Plugin install fails | Ensure JSON is valid; paste into a JSON validator first |
| AI says "tool not found" | Restart TypingMind after installing the plugin |
| Connection refused | Verify `curl <your MCP URL>/health` returns `{"status":"ok"}` |
| 401 unauthorized | Check the `Authorization` header in plugin user settings |
| Slow first response | Embedding the query takes ~500ms — normal |

---

## Next

- Want to share with friends? → see [`zeabur-deploy.md`](./zeabur-deploy.md) for public HTTPS
- Want to also use the memory in Claude Desktop / Cursor? → same MCP URL works in any MCP client
- Want to extend with custom tools? → edit `src/adaptive_memory_engine/server.py`
