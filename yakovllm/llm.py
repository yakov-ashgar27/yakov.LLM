"""Talking to Claude (streaming), plus an offline mode that needs no API key.

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
- Reply in the language of the user's latest message (Hebrew or English). Hebrew answers use natural, modern Hebrew; keep code, file names and identifiers in English.
- Base every factual claim about the projects on the numbered <source> excerpts in the user's message. Cite them inline as [1], [2] right after the claim. Never invent sources, file names, numbers or features.
- If the sources don't contain the answer, say so plainly, and suggest where in the repo it might be or what to ask instead. General programming knowledge is fine when clearly marked as general.
- Be concrete: name files and functions, quote short code snippets in fenced code blocks with a language tag, and explain why the code is built that way.
- Keep it tight: lead with the direct answer, then the details. Use short paragraphs, lists only for parallel items.
- When asked about Yakov himself (skills, experience, what he built), answer like a knowledgeable colleague, based on the projects."""

REWRITE_PROMPT = """You turn a chat question about a developer's GitHub projects into search keywords.
The code and most docs are in English; some docs are in Hebrew. Return ONLY a JSON array of 4-12 short \
keywords or identifiers likely to appear in the relevant files: English technical terms, probable function \
or file names, and the key Hebrew words. Resolve pronouns from the conversation."""


def model_name() -> str:
    return os.environ.get("YAKOV_MODEL", "claude-sonnet-5-5")


def fast_model_name() -> str:
    return os.environ.get("YAKOV_FAST_MODEL", "claude-haiku-5-5")


def has_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def format_sources(hits: list[dict]) -> str:
    parts = []
    for h in hits:
        parts.append(
            f'<source n="{h["n"]}" repo="{h["repo"]}" path="{h["path"]}" lines="{h["start"]}-{h["end"]}">\n'
            f'{h["text"]}\n</source>'
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
    context = format_sources(hits) if hits else "(no matching excerpts were found)"
    msgs[-1] = {"role": "user", "content": f"<sources>\n{context}\n</sources>\n\nQuestion: {last}"}
    return msgs


def project_list(repos: list[dict]) -> str:
    lines = []
    for r in repos:
        summary = (r.get("summary") or r.get("description") or "")[:220]
        lines.append(f'- {r["title"]} ({r["key"]}): {summary}')
    return "\n".join(lines)


class ClaudeError(RuntimeError):
    pass


def _post(payload: dict, stream: bool, timeout: float = 120):
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "anthropic-version": API_VERSION,
            **({"accept": "text/event-stream"} if stream else {}),
        },
        method="POST",
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:300]
        raise ClaudeError(f"Claude API {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise ClaudeError(f"Cannot reach the Claude API: {e.reason}") from None


def stream_claude(system: str, messages: list[dict], max_tokens: int = 1800) -> Iterator[str]:
    """Yield text deltas from a streaming Messages API call."""
    payload = {"model": model_name(), "max_tokens": max_tokens, "system": system,
               "messages": messages, "stream": True}
    with _post(payload, stream=True) as resp:
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
    if not has_key():
        return []
    convo = "\n".join(f'{m["role"]}: {str(m["content"])[:400]}' for m in history[-4:-1])
    payload = {"model": fast_model_name(), "max_tokens": 200, "system": REWRITE_PROMPT,
               "messages": [{"role": "user", "content": f"Conversation so far:\n{convo or '(none)'}\n\nQuestion: {question}"}]}
    try:
        with _post(payload, stream=False, timeout=15) as resp:
            data = json.load(resp)
        text = "".join(b.get("text", "") for b in data.get("content", []))
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
        if h["kind"] in ("doc", "page", "overview"):
            piece += "> " + body.replace("\n", "\n> ") + "\n\n"
        else:
            piece += f"```{lang}\n{body}\n```\n\n"
        for i in range(0, len(piece), 60):  # stream it like a model would
            yield piece[i:i + 60]
            time.sleep(0.01)
    yield ("כדי לקבל תשובות מנוסחות, הגדר `ANTHROPIC_API_KEY` והפעל מחדש את השרת."
           if he else "Set `ANTHROPIC_API_KEY` and restart the server for written answers.")
