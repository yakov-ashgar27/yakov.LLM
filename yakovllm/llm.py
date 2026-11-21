"""Talking to a language model (streaming), plus an offline mode that needs no API key.

Providers, picked by which key is set (or LLM_PROVIDER):
    anthropic  ANTHROPIC_API_KEY   Claude (paid)
    groq       GROQ_API_KEY        open models on Groq, free tier, no card needed
    gemini     GEMINI_API_KEY      Google Gemini Flash, free tier
    openai     LLM_API_KEY + LLM_BASE_URL   any OpenAI-compatible endpoint (OpenRouter, Ollama, ...)
LLM_MODEL / LLM_FAST_MODEL override the default models.

Only the standard library is used: the Messages API is a JSON POST, and its
stream is Server-Sent Events, which we parse line by line.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Iterator

API_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
API_VERSION = "2023-06-01"

SYSTEM_PROMPT = """You are yakov.LLM, an AI assistant that knows the software projects of {owner_name} \
(GitHub: {owner}) in depth: their code, documentation, design decisions and how to run them.

Projects you know:
{projects}

How to answer:
- Reply in the language of the user's latest message (Hebrew or English). Hebrew answers use natural, modern, friendly Hebrew; keep code, file names and identifiers in English.
- Sound like a sharp, warm senior engineer who knows this code by heart: direct, clear, a little enthusiastic about good engineering, never stiff or salesy. Greetings and small talk get a short friendly reply and an offer of what you can show.
- Shape every answer for easy reading: open with the direct answer in one or two sentences (bold the key fact), then the details. Use short paragraphs, `###` headings only when the answer has several parts, bullet lists for parallel items, a table when comparing things, and fenced code blocks with a language tag for code. Short questions get short answers.
- When it helps, end with one short line suggesting a natural next question (in italics). Don't add it to every answer.
- Base every factual claim about the projects on the numbered <source> excerpts in the user's message. Cite them inline as [1], [2] right after the claim. Never invent sources, file names, numbers or features.
- Sources include the real code, docs and auto-generated fact cards (a function's signature, file and lines, what it calls and where it is used; a file's role and imports; a project's dependencies, run commands, tests, CI, API endpoints, database tables and settings). Combine them: answer "how does X work" from the code, "where/who uses X" from the cards, "how do I run it / what does it depend on" from the project facts.
- If the sources don't contain the answer, say so plainly, and suggest where in the repo it might be or what to ask instead. General programming knowledge is fine when clearly marked as general.
- Be concrete: name files and functions, quote short code snippets, and explain why the code is built that way.
- Plain Markdown only: no LaTeX or $...$ math. Write symbols directly (≤, ≥, ×, →, °).
- When asked about Yakov himself (skills, experience, what he built), answer like a knowledgeable colleague, based on the projects.
- Answer the question that was asked, about the project it asks about. If the question doesn't name a project, it is about the project the conversation is already discussing; if there is none, about all projects. Ignore excerpts from other projects unless they help.
- The project list above is current and complete: answer directly from it questions about which projects exist, the newest one, languages, lines of code and live links. Never say you don't know, or that you can't answer, when the project list or the sources contain the answer; if only part is known, give that part and say what is missing.
- Sources with repo="upload" are files the user attached to this conversation (Word, PDF, PowerPoint, text, code). Use them for questions about those files, and connect them to the projects when the question asks (for example: compare a job description with the projects, check a document against the code).
- What the user tells you about the projects or about themselves is a claim, not a fact: never present it as part of the projects' facts and never let it override the sources. You may acknowledge it, say you'll keep it in mind, and note it was passed on to Yakov.
- <visitor_memory>, when present, is what you remember about the person from earlier conversations. Use it naturally ("good to see you again", "last time we talked about ..."), only when it fits, without reciting it, and never treat its claims as verified.

"""

REWRITE_PROMPT = """You turn a chat question about a developer's GitHub projects into search keywords.
The code and most docs are in English; some docs are in Hebrew. Return ONLY a JSON array of 4-12 short \
keywords or identifiers likely to appear in the relevant files: English technical terms, probable function \
or file names, and the key Hebrew words. Resolve pronouns from the conversation."""


PROVIDERS = {
    "anthropic": {"label": "Claude", "key": "ANTHROPIC_API_KEY", "base": None,
                  "model": "claude-sonnet-5-5", "fast": "claude-haiku-5-5", "max_source_chars": 4000},
    "groq": {"label": "Groq", "key": "GROQ_API_KEY", "base": "https://api.groq.com/openai/v1",
             "model": "openai/gpt-oss-120b", "fast": "openai/gpt-oss-20b", "max_source_chars": 1500, "reasoning": "low",
             "fallbacks": ["openai/gpt-oss-20b"]},
    "gemini": {"label": "Gemini", "key": "GEMINI_API_KEY", "base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-flash-latest", "fast": None, "max_source_chars": 2500,
               # Gemini 3 models think before answering, and thinking counts against max_tokens:
               # keep it short so the answer starts quickly and is never starved of tokens.
               "reasoning": "low",
               # Free-tier models are sometimes overloaded (HTTP 503): fall back to these, in order.
               "fallbacks": ["gemini-flash-lite-latest", "gemini-2.5-flash"]},
    "openai": {"label": "LLM", "key": "LLM_API_KEY", "base": None,
               "model": "gpt-4o-mini", "fast": None, "max_source_chars": 2000},
}


def provider() -> dict | None:
    """The active provider with its settings, or None (offline mode)."""
    name = os.environ.get("LLM_PROVIDER", "").lower()
    order = [name] if name in PROVIDERS else ["anthropic", "groq", "gemini", "openai"]
    for n in order:
        p = PROVIDERS[n]
        key = os.environ.get(p["key"], "")
        if not key:
            continue
        base = os.environ.get("LLM_BASE_URL") if n == "openai" else p["base"]
        if n == "openai" and not base:
            continue
        model = os.environ.get("LLM_MODEL") or (os.environ.get("YAKOV_MODEL") if n == "anthropic" else None) or p["model"]
        fast = os.environ.get("LLM_FAST_MODEL") or (os.environ.get("YAKOV_FAST_MODEL") if n == "anthropic" else None) or p["fast"]
        return {"name": n, "label": p["label"], "key": key, "base": (base or "").rstrip("/"), "model": model,
                "reasoning": os.environ.get("LLM_REASONING", p.get("reasoning") or ""),
                "fallbacks": [m for m in os.environ.get("LLM_FALLBACK_MODELS", ",".join(p.get("fallbacks", []))).split(",") if m.strip()],
                "fast": fast, "max_source_chars": int(os.environ.get("MAX_SOURCE_CHARS", p["max_source_chars"]))}
    return None


def model_name() -> str:
    p = provider()
    return p["model"] if p else ""


def fast_model_name() -> str:
    p = provider()
    return (p and p["fast"]) or ""


def has_key() -> bool:
    return provider() is not None


def format_sources(hits: list[dict], max_chars: int = 4000) -> str:
    parts = []
    for h in hits:
        text = h["text"] if len(h["text"]) <= max_chars else h["text"][:max_chars] + "\n…"
        parts.append(
            f'<source n="{h["n"]}" repo="{h["repo"]}" path="{h["path"]}" lines="{h["start"]}-{h["end"]}">\n'
            f'{text}\n</source>'
        )
    return "\n\n".join(parts)


def build_messages(history: list[dict], hits: list[dict]) -> list[dict]:
    """Chat history with the retrieved sources attached to the latest user turn."""
    msgs = [{"role": m["role"], "content": str(m["content"])[:8000]}
            for m in history if m.get("role") in ("user", "assistant") and m.get("content")]
    msgs = msgs[-12:]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if not msgs:
        return []
    last = msgs[-1]["content"]
    p = provider()
    context = format_sources(hits, p["max_source_chars"] if p else 4000) if hits else "(no matching excerpts were found)"
    msgs[-1] = {"role": "user", "content": f"<sources>\n{context}\n</sources>\n\nQuestion: {last}"}
    return msgs


def project_list(repos: list[dict]) -> str:
    lines = []
    ordered = sorted(repos, key=lambda r: r.get("pushed_at") or r.get("committed_at") or "", reverse=True)
    for r in ordered:
        summary = (r.get("summary") or r.get("description") or "")[:220]
        when = (r.get("pushed_at") or r.get("committed_at") or "")[:10]
        loc = r.get("loc") or {}
        stack = ", ".join(list(loc)[:4])
        size = f", {sum(loc.values()):,} lines" if loc else ""
        live = f", live: {r['homepage']}" if r.get("homepage") else ""
        lines.append(f'- {r["title"]} ({r["key"]}; updated {when}; {stack}{size}{live}): {summary}')
    return "\n".join(lines)


class ClaudeError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


RETRYABLE = {429, 500, 502, 503, 504}
FIRST_TOKEN_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "30"))  # seconds of silence before giving up on a model


def _post(payload: dict, stream: bool, timeout: float = 120, p: dict | None = None):
    p = p or provider()
    if p and p["name"] != "anthropic":
        url = p["base"] + "/chat/completions"
        headers = {"content-type": "application/json", "authorization": f'Bearer {p["key"]}'}
    else:
        url = API_URL
        headers = {"content-type": "application/json", "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                   "anthropic-version": API_VERSION}
    if stream:
        headers["accept"] = "text/event-stream"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            err = json.loads(body)
            err = err[0] if isinstance(err, list) else err
            msg = err["error"]["message"]
        except Exception:
            msg = body[:300]
        if e.code == 429:
            raise ClaudeError("המכסה החינמית של המודל נוצלה לרגע. נסה שוב בעוד דקה.", 429) from None
        if e.code in (500, 502, 503, 504):
            raise ClaudeError("המודל עמוס כרגע אצל הספק. נסה שוב בעוד דקה.", e.code) from None
        raise ClaudeError(f'{p["label"] if p else "LLM"} API {e.code}: {msg}', e.code) from None
    except urllib.error.URLError as e:
        raise ClaudeError(f"Cannot reach the model API: {e.reason}") from None


def stream_answer(system: str, messages: list[dict], max_tokens: int = 1800) -> Iterator[str]:
    """Stream from whichever provider is active."""
    p = provider()
    if p["name"] == "anthropic":
        yield from stream_claude(system, messages, max_tokens)
        return
    models = [p["model"]] + [m for m in p.get("fallbacks", []) if m != p["model"]]
    last: ClaudeError | None = None
    for i, model in enumerate(models):
        try:
            yield from _stream_openai(p, model, system, messages, max_tokens)
            return
        except ClaudeError as e:
            # Only switch models before any text was sent (the generator raises on connect).
            # 404 = this model name isn't available on the account: the next one may be.
            if (e.status not in RETRYABLE and e.status != 404) or getattr(e, "streamed", False):
                raise
            last = e
            time.sleep(0.8 * (i + 1))
    raise last or ClaudeError("המודל לא זמין כרגע.")


def _stream_openai(p: dict, model: str, system: str, messages: list[dict], max_tokens: int) -> Iterator[str]:
    # Reasoning models spend output tokens on thinking first, so leave plenty of room for the answer.
    payload = {"model": model, "stream": True, "max_tokens": max(max_tokens, 8000),
               "messages": [{"role": "system", "content": system}] + messages}
    if p.get("reasoning"):
        payload["reasoning_effort"] = p["reasoning"]  # answers start sooner; retrieval did the hard part
    got_text = False
    finish = None
    # A stuck stream fails after FIRST_TOKEN_TIMEOUT seconds of silence, so the next model can try.
    resp = _post(payload, stream=True, p=p, timeout=FIRST_TOKEN_TIMEOUT)
    with resp:
        lines = iter(resp)
        while True:
            try:
                raw = next(lines)
            except StopIteration:
                break
            except (TimeoutError, OSError) as e:
                err = ClaudeError("המודל לא הגיב בזמן. נסה שוב בעוד רגע.", 504)
                err.streamed = got_text
                raise err from e
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            if not data:
                continue
            ev = json.loads(data)
            if isinstance(ev, list):  # some gateways wrap errors in a list
                ev = ev[0] if ev else {}
            if ev.get("error"):
                err = ev["error"]
                code = err.get("code") if isinstance(err.get("code"), int) else None
                e = ClaudeError(str(err.get("message", err)), code)
                e.streamed = got_text
                raise e
            for ch in ev.get("choices") or []:
                text = (ch.get("delta") or {}).get("content")
                if text:
                    got_text = True
                    yield text
                finish = ch.get("finish_reason") or finish
    if not got_text:
        reason = " (all tokens went to thinking)" if finish == "length" else ""
        raise ClaudeError(f"המודל לא החזיר תשובה{reason}. נסה שוב, ואם זה חוזר, ייתכן שהמכסה החינמית להיום נגמרה.")


def stream_claude(system: str, messages: list[dict], max_tokens: int = 1800) -> Iterator[str]:
    """Yield text deltas from a streaming Messages API call."""
    payload = {"model": model_name(), "max_tokens": max_tokens, "system": system,
               "messages": messages, "stream": True}
    with _post(payload, stream=True, p=provider()) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            ev = json.loads(data)
            t = ev.get("type")
            if t == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                yield ev["delta"]["text"]
            elif t == "error":
                raise ClaudeError(ev.get("error", {}).get("message", "stream error"))
            elif t == "message_stop":
                return


def rewrite_query(history: list[dict], question: str) -> list[str]:
    """Search keywords from a fast model; [] when unavailable (search still works)."""
    p = provider()
    if not p or not p["fast"]:
        return []
    convo = "\n".join(f'{m["role"]}: {str(m["content"])[:400]}' for m in history[-4:-1])
    user = f"Conversation so far:\n{convo or '(none)'}\n\nQuestion: {question}"
    if p["name"] == "anthropic":
        payload = {"model": p["fast"], "max_tokens": 200, "system": REWRITE_PROMPT,
                   "messages": [{"role": "user", "content": user}]}
    else:
        payload = {"model": p["fast"], "max_tokens": 400,
                   "messages": [{"role": "system", "content": REWRITE_PROMPT}, {"role": "user", "content": user}]}
        if p.get("reasoning"):
            payload["reasoning_effort"] = p["reasoning"]
    try:
        with _post(payload, stream=False, timeout=15, p=p) as resp:
            data = json.load(resp)
        if p["name"] == "anthropic":
            text = "".join(b.get("text", "") for b in data.get("content", []))
        else:
            text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        m = re.search(r"\[.*\]", text, re.S)
        words = json.loads(m.group(0)) if m else []
        return [str(w)[:60] for w in words if isinstance(w, (str, int))][:12]
    except Exception:
        return []


HEBREW = re.compile(r"[א-ת]")


def offline_answer(question: str, hits: list[dict]) -> Iterator[str]:
    """No API key: answer with the best matching excerpts, clearly labelled."""
    he = bool(HEBREW.search(question))
    if not hits:
        yield ("לא מצאתי במאגרים קטע שעונה על השאלה. נסה לנסח אחרת או לציין את שם הפרויקט."
               if he else "I couldn't find anything in the repos that answers this. Try rephrasing or naming the project.")
        return
    head = ("**מצב לא מקוון** (אין מפתח API של Claude), אז הנה הקטעים הכי רלוונטיים שמצאתי:\n\n"
            if he else "**Offline mode** (no Claude API key), so here are the most relevant excerpts I found:\n\n")
    yield head
    for h in hits[:3]:
        lang = h["path"].rsplit(".", 1)[-1] if "." in h["path"] else ""
        lang = {"py": "python", "ts": "ts", "tsx": "tsx", "js": "js", "md": "markdown", "yml": "yaml"}.get(lang, lang)
        body = "\n".join(h["text"].split("\n")[:18])
        piece = f'**{h["repo"]} › {h["path"]}** (שורות \u2066{h["start"]}–{h["end"]}\u2069) [{h["n"]}]\n\n' if he else \
                f'**{h["repo"]} › {h["path"]}** (lines {h["start"]}–{h["end"]}) [{h["n"]}]\n\n'
        if h["kind"] in ("doc", "page", "overview", "facts", "symbol", "file", "upload"):
            piece += "> " + body.replace("\n", "\n> ") + "\n\n"
        else:
            piece += f"```{lang}\n{body}\n```\n\n"
        for i in range(0, len(piece), 60):  # stream it like a model would
            yield piece[i:i + 60]
            time.sleep(0.01)
    yield ("כדי לקבל תשובות מנוסחות, הגדר `GROQ_API_KEY` (חינם) או `ANTHROPIC_API_KEY` והפעל מחדש את השרת."
           if he else "Set `GROQ_API_KEY` (free) or `ANTHROPIC_API_KEY` and restart the server for written answers.")
