"""`adaptive-memory` command: serve (default), warmup, stats, export."""

from __future__ import annotations

import json
import sys

from .store import MemoryStore

USAGE = """adaptive-memory [serve|serve-http|warmup|stats|export]

  serve    run the MCP server over stdio (default)
  serve-http  remote mode: MCP over HTTP, needs ADAPTIVE_MEMORY_TOKEN (--host, --port)
  warmup   download the embedding model now (~130 MB, first time only)
  stats    show memory count and database location
  export   print all memories as JSON
"""


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "serve":
        from .server import main as serve

        serve()
    elif cmd == "serve-http":
        from .http import main as serve_http

        serve_http(sys.argv[2:])
    elif cmd == "warmup":
        store = MemoryStore()
        store.embedder.embed(["warmup"])
        store._embed_missing()
        print(f"Model ready: {store.embedder.model}")
    elif cmd == "stats":
        print(json.dumps(MemoryStore().stats(), indent=2))
    elif cmd == "export":
        print(json.dumps(MemoryStore().export(), indent=2))
    else:
        print(USAGE)
        sys.exit(0 if cmd in ("-h", "--help", "help") else 2)


if __name__ == "__main__":
    main()
