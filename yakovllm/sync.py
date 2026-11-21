"""Keep the knowledge base in step with a GitHub account.

Every SYNC_INTERVAL minutes (and whenever a webhook or the UI asks) we list the
user's public repositories and compare each repo's ``pushed_at`` time with the
one stored in kb.json:

* a new repo        -> cloned and indexed
* a repo with new commits -> pulled and re-indexed (only that repo)
* a deleted / archived repo -> dropped from the index

The new kb.json is written atomically and handed to ``on_update`` so the
running server swaps in the new index without a restart.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

from . import ingest


class GitHubSync:
    def __init__(self, user: str, kb_path: Path, interval_min: float = 30,
                 on_update: Callable[[dict], None] | None = None):
        self.user = user
        self.kb_path = Path(kb_path)
        self.interval = max(1.0, float(interval_min)) * 60
        self.on_update = on_update
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self.status: dict = {"user": user, "enabled": True, "interval_min": self.interval / 60,
                             "last_check": None, "last_change": None, "last_error": None,
                             "running": False, "last_result": None}

    # ------------------------------------------------------------------ core
    def _load(self) -> dict:
        if self.kb_path.exists():
            return json.loads(self.kb_path.read_text(encoding="utf-8"))
        return {"repos": [], "chunks": []}

    def check(self, force: bool = False) -> dict:
        """One sync pass. Returns {"added": [...], "updated": [...], "removed": [...]}."""
        if not self._lock.acquire(blocking=False):
            return {"busy": True}
        self.status["running"] = True
        try:
            listed = ingest.list_user_repos_meta(self.user)
            kb = self._load()
            if kb.get("version") != ingest.KB_VERSION:
                force = True  # the knowledge base format changed: rebuild every repo once
            repos = {r["key"]: r for r in kb["repos"]}
            chunks_by_repo: dict[str, list[dict]] = {}
            for c in kb["chunks"]:
                if c.get("path") != ingest.ACCOUNT_PATH:  # rebuilt by write_kb every time
                    chunks_by_repo.setdefault(c["repo"], []).append(c)

            result = {"added": [], "updated": [], "removed": []}
            seen = set()
            for m in listed:
                name = m["full_name"].split("/")[-1]
                key = name.lower()
                seen.add(key)
                old = repos.get(key)
                if old and not force and old.get("pushed_at") == m["pushed_at"]:
                    continue
                path = ingest.clone(m["full_name"])
                extra = {k: m[k] for k in ("pushed_at", "description", "homepage", "stars")}
                meta, cs = ingest.ingest_repo(path, name, extra)
                repos[key] = meta
                chunks_by_repo[key] = cs
                result["updated" if old else "added"].append(key)

            for key, r in list(repos.items()):
                if key not in seen and (r.get("owner", "").lower() == self.user.lower() or not r.get("owner")):
                    del repos[key]
                    chunks_by_repo.pop(key, None)
                    result["removed"].append(key)

            changed = any(result.values())
            if changed or not self.kb_path.exists():
                ordered = sorted(repos.values(), key=lambda r: r.get("pushed_at") or r.get("committed_at") or "", reverse=True)
                chunks = [c for r in ordered for c in chunks_by_repo.get(r["key"], [])]
                tmp = self.kb_path.with_suffix(".tmp")
                new_kb = ingest.write_kb(ordered, chunks, tmp, owner=self.user)
                tmp.replace(self.kb_path)
                self.status["last_change"] = time.time()
                if self.on_update:
                    self.on_update(new_kb)
            self.status.update(last_check=time.time(), last_error=None, last_result=result)
            ingest.log(f"sync {self.user}: {result}")
            return result
        except Exception as e:  # network down, rate limit, git error: keep serving the old index
            self.status.update(last_check=time.time(), last_error=f"{type(e).__name__}: {e}")
            ingest.log(f"sync failed: {e}")
            return {"error": str(e)}
        finally:
            self.status["running"] = False
            self._lock.release()

    # ------------------------------------------------------------ background
    def trigger(self) -> None:
        """Ask the background loop to sync now (webhook, UI button)."""
        self._wake.set()

    def start(self) -> threading.Thread:
        def loop() -> None:
            while True:
                self.check()
                self._wake.wait(self.interval)
                self._wake.clear()
        t = threading.Thread(target=loop, name="github-sync", daemon=True)
        t.start()
        return t
