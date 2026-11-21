"""Build the knowledge base (data/kb.json) from GitHub repositories.

    python -m yakovllm.ingest --github yakov-ashgar27          # every public repo of a user (only what changed)
    python -m yakovllm.ingest --github yakov-ashgar27 --force  # rebuild everything
    python -m yakovllm.ingest --repo yakov-ashgar27/Bomberman  # one or more repos
    python -m yakovllm.ingest --local ~/code/bomberman ~/code/the-map-lies

Repos are shallow-cloned into .cache/repos. Only text files that help answer
questions are read: source code, Markdown, HTML pages and config. Lock files,
build output, binaries and anything over 200 KB are skipped.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import tokenizer
from . import facts
from .chunker import chunk_file

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "repos"
DEFAULT_OUT = ROOT / "data" / "kb.json"

TEXT_EXT = {
    ".py", ".pyw", ".ts", ".tsx", ".js", ".mjs", ".jsx", ".md", ".html", ".htm",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".bat", ".sh", ".sql", ".txt", ".json",
    # other languages, so a future project in any of them is read too
    ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".swift", ".php", ".rb",
    ".vue", ".svelte", ".scss", ".ps1", ".r", ".ipynb",
}
SKIP_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__", ".cache", "coverage", ".next"}
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}
JSON_KEEP = {"package.json", "manifest.webmanifest", "tsconfig.json"}
MAX_BYTES = 200_000
KB_VERSION = 4          # bump when chunks or metadata change shape: forces a full re-index
IGNORE_FILE = ".yakovllm-ignore"  # optional, in a repo's root: glob patterns of files to skip
CODE_EXT = {".py", ".pyw", ".ts", ".tsx", ".js", ".mjs", ".jsx", ".html", ".htm", ".css", ".sql", ".sh", ".bat",
            ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".swift", ".php", ".rb",
            ".vue", ".svelte", ".scss", ".ps1", ".r"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def github_api(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "yakov.LLM"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def list_user_repos_meta(user: str) -> list[dict]:
    """Public, non-fork, non-archived repos of a GitHub user, with their last push time."""
    data = github_api(f"https://api.github.com/users/{user}/repos?per_page=100&type=owner&sort=pushed")
    return [{"full_name": d["full_name"], "pushed_at": d.get("pushed_at", ""), "description": d.get("description") or "",
             "homepage": d.get("homepage") or "", "stars": d.get("stargazers_count", 0)}
            for d in data if not d.get("fork") and not d.get("archived")]


def list_user_repos(user: str) -> list[str]:
    return [d["full_name"] for d in list_user_repos_meta(user)]


def clone(full_name: str) -> Path:
    dest = CACHE / full_name.replace("/", "__")
    if (dest / ".git").exists():
        log(f"  updating {full_name}")
        git("fetch", "--depth", "1", "origin", cwd=dest)
        git("reset", "--hard", "FETCH_HEAD", cwd=dest)
    else:
        log(f"  cloning {full_name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"https://github.com/{full_name}", str(dest)], check=True, env=env)
    return dest


def wanted(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    if name in SKIP_FILES or name.endswith(".min.js"):
        return False
    low = name.lower()
    if low == "dockerfile" or low.startswith("dockerfile."):
        return True
    ext = os.path.splitext(low)[1]
    if ext == ".json":
        return name in JSON_KEEP
    if ext == ".html" and re.fullmatch(r"google[0-9a-f]+\.html", name):
        return False  # search-console verification stub
    return ext in TEXT_EXT


def repo_info(path: Path, fallback_name: str) -> dict:
    try:
        remote = git("remote", "get-url", "origin", cwd=path)
        m = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", remote)
        owner, name = (m.group(1), m.group(2)) if m else ("", fallback_name)
        branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=path)
        commit = git("rev-parse", "--short", "HEAD", cwd=path)
        committed = git("log", "-1", "--format=%cI", cwd=path)
    except Exception:
        owner, name, branch, commit, committed = "", fallback_name, "main", "", ""
    return {"owner": owner, "name": name, "branch": branch, "commit": commit, "committed_at": committed,
            "url": f"https://github.com/{owner}/{name}" if owner else ""}


def describe(name: str, owner: str, files: dict[str, str]) -> tuple[str, str]:
    """(title, one-paragraph summary) from the repo's README."""
    readme = next((files[k] for k in files if k.lower() == "readme.md"), "")
    if name.lower() == owner.lower():
        title = "Profile README"
    elif name.lower().endswith(".github.io"):
        title = "Portfolio website"
    else:
        h1 = re.search(r"^#\s+(.+)$", readme, re.M)
        title = h1.group(1).strip() if h1 else name
    summary = ""
    intro = re.split(r"^##\s", readme, maxsplit=1, flags=re.M)[0]  # only the part before the first section
    for block in re.split(r"\n\s*\n", intro):
        b = block.strip()
        # skip badge rows ([![CI](...)](...)), images, headings, tables, lists, quotes and code
        bold_tagline = b.startswith("**")  # "**Real-time fraud detection.** A streaming pipeline..."
        if not b or (b.startswith(("#", "!", "|", "<", "```", "-", "*", ">", "[!", "[![")) and not bold_tagline) \
                or "badge" in b.lower() or "codespaces" in b.lower() or b.count("http") >= 2:
            continue
        b = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", b)              # images
        b = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", b)           # links -> their text
        b = re.sub(r"\s+", " ", re.sub(r"[*_`]", "", b)).strip()
        if len(b) > 40:
            summary = b[:400]
            break
    if not summary and name.lower().endswith(".github.io"):
        summary = "The personal portfolio site with a page per project."
    if not summary:
        summary = re.sub(r"[^\w\s&:,.'()/-]", "", title).strip()  # a descriptive title beats a random paragraph
    return title, summary


def overview_chunk(meta: dict, files: dict[str, str]) -> dict:
    """A synthetic chunk that answers "what is this project?" questions."""
    top = sorted({f.split("/")[0] + ("/" if "/" in f else "") for f in files})
    langs = ", ".join(f"{k} ({v})" for k, v in meta["languages"].items())
    lines = [
        f"# {meta['title']} ({meta['name']})",
        f"Project overview / סקירת הפרויקט {meta['name']}.",
        meta.get("description") or "",
        meta["summary"],
        f"GitHub: {meta['url']}" if meta["url"] else "",
        f"Homepage / live: {meta['homepage']}" if meta.get("homepage") else "",
        f"Files indexed: {meta['files']}. File types: {langs}.",
        (f"Lines of code / שורות קוד: {sum(meta['loc'].values()):,} non-empty lines in total ("
         + ", ".join(f"{k}: {v:,}" for k, v in meta["loc"].items()) + "). גודל הפרויקט, כמה שורות קוד יש בו."
         if meta.get("loc") else ""),
        f"Top-level folders and files: {', '.join(top[:40])}",
        f"Last commit: {meta.get('committed_at', '')[:10]} ({meta.get('commit', '')})",
    ]
    text = "\n".join(l for l in lines if l)
    return {"id": f"{meta['key']}:(overview):1-1", "repo": meta["key"], "path": "(overview)", "start": 1, "end": 1,
            "title": f"{meta['title']} › overview", "kind": "overview", "text": text}


def ignore_patterns(path: Path) -> list[str]:
    f = path / IGNORE_FILE
    if not f.exists():
        return []
    return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


LANG_NAMES = {".py": "Python", ".pyw": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
              ".mjs": "JavaScript", ".jsx": "JavaScript", ".html": "HTML", ".htm": "HTML", ".css": "CSS",
              ".scss": "CSS", ".sql": "SQL", ".sh": "Shell", ".bat": "Batch", ".ps1": "PowerShell", ".java": "Java",
              ".kt": "Kotlin", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".cs": "C#", ".go": "Go",
              ".rs": "Rust", ".swift": "Swift", ".php": "PHP", ".rb": "Ruby", ".vue": "Vue", ".svelte": "Svelte",
              ".r": "R"}


def line_counts(path: Path) -> dict:
    """Non-empty lines of code per language, for "how big is it?" questions."""
    per: dict[str, int] = {}
    for p in path.rglob("*"):
        rel = p.relative_to(path).as_posix()
        ext = p.suffix.lower()
        if not p.is_file() or ext not in CODE_EXT or any(x in SKIP_DIRS for x in rel.split("/")[:-1]):
            continue
        if p.name.endswith(".min.js") or p.stat().st_size > 2_000_000:
            continue
        try:
            n = sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
        except (UnicodeDecodeError, OSError):
            continue
        lang = LANG_NAMES.get(ext, ext.lstrip("."))
        per[lang] = per.get(lang, 0) + n
    return dict(sorted(per.items(), key=lambda kv: -kv[1]))


def ingest_repo(path: Path, fallback_name: str, extra: dict | None = None) -> tuple[dict, list[dict]]:
    info = repo_info(path, fallback_name)
    ignore = ignore_patterns(path)
    files: dict[str, str] = {}
    for p in sorted(path.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(path).as_posix()
        if not wanted(rel) or p.stat().st_size > MAX_BYTES:
            continue
        if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
            continue
        try:
            files[rel] = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    repo_key = info["name"].lower()
    chunks = []
    for rel, content in files.items():
        chunks.extend(c.to_dict() for c in chunk_file(repo_key, rel, content))
    title, summary = describe(info["name"], info["owner"], files)
    skip = lambda rel: any(x in SKIP_DIRS for x in rel.split("/")[:-1]) or any(fnmatch.fnmatch(rel, pat) for pat in ignore)
    try:
        fact_chunks, fact_summary = facts.build(repo_key, title, path, files, skip)
    except Exception as e:  # facts are an extra; never let one odd file stop the index
        log(f"  {repo_key}: facts skipped ({e})")
        fact_chunks, fact_summary = [], {}
    langs: dict[str, int] = {}
    for rel in files:
        ext = os.path.splitext(rel)[1].lstrip(".") or rel.rsplit("/", 1)[-1]
        langs[ext] = langs.get(ext, 0) + 1
    meta = {**info, "key": repo_key, "title": title, "summary": summary,
            "description": "", "homepage": "", "pushed_at": "",
            **(extra or {}),
            "files": len(files), "chunks": len(chunks) + len(fact_chunks) + 1, "loc": line_counts(path),
            "facts": fact_summary,
            "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])[:6])}
    if len(meta.get("description") or "") >= 20:  # the repo's own GitHub description says it best
        meta["summary"] = meta["description"]
    chunks.insert(0, overview_chunk(meta, files))
    chunks.extend(fact_chunks)
    log(f"  {repo_key}: {len(files)} files -> {len(chunks)} chunks")
    return meta, chunks


def build(paths: list[tuple[Path, str]], out: Path, owner: str = "") -> dict:
    repos, chunks = [], []
    for path, name in paths:
        meta, cs = ingest_repo(path, name)
        repos.append(meta)
        chunks.extend(cs)
    return write_kb(repos, chunks, out, owner)


ACCOUNT_PATH = "(all projects)"


def account_chunk(repos: list[dict], owner: str) -> dict | None:
    """One chunk about the whole account: every project, newest first, with dates, stack and size.
    Answers "which projects does Yakov have?", "what is the newest one?", "what does he use?"."""
    if not repos:
        return None
    ordered = sorted(repos, key=lambda r: r.get("pushed_at") or r.get("committed_at") or "", reverse=True)
    home = next((r["key"] for r in repos if r["key"] == (owner or "").lower()), ordered[0]["key"])
    lines = [f"# All projects of {owner} on GitHub / כל הפרויקטים של יעקב ב-GitHub",
             f"{len(repos)} projects (פרויקטים), newest first (מהחדש לישן). Portfolio, skills, technologies, experience.", ""]
    for r in ordered:
        loc = sum((r.get("loc") or {}).values())
        langs = ", ".join(list((r.get("loc") or {}).keys())[:4]) or ", ".join(list((r.get("languages") or {}).keys())[:4])
        when = (r.get("pushed_at") or r.get("committed_at") or "")[:10]
        lines.append(f"- {r['title']} ({r['key']}), last updated {when}: {(r.get('summary') or r.get('description') or '')[:220]}"
                     f" Stack: {langs}. {loc:,} lines of code." + (f" Live: {r['homepage']}" if r.get("homepage") else ""))
    return {"id": f"{home}:{ACCOUNT_PATH}:1-1", "repo": home, "path": ACCOUNT_PATH, "start": 1, "end": 1,
            "title": "All projects › overview", "kind": "overview", "text": "\n".join(lines)}


def write_kb(repos: list[dict], chunks: list[dict], out: Path, owner: str = "") -> dict:
    owner = owner or next((r["owner"] for r in repos if r.get("owner")), "")
    chunks = [c for c in chunks if c.get("path") != ACCOUNT_PATH]
    acc = account_chunk(repos, owner)
    if acc:
        chunks = [acc] + chunks
    kb = {
        "version": KB_VERSION,
        "owner": owner,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repos": repos,
        "tokenizer": {  # shared with web/engine.js
            "stopwords": sorted(tokenizer.STOPWORDS),
            "glossary": tokenizer.GLOSSARY,
            "aliases": tokenizer.repo_aliases(repos),
            "prefix1": "".join(sorted(tokenizer.HE_PREFIX_1)),
            "prefix2": sorted(tokenizer.HE_PREFIX_2),
        },
        "chunks": chunks,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(kb, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"wrote {out} · {len(repos)} repos · {len(chunks)} chunks · {out.stat().st_size / 1e6:.1f} MB")
    return kb


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build the yakov.LLM knowledge base")
    ap.add_argument("--github", metavar="USER", help="ingest every public repo of this GitHub user")
    ap.add_argument("--repo", nargs="*", default=[], metavar="OWNER/NAME", help="specific GitHub repos")
    ap.add_argument("--local", nargs="*", default=[], metavar="DIR", help="local folders (git checkouts)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--force", action="store_true", help="with --github: re-index every repo, not only changed ones")
    a = ap.parse_args(argv)

    if a.github and not a.repo and not a.local:
        from .sync import GitHubSync  # full, incremental GitHub sync
        result = GitHubSync(a.github, Path(a.out)).check(force=a.force)
        print(json.dumps(result))
        if "error" in result:
            sys.exit(1)
        return
    targets: list[tuple[Path, str]] = []
    for full in a.repo:
        targets.append((clone(full), full.split("/")[-1]))
    for d in a.local:
        p = Path(d).expanduser().resolve()
        targets.append((p, p.name))
    if not targets:
        ap.error("give --github USER, --repo OWNER/NAME or --local DIR")
    build(targets, Path(a.out), owner=a.github or "")


if __name__ == "__main__":
    main()
