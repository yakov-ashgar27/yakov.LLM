"""yakov.LLM web server: the chat UI, a JSON API and live GitHub sync.

    python -m yakovllm.server            # http://localhost:8000

Standard library only (ThreadingHTTPServer), so it runs anywhere Python 3.10+
runs, with no install step. Answers stream to the browser as Server-Sent Events.

Environment:
    GROQ_API_KEY        free written answers (open models on Groq), or
    GEMINI_API_KEY      free written answers (Gemini Flash), or
    ANTHROPIC_API_KEY   Claude answers (paid). Without any key: offline excerpt mode.
    LLM_MODEL           answer model (defaults per provider, see llm.PROVIDERS)
    GITHUB_USER         account to follow       (default: the owner in kb.json)
    GITHUB_TOKEN        optional, raises the GitHub API rate limit
    SYNC_INTERVAL_MIN   minutes between GitHub checks (default 30, 0 = off)
    WEBHOOK_SECRET      secret of the GitHub webhook that triggers an instant sync
    SYNC_TOKEN          if set, POST /api/sync needs "Authorization: Bearer <token>"
    RATE_LIMIT          chat requests per IP per 10 minutes (default 30)
    CORS_ORIGINS        sites whose pages may call this API, comma-separated
                        (default https://yakov-ashgar27.github.io, the static demo)
    ADMIN_TOKEN         password for GET /api/memory (visitors, their questions and unverified notes)
    MEMORY_REPO         private GitHub repo "owner/name" that keeps the memory across deploys
    MEMORY_TOKEN        GitHub token that can write MEMORY_REPO (fine-grained, Contents: read & write)
    MEMORY_PATH         local memory file (default .cache/memory.json)
    HOST / PORT         default 0.0.0.0:8000
"""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import queue
import threading
import time
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import dialog, extract, llm, tokenizer
from .memory import Memory
from .search import Index
from .sync import GitHubSync

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
KB_PATH = Path(os.environ.get("KB_PATH", ROOT / "data" / "kb.json"))
OWNER_NAME = os.environ.get("OWNER_NAME", "Yakov Ashgar")
STARTED = time.time()
CORS_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "https://yakov-ashgar27.github.io").split(",") if o.strip()}


class State:
    """The live index. Sync swaps it under a lock; requests read a reference."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.index = Index.load(KB_PATH) if KB_PATH.exists() else Index({"repos": [], "chunks": []})
        self.sync: GitHubSync | None = None

    def swap(self, kb: dict) -> None:
        new = Index(kb)
        with self.lock:
            self.index = new


STATE = State()


class RateLimiter:
    def __init__(self, limit: int, window_s: int = 600):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


LIMITER = RateLimiter(int(os.environ.get("RATE_LIMIT", "30")))
MEMORY: Memory | None = None
MAX_ATTACH = 8
MAX_ATTACH_CHARS = 3500


def memory() -> Memory:
    global MEMORY
    if MEMORY is None:
        MEMORY = Memory.from_env()
    return MEMORY


def attachment_sources(items) -> list[dict]:
    """Excerpts of files the user attached, already picked in the browser."""
    out = []
    for a in (items or [])[:MAX_ATTACH]:
        if not isinstance(a, dict) or not a.get("text"):
            continue
        name = str(a.get("name") or "file")[:160]
        out.append({"id": f"upload:{name}:{a.get('start', 1)}", "repo": "upload", "path": name,
                    "start": int(a.get("start") or 1), "end": int(a.get("end") or 1),
                    "title": f"📎 {name}", "kind": "upload", "text": str(a["text"])[:MAX_ATTACH_CHARS],
                    "score": 0, "terms": [], "url": ""})
    return out


def source_payload(index: Index, hits) -> list[dict]:
    out = []
    for n, h in enumerate(hits, 1):
        d = h.to_dict(n)
        d["url"] = index.github_url(h.chunk)
        out.append(d)
    return out


def retrieval_query(messages: list[dict]) -> tuple[str, str]:
    """(latest question, text to search). Short follow-ups borrow the previous question;
    "2" after a numbered list means that option's text."""
    users = [str(m["content"]) for m in messages if m.get("role") == "user" and m.get("content")]
    if not users:
        return "", ""
    q = users[-1]
    choice = dialog.resolve_choice(messages)
    if choice:
        return q, f"{choice[1]} {users[-2] if len(users) > 1 else ''}".strip()
    if len(users) > 1 and len(tokenizer.tokenize(q)) < 6:
        return q, f"{users[-2]} {q}"
    return q, q


class Handler(BaseHTTPRequestHandler):
    server_version = "yakov.LLM"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter logs: method, path, status
        if os.environ.get("QUIET"):
            return
        super().log_message(fmt, *args)

    # ---------------------------------------------------------------- utils
    def _cors(self):
        """Let the GitHub Pages demo call this API from the browser."""
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin and (origin in CORS_ORIGINS or "*" in CORS_ORIGINS):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Filename")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self, limit=200_000) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("request too large")
        return self.rfile.read(n) if n else b""

    def _client_ip(self) -> str:
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or self.client_address[0]

    # ----------------------------------------------------------------- GET
    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        if p == "/api/health":
            return self._json(self.health())
        if p == "/api/repos":
            ix = STATE.index
            return self._json({"repos": ix.kb["repos"], "built_at": ix.kb.get("built_at"), "owner": ix.kb.get("owner", ""),
                               "tokenizer": ix.kb.get("tokenizer")})
        if p == "/api/memory":
            return self.memory_dump()
        if p == "/api/search":
            qs = parse_qs(url.query)
            return self._json(self.search(qs.get("q", [""])[0], qs.get("repo", [None])[0], int(qs.get("k", ["6"])[0])))
        return self.static(p)

    def static(self, p: str):
        if p in ("", "/"):
            p = "/index.html"
        target = (WEB / p.lstrip("/")).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            target = WEB / "index.html"  # single-page app
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def health(self) -> dict:
        ix = STATE.index
        sync = STATE.sync.status if STATE.sync else {"enabled": False}
        prov = llm.provider()
        return {"ok": True, "name": "yakov.LLM", "mode": "llm" if prov else "offline",
                "provider": prov["label"] if prov else None, "model": prov["model"] if prov else None,
                "owner": ix.kb.get("owner", ""), "owner_name": OWNER_NAME,
                "repos": len(ix.repos), "chunks": ix.n, "built_at": ix.kb.get("built_at"),
                "uptime_s": int(time.time() - STARTED), "sync": sync, "memory": memory().stats(),
                "features": ["attachments", "extract", "memory"]}

    def search(self, q: str, repo: str | None, k: int) -> dict:
        ix = STATE.index
        t = time.perf_counter()
        hits = ix.search(q, k=max(1, min(k, 20)), repo=repo or None)
        return {"query": q, "ms": round((time.perf_counter() - t) * 1000, 2), "results": source_payload(ix, hits)}

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        p = urlparse(self.path).path
        try:
            if p == "/api/chat":
                return self.chat()
            if p == "/api/search":
                data = json.loads(self._body() or b"{}")
                return self._json(self.search(data.get("q", ""), data.get("repo"), int(data.get("k", 6))))
            if p == "/api/sync":
                return self.sync_now()
            if p == "/api/extract":
                return self.extract_file()
            if p == "/api/feedback":
                d = json.loads(self._body() or b"{}")
                ok = memory().feedback(str(d.get("visitor", "")), str(d.get("chat", "")), str(d.get("vote", "")),
                                       str(d.get("question", "")), str(d.get("answer", "")))
                return self._json({"ok": ok}, 200 if ok else 400)
            if p == "/api/memory/me":
                return self._json(memory().mine(str(json.loads(self._body() or b"{}").get("visitor", ""))))
            if p == "/api/memory/forget":
                return self._json({"ok": memory().forget(str(json.loads(self._body() or b"{}").get("visitor", "")))})
            if p == "/api/webhook/github":
                return self.webhook()
        except (ValueError, json.JSONDecodeError) as e:
            return self._json({"error": str(e)}, 400)
        self._json({"error": "not found"}, 404)

    def memory_dump(self):
        token = os.environ.get("ADMIN_TOKEN", "")
        given = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not token:
            return self._json({"error": "ADMIN_TOKEN is not set on the server"}, 403)
        if not hmac.compare_digest(given, token):
            return self._json({"error": "unauthorized"}, 401)
        return self._json(memory().export())

    def extract_file(self):
        if not LIMITER.allow("x:" + self._client_ip()):
            return self._json({"error": "rate_limited"}, 429)
        from urllib.parse import unquote
        name = unquote(self.headers.get("X-Filename") or "file")
        data = self._body(15_000_000)
        try:
            text = extract.extract(name, data)
        except extract.ExtractError as e:
            return self._json({"error": str(e)}, 422)
        return self._json({"name": name, "chars": len(text), "text": text})

    def sync_now(self):
        token = os.environ.get("SYNC_TOKEN")
        if token and self.headers.get("Authorization") != f"Bearer {token}":
            return self._json({"error": "unauthorized"}, 401)
        if not STATE.sync:
            return self._json({"error": "sync is off (no GITHUB_USER)"}, 409)
        STATE.sync.trigger()
        return self._json({"ok": True, "status": STATE.sync.status}, 202)

    def webhook(self):
        body = self._body(5_000_000)
        secret = os.environ.get("WEBHOOK_SECRET", "")
        if not secret:
            return self._json({"error": "WEBHOOK_SECRET is not set"}, 403)
        sig = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return self._json({"error": "bad signature"}, 401)
        event = self.headers.get("X-GitHub-Event", "")
        if event in ("push", "repository", "create", "delete", "public", "release") and STATE.sync:
            STATE.sync.trigger()
            return self._json({"ok": True, "event": event, "sync": "scheduled"}, 202)
        return self._json({"ok": True, "event": event, "sync": "ignored"})

    def chat(self):
        if not LIMITER.allow(self._client_ip()):
            return self._json({"error": "rate_limited", "message": "Too many questions, try again in a few minutes."}, 429)
        data = json.loads(self._body() or b"{}")
        messages = data.get("messages") or []
        repo = data.get("repo") or None
        visitor = str(data.get("visitor") or "")
        chat_id = str(data.get("chat") or "")[:64]
        attachments = attachment_sources(data.get("attachments"))
        given_name = str(data.get("name") or "").strip()[:40]
        temporary = bool(data.get("temporary"))
        instructions = str(data.get("instructions") or "").strip()[:1500]
        lang = {"he": "Hebrew", "en": "English"}.get(str(data.get("lang") or ""))
        question, search_text = retrieval_query(messages)
        if not question:
            return self._json({"error": "empty question"}, 400)

        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def send(event: str, obj) -> None:
            self.wfile.write(f"event: {event}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

        t0 = time.perf_counter()
        ix = STATE.index
        try:
            keywords = llm.rewrite_query(messages, question)
            # Projects the conversation was already about: "what was hardest there?" stays on topic.
            earlier = " ".join(str(m.get("content", ""))[:600] for m in messages[:-1][-4:])
            context = ix.detect(earlier) if earlier else []
            hits = ix.answer_context(search_text, k=8 if not attachments else 6, repo=repo, extra_terms=keywords,
                                     context_repos=context)
            sources = attachments + source_payload(ix, hits)
            for n, src in enumerate(sources, 1):
                src["n"] = n
            projects = [repo] if repo else (ix.detect(question) or context)[:3]
            mem = memory()
            titles = {r["key"]: r.get("title") or r["key"] for r in ix.kb["repos"]}
            user_text = "\n".join(str(m.get("content", ""))[:500] for m in messages if m.get("role") == "user")
            recall = mem.context(visitor, chat_id, user_text, titles) if visitor and not temporary else ""
            if given_name:
                recall = (f"The user's name, from their profile: {given_name}. Use it naturally now and then, not in every answer.\n" + recall).strip()
            if visitor and not temporary:  # a temporary chat leaves no trace
                mem.record(visitor, chat_id, question, projects, given_name=given_name)
            send("meta", {"sources": sources, "keywords": keywords, "mode": "llm" if llm.has_key() else "offline",
                          "search_ms": round((time.perf_counter() - t0) * 1000, 1)})
            if llm.has_key():
                system = llm.SYSTEM_PROMPT.format(owner_name=OWNER_NAME, owner=ix.kb.get("owner", ""),
                                                  projects=llm.project_list(ix.kb["repos"]))
                if recall:
                    system += "\n\n<visitor_memory>\n" + recall + "\n</visitor_memory>"
                if instructions:
                    system += ("\n\n<user_instructions>\nThe user's standing preferences for how you answer (style, length, tone, "
                               "level of detail). Follow them, but never against the rules above or the sources:\n"
                               + instructions + "\n</user_instructions>")
                stream = llm.stream_answer(system, llm.build_messages(messages, sources, lang=lang))
            else:
                stream = llm.offline_answer(question, sources)
            # Run the model in a thread so we can send keep-alive comments while it thinks:
            # some proxies close a stream that stays silent for too long.
            q: queue.Queue = queue.Queue()

            def pump() -> None:
                try:
                    for piece in stream:
                        q.put(("delta", piece))
                    q.put(("end", None))
                except Exception as e:  # noqa: BLE001 - reported to the browser below
                    q.put(("error", e))

            threading.Thread(target=pump, daemon=True).start()
            while True:
                try:
                    kind, val = q.get(timeout=8)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                if kind == "delta":
                    send("delta", {"text": val})
                elif kind == "error":
                    raise val
                else:
                    break
            send("done", {"ms": round((time.perf_counter() - t0) * 1000)})
        except (BrokenPipeError, ConnectionResetError):
            return  # the user pressed stop
        except Exception as e:
            try:
                send("error", {"message": str(e)})
            except Exception:
                pass


def start_sync() -> None:
    user = os.environ.get("GITHUB_USER") or STATE.index.kb.get("owner", "")
    interval = float(os.environ.get("SYNC_INTERVAL_MIN", "30"))
    if not user or interval <= 0:
        return
    STATE.sync = GitHubSync(user, KB_PATH, interval, on_update=STATE.swap)
    STATE.sync.start()


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    start_sync()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    ix = STATE.index
    print(f"yakov.LLM on http://localhost:{port} · {len(ix.repos)} repos · {ix.n} chunks · "
          f"{(llm.provider()['label'] + ' ' + llm.model_name()) if llm.has_key() else 'offline mode (set GROQ_API_KEY or ANTHROPIC_API_KEY)'}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
