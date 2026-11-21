"""Conversation memory: who talked with yakov.LLM, about what, and what they said.

Kept strictly apart from the knowledge base. Nothing a visitor writes ever becomes a "fact" about
the projects: it is stored as an unverified note, for Yakov to read and decide on later.

What it gives the model:
* the same device again (a random id the browser keeps): "you talked before on <date> about
  wifi-doctor; their last questions were ...; things they told you (unverified) ...";
* someone on another device who gives a name we have seen ("I'm Shmulik"): only that a person by
  that name talked before, when and about which projects, never what they said, because a name
  proves nothing.

Storage: a JSON file (MEMORY_PATH). A free host's disk is wiped on every deploy, so when
MEMORY_REPO (a *private* GitHub repo, "owner/name") and MEMORY_TOKEN are set the file is also
kept in that repo and loaded from it on start.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

MAX_QUESTIONS = 40       # per visitor
MAX_NOTES = 60           # per visitor
MAX_VISITORS = 5000
SAVE_DELAY = 5           # seconds: batch writes
GITHUB_DELAY = 60

NAME_STOP = {
    # Hebrew words that follow "אני" but are not names
    "רוצה", "לא", "צריך", "צריכה", "יכול", "יכולה", "מחפש", "מחפשת", "חושב", "חושבת", "יודע", "יודעת", "מבין",
    "מבינה", "מנסה", "שואל", "שואלת", "עובד", "עובדת", "רק", "גם", "פה", "כאן", "מגייס", "מגייסת", "מתכנת",
    "מתכנתת", "סטודנט", "סטודנטית", "מפתח", "מפתחת", "מעוניין", "מעוניינת", "אוהב", "אוהבת", "בא", "באה",
    "לומד", "לומדת", "חדש", "חדשה", "שוב", "עדיין", "כבר", "מאוד", "ממש", "בטוח", "בטוחה", "מצטער", "מצטערת",
    "זה", "זאת", "פשוט", "מנהל", "מנהלת", "ראש", "איש", "אשת", "מ", "על", "של", "את", "עם", "אחד", "אחת",
    # English
    "a", "an", "the", "not", "looking", "trying", "interested", "just", "here", "new", "from", "working",
    "asking", "curious", "sorry", "fine", "good", "ok", "okay", "back", "also", "still", "very", "really",
    "recruiter", "developer", "student", "engineer", "hiring", "glad", "happy", "going", "wondering",
}
HE_NAME = re.compile(r"(?:קוראים לי|שמי|השם שלי(?: הוא)?)\s+([א-ת][א-ת'׳\-]{1,14}(?:\s[א-ת][א-ת'׳\-]{1,14})?)")
HE_INTRO = re.compile(r"(?:(?:^|[,.!]\s*|(?:שלום|היי|הי|אהלן|בוקר טוב|ערב טוב)[,!.]?\s+)אני|(?:שלום|היי|הי|אהלן)[,!.]?\s+זה)\s+([א-ת][א-ת'׳\-]{1,14})")
EN_NAME = re.compile(r"(?i:my name is|name's|call me|i am|i'm|this is)\s+([A-Z][a-zA-Z'\-]{1,14}(?:\s[A-Z][a-zA-Z'\-]{1,14})?)")
QUESTION_START = re.compile(
    r"^\s*(?:מה|איך|למה|מדוע|איפה|היכן|מי|כמה|האם|מתי|איזה|איזו|אילו|תסביר|הסבר|ספר|תספר|תן|תני|הראה|תראה|"
    r"תפרט|תשווה|אפשר|יש|what|how|why|where|who|which|when|does|do|is|are|can|could|would|should|explain|"
    r"tell|show|list|give|describe|compare|summari[sz]e)\b", re.I)
CORRECTION = re.compile(r"לא נכון|טעית|טעות|בעצם|למעשה|תתקן|תיקון|זה לא|actually|wrong|incorrect|not true|mistake|correction", re.I)


def detect_name(text: str) -> str | None:
    for rx in (HE_NAME, HE_INTRO, EN_NAME):
        m = rx.search(text if rx is not EN_NAME else text.strip())
        if not m:
            continue
        name = m.group(1).strip(" '\"-")
        first = name.split()[0]
        if first.lower() in NAME_STOP or first in NAME_STOP:
            continue
        if rx is HE_INTRO:  # "אני X" only counts as a name when nothing follows but punctuation or a short tail
            tail = text[m.end():].strip()
            if tail and not re.match(r"^[,.!]|^(?:ו?אני|ו?רציתי|רוצה|מ|ואני)", tail):
                continue
        return name[:30]
    return None


def is_statement(text: str) -> bool:
    t = text.strip()
    if len(t.split()) < 3 or t.endswith("?") or "?" in t[-3:]:
        return False
    return bool(CORRECTION.search(t)) or not QUESTION_START.match(t)


def _norm(name: str) -> str:
    return re.sub(r"[^\wא-ת]", "", name).lower()


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


class GitHubFile:
    """One JSON file in a private GitHub repo, through the contents API."""

    def __init__(self, repo: str, token: str, path: str = "memory.json"):
        self.repo, self.token, self.path, self.sha = repo, token, path, None

    def _req(self, method: str, url: str, body: dict | None = None):
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers={
            "authorization": f"Bearer {self.token}", "accept": "application/vnd.github+json",
            "user-agent": "yakov.LLM", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")

    def load(self) -> dict | None:
        info = self._req("GET", f"https://api.github.com/repos/{self.repo}")
        if not info.get("private"):
            raise RuntimeError(f"{self.repo} is public: memory is only kept in a private repo")
        try:
            f = self._req("GET", f"https://api.github.com/repos/{self.repo}/contents/{self.path}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        self.sha = f.get("sha")
        return json.loads(base64.b64decode(f.get("content") or b"e30=").decode("utf-8"))

    def save(self, data: dict) -> None:
        body = {"message": "memory: update", "content": base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=1).encode()).decode()}
        if self.sha:
            body["sha"] = self.sha
        try:
            r = self._req("PUT", f"https://api.github.com/repos/{self.repo}/contents/{self.path}", body)
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise
            self.load()  # someone else wrote: take the new sha and retry once
            body["sha"] = self.sha
            r = self._req("PUT", f"https://api.github.com/repos/{self.repo}/contents/{self.path}", body)
        self.sha = (r.get("content") or {}).get("sha", self.sha)


class Memory:
    def __init__(self, path: str | Path | None = None, remote: GitHubFile | None = None):
        self.path = Path(path) if path else None
        self.remote = remote
        self.lock = threading.Lock()
        self.data = {"visitors": {}}
        self.status = {"remote": bool(remote), "loaded_from": None, "last_save": None, "error": None}
        self._timer = None
        self._remote_timer = None
        self.load()

    @classmethod
    def from_env(cls) -> "Memory":
        remote = None
        if os.environ.get("MEMORY_REPO") and os.environ.get("MEMORY_TOKEN"):
            remote = GitHubFile(os.environ["MEMORY_REPO"], os.environ["MEMORY_TOKEN"])
        return cls(os.environ.get("MEMORY_PATH", ".cache/memory.json"), remote)

    # ---------------------------------------------------------------- persistence
    def load(self) -> None:
        if self.remote:
            try:
                d = self.remote.load()
                if d:
                    self.data = d
                    self.status["loaded_from"] = "github"
                    return
            except Exception as e:  # noqa: BLE001
                self.status["error"] = f"load: {e}"
                self.remote = None if "public" in str(e) else self.remote
        if self.path and self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                self.status["loaded_from"] = "file"
            except ValueError:
                pass
        self.data.setdefault("visitors", {})

    def _schedule(self) -> None:
        if self._timer is None:
            self._timer = threading.Timer(SAVE_DELAY, self.flush)
            self._timer.daemon = True
            self._timer.start()
        if self.remote and self._remote_timer is None:
            self._remote_timer = threading.Timer(GITHUB_DELAY, self.flush_remote)
            self._remote_timer.daemon = True
            self._remote_timer.start()

    def flush(self) -> None:
        self._timer = None
        if not self.path:
            return
        with self.lock:
            text = json.dumps(self.data, ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.path)
        self.status["last_save"] = time.time()

    def flush_remote(self) -> None:
        self._remote_timer = None
        if not self.remote:
            return
        try:
            with self.lock:
                snapshot = json.loads(json.dumps(self.data))
            self.remote.save(snapshot)
            self.status["error"] = None
        except Exception as e:  # noqa: BLE001
            self.status["error"] = f"save: {e}"

    # ---------------------------------------------------------------- recording
    def record(self, visitor: str, chat: str, text: str, projects: list[str], now: float | None = None,
               given_name: str = "") -> dict:
        """Store one user message. Returns what was learned: {"name": ..., "note": bool}."""
        visitor = re.sub(r"[^\w\-]", "", visitor or "")[:64]
        if not visitor:
            return {}
        now = now or time.time()
        text = str(text).strip()[:2000]
        name = detect_name(text) or (given_name.strip()[:30] or None)
        note = is_statement(text) and not (name and len(text.split()) <= 5)  # "hi, I'm Dana" is not a claim
        with self.lock:
            vs = self.data["visitors"]
            v = vs.get(visitor)
            if v is None:
                if len(vs) >= MAX_VISITORS:  # forget the longest-unseen visitor
                    oldest = min(vs, key=lambda k: vs[k].get("last", 0))
                    vs.pop(oldest)
                v = vs[visitor] = {"first": now, "last": now, "names": [], "chats": [], "projects": {},
                                   "questions": [], "notes": []}
            v["last"] = now
            if chat and chat not in v["chats"]:
                v["chats"] = (v["chats"] + [chat])[-50:]
            for p in projects:
                v["projects"][p] = v["projects"].get(p, 0) + 1
            if name and _norm(name) not in [_norm(n) for n in v["names"]]:
                v["names"].append(name)
            v["questions"] = (v["questions"] + [{"t": now, "chat": chat, "text": text, "projects": projects}])[-MAX_QUESTIONS:]
            if note:
                v["notes"] = (v["notes"] + [{"t": now, "chat": chat, "text": text, "projects": projects,
                                             "correction": bool(CORRECTION.search(text)), "verified": False}])[-MAX_NOTES:]
        self._schedule()
        return {"name": name, "note": note}

    # ---------------------------------------------------------------- recall
    def context(self, visitor: str, chat: str, messages_text: str, project_titles: dict[str, str] | None = None) -> str:
        """What the model may know about whoever is talking, as a short block for the system prompt."""
        titles = project_titles or {}
        visitor = re.sub(r"[^\w\-]", "", visitor or "")[:64]
        name_now = None
        for line in messages_text.split("\n"):
            name_now = detect_name(line) or name_now
        with self.lock:
            v = self.data["visitors"].get(visitor)
            lines = []
            if v:
                earlier = [q for q in v["questions"] if q.get("chat") != chat]
                if earlier:
                    first = _day(v["first"])
                    chats = len({q.get("chat") for q in earlier})
                    projects = sorted(v["projects"], key=lambda p: -v["projects"][p])[:5]
                    lines.append(f"This visitor (same device) talked with you before: first on {first}, last on "
                                 f"{_day(earlier[-1]['t'])}, {chats} earlier conversation(s).")
                    if v["names"]:
                        lines.append(f"Names they gave: {', '.join(v['names'])} (not verified).")
                    if projects:
                        lines.append("Projects they asked about: " + ", ".join(titles.get(p, p) for p in projects) + ".")
                    lines.append("Their last questions before this conversation:")
                    lines += [f"- {q['text'][:160]}" for q in earlier[-5:]]
                    notes = [n for n in v["notes"] if n.get("chat") != chat][-5:]
                    if notes:
                        lines.append("Things they told you before (UNVERIFIED claims, not facts about the projects):")
                        lines += [f"- {n['text'][:200]}" for n in notes]
                elif v["names"]:
                    lines.append(f"This visitor said their name is {', '.join(v['names'])} (not verified).")
            if name_now and not (v and _norm(name_now) in [_norm(n) for n in v["names"]][:-1] and lines):
                others = [(k, o) for k, o in self.data["visitors"].items()
                          if k != visitor and _norm(name_now) in [_norm(n) for n in o.get("names", [])]]
                if others:
                    k, o = max(others, key=lambda kv: kv[1].get("last", 0))
                    projects = sorted(o["projects"], key=lambda p: -o["projects"][p])[:4]
                    lines.append(f"Someone who introduced themselves as \"{name_now}\" talked with you before, on "
                                 f"{_day(o['last'])}" + (f", about {', '.join(titles.get(p, p) for p in projects)}" if projects else "")
                                 + ". It may be the same person or not (a name proves nothing): you may say you "
                                 "remember a conversation with someone by that name, but never reveal what was said in it.")
        return "\n".join(lines)

    # ---------------------------------------------------------------- the visitor's own data
    def feedback(self, visitor: str, chat: str, vote: str, question: str, answer: str) -> bool:
        visitor = re.sub(r"[^\w\-]", "", visitor or "")[:64]
        if not visitor or vote not in ("up", "down"):
            return False
        with self.lock:
            v = self.data["visitors"].setdefault(visitor, {"first": time.time(), "last": time.time(), "names": [], "chats": [],
                                                           "projects": {}, "questions": [], "notes": []})
            v["feedback"] = (v.get("feedback", []) + [{"t": time.time(), "chat": chat[:64], "vote": vote,
                                                        "question": str(question)[:300], "answer": str(answer)[:600]}])[-50:]
        self._schedule()
        return True

    def mine(self, visitor: str) -> dict:
        """What yakov.LLM remembers about this visitor, for the "what do you remember about me?" screen."""
        visitor = re.sub(r"[^\w\-]", "", visitor or "")[:64]
        with self.lock:
            v = json.loads(json.dumps(self.data["visitors"].get(visitor) or {}))
        if not v:
            return {"known": False}
        return {"known": True, "names": v.get("names", []), "first": _day(v["first"]), "last": _day(v["last"]),
                "conversations": len(v.get("chats", [])), "projects": sorted(v.get("projects", {}), key=lambda p: -v["projects"][p]),
                "questions": [q["text"] for q in v.get("questions", [])][-10:], "notes": [n["text"] for n in v.get("notes", [])][-10:]}

    def forget(self, visitor: str) -> bool:
        visitor = re.sub(r"[^\w\-]", "", visitor or "")[:64]
        with self.lock:
            gone = self.data["visitors"].pop(visitor, None) is not None
        if gone:
            self._schedule()
        return gone

    # ---------------------------------------------------------------- admin
    def export(self) -> dict:
        with self.lock:
            vs = json.loads(json.dumps(self.data["visitors"]))
        people = []
        for k, v in sorted(vs.items(), key=lambda kv: -kv[1].get("last", 0)):
            people.append({"visitor": k, "names": v["names"], "first": _day(v["first"]), "last": _day(v["last"]),
                           "conversations": len(v["chats"]), "projects": v["projects"],
                           "notes": [{**n, "day": _day(n["t"])} for n in v["notes"]],
                           "feedback": [{**f, "day": _day(f["t"])} for f in v.get("feedback", [])],
                           "questions": [{**q, "day": _day(q["t"])} for q in v["questions"]]})
        return {"visitors": len(people), "notes": sum(len(p["notes"]) for p in people), "storage": self.status,
                "people": people}

    def stats(self) -> dict:
        with self.lock:
            vs = self.data["visitors"]
            return {"visitors": len(vs), "notes": sum(len(v["notes"]) for v in vs.values()),
                    "persistent": bool(self.remote), "error": self.status["error"]}
