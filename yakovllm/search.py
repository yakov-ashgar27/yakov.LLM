"""BM25 search over the knowledge base, written from scratch (no libraries).

BM25 scores a chunk higher when it contains the query's rare words many times,
and normalises for chunk length. On top of plain BM25 we add three things that
matter for a code + docs corpus:

* field weighting: words in the repo name, file path and section title count
  as if they appeared META_WEIGHT times;
* repo focus: when the question names a project ("in Bomberman ..."), chunks
  from that project get a boost (or a hard filter when the UI picks a project);
* diversity: at most MAX_PER_FILE chunks from one file in the results, so the
  answer can draw on several places.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import tokenizer

K1 = 1.2
B = 0.75
META_WEIGHT = 3
REPO_BOOST = 1.6
README_BOOST = 1.15
TEST_PENALTY = 0.8    # test files echo the code's words; prefer the code unless tests are asked about
TEST_WORDS = {"test", "tests", "pytest", "vitest", "בדיקה", "בדיקות", "e2e", "playwright"}
MAX_PER_FILE = 2


@dataclass
class Hit:
    chunk: dict
    score: float
    terms: list[str]

    def to_dict(self, n: int | None = None) -> dict:
        c = self.chunk
        d = {k: c[k] for k in ("id", "repo", "path", "start", "end", "title", "kind", "text")}
        d["score"] = round(self.score, 3)
        d["terms"] = self.terms
        if n is not None:
            d["n"] = n
        return d


def is_test_path(path: str) -> bool:
    p = path.lower()
    name = p.rsplit("/", 1)[-1]
    return p.startswith(("tests/", "test/", "e2e/")) or "/tests/" in p or "/e2e/" in p \
        or name.startswith("test_") or ".test." in name or ".spec." in name


class Index:
    def __init__(self, kb: dict):
        self.kb = kb
        self.repos = {r["key"]: r for r in kb["repos"]}
        self.chunks: list[dict] = kb["chunks"]
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths: list[int] = []
        for i, c in enumerate(self.chunks):
            meta = f'{c["repo"]} {c["path"].replace("/", " ").replace(".", " ")} {c["title"]}'
            counts = Counter(tokenizer.tokenize(c["text"]))
            for t in tokenizer.tokenize(meta):
                counts[t] += META_WEIGHT
            self.lengths.append(sum(counts.values()))
            for t, tf in counts.items():
                self.postings[t].append((i, tf))
        self.n = len(self.chunks)
        self.avg_len = (sum(self.lengths) / self.n) if self.n else 1.0

    @classmethod
    def load(cls, path: str | Path) -> "Index":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def idf(self, term: str) -> float:
        df = len(self.postings.get(term, ()))
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 6, repo: str | None = None,
               expand: bool = True, extra_terms: list[str] | None = None) -> list[Hit]:
        terms = tokenizer.expand_query(query) if expand else tokenizer.tokenize(query)
        if extra_terms:
            for t in extra_terms:
                terms.extend(tokenizer.tokenize(t))
        q = Counter(terms)
        focus = set(tokenizer.detect_repos(query)) if not repo else set()
        wants_tests = bool(TEST_WORDS & set(terms))
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, list[str]] = defaultdict(list)
        for term, qtf in q.items():
            plist = self.postings.get(term)
            if not plist:
                continue
            w = self.idf(term) * (1 + 0.3 * (qtf - 1))
            for i, tf in plist:
                dl = self.lengths[i]
                scores[i] += w * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / self.avg_len))
                matched[i].append(term)
        ranked: list[tuple[float, int]] = []
        for i, s in scores.items():
            c = self.chunks[i]
            if repo and c["repo"] != repo:
                continue
            if c["repo"] in focus:
                s *= REPO_BOOST
            if c["path"].lower().endswith("readme.md"):
                s *= README_BOOST
            if not wants_tests and is_test_path(c["path"]):
                s *= TEST_PENALTY
            ranked.append((s, i))
        ranked.sort(reverse=True)
        out: list[Hit] = []
        per_file: Counter = Counter()
        for s, i in ranked:
            c = self.chunks[i]
            key = (c["repo"], c["path"])
            if per_file[key] >= MAX_PER_FILE:
                continue
            per_file[key] += 1
            out.append(Hit(c, s, sorted(set(matched[i]))))
            if len(out) >= k:
                break
        return out

    def github_url(self, chunk: dict) -> str:
        r = self.repos.get(chunk["repo"], {})
        if not r.get("url"):
            return ""
        return f'{r["url"]}/blob/{r.get("branch") or "main"}/{chunk["path"]}#L{chunk["start"]}-L{chunk["end"]}'
