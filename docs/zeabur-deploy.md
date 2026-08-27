# Deploying AdaptiveMemoryEngine v3 on Zeabur

## Services

Deploy two separate services in one Zeabur project:

1. **PostgreSQL with pgvector** using Zeabur's pgvector template.
2. **AdaptiveMemoryEngine** from this GitHub repository.

Use PostgreSQL's private `zeabur.internal` connection from the application. Public database networking is needed only if migration is run from your computer, and should be disabled afterward.

## Application variables

| Variable | Value |
|---|---|
| `STORAGE_BACKEND` | `postgres` |
| `DATABASE_URL` | Private PostgreSQL pgvector URL |
| `DATABASE_POOL_MIN` | `1` |
| `DATABASE_POOL_MAX` | `10` |
| `TRANSPORT` | `http` |
| `PORT` | `3000` or Zeabur-injected port |
| `PROVIDER_TYPE` | `openai`, `gemini`, `ollama`, or `anthropic` |
| `OPENAI_API_KEY` | Required for the default provider |
| `AUTH_TOKEN` | Optional random value of at least 32 bytes |
| `ALLOWED_ORIGINS` | Optional exact browser client origin |
| `ALLOWED_HOSTS` | Optional application hostname; enables strict Host validation |
| `DATA_DIR` | Optional `/data` path for controlled imports/exports |

The model used at runtime must have the same vector dimension as the migration. A database created using 1536-dimensional OpenAI vectors cannot be opened with a 768-dimensional Gemini embedding configuration.

If `ALLOWED_HOSTS` is unset, Zeabur proxy hosts are accepted. If it is set,
include the exact public application hostname or MCP requests will return 421.

## Migrate the backup

For an existing SQLite backup, run `adaptive-memory-migrate` on the computer
containing the backup and target Zeabur's temporary public PostgreSQL URL. The
database file does not need to be uploaded to Zeabur. The command verifies row
counts and content hashes before reporting `status=complete`; afterward, switch
the application to Zeabur's private PostgreSQL URL and disable public database
networking.

## Verify

```bash
curl https://YOUR-APP.zeabur.app/health
```

Expected shape:

```json
{
  "status": "ok",
  "engineReady": true,
  "storage": {
    "ok": true,
    "backend": "postgres-pgvector"
  },
  "memories": 1140,
  "embeddings": 1140,
  "chunks": 1140
}
```

After a final `reembed` migration, `chunks` will normally exceed the memory count.

## Connect clients

The MCP endpoint remains:

```text
https://YOUR-APP.zeabur.app/mcp
```

Clients must send:

```text
Authorization: Bearer <AUTH_TOKEN>
```

See [TypingMind setup](./typingmind-setup.md) for plugin configuration.

## Backup and rollback

- Enable scheduled PostgreSQL backups or snapshots.
- Retain the original v2 `data` backup unchanged.
- Keep the v2 endpoint available but read-only during acceptance.
- Rollback means restoring the old client endpoint; no reverse migration is required.

## Troubleshooting

| Symptom | Resolution |
|---|---|
| Database dimension mismatch | Use the migration embedding model or migrate into a fresh database |
| `extension vector does not exist` | Deploy the PostgreSQL-with-pgvector template, not plain PostgreSQL |
| Health returns 503 | Verify private `DATABASE_URL`, credentials, and service relationship |
| Migration reports malformed SQLite | Install SQLite CLI; automatic `.recover` will preserve base rows |
| Keyword works but graph is empty | Run `backfill_graph(rebuild_all=true)` |
| 401 from MCP | Configure the same 32+ byte `AUTH_TOKEN` in client and server |
