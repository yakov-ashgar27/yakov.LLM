"""Checks the answer context for a bank of everyday questions (eval/question_bank.json).

For every project and question template it measures:
  fact sheet  - the project's overview (summary, languages, lines of code, links) is in the context
  on topic    - share of context excerpts that come from the project asked about
  top on topic- the best search hit is from that project
Follow-up questions ("and how do I run it?") must stay on the project of the conversation, and
account-wide questions must get the all-projects overview.

    python eval/run_bank.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from yakovllm.search import Index  # noqa: E402


def display_name(r: dict) -> str:
    title = re.sub(r"[^\w\s.&'-]", " ", r["title"]).strip()
    return re.split(r"\s[—–:|·-]\s|:|\s{2,}", title)[0].strip() or r["name"]


def run(index: Index) -> dict:
    bank = json.loads((ROOT / "eval" / "question_bank.json").read_text(encoding="utf-8"))
    owner = (index.kb.get("owner") or "").lower()
    projects = [r for r in index.kb["repos"] if r["key"] not in (owner, f"{owner}.github.io")]
    rows = []
    for r in projects:
        name = display_name(r)
        for tpl in bank["project_questions"]:
            q = tpl.replace("{p}", name)
            hits = index.answer_context(q)
            rows.append(score(r["key"], q, hits))
        for first, second in bank["follow_ups"]:
            first = first.replace("{p}", name)
            context = index.detect(first)
            hits = index.answer_context(second, context_repos=context)
            rows.append(score(r["key"], f"{first} → {second}", hits))
    acc = []
    for q in bank["account_questions"]:
        hits = index.answer_context(q)
        acc.append({"q": q, "overview": any(h.chunk["path"] == "(all projects)" for h in hits)})
    n = len(rows)
    summary = {
        "project_questions": n,
        "fact_sheet": sum(x["fact_sheet"] for x in rows) / n,
        "on_topic": sum(x["on_topic"] for x in rows) / n,
        "top_on_topic": sum(x["top_on_topic"] for x in rows) / n,
        "account_questions": len(acc),
        "account_overview": sum(x["overview"] for x in acc) / len(acc),
    }
    return {"summary": summary, "rows": rows, "account": acc}


def score(key: str, q: str, hits) -> dict:
    searched = [h for h in hits if h.score > 0] or hits
    return {"q": q, "repo": key,
            "fact_sheet": any(h.chunk["repo"] == key and h.chunk["path"] == "(overview)" for h in hits),
            "on_topic": sum(h.chunk["repo"] == key for h in hits) / max(1, len(hits)),
            "top_on_topic": bool(searched) and searched[0].chunk["repo"] == key}


def main() -> None:
    res = run(Index.load(ROOT / "data" / "kb.json"))
    s = res["summary"]
    print(f"{s['project_questions']} project questions · {s['account_questions']} account questions\n")
    print("| Check | Result |\n| --- | --- |")
    print(f"| Project fact sheet in context | {s['fact_sheet']:.0%} |")
    print(f"| Excerpts from the project asked about | {s['on_topic']:.0%} |")
    print(f"| Best search hit from that project | {s['top_on_topic']:.0%} |")
    print(f"| Account overview for account questions | {s['account_overview']:.0%} |")
    bad = [x for x in res["rows"] if not x["fact_sheet"] or x["on_topic"] < 0.75]
    if bad:
        print("\nWeak spots:")
        for x in bad[:15]:
            print(f"  - [{x['repo']}] {x['q']}  (on topic {x['on_topic']:.0%})")


if __name__ == "__main__":
    main()
