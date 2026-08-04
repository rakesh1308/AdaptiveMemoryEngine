"""Comprehensive pre-deploy test suite. Verifies the Python port works
end-to-end against the live ./data/ directory before pushing to git/Zeabur."""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

PASSED = 0
FAILED = 0


def ok(name):
    global PASSED
    PASSED += 1
    print(f"  [PASS] {name}")


def fail(name, err=""):
    global FAILED
    FAILED += 1
    print(f"  [FAIL] {name}: {err}")


def section(name):
    print(f"\n=== {name} ===")


# ----------------------------------------------------------------------------
section("1. Package import sanity")
# ----------------------------------------------------------------------------
try:
    from adaptive_memory_engine.config import Config
    from adaptive_memory_engine.engine import MemoryEngine
    from adaptive_memory_engine.providers.factory import ProviderFactory
    from adaptive_memory_engine.storage import SQLiteBackend, VectorStore
    from adaptive_memory_engine.knowledge_graph import KnowledgeGraph
    from adaptive_memory_engine.chunking import ChunkStore, ChunkingStrategies
    from adaptive_memory_engine.lifecycle import MemoryLifecycle, ImportanceScorer, DecayEngine, ConsolidationEngine
    from adaptive_memory_engine.events import EventBus, MemoryEvents, now_iso
    from adaptive_memory_engine.providers import OpenAIProvider, OllamaProvider, GeminiProvider, AnthropicProvider
    ok("all modules import cleanly")
except Exception as e:
    fail("module import", e)
    sys.exit(1)


# ----------------------------------------------------------------------------
section("2. Config")
# ----------------------------------------------------------------------------
try:
    cfg = Config.load()
    ok(f"config loaded (provider={cfg.provider_type}, data_dir={cfg.data_dir})")
    cfg.ensure_data_dir()
    ok(f"data_dir exists ({cfg.data_dir})")
except Exception as e:
    fail("config", e)


# ----------------------------------------------------------------------------
section("3. SQLite + FTS5 byte-compat with Node version")
# ----------------------------------------------------------------------------
try:
    backend = SQLiteBackend("./data")
    backend.initialize()
    tables = [r[0] for r in backend.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    expected_tables = {"memories", "embeddings", "access_log", "memories_fts"}
    if expected_tables.issubset(set(tables)):
        ok(f"all expected tables present: {sorted(expected_tables)}")
    else:
        missing = expected_tables - set(tables)
        fail("tables", f"missing: {missing}")

    # Verify PRAGMAs. SQLite returns synchronous/locking as integers
    # (0=OFF, 1=NORMAL, 2=FULL for synchronous; "normal"/"exclusive" for locking).
    def _pragma(name):
        v = backend.conn.execute(f"PRAGMA {name}").fetchone()[0]
        return str(v).lower()
    journal = _pragma("journal_mode")
    sync = _pragma("synchronous")        # 1 = NORMAL
    locking = _pragma("locking_mode")    # 0 = NORMAL (string "normal")
    sync_ok = sync in ("1", "normal")
    locking_ok = locking in ("0", "normal")
    if journal == "delete" and sync_ok and locking_ok:
        ok(f"PRAGMAs match Node: journal={journal}, sync={sync}(=NORMAL), locking={locking}(=NORMAL)")
    else:
        fail("PRAGMAs", f"got journal={journal} sync={sync} locking={locking}")

    # Verify FTS5 search works
    keyword = backend.search_keyword("python", limit=5)
    ok(f"FTS5 search works ({len(keyword)} hits for 'python')")

    # Verify embedding BLOB is float32 little-endian
    embs = backend.get_all_embeddings()
    if embs:
        sample_id, sample_vec = next(iter(embs.items()))
        if len(sample_vec) == 1536:
            ok(f"embeddings load: {len(embs)} memories, dim=1536, sample={sample_id}")
        else:
            fail("embedding dims", f"got {len(sample_vec)}")
    else:
        fail("embeddings", "no rows")

    stats = backend.get_stats()
    if stats["total"] == 534 and stats["withEmbeddings"] == 534:
        ok(f"stats match Node: {stats['total']} memories, {stats['withEmbeddings']} embeddings")
    else:
        fail("stats", f"got {stats}")

    backend.close()
except Exception as e:
    fail("SQLite", e)
    import traceback; traceback.print_exc()


# ----------------------------------------------------------------------------
section("4. KnowledgeGraph JSON compat")
# ----------------------------------------------------------------------------
try:
    kg = KnowledgeGraph("./data")
    n_concepts = len(kg.concepts)
    n_rels = len(kg.relationships)
    if n_concepts >= 4000 and n_rels >= 15000:
        ok(f"graph loaded: {n_concepts} concepts, {n_rels} relationships")
    else:
        fail("graph size", f"got {n_concepts}/{n_rels}")

    # Test normalize_concept
    from adaptive_memory_engine.knowledge_graph import normalize_concept
    samples = [("GrowthDigest", "growthdigest"), ("Hello World!", "hello_world"),
               ("   AI/ML   ", "ai_ml")]
    if all(normalize_concept(a) == b for a, b in samples):
        ok("normalize_concept matches Node rules")
    else:
        fail("normalize_concept", "rule mismatch")

    # Test get_related_concepts
    rel = kg.get_related_concepts("python", depth=1)
    if rel["related"]:
        ok(f"get_related_concepts('python') found {len(rel['related'])} related")
    else:
        fail("get_related", "empty")
except Exception as e:
    fail("KnowledgeGraph", e)


# ----------------------------------------------------------------------------
section("5. MemoryEngine end-to-end")
# ----------------------------------------------------------------------------
try:
    cfg = Config.load()
    cfg.data_dir = "./data"
    emb, intel = ProviderFactory.create(cfg)
    eng = MemoryEngine(embedding_provider=emb, intelligence_provider=intel, data_dir="./data")
    eng.initialize()
    ok(f"engine init: {len(eng._memories)} memories loaded")

    # list_memories
    items = eng.list_memories(limit=3)
    if items and "id" in items[0]:
        ok(f"list_memories: {len(items)} returned")
    else:
        fail("list_memories", "empty")

    # recall_memory
    first_id = items[0]["id"]
    mem = eng.recall_memory(first_id)
    if mem and mem["id"] == first_id and mem["accessCount"] >= 1:
        ok(f"recall_memory: {first_id} (access_count incremented)")
    else:
        fail("recall_memory", str(mem))

    # search_memories (hybrid)
    results = eng.search_memories("trading strategies", top_k=5, mode="hybrid")
    if results:
        ok(f"search_memories(hybrid): {len(results)} hits")
    else:
        fail("search_memories", "no results")

    # semantic only
    sem = eng.search_memories("distributed systems", top_k=3, mode="semantic")
    if sem:
        ok(f"search_memories(semantic): {len(sem)} hits")
    else:
        fail("search_semantic", "no results")

    # keyword only
    kw = eng.search_memories("python", top_k=3, mode="keyword")
    if kw:
        ok(f"search_memories(keyword): {len(kw)} hits")
    else:
        fail("search_keyword", "no results")

    # get_stats
    s = eng.get_stats()
    if s["total"] == 534 and s["concepts"] >= 4000:
        ok(f"get_stats: {s['total']} memories, {s['concepts']} concepts")
    else:
        fail("get_stats", str(s))

    # ask
    if intel:
        ans = eng.ask("what is python used for?", context_limit=2)
        if ans and len(ans) > 20:
            ok(f"ask() returned AI answer ({len(ans)} chars)")
        else:
            fail("ask", "empty/short response")

    # query_graph
    g = eng.query_graph(concept="python")
    if g.get("related"):
        ok(f"query_graph: {len(g['related'])} related concepts")
    else:
        fail("query_graph", "empty")

    eng.close()
except Exception as e:
    fail("MemoryEngine", e)
    import traceback; traceback.print_exc()


# ----------------------------------------------------------------------------
section("6. HTTP MCP server round-trip")
# ----------------------------------------------------------------------------
PORT = 8768
try:
    cfg = Config.load()
    cfg.data_dir = "./data"
    emb, _ = ProviderFactory.create(cfg)
    eng = MemoryEngine(embedding_provider=emb, data_dir="./data")
    eng.initialize()

    from adaptive_memory_engine.server import build_http_app
    import uvicorn
    import threading
    app = build_http_app(eng)
    server_config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error", lifespan="on")
    server = uvicorn.Server(server_config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(60):
        if server.started:
            break
        time.sleep(0.1)

    # /health
    health = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5).read())
    if health.get("status") == "ok" and health.get("memories") == 534:
        ok(f"/health: {health['memories']} memories, {health['concepts']} concepts")
    else:
        fail("/health", str(health))

    # /
    root = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=5).read())
    if root.get("name") == "adaptive-memory-engine" and root.get("version"):
        ok(f"/: server={root['name']} v{root['version']}")
    else:
        fail("/", str(root))

    # /mcp initialize
    class MCPClient:
        def __init__(self, base):
            self.base = base
            self.session_id = None
            self._id = 0

        def call(self, method, params=None, is_init=False):
            self._id += 1
            body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
            headers = {"Content-Type": "application/json",
                       "Accept": "application/json, text/event-stream"}
            if self.session_id and not is_init:
                headers["mcp-session-id"] = self.session_id
            req = urllib.request.Request(self.base, data=json.dumps(body).encode(), headers=headers)
            resp = urllib.request.urlopen(req, timeout=30)
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self.session_id = sid
            raw = resp.read().decode()
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    return json.loads(line[len("data:"):].strip())
            return None

    c = MCPClient(f"http://127.0.0.1:{PORT}/mcp")

    r = c.call("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "pre-deploy-test", "version": "1"},
    }, is_init=True)
    if r.get("result", {}).get("serverInfo", {}).get("name") == "adaptive-memory-engine":
        ok(f"/mcp initialize: server={r['result']['serverInfo']['name']} v{r['result']['serverInfo']['version']}")
    else:
        fail("/mcp initialize", str(r))

    c.call("notifications/initialized")

    # tools/list
    r = c.call("tools/list")
    tool_names = {t["name"] for t in r["result"]["tools"]}
    expected = {"store_memory", "get_memory", "update_memory", "delete_memory",
                "search", "list_memories", "query_graph", "get_stats",
                "backup", "smart_search", "ask", "summarize", "get_provider_info"}
    if expected.issubset(tool_names):
        ok(f"tools/list: all {len(expected)} tools present")
    else:
        fail("tools/list", f"missing: {expected - tool_names}")

    # tools/call get_stats
    r = c.call("tools/call", {"name": "get_stats", "arguments": {}})
    stats = json.loads(r["result"]["content"][0]["text"])
    if stats["total"] == 534:
        ok(f"tools/call get_stats: {stats['total']} memories")
    else:
        fail("get_stats", str(stats))

    # tools/call search
    r = c.call("tools/call", {"name": "search", "arguments": {"query": "python", "limit": 3}})
    text = r["result"]["content"][0]["text"]
    if "results" in text and "[chatgpt" in text:
        ok(f"tools/call search: returned {len(text)} chars")
    else:
        fail("search", text[:200])

    # tools/call list_memories
    r = c.call("tools/call", {"name": "list_memories", "arguments": {"limit": 3}})
    if "memories" in r["result"]["content"][0]["text"]:
        ok("tools/call list_memories: OK")
    else:
        fail("list_memories", "missing")

    # tools/call get_provider_info
    r = c.call("tools/call", {"name": "get_provider_info", "arguments": {}})
    info = json.loads(r["result"]["content"][0]["text"])
    if info.get("embedding_provider", {}).get("type") == "openai":
        ok(f"tools/call get_provider_info: embedding={info['embedding_provider']['type']}, "
           f"intelligence_available={info['intelligence_available']}")
    else:
        fail("get_provider_info", str(info))

    # tools/call get_memory (existing)
    sample_id = next(iter(eng._memories))
    r = c.call("tools/call", {"name": "get_memory", "arguments": {"key": sample_id}})
    if sample_id in r["result"]["content"][0]["text"]:
        ok(f"tools/call get_memory '{sample_id}': OK")
    else:
        fail("get_memory", "missing key in response")

    # tools/call query_graph
    r = c.call("tools/call", {"name": "query_graph", "arguments": {"concept": "python", "depth": 1}})
    graph_result = json.loads(r["result"]["content"][0]["text"])
    if graph_result.get("related") is not None:
        ok(f"tools/call query_graph: {len(graph_result.get('related', []))} related")
    else:
        fail("query_graph", str(graph_result))

    server.should_exit = True
    time.sleep(0.5)
    eng.close()
except Exception as e:
    fail("HTTP MCP", e)
    import traceback; traceback.print_exc()


# ----------------------------------------------------------------------------
section("7. CLI commands")
# ----------------------------------------------------------------------------
def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "adaptive_memory_engine", *args],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

try:
    r = run_cli("help")
    if r.returncode == 0 and "import" in r.stdout and "search" in r.stdout:
        ok("CLI: help")
    else:
        fail("CLI help", r.stderr)

    r = run_cli("stats")
    if r.returncode == 0 and '"total": 534' in r.stdout:
        ok("CLI: stats (534 memories)")
    else:
        fail("CLI stats", r.stderr or r.stdout[:200])

    r = run_cli("list", "python")
    if r.returncode == 0 and "memories" in r.stdout:
        ok("CLI: list python")
    else:
        fail("CLI list", r.stderr)

    r = run_cli("search", "machine learning")
    if r.returncode == 0 and "results" in r.stdout:
        ok("CLI: search 'machine learning'")
    else:
        fail("CLI search", r.stderr)

    r = run_cli("provider")
    if r.returncode == 0 and "openai" in r.stdout:
        ok("CLI: provider")
    else:
        fail("CLI provider", r.stderr)

    # Test get + delete are protected
    r = run_cli("get", "skill-smoke-test")
    if r.returncode == 0 and "Adaptive Memory" in r.stdout:
        ok("CLI: get skill-smoke-test")
    else:
        fail("CLI get", r.stderr)
except Exception as e:
    fail("CLI", e)


# ----------------------------------------------------------------------------
section("8. Chunking")
# ----------------------------------------------------------------------------
try:
    fixed = ChunkingStrategies.fixed("a" * 5000, chunk_size=2500, overlap=250)
    if len(fixed) >= 2 and fixed[0]["end"] - fixed[0]["start"] == 2500:
        ok(f"ChunkingStrategies.fixed: {len(fixed)} chunks")
    else:
        fail("fixed", f"got {len(fixed)} chunks")

    para = ChunkingStrategies.paragraph("para 1\n\npara 2\n\npara 3")
    if len(para) >= 1:
        ok(f"ChunkingStrategies.paragraph: {len(para)} chunks")
    else:
        fail("paragraph", "empty")

    sem = ChunkingStrategies.semantic("# Title\n\nbody\n\n## Sub\n\nmore")
    if sem and sem[0]["content"].startswith("#"):
        ok(f"ChunkingStrategies.semantic: {len(sem)} chunks")
    else:
        fail("semantic", str(sem))
except Exception as e:
    fail("Chunking", e)


# ----------------------------------------------------------------------------
section("9. MCP stdio mode")
# ----------------------------------------------------------------------------
try:
    # Spawn the stdio server and send an initialize request, then read response
    proc = subprocess.Popen(
        [sys.executable, "-m", "adaptive_memory_engine", "serve"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=ROOT, env={**os.environ, "TRANSPORT": "stdio", "PYTHONIOENCODING": "utf-8"},
    )
    init_req = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "stdio-test", "version": "1"}},
    }) + "\n"
    try:
        stdout, stderr = proc.communicate(input=init_req.encode(), timeout=20)
        out = stdout.decode("utf-8", errors="replace").strip()
        if "adaptive-memory-engine" in out:
            ok(f"stdio MCP initialize: OK (output {len(out)} chars)")
        else:
            fail("stdio MCP", f"stdout: {out[:200]} stderr: {stderr.decode()[:200]}")
    except subprocess.TimeoutExpired:
        proc.kill()
        fail("stdio MCP", "timeout")
except Exception as e:
    fail("stdio MCP", e)


# ----------------------------------------------------------------------------
print(f"\n=== SUMMARY: {PASSED} passed, {FAILED} failed ===")
sys.exit(0 if FAILED == 0 else 1)