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
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import tokenizer

K1 = 1.2
B = 0.75
META_WEIGHT = 3
REPO_BOOST = 3.0       # the question names the project
CONTEXT_BOOST = 1.8    # the conversation so far was about the project
README_BOOST = 1.15
TEST_PENALTY = 0.8    # test files echo the code's words; prefer the code unless tests are asked about
TEST_WORDS = {"test", "tests", "pytest", "vitest", "בדיקה", "בדיקות", "e2e", "playwright"}
MAX_PER_FILE = 2
CARD_KINDS = {"symbol", "file"}   # fact cards about a file get their own per-file budget beside its code
FACTS_PATH = "(project facts)"
PER_PROJECT = 2       # excerpts per project when a question covers many projects
# "all the projects", "of all of them", "each project": the answer must cover every project
ALL_PROJECTS = re.compile(r"כל ה?פרויקטים|כל אחד מה?פרויקטים|בכל אחד|לכל אחד|של כולם|כולם|לכולם|בכולם|בכל ה?פרויקטים|"
                          r"\ball (?:the |my |of the |of his |his )?(?:projects|repos|repositories)\b|\b(?:every|each) (?:project|repo)\b|"
                          r"\ball of them\b|\bfor each\b|\bacross (?:all )?(?:the )?projects\b", re.I)


def wants_all(text: str) -> bool:
    return bool(ALL_PROJECTS.search(text or ""))


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
        self.aliases = (kb.get("tokenizer") or {}).get("aliases") or tokenizer.repo_aliases(kb["repos"])
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
        self.by_id = {c["id"]: c for c in self.chunks}
        self.n = len(self.chunks)
        self.avg_len = (sum(self.lengths) / self.n) if self.n else 1.0

    @classmethod
    def load(cls, path: str | Path) -> "Index":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def idf(self, term: str) -> float:
        df = len(self.postings.get(term, ()))
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 6, repo: str | None = None,
               expand: bool = True, extra_terms: list[str] | None = None,
               context_repos: list[str] | None = None) -> list[Hit]:
        terms = tokenizer.expand_query(query) if expand else tokenizer.tokenize(query)
        if extra_terms:
            for t in extra_terms:
                terms.extend(tokenizer.tokenize(t))
        q = Counter(terms)
        focus = set(self.detect(query)) if not repo else set()
        context = set(context_repos or []) if not repo and not focus else set()
        wants_tests = bool(TEST_WORDS & set(terms)) or "test_" in query.lower()
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
            elif c["repo"] in context:
                s *= CONTEXT_BOOST
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
            key = (c["repo"], c["path"], c["kind"] in CARD_KINDS)
            if per_file[key] >= MAX_PER_FILE:
                continue
            per_file[key] += 1
            out.append(Hit(c, s, sorted(set(matched[i]))))
            if len(out) >= k:
                break
        return out

    def answer_context(self, query: str, k: int = 8, repo: str | None = None,
                       extra_terms: list[str] | None = None, context_repos: list[str] | None = None) -> list[Hit]:
        """The excerpts a chat answer is written from.

        1. Work out which project(s) the question is about: the one picked in the UI, else the ones
           the question names, else the ones the conversation was about.
        2. Search, keeping only those projects (other projects only fill in if too little is found).
        3. Pin the project's fact sheet (summary, languages, lines of code, folders, links) and the
           start of its README, which answer most everyday questions: what it is, why, how to run it,
           what it's built with. With no project in play, pin the all-projects overview instead.
        """
        named = self.detect(query)
        if not repo and (wants_all(query) or len(named) > 3):
            return self.per_project_context(query, named if len(named) > 3 else self.project_keys(), extra_terms)
        targets = [repo] if repo else (named or list(context_repos or []))
        targets = targets[:3]
        if targets:
            pool = self.search(query, k=60, extra_terms=extra_terms, context_repos=targets)
            hits = [h for h in pool if h.chunk["repo"] in targets][:k]  # the fact sheet below covers thin matches
        else:
            hits = self.search(query, k=k, extra_terms=extra_terms)
        wanted: list[str] = []
        if targets:
            for t in targets[:2]:
                wanted.append(f"{t}:(overview):1-1")
                wanted.append(f"{t}:{FACTS_PATH}:1")
                readme = sorted((c for c in self.chunks if c["repo"] == t and c["path"].lower() == "readme.md"),
                                key=lambda c: c["start"])
                wanted += [c["id"] for c in readme[:2]]
        else:
            wanted += [c["id"] for c in self.chunks if c["path"] == "(all projects)"][:1]
            owner = (self.kb.get("owner") or "").lower()
            wanted += [c["id"] for c in self.chunks if c["repo"] == owner and c["path"].lower() == "readme.md"][:1]
        have = {h.chunk["id"] for h in hits}
        pinned = [Hit(self.by_id[i], 0.0, []) for i in dict.fromkeys(wanted) if i in self.by_id and i not in have]
        return pinned + hits

    def project_keys(self) -> list[str]:
        """Real projects, newest first: not the profile README, not one-file repos."""
        owner = (self.kb.get("owner") or "").lower()
        repos = [r for r in self.kb["repos"] if r["key"] != owner and (r.get("files") or 0) > 1]
        repos.sort(key=lambda r: r.get("pushed_at") or r.get("committed_at") or "", reverse=True)
        return [r["key"] for r in repos]

    def per_project_context(self, query: str, targets: list[str], extra_terms: list[str] | None = None) -> list[Hit]:
        """A question about every project ("data structures of all of them"): the best PER_PROJECT
        excerpts from EACH project, so the answer can't cover three and forget the rest."""
        out: list[Hit] = []
        for t in targets:
            hits = self.search(query, k=PER_PROJECT, repo=t, extra_terms=extra_terms)
            if not hits and f"{t}:(overview):1-1" in self.by_id:
                hits = [Hit(self.by_id[f"{t}:(overview):1-1"], 0.0, [])]
            out.extend(hits)
        return out

    def detect(self, text: str) -> list[str]:
        return tokenizer.detect_repos(text, self.aliases)

    def github_url(self, chunk: dict) -> str:
        r = self.repos.get(chunk["repo"], {})
        if not r.get("url"):
            return ""
        if chunk["path"].startswith("("):
            return r["url"]
        return f'{r["url"]}/blob/{r.get("branch") or "main"}/{chunk["path"]}#L{chunk["start"]}-L{chunk["end"]}'
