import asyncio
import os
import subprocess
import sys
import textwrap

import pytest

SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def test_two_processes_write_same_db(tmp_path):
    """Two agents (two server processes) share one database without errors."""
    script = textwrap.dedent(
        """
        import sys
        from adaptive_memory.embedder import Embedder
        from adaptive_memory.store import MemoryStore

        class Off(Embedder):
            def embed(self, texts):
                raise RuntimeError("off")

        s = MemoryStore(sys.argv[1], Off(model="off"))
        for i in range(40):
            s.store(f"{sys.argv[2]}/{i}", f"fact number {i} from {sys.argv[2]}")
        """
    )
    env = {**os.environ, "PYTHONPATH": SRC}
    procs = [
        subprocess.Popen([sys.executable, "-c", script, str(tmp_path / "m.db"), name], env=env)
        for name in ("a", "b")
    ]
    assert [p.wait(timeout=60) for p in procs] == [0, 0]

    from adaptive_memory.embedder import Embedder
    from adaptive_memory.store import MemoryStore

    s = MemoryStore(tmp_path / "m.db", Embedder(model="off"))
    assert s.stats()["memories"] == 80
    s.close()


@pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="downloads the real model (set RUN_SLOW=1)")
def test_real_model_over_mcp_stdio(tmp_path):
    """Full path: MCP client -> stdio server -> real local model -> semantic hit with no shared words."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "adaptive_memory"],
            env={**os.environ, "ADAPTIVE_MEMORY_DB": str(tmp_path / "m.db"), "PYTHONPATH": SRC},
        )
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert names == {
                "store_memory", "get_memory", "search", "list_memories",
                "delete_memory", "get_stats", "export_memories",
            }
            await s.call_tool("store_memory", {"key": "p/db", "content": "We chose PostgreSQL because we need vector search"})
            await s.call_tool("store_memory", {"key": "p/ui", "content": "Primary button colour is teal"})
            hit = (await s.call_tool("search", {"query": "which database did we pick?", "limit": 1})).content[0].text
            assert hit.startswith("p/db")
            await s.call_tool("delete_memory", {"key": "p/db"})
            gone = (await s.call_tool("get_memory", {"key": "p/db"})).content[0].text
            assert "No memory" in gone

    asyncio.run(run())
