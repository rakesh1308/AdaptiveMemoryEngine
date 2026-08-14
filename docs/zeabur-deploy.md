# Deploying Adaptive Memory Engine on Zeabur

Zeabur's free tier is enough for personal + small-team use. Total monthly cost: **$0** (free tier) or **$5/mo** (hobby tier with persistent disk).

---

## 1. Prerequisites

- A [Zeabur](https://zeabur.com) account (free)
- An OpenAI API key (or any other supported provider)
- This repo (already public at `github.com/rakesh1308/AdaptiveMemoryEngine`)

---

## 2. Deploy from GitHub

### Option A — One-click from the dashboard

1. Log into [zeabur.com](https://zeabur.com) → **Create Project** → **Deploy New Service** → **GitHub**.
2. Select `rakesh1308/AdaptiveMemoryEngine`.
3. Zeabur auto-detects the [`Dockerfile`](../Dockerfile) and builds it.
4. Once deployed, click **Networking** → **Generate Domain** (or attach your own).
5. Note your URL: `https://adaptive-memory.<region>.zeabur.app`.

### Option B — `zbctl` CLI

```bash
# install
npm install -g @zeabur/cli

# login
zbctl login

# deploy from current dir
zbctl deploy
```

---

## 3. Configure environment variables

In Zeabur → **Service** → **Variables**, set:

| Variable | Value | Required |
|---|---|---|
| `TRANSPORT` | `http` | ✅ |
| `PORT` | `3000` | ✅ (Zeabur injects `$PORT`; we honor it) |
| `OPENAI_API_KEY` | `sk-...` | ✅ |
| `PROVIDER_TYPE` | `openai` (default) | optional |
| `INTELLIGENCE_PROVIDER` | `openai` (default) | optional |
| `AUTH_TOKEN` | `<random 32+ chars>` | ⚠️ recommended for public deploys |
| `DATA_DIR` | `/data` | ⚠️ recommended — wire a persistent volume |
| `LOG_LEVEL` | `INFO` | optional |

To generate an auth token:

```bash
openssl rand -hex 32
```

---

## 4. Persistent disk (so memories survive restarts)

The SQLite DB lives in `DATA_DIR`. By default Zeabur's container filesystem is **ephemeral** — restarts wipe data. Fix:

1. In Zeabur → **Service** → **Storage** → **Add Volume**.
2. Mount path: `/data`
3. Size: `1GB` is plenty for tens of thousands of memories.
4. Set `DATA_DIR=/data` in env vars.

Now SQLite + knowledge graph snapshots persist across deploys and restarts.

---

## 5. Verify the deploy

```bash
curl https://adaptive-memory.<region>.zeabur.app/health
```

Expected:

```json
{
  "status": "ok",
  "engineReady": true,
  "memories": 0,
  "concepts": 0,
  "embeddings": 0,
  "provider": {"type": "openai", "model": "text-embedding-3-small"}
}
```

The MCP endpoint is at `https://adaptive-memory.<region>.zeabur.app/mcp` (streamable HTTP transport).

---

## 6. Connect TypingMind

See [`typingmind-setup.md`](./typingmind-setup.md). The plugin's **MCP Server URL** setting should be:

```
https://adaptive-memory.<region>.zeabur.app
```

And **Auth Token** = the `AUTH_TOKEN` env var you set above.

---

## 7. Connect other MCP clients

The same URL works in:

- **Claude Desktop** — add to `claude_desktop_config.json`:
  ```json
  {
    "mcpServers": {
      "memory": {
        "url": "https://adaptive-memory.<region>.zeabur.app/mcp",
        "headers": {"Authorization": "Bearer <your AUTH_TOKEN>"}
      }
    }
  }
  ```
- **Cursor / Cline / Windsurf / Zed** — same `url` + `headers` shape
- **Claude Code** — `claude mcp add memory --url https://... --header "Authorization: Bearer ..."`

All clients share the **same memory**. Whatever you save in Claude Desktop is instantly visible in TypingMind.

---

## 8. Backups

Snapshot the entire memory store:

```bash
curl -H "Authorization: Bearer <AUTH_TOKEN>" \
     https://adaptive-memory.<region>.zeabur.app/mcp \
     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"backup","arguments":{}},"id":1}'
```

Or call the MCP tool from any client (`backup` → returns path + size).

Snapshots land in `DATA_DIR/snapshots/snapshot-<timestamp>.json`. Pull them via Zeabur's volume export, or schedule a daily export to S3 / GitHub via a cron service.

---

## 9. Costs

| Resource | Free tier | Hobby tier (~$5/mo) |
|---|---|---|
| Container hours | 100 hr/mo | unlimited |
| Persistent disk | 1 GB | 10 GB |
| Egress | 100 GB | unlimited |
| Memory | enough for thousands of memories + KG | enough for hundreds of thousands |

**Real-world cost: $0 for personal use, ~$5/mo if you go past free tier.** Plus your OpenAI embedding API costs (~$1-5/mo for normal use).

Compare to **MemoryPlugin.com**: $180-300/yr, plus the privacy cost of a third party holding your memory.

---

## 10. Custom domain

In Zeabur → **Networking** → **Custom Domain**:

```
memory.yourdomain.com  →  adaptive-memory.<region>.zeabur.app
```

Then your TypingMind plugin URL becomes:

```
https://memory.yourdomain.com
```

Cleaner for sharing with friends.

---

## 11. Team / multi-user

For multi-tenant use, generate one `AUTH_TOKEN` per user (or per team). The current SQLite is **single-tenant** — one user per server instance. To support multiple isolated users on one server, you'd fork the engine to add a `user_id` column to all tables. (Out of scope for v2.x.)

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `engine not initialized` | Check `OPENAI_API_KEY` is set and valid |
| `401` from MCP endpoint | Verify `Authorization: Bearer <token>` header is set |
| `connection refused` | Zeabur service must be running; check logs |
| Memories vanish after restart | Persistent volume not mounted; `DATA_DIR` mismatch |
| Slow embeddings | Normal first-request latency; subsequent requests are cached |

---

## Next

- Connect TypingMind → [`typingmind-setup.md`](./typingmind-setup.md)
- Add the [Custom GPT / OpenAPI mirror](./openapi-setup.md) (Tier 2 — only needed if sharing with non-dev friends)