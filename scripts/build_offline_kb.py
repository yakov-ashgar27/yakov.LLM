"""Rebuild data/kb.json from local checkouts, with real GitHub push times.

Used where the GitHub API is unreachable (CI sandboxes). Normal use:
    python -m yakovllm.ingest --github yakov-ashgar27
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yakovllm import ingest  # noqa: E402
from yakovllm.sync import GitHubSync  # noqa: E402

src = Path(sys.argv[1])
meta = json.loads(Path(sys.argv[2]).read_text())  # [{"full_name","pushed_at","homepage",...}]
ingest.list_user_repos_meta = lambda user: [{"description": "", "homepage": "", "stars": 0, **m} for m in meta]
ingest.clone = lambda full: next(p for p in src.iterdir() if p.name.lower() == full.split("/")[1].lower())
GitHubSync(meta[0]["full_name"].split("/")[0], Path("data/kb.json")).check(force=True)
