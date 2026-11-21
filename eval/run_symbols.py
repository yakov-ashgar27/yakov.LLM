"""Auto-generated questions over every function, class, route and file in the knowledge base.

For each code symbol we ask a few questions the way people do, in Hebrew and English, with the
identifier written in words ("find path step" for find_path_step) as often as by its name, and
check that the answer context holds the right file. Run:  python eval/run_symbols.py [--sample N]
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yakovllm.facts import _ident_words  # noqa: E402
from yakovllm.search import Index  # noqa: E402

TEMPLATES = [
    "מה עושה {words} ב{project}?",
    "איפה מוגדר {name} בפרויקט {project}?",
    "תסביר לי את {name} ב{project}",
    "What does {name} do in {project}?",
    "Where is {words} implemented in {project}?",
    "who calls {name} in {project}?",
]
FILE_TEMPLATES = [
    "מה התפקיד של הקובץ {file} ב{project}?",
    "What is {file} for in {project}?",
]


def project_name(ix: Index, key: str) -> str:
    r = ix.repos[key]
    return (r.get("title") or r["name"]).split(" — ")[0].split(" - ")[0]


def run(ix: Index, sample: int, seed: int = 7) -> dict:
    rnd = random.Random(seed)
    symbols = [c for c in ix.chunks if c["kind"] == "symbol" and len(c["title"].split("›")[-1].strip()) >= 5]
    files = [c for c in ix.chunks if c["kind"] == "file"]
    picks = rnd.sample(symbols, min(sample, len(symbols)))
    fpicks = rnd.sample(files, min(sample // 4, len(files)))
    total = good = 0
    misses = []
    for c in picks:
        name = c["title"].split("›")[-1].strip().split(".")[-1]
        q = rnd.choice(TEMPLATES).format(name=name, words=_ident_words(name), project=project_name(ix, c["repo"]))
        hits = ix.answer_context(q, k=8)
        ok = any(h.chunk["path"] == c["path"] for h in hits)
        total += 1
        good += ok
        if not ok:
            misses.append(q)
    for c in fpicks:
        q = rnd.choice(FILE_TEMPLATES).format(file=c["path"].split("/")[-1], project=project_name(ix, c["repo"]))
        hits = ix.answer_context(q, k=8)
        ok = any(h.chunk["path"] == c["path"] for h in hits)
        total += 1
        good += ok
        if not ok:
            misses.append(q)
    return {"questions": total, "hit": good / total if total else 1.0, "misses": misses}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=600)
    ap.add_argument("--kb", default="data/kb.json")
    a = ap.parse_args()
    res = run(Index.load(a.kb), a.sample)
    print(f"{res['questions']} auto questions · right file in the answer context: {res['hit']:.0%}")
    for q in res["misses"][:15]:
        print("  miss:", q)


if __name__ == "__main__":
    main()
