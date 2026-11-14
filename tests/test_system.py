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
    assert h["name"] == "yakov.LLM" and h["mode"] == "claude" and h["chunks"] > 100
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
