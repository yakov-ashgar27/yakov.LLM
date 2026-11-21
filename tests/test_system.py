"""Whole-system tests: GitHub sync, the HTTP API with a fake Claude, JS/Python parity, retrieval quality."""
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from yakovllm import ingest  # noqa: E402
from yakovllm.search import Index  # noqa: E402
from yakovllm.sync import GitHubSync  # noqa: E402


# ---------------------------------------------------------------- GitHub sync
def _git_repo(path: Path, files: dict[str, str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    if not (path / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
        subprocess.run(["git", "remote", "add", "origin", f"https://github.com/u/{path.name}"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "c"], cwd=path, check=True, env=env)


def test_sync_adds_updates_and_removes_repos(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _git_repo(src / "alpha", {"README.md": "# Alpha\n\nAlpha is a tool that counts penguins on ice floes all day long.\n",
                              "alpha.py": "def count_penguins():\n    return 42\n" * 5})
    listing = [{"full_name": "u/alpha", "pushed_at": "2026-01-01T00:00:00Z", "description": "", "homepage": "", "stars": 0}]
    monkeypatch.setattr(ingest, "list_user_repos_meta", lambda user: list(listing))
    monkeypatch.setattr(ingest, "clone", lambda full: src / full.split("/")[1])
    kb_path = tmp_path / "kb.json"
    swapped = []
    s = GitHubSync("u", kb_path, on_update=swapped.append)

    assert s.check() == {"added": ["alpha"], "updated": [], "removed": []}
    assert s.check() == {"added": [], "updated": [], "removed": []}          # nothing changed: no work

    _git_repo(src / "beta", {"README.md": "# Beta\n\nBeta is a brand new project about zebras crossing the savanna.\n"})
    listing.append({"full_name": "u/beta", "pushed_at": "2026-02-01T00:00:00Z", "description": "", "homepage": "", "stars": 0})
    assert s.check()["added"] == ["beta"]                                    # new project appears

    _git_repo(src / "alpha", {"alpha.py": "def count_walruses():\n    return 7\n" * 5})
    listing[0]["pushed_at"] = "2026-03-01T00:00:00Z"
    assert s.check()["updated"] == ["alpha"]                                 # push -> re-index that repo
    ix = Index(json.loads(kb_path.read_text()))
    assert ix.search("walruses")[0].chunk["repo"] == "alpha"
    assert not any("count_penguins" in c["text"] for c in ix.chunks)          # old code is gone

    listing.pop(1)
    assert s.check()["removed"] == ["beta"]                                  # deleted on GitHub -> dropped
    assert [r["key"] for r in json.loads(kb_path.read_text())["repos"]] == ["alpha"]
    assert len(swapped) == 4                                                 # live index swapped each time


def test_sync_survives_github_errors(tmp_path, monkeypatch):
    def boom(user):
        raise OSError("network down")
    monkeypatch.setattr(ingest, "list_user_repos_meta", boom)
    s = GitHubSync("u", tmp_path / "kb.json")
    assert "error" in s.check()
    assert "network down" in s.status["last_error"]


# ---------------------------------------------------------------- HTTP API
class FakeClaude(BaseHTTPRequestHandler):
    """Speaks the Messages API: JSON for the rewrite call, SSE for the answer."""
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeClaude.seen.append(body)
        if not body.get("stream"):
            out = json.dumps({"content": [{"type": "text", "text": '["find_path_step", "bfs", "enemy"]'}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        events = [{"type": "message_start"},
                  {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "The enemy uses BFS "}},
                  {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "[1]."}},
                  {"type": "message_stop"}]
        for e in events:
            self.wfile.write(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode())
            self.wfile.flush()


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _sse(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    events = []
    with urllib.request.urlopen(req, timeout=10) as r:
        for block in r.read().decode().split("\n\n"):
            if block.strip():
                lines = dict(l.split(": ", 1) for l in block.split("\n"))
                events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture(scope="module")
def app():
    claude, claude_url = _serve(FakeClaude)
    os.environ.update(ANTHROPIC_API_KEY="test", ANTHROPIC_BASE_URL=claude_url, WEBHOOK_SECRET="s3cret", RATE_LIMIT="1000")
    import importlib
    from yakovllm import llm, server
    importlib.reload(llm)
    importlib.reload(server)
    srv, url = _serve(server.Handler)
    yield server, url
    srv.shutdown()
    claude.shutdown()
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "WEBHOOK_SECRET", "RATE_LIMIT"):
        os.environ.pop(k, None)


def test_health_and_ui(app):
    _, url = app
    h = json.load(urllib.request.urlopen(url + "/api/health"))
    assert h["name"] == "yakov.LLM" and h["mode"] == "llm" and h["provider"] == "Claude" and h["chunks"] > 100
    html = urllib.request.urlopen(url + "/").read().decode()
    assert "yakov" in html and "app.js" in html


def test_chat_streams_sources_then_answer(app):
    _, url = app
    FakeClaude.seen.clear()
    events = _sse(url + "/api/chat", {"messages": [{"role": "user", "content": "How does the Bomberman enemy chase the player?"}]})
    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and "delta" in kinds
    meta = events[0][1]
    assert meta["keywords"] == ["find_path_step", "bfs", "enemy"]
    assert any(s["path"] == "bomberman/ai.py" for s in meta["sources"])
    assert all(s["url"].startswith("https://github.com/") for s in meta["sources"])
    answer = "".join(d["text"] for e, d in events if e == "delta")
    assert answer == "The enemy uses BFS [1]."
    stream_call = FakeClaude.seen[-1]
    assert stream_call["stream"] and "<source n=\"1\"" in stream_call["messages"][-1]["content"]
    assert "yakov.LLM" in stream_call["system"]


def test_webhook_needs_a_valid_signature(app):
    _, url = app
    body = b'{"ref":"refs/heads/main"}'
    bad = urllib.request.Request(url + "/api/webhook/github", data=body, headers={"X-Hub-Signature-256": "sha256=00", "X-GitHub-Event": "push"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(bad)
    assert e.value.code == 401
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    ok = urllib.request.Request(url + "/api/webhook/github", data=body, headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "push"})
    assert urllib.request.urlopen(ok).status in (200, 202)


def test_rate_limit(app):
    server, url = app
    old = server.LIMITER
    server.LIMITER = server.RateLimiter(1)
    try:
        _sse(url + "/api/chat", {"messages": [{"role": "user", "content": "hi bomberman"}]})
        with pytest.raises(urllib.error.HTTPError) as e:
            _sse(url + "/api/chat", {"messages": [{"role": "user", "content": "again"}]})
        assert e.value.code == 429
    finally:
        server.LIMITER = old


def test_offline_mode_answers_with_excerpts():
    from yakovllm import llm
    hits = [{"n": 1, "repo": "r", "path": "a.py", "start": 1, "end": 3, "kind": "code", "text": "def f():\n    pass"}]
    text = "".join(llm.offline_answer("how?", hits))
    assert "a.py" in text and "```py" in text and "[1]" in text


# ---------------------------------------------------------------- parity + quality
@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_browser_engine_matches_python():
    script = f"""
      const {{Index}} = require({json.dumps(str(ROOT / 'web' / 'engine.js'))});
      const fs = require('fs');
      const kb = JSON.parse(fs.readFileSync({json.dumps(str(ROOT / 'data' / 'kb.json'))}, 'utf8'));
      const qs = JSON.parse(fs.readFileSync({json.dumps(str(ROOT / 'eval' / 'questions.json'))}, 'utf8'));
      const ix = new Index(kb);
      console.log(JSON.stringify(qs.map(q => ix.search(q.q, {{k: 8}}).map(h => [h.chunk.id, h.score]))));
    """
    js = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    ix = Index.load(ROOT / "data" / "kb.json")
    qs = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    for q, j in zip(qs, js):
        py = [[h.chunk["id"], h.score] for h in ix.search(q["q"], k=8)]
        assert [a for a, _ in py] == [a for a, _ in j], q["q"]
        assert all(abs(a[1] - b[1]) < 1e-6 for a, b in zip(py, j))


def test_retrieval_quality_does_not_regress():
    sys.path.insert(0, str(ROOT / "eval"))
    from run_eval import evaluate
    ix = Index.load(ROOT / "data" / "kb.json")
    qs = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    r = evaluate(ix, qs)
    assert r["all"]["hit@5"] >= 0.80, r["all"]


def test_cors_lets_the_static_demo_call_the_api(app):
    _, url = app
    allowed = urllib.request.Request(url + "/api/health", headers={"Origin": "https://yakov-ashgar27.github.io"})
    assert urllib.request.urlopen(allowed).headers["Access-Control-Allow-Origin"] == "https://yakov-ashgar27.github.io"
    other = urllib.request.Request(url + "/api/health", headers={"Origin": "https://evil.example"})
    assert urllib.request.urlopen(other).headers["Access-Control-Allow-Origin"] is None
    pre = urllib.request.Request(url + "/api/chat", method="OPTIONS", headers={"Origin": "https://yakov-ashgar27.github.io"})
    r = urllib.request.urlopen(pre)
    assert r.status == 204 and "POST" in r.headers["Access-Control-Allow-Methods"]


class FakeOpenAI(BaseHTTPRequestHandler):
    """An OpenAI-compatible endpoint (Groq, Gemini, OpenRouter...)."""
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenAI.seen.append((self.path, self.headers["Authorization"], body))
        if not body.get("stream"):
            out = json.dumps({"choices": [{"message": {"content": '["bfs", "find_path_step"]'}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in ["BFS ", "[1]."]:
            ev = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


def test_free_provider_groq(monkeypatch):
    from yakovllm import llm
    srv, url = _serve(FakeOpenAI)
    try:
        for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        monkeypatch.setitem(llm.PROVIDERS["groq"], "base", url + "/openai/v1")
        p = llm.provider()
        assert p["name"] == "groq" and p["model"] == "openai/gpt-oss-120b"
        assert llm.rewrite_query([], "how does the enemy chase?") == ["bfs", "find_path_step"]
        hits = [{"n": 1, "repo": "r", "path": "a.py", "start": 1, "end": 2, "kind": "code", "text": "x" * 5000}]
        out = "".join(llm.stream_answer("sys", llm.build_messages([{"role": "user", "content": "q"}], hits)))
        assert out == "BFS [1]."
        path, auth, body = FakeOpenAI.seen[-1]
        assert path == "/openai/v1/chat/completions" and auth == "Bearer gsk_test"
        assert body["messages"][0] == {"role": "system", "content": "sys"}
        assert body["reasoning_effort"] == "low" and body["max_tokens"] >= 8000
        assert len(body["messages"][-1]["content"]) < 2000      # long sources are trimmed for free-tier token limits
    finally:
        srv.shutdown()


class FakeThinkingOnly(BaseHTTPRequestHandler):
    """A reasoning model that spends every token thinking and streams no text."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":"length"}]}\n\n')
        self.wfile.write(b"data: [DONE]\n\n")


def test_empty_answer_is_an_error_not_silence(monkeypatch):
    from yakovllm import llm
    srv, url = _serve(FakeThinkingOnly)
    try:
        for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "LLM_PROVIDER"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
        monkeypatch.setitem(llm.PROVIDERS["gemini"], "base", url)
        assert llm.provider()["reasoning"] == "low"
        with pytest.raises(llm.ClaudeError, match="thinking"):
            list(llm.stream_answer("sys", [{"role": "user", "content": "q"}]))
    finally:
        srv.shutdown()


class FakeOverloaded(BaseHTTPRequestHandler):
    """The main model answers 503 (overloaded); the fallback model works."""
    models: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOverloaded.models.append(body["model"])
        if body["model"] == "gemini-flash-latest":
            out = json.dumps([{"error": {"code": 503, "message": "This model is currently experiencing high demand."}}]).encode()
            self.send_response(503)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b'data: {"choices":[{"delta":{"content":"ok [1]."}}]}\n\ndata: [DONE]\n\n')


def test_overloaded_model_falls_back(monkeypatch):
    from yakovllm import llm
    srv, url = _serve(FakeOverloaded)
    try:
        for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "LLM_PROVIDER", "LLM_FALLBACK_MODELS"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
        monkeypatch.setitem(llm.PROVIDERS["gemini"], "base", url)
        assert "".join(llm.stream_answer("sys", [{"role": "user", "content": "q"}])) == "ok [1]."
        assert FakeOverloaded.models == ["gemini-flash-latest", "gemini-flash-lite-latest"]
    finally:
        srv.shutdown()


class FakeSilent(BaseHTTPRequestHandler):
    """The main model accepts the request and then says nothing; the fallback answers."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.flush()
        if body["model"] == "gemini-flash-latest":
            time.sleep(3)
            return
        self.wfile.write(b'data: {"choices":[{"delta":{"content":"fallback"}}]}\n\ndata: [DONE]\n\n')


def test_silent_model_times_out_and_falls_back(monkeypatch):
    from yakovllm import llm
    srv, url = _serve(FakeSilent)
    try:
        for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "LLM_PROVIDER", "LLM_FALLBACK_MODELS"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
        monkeypatch.setitem(llm.PROVIDERS["gemini"], "base", url)
        monkeypatch.setattr(llm, "FIRST_TOKEN_TIMEOUT", 1.0)
        assert "".join(llm.stream_answer("sys", [{"role": "user", "content": "q"}])) == "fallback"
    finally:
        srv.shutdown()


def test_ignore_file_and_line_counts(tmp_path):
    repo = tmp_path / "proj"
    _git_repo(repo, {"README.md": "# Proj\n\nProj is a small project used to test ignore files and line counting.\n",
                     "app.py": "a = 1\n\nb = 2\nc = 3\n" * 10, "web/index.html": "<p>" + "sample question " * 20 + "</p>\n",
                     ".yakovllm-ignore": "# skip the UI\nweb/index.html\n"})
    meta, chunks = ingest.ingest_repo(repo, "proj")
    assert not any(c["path"] == "web/index.html" for c in chunks)
    assert meta["loc"]["Python"] == 30
    overview = chunks[0]
    assert overview["path"] == "(overview)" and "שורות קוד" in overview["text"] and "Python: 30" in overview["text"]


def test_fact_sheet_is_always_in_the_answer_context():
    ix = Index.load(ROOT / "data" / "kb.json")
    some = next(r["key"] for r in ix.kb["repos"] if r.get("loc"))
    hits = ix.answer_context("כמה שורות קוד יש בפרויקט?", repo=some)
    sheet = next(h for h in hits if h.chunk["path"] == "(overview)")
    assert sheet.chunk["repo"] == some and "שורות קוד" in sheet.chunk["text"]
    assert all(h.chunk["repo"] == some for h in hits)
    general = ix.answer_context("מה הפרויקט הכי חדש?")
    assert any(h.chunk["path"] == "(all projects)" for h in general)
    follow = ix.answer_context("ומה היה הכי קשה שם?", context_repos=[some])
    assert all(h.chunk["repo"] == some for h in follow)


def test_repo_names_are_recognised_loosely():
    from yakovllm import tokenizer
    aliases = tokenizer.repo_aliases([{"key": "wifi-doctor", "title": "🩺 WiFi-Doctor"},
                                      {"key": "pulseport-analytics", "title": "⚓ PulsePort Analytics"}])
    assert tokenizer.detect_repos("איך מריצים את wifi doctor?", aliases) == ["wifi-doctor"]
    assert tokenizer.detect_repos("מה זה Pulse Port", aliases) == ["pulseport-analytics"]


def test_summary_skips_badges_and_uses_the_tagline():
    readme = ("# GuardStream\n\n[![CI](https://x/badge.svg)](https://x)\n![Python](https://img.shields.io/badge/x)\n\n"
              "**Real-time fraud detection.** A streaming pipeline that scores every card transaction.\n")
    title, summary = ingest.describe("guardstream", "u", {"README.md": readme})
    assert title == "GuardStream" and summary.startswith("Real-time fraud detection.")


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_browser_answer_context_matches_python():
    qs = ["ספר לי על DocMind", "כמה שורות קוד יש ב-GuardStream?", "מה הפרויקט הכי חדש?", "How do I run wifi doctor?"]
    script = f"""
      const {{Index}} = require({json.dumps(str(ROOT / 'web' / 'engine.js'))});
      const kb = JSON.parse(require('fs').readFileSync({json.dumps(str(ROOT / 'data' / 'kb.json'))}, 'utf8'));
      const ix = new Index(kb);
      console.log(JSON.stringify({json.dumps(qs)}.map(q => ix.answerContext(q).map(h => h.chunk.id))));
    """
    js = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    ix = Index.load(ROOT / "data" / "kb.json")
    for q, j in zip(qs, js):
        assert [h.chunk["id"] for h in ix.answer_context(q)] == j, q


def test_question_bank_stays_on_topic():
    sys.path.insert(0, str(ROOT / "eval"))
    from run_bank import run
    s = run(Index.load(ROOT / "data" / "kb.json"))["summary"]
    assert s["fact_sheet"] == 1.0 and s["account_overview"] == 1.0
    assert s["on_topic"] >= 0.95 and s["top_on_topic"] >= 0.95, s


def test_symbol_questions_find_the_right_file():
    sys.path.insert(0, str(ROOT / "eval"))
    from run_symbols import run
    res = run(Index.load(ROOT / "data" / "kb.json"), sample=200)
    assert res["hit"] >= 0.9, res["misses"][:10]


def test_facts_extract_symbols_routes_tables_and_project_facts(tmp_path):
    from yakovllm import facts
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        '"""The API."""\nimport os\nfrom fastapi import FastAPI\napp = FastAPI()\n'
        'KEY = os.environ.get("SECRET_KEY")\n\n'
        '@app.get("/api/items")\ndef list_items(limit: int = 10) -> list:\n    """Return items."""\n    return load_items(limit)\n\n'
        'def load_items(n):\n    return []\n\n'
        'class Item(Base):\n    __tablename__ = "items"\n    name = 1\n', encoding="utf-8")
    (tmp_path / "web.tsx").write_text("export function ItemList({ items }) {\n  return <ul>{items.map(i => <li>{i}</li>)}</ul>;\n}\n"
                                      "export const useItems = () => {\n  return fetch('/api/items');\n};\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi>=0.1\nuvicorn\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("import pytest\ndef test_a():\n    pass\ndef test_b():\n    pass\n", encoding="utf-8")
    files = {p.relative_to(tmp_path).as_posix(): p.read_text() for p in tmp_path.rglob("*") if p.is_file()}
    chunks, summary = facts.build("demo", "Demo", tmp_path, files, lambda rel: False)
    text = "\n".join(c["text"] for c in chunks)
    assert "GET /api/items" in text and "list_items" in text and "table items" in text
    assert "component ItemList" in text and "hook useItems" in text
    assert "SECRET_KEY" in text and "fastapi, uvicorn" in text
    assert summary["tests"] == 2 and summary["endpoints"] == 1
    card = next(c for c in chunks if c["kind"] == "symbol" and c["title"].endswith("load_items"))
    assert card["path"] == "app/main.py" and card["start"] == 12 and "Used in" not in card["text"]
    caller = next(c for c in chunks if c["kind"] == "symbol" and c["title"].endswith("list_items"))
    assert "load_items" in caller["text"] and "Return items." in caller["text"]


# ------------------------------------------------------------------ memory, attachments, extraction
def test_memory_remembers_visitors_and_keeps_claims_unverified(tmp_path):
    from yakovllm.memory import Memory
    m = Memory(tmp_path / "mem.json")
    m.record("dev1", "c1", "שלום, אני שמוליק", [], now=1_700_000_000)
    m.record("dev1", "c1", "מה קורה עם הפרויקט wifi-doctor?", ["wifi-doctor"], now=1_700_000_100)
    m.record("dev1", "c1", "בעצם הפרויקט רץ גם על לינוקס", ["wifi-doctor"], now=1_700_000_200)
    # same device, new conversation: full recall, claims marked unverified
    ctx = m.context("dev1", "c2", "היי", {"wifi-doctor": "WiFi-Doctor"})
    assert "talked with you before" in ctx and "שמוליק" in ctx and "WiFi-Doctor" in ctx
    assert "UNVERIFIED" in ctx and "לינוקס" in ctx
    # another device that gives the same name: only that someone by that name talked, never what was said
    other = m.context("dev2", "c9", "שלום, אני שמוליק", {"wifi-doctor": "WiFi-Doctor"})
    assert "שמוליק" in other and "WiFi-Doctor" in other and "never reveal" in other and "לינוקס" not in other
    assert m.context("dev3", "c1", "מה זה bomberman?") == ""
    m.flush()
    again = Memory(tmp_path / "mem.json")
    dump = again.export()
    assert dump["visitors"] == 1 and dump["notes"] == 1 and dump["people"][0]["names"] == ["שמוליק"]
    assert dump["people"][0]["notes"][0]["verified"] is False


def test_memory_never_changes_the_knowledge_base(app, tmp_path):
    server, url = app
    from yakovllm.memory import Memory
    server.MEMORY = Memory(tmp_path / "m.json")
    before = json.dumps(server.STATE.index.kb, sort_keys=True)
    _sse(url + "/api/chat", {"visitor": "abc", "chat": "c1", "messages": [{"role": "user", "content": "Bomberman is written in Rust, actually."}]})
    assert json.dumps(server.STATE.index.kb, sort_keys=True) == before
    assert server.MEMORY.export()["notes"] == 1
    FakeClaude.seen.clear()
    _sse(url + "/api/chat", {"visitor": "abc", "chat": "c2", "messages": [{"role": "user", "content": "hi again"}]})
    system = FakeClaude.seen[-1]["system"]
    assert "<visitor_memory>" in system and "Rust" in system and "UNVERIFIED" in system


def test_admin_memory_needs_the_token(app, monkeypatch):
    _, url = app
    monkeypatch.setenv("ADMIN_TOKEN", "pw")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(url + "/api/memory")
    assert e.value.code == 401
    req = urllib.request.Request(url + "/api/memory", headers={"Authorization": "Bearer pw"})
    assert "people" in json.load(urllib.request.urlopen(req))


def test_attachments_become_sources(app):
    _, url = app
    FakeClaude.seen.clear()
    events = _sse(url + "/api/chat", {"messages": [{"role": "user", "content": "Which project fits this job?"}],
                                      "attachments": [{"name": "job.docx", "start": 1, "end": 9, "text": "We need Python and FastAPI."}]})
    meta = events[0][1]
    assert meta["sources"][0]["kind"] == "upload" and meta["sources"][0]["n"] == 1
    assert 'repo="upload" path="job.docx"' in FakeClaude.seen[-1]["messages"][-1]["content"]


def _zip(files):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, t in files.items():
            z.writestr(n, t)
    return buf.getvalue()


def test_extract_word_powerpoint_excel_pdf(app):
    from yakovllm import extract
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    docx = _zip({"word/document.xml": f'<w:document {W}><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>דרישות</w:t></w:r></w:p>'
                 '<w:p><w:r><w:t>Python, </w:t></w:r><w:r><w:t>React</w:t></w:r></w:p></w:body></w:document>'})
    assert extract.extract("cv.docx", docx) == "# דרישות\nPython, React"
    A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    pptx = _zip({"ppt/slides/slide2.xml": f'<p:sld {A} xmlns:p="x"><a:p><a:r><a:t>Second</a:t></a:r></a:p></p:sld>',
                 "ppt/slides/slide1.xml": f'<p:sld {A} xmlns:p="x"><a:p><a:r><a:t>First</a:t></a:r></a:p></p:sld>'})
    assert extract.extract("deck.pptx", pptx).startswith("## Slide 1\nFirst")
    S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    xlsx = _zip({"xl/sharedStrings.xml": f'<sst {S}><si><t>Name</t></si></sst>',
                 "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData><row><c t="s"><v>0</v></c><c><v>42</v></c></row></sheetData></worksheet>'})
    assert "Name | 42" in extract.extract("t.xlsx", xlsx)
    try:
        from pypdf import PdfWriter
    except ImportError:
        pytest.skip("pypdf not installed")
    import io
    w = PdfWriter()
    w.add_blank_page(100, 100)
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(extract.ExtractError):
        extract.extract("blank.pdf", buf.getvalue())
    # the HTTP endpoint
    _, url = app
    req = urllib.request.Request(url + "/api/extract", data=docx, headers={"X-Filename": "cv.docx"})
    assert json.load(urllib.request.urlopen(req))["text"].endswith("Python, React")


def test_browser_reads_office_files_and_picks_excerpts():
    script = r"""
const Files = require('./web/files.js');
globalThis.YakovEngine = require('./web/engine.js');
const kb = require('./data/kb.json');
const files = [{ name: 'job.txt', text: 'About us\n\nWe build fraud detection with FastAPI, Redis streams and React dashboards.\n\nBenefits: lunch.' }];
const hits = Files.pick(files, 'which skills does the job need? fraud detection', 3, kb.tokenizer);
console.log(JSON.stringify({ n: hits.length, first: hits[0].path, kind: hits[0].kind, supported: [Files.supported('a.pdf'), Files.supported('b.docx'), Files.supported('c.exe')] }));
"""
    out = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    assert r["n"] >= 1 and r["first"] == "job.txt" and r["kind"] == "upload" and r["supported"] == [True, True, False]


def test_reply_language_follows_the_latest_message():
    from yakovllm.dialog import reply_language
    assert reply_language([{"role": "user", "content": "מה זה FitVision?"}, {"role": "assistant", "content": "..."},
                           {"role": "user", "content": "Yes"}]) == "English"
    assert reply_language([{"role": "user", "content": "Tell me about Bomberman"}, {"role": "user", "content": "2"}]) == "English"
    assert reply_language([{"role": "user", "content": "תסביר את ה-API של guardstream"}]) == "Hebrew"


OPTIONS_ANSWER = """מעולה! על מה תרצה שנתמקד?

1. **חישוב זוויות המפרקים** – איך MediaPipe מנתח את ה-Pose
2. **ארכיטקטורת ה-Offline Sync** – איך ה-PWA שומר אימונים
3. **תשתית ה-CI** – איך ה-Backend נבדק

מה הכי מעניין אותך?"""


def test_a_number_picks_the_option_from_the_last_answer(app):
    from yakovllm.dialog import resolve_choice
    convo = [{"role": "user", "content": "ספר לי על FitVision"}, {"role": "assistant", "content": OPTIONS_ANSWER}]
    for pick in ("2", "2.", "אפשרות 2", "השני", "the second one", "option 2"):
        assert resolve_choice(convo + [{"role": "user", "content": pick}])[0] == 2, pick
    assert resolve_choice(convo + [{"role": "user", "content": "ספר לי על 2 פרויקטים"}]) is None
    _, url = app
    FakeClaude.seen.clear()
    events = _sse(url + "/api/chat", {"messages": convo + [{"role": "user", "content": "2"}]})
    sent = FakeClaude.seen[-1]["messages"][-1]["content"]
    assert 'picked option 2' in sent and "Offline Sync" in sent and "Reply in Hebrew" in sent
    assert all(s["repo"] == "fitvision-ai" for s in events[0][1]["sources"])


def test_temporary_chat_feedback_and_forget_me(app, tmp_path):
    server, url = app
    from yakovllm.memory import Memory
    server.MEMORY = Memory(tmp_path / "m.json")
    _sse(url + "/api/chat", {"visitor": "v1", "chat": "t1", "temporary": True,
                             "messages": [{"role": "user", "content": "my secret plan is X"}]})
    assert server.MEMORY.export()["visitors"] == 0  # a temporary chat leaves no trace
    FakeClaude.seen.clear()
    _sse(url + "/api/chat", {"visitor": "v1", "chat": "c1", "name": "Dana", "instructions": "Answer in 3 bullets",
                             "messages": [{"role": "user", "content": "What is Bomberman?"}]})
    system = FakeClaude.seen[-1]["system"]
    assert "Dana" in system and "Answer in 3 bullets" in system and "<user_instructions>" in system

    def post(path, body):
        req = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req))
    assert post("/api/feedback", {"visitor": "v1", "chat": "c1", "vote": "up", "question": "q", "answer": "a"})["ok"]
    me = post("/api/memory/me", {"visitor": "v1"})
    assert me["known"] and me["names"] == ["Dana"] and me["conversations"] == 1
    assert server.MEMORY.export()["people"][0]["feedback"][0]["vote"] == "up"
    assert post("/api/memory/forget", {"visitor": "v1"})["ok"]
    assert post("/api/memory/me", {"visitor": "v1"}) == {"known": False}
