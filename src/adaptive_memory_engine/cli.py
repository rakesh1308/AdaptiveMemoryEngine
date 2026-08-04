"""CLI for AdaptiveMemoryEngine. Mirrors cli.js 1:1."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable

from .config import Config
from .engine import MemoryEngine
from .providers.factory import ProviderFactory

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".md", ".txt", ".pdf", ".js", ".ts", ".jsx", ".tsx", ".py", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".r", ".m", ".mm",
    ".sql", ".sh", ".bash", ".zsh", ".ps1", ".yaml", ".yml", ".json", ".xml", ".html", ".htm",
    ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".astro", ".mdx", ".rst", ".adoc",
    ".tex", ".csv", ".tsv", ".log", ".ini", ".conf", ".cfg", ".properties", ".env",
}

SPECIAL_FILENAMES = {
    "Dockerfile", "Makefile", "Gemfile", "Rakefile", "Jenkinsfile",
}


def _slugify(filename: str) -> str:
    """Mirror Node `makeKey`: take basename, strip ext, lowercase, alphanum→_, trim _."""
    base = Path(filename).stem
    s = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    return s or "memory"


def _extract_text(path: Path) -> str:
    """Read file. PDFs use pypdf."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                pages.append("")
        return f"PDF: {path.name}\n\n" + "\n\n".join(pages)
    return path.read_text(encoding="utf-8", errors="replace")


def _walk_files(target: Path, recursive: bool) -> Iterable[Path]:
    if target.is_file():
        yield target
        return
    if recursive:
        for p in target.rglob("*"):
            if p.is_file() and _is_supported(p):
                yield p
    else:
        for p in target.iterdir():
            if p.is_file() and _is_supported(p):
                yield p


def _is_supported(path: Path) -> bool:
    if path.name in SPECIAL_FILENAMES:
        return True
    if path.name.startswith("."):
        return True  # hidden config files
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _build_engine() -> MemoryEngine:
    cfg = Config.load()
    emb, intel = ProviderFactory.create(cfg)
    eng = MemoryEngine(
        embedding_provider=emb,
        intelligence_provider=intel,
        data_dir=cfg.data_dir,
    )
    eng.initialize()
    return eng


# ---- commands ----

def cmd_import(args: list[str]) -> int:
    if not args:
        print("Usage: import <path> [-r|--recursive] [-t tag1,tag2]", file=sys.stderr)
        return 1
    target = Path(args[0])
    if not target.exists():
        print(f"Path not found: {target}", file=sys.stderr)
        return 1
    recursive = "-r" in args or "--recursive" in args
    tags: list[str] = []
    if "-t" in args:
        i = args.index("-t")
        if i + 1 < len(args):
            tags = [t.strip() for t in args[i + 1].split(",") if t.strip()]
    elif "--tag" in args:
        i = args.index("--tag")
        if i + 1 < len(args):
            tags = [t.strip() for t in args[i + 1].split(",") if t.strip()]

    eng = _build_engine()
    try:
        count = 0
        for f in _walk_files(target, recursive):
            try:
                content = _extract_text(f)
                key = _slugify(f.name)
                eng.store_memory(key, content, tags=tags, auto_tag=False, source="import")
                print(f"  imported {key}  ({len(content)} chars)")
                count += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ! {f.name}: {e}", file=sys.stderr)
        print(f"\nImported {count} file(s).")
    finally:
        eng.close()
    return 0


def cmd_list(args: list[str]) -> int:
    eng = _build_engine()
    try:
        flt = args[0] if args else None
        items = eng.list_memories(filter_text=flt, limit=200)
        print(f"=== {len(items)} memories ===")
        for m in items:
            snippet = (m.get("content") or "").replace("\n", " ")[:80]
            tags = m.get("tags") or []
            print(f"  [{m['id']}] imp={m.get('importance')} tags={','.join(tags)}")
            print(f"      {snippet}...")
    finally:
        eng.close()
    return 0


def cmd_search(args: list[str]) -> int:
    if not args:
        print("Usage: search <query>", file=sys.stderr)
        return 1
    eng = _build_engine()
    try:
        results = eng.search_memories(" ".join(args), top_k=20, mode="hybrid")
        print(f"=== {len(results)} results ===")
        for r in results:
            m = r["memory"]
            snippet = (m.get("content") or "").replace("\n", " ")[:200]
            print(f"  [{m['id']}] score={r['score']:.3f}")
            print(f"      {snippet}")
    finally:
        eng.close()
    return 0


def cmd_get(args: list[str]) -> int:
    if not args:
        print("Usage: get <id>", file=sys.stderr)
        return 1
    eng = _build_engine()
    try:
        m = eng.recall_memory(args[0])
        if not m:
            print(f"Not found: {args[0]}", file=sys.stderr)
            return 1
        print(json.dumps(m, indent=2, ensure_ascii=False))
    finally:
        eng.close()
    return 0


def cmd_delete(args: list[str]) -> int:
    if not args:
        print("Usage: delete <id>", file=sys.stderr)
        return 1
    eng = _build_engine()
    try:
        ok = eng.delete_memory(args[0])
        print("Deleted." if ok else "Not found.")
    finally:
        eng.close()
    return 0


def cmd_stats(_: list[str]) -> int:
    eng = _build_engine()
    try:
        s = eng.get_stats()
        print(json.dumps(s, indent=2, ensure_ascii=False))
    finally:
        eng.close()
    return 0


def cmd_export(args: list[str]) -> int:
    out = Path(args[0]) if args else Path(f"export-{int(time.time())}.json")
    eng = _build_engine()
    try:
        payload = eng.export()
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {out}")
    finally:
        eng.close()
    return 0


def cmd_import_backup(args: list[str]) -> int:
    if not args:
        print("Usage: import-backup <file.jsonl>", file=sys.stderr)
        return 1
    path = Path(args[0])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    eng = _build_engine()
    try:
        existing = {m["id"] for m in eng.list_memories(limit=100_000)}
        count = 0
        skipped = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mid = rec.get("id")
                if not mid:
                    continue
                if mid in existing:
                    skipped += 1
                    continue
                eng.store_memory(
                    mid,
                    rec.get("content", ""),
                    tags=rec.get("tags") or [],
                    auto_tag=False,
                    source="import",
                )
                count += 1
                time.sleep(0.02)
        print(f"Imported {count}, skipped {skipped}")
    finally:
        eng.close()
    return 0


def cmd_snapshot(_: list[str]) -> int:
    eng = _build_engine()
    try:
        info = eng.create_snapshot()
        print(json.dumps(info, indent=2))
    finally:
        eng.close()
    return 0


def cmd_graph(args: list[str]) -> int:
    if not args:
        print("Usage: graph <concept>", file=sys.stderr)
        return 1
    eng = _build_engine()
    try:
        result = eng.knowledge_graph.get_related_concepts(args[0], depth=2)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        eng.close()
    return 0


def cmd_ask(args: list[str]) -> int:
    if not args:
        print("Usage: ask <question>", file=sys.stderr)
        return 1
    eng = _build_engine()
    try:
        print(eng.ask(" ".join(args), context_limit=3))
    finally:
        eng.close()
    return 0


def cmd_provider(_: list[str]) -> int:
    cfg = Config.load()
    emb, intel = ProviderFactory.create(cfg)
    out = {"embedding": emb.get_config(), "intelligence": intel.get_config() if intel else None}
    print(json.dumps(out, indent=2))
    return 0


def cmd_serve(_: list[str]) -> int:
    from .server import serve
    serve()
    return 0


def cmd_help(_: list[str]) -> int:
    print("""AdaptiveMemoryEngine CLI

Commands:
  import <path> [-r] [-t tag1,tag2]    Import files (pdf/md/code/etc.)
  list [filter]                        List memories
  search <query>                       Hybrid search
  get <id>                             Show one memory
  delete <id>                          Delete a memory
  stats                                Engine statistics
  export [file]                        Export to JSON
  import-backup <file.jsonl>           Resumable import (skip existing)
  snapshot                             Create snapshot under data/snapshots
  graph <concept>                      Query knowledge graph
  ask <question>                       Ask AI over your memories
  provider                             Show provider config
  serve                                Start the MCP server (stdio or http)
  help                                 Show this help
""")
    return 0


_COMMANDS = {
    "import": cmd_import,
    "list": cmd_list,
    "search": cmd_search,
    "get": cmd_get,
    "delete": cmd_delete,
    "stats": cmd_stats,
    "export": cmd_export,
    "import-backup": cmd_import_backup,
    "snapshot": cmd_snapshot,
    "graph": cmd_graph,
    "ask": cmd_ask,
    "provider": cmd_provider,
    "serve": cmd_serve,
    "help": cmd_help,
}


def main(argv: list[str] | None = None) -> int:
    # Force UTF-8 on stdout/stderr so Unicode-rich memory content prints cleanly on Windows.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return cmd_help([])
    cmd, rest = args[0], args[1:]
    fn = _COMMANDS.get(cmd)
    if fn is None:
        print(f"Unknown command: {cmd}\n", file=sys.stderr)
        cmd_help([])
        return 1
    try:
        return fn(rest)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())