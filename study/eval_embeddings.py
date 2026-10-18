"""Compare retrieval quality of embedding models on a small paraphrase question set.

Usage:
    python study/eval_embeddings.py                      # local models only
    OPENAI_API_KEY=sk-... python study/eval_embeddings.py   # adds OpenAI text-embedding-3-small

Metrics: top-1 accuracy and MRR@5 (mean reciprocal rank of the correct memory in the top 5).
Modes: keyword (BM25 only), semantic (vectors only), hybrid (rank fusion, what the server uses).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

from adaptive_memory.embedder import Embedder
from adaptive_memory.store import MemoryStore

DATA = json.loads((Path(__file__).with_name("eval_data.json")).read_text())
LOCAL_MODELS = [
    "BAAI/bge-small-en-v1.5",
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-base-en-v1.5",
]


class OpenAIEmbedder(Embedder):
    def __init__(self, model: str = "text-embedding-3-small") -> None:
        super().__init__(model=f"openai/{model}")
        self._name = model

    def embed(self, texts):
        req = urllib.request.Request(
            "https://api.openai.com/v1/embeddings",
            data=json.dumps({"model": self._name, "input": list(texts)}).encode(),
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            vecs = np.array([d["embedding"] for d in json.load(r)["data"]], dtype=np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def score(ranker, queries) -> tuple[float, float]:
    top1 = mrr = 0.0
    for q, expected in queries:
        keys = ranker(q)[:5]
        top1 += bool(keys) and keys[0] == expected
        mrr += 1 / (keys.index(expected) + 1) if expected in keys else 0
    n = len(queries)
    return top1 / n, mrr / n


def evaluate(embedder: Embedder) -> dict[str, tuple[float, float]]:
    store = MemoryStore(Path(tempfile.mkdtemp()) / "eval.db", embedder)
    for k, v in DATA["facts"].items():
        store.store(k, v)
    out = {}
    for label, q in (("paraphrase", DATA["queries"]), ("exact", DATA["exact_queries"])):
        out[f"{label}/keyword"] = score(lambda s: store._keyword_keys(s, 5), q)
        out[f"{label}/semantic"] = score(lambda s: sorted(sims, key=sims.get, reverse=True) if (sims := store._similarities(s, 5)) else [], q)
        out[f"{label}/hybrid"] = score(lambda s: [m["key"] for m in store.search(s, 5)[0]], q)
    store.close()
    return out


def main() -> None:
    embedders: list[Embedder] = [Embedder(model=m) for m in LOCAL_MODELS]
    if os.environ.get("OPENAI_API_KEY"):
        embedders.append(OpenAIEmbedder())
    else:
        print("(set OPENAI_API_KEY to include OpenAI text-embedding-3-small)\n", file=sys.stderr)
    print(f"{len(DATA['facts'])} memories, {len(DATA['queries'])} paraphrased + {len(DATA['exact_queries'])} exact-term queries\n")
    print(f"{'model':40} {'queries/mode':20} {'top-1':>6} {'MRR@5':>6}")
    for emb in embedders:
        for mode, (t1, mrr) in evaluate(emb).items():
            print(f"{emb.model:40} {mode:20} {t1:6.0%} {mrr:6.2f}")
        print()


if __name__ == "__main__":
    main()
