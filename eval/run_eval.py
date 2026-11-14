"""Measure retrieval quality on a fixed question set.

    python eval/run_eval.py            # table to stdout, details in eval/results.json

For every question we know which file(s) hold the answer. A question counts
as a hit@k when one of those files is among the top k search results.
MRR (mean reciprocal rank) rewards putting the right file first.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from yakovllm.search import Index  # noqa: E402

HEBREW = re.compile(r"[א-ת]")


def rank_of(hits, expect: list[str]) -> int | None:
    for i, h in enumerate(hits, 1):
        if f'{h.chunk["repo"]}:{h.chunk["path"]}' in expect:
            return i
    return None


def evaluate(index: Index, questions: list[dict], **kw) -> dict:
    rows, t0 = [], time.perf_counter()
    for q in questions:
        hits = index.search(q["q"], k=10, **kw)
        r = rank_of(hits, q["expect"])
        rows.append({"q": q["q"], "rank": r, "lang": "he" if HEBREW.search(q["q"]) else "en",
                     "top": [f'{h.chunk["repo"]}:{h.chunk["path"]}' for h in hits[:3]]})
    ms = (time.perf_counter() - t0) * 1000 / max(1, len(questions))

    def summary(sel):
        n = len(sel) or 1
        return {"n": len(sel),
                "hit@1": sum(1 for x in sel if x["rank"] == 1) / n,
                "hit@5": sum(1 for x in sel if x["rank"] and x["rank"] <= 5) / n,
                "mrr": sum(1 / x["rank"] for x in sel if x["rank"]) / n}
    return {"all": summary(rows), "he": summary([x for x in rows if x["lang"] == "he"]),
            "en": summary([x for x in rows if x["lang"] == "en"]), "ms_per_query": ms, "rows": rows}


def main() -> None:
    index = Index.load(ROOT / "data" / "kb.json")
    questions = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    configs = {
        "BM25 (plain tokens)": dict(expand=False),
        "BM25 + Hebrew→English glossary": dict(expand=True),
    }
    results = {name: evaluate(index, questions, **kw) for name, kw in configs.items()}

    print(f"{len(questions)} questions · {index.n} chunks · {len(index.repos)} repos\n")
    print(f"| Setup | Hit@1 | Hit@5 | MRR | Hit@5 Hebrew | Hit@5 English | ms/query |")
    print(f"| --- | --- | --- | --- | --- | --- | --- |")
    for name, r in results.items():
        a, he, en = r["all"], r["he"], r["en"]
        print(f"| {name} | {a['hit@1']:.0%} | {a['hit@5']:.0%} | {a['mrr']:.2f} | {he['hit@5']:.0%} | {en['hit@5']:.0%} | {r['ms_per_query']:.1f} |")
    best = list(results.values())[-1]
    misses = [x for x in best["rows"] if not x["rank"] or x["rank"] > 5]
    if misses:
        print("\nMisses (full setup):")
        for x in misses:
            print(f"  - {x['q']}  -> {x['top']}")
    (ROOT / "eval" / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
