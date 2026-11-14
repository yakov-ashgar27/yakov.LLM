"""Build the static demo: ONE self-contained HTML file with the knowledge base inside.

    python scripts/build_demo.py            # -> dist/index.html (+ dist/kb.json)
    python scripts/build_demo.py --embedded # no live refresh from GitHub (for sandboxed hosts)

The demo needs no server. Search runs in the browser (web/engine.js); answers
come from Claude when the page is opened inside Claude, otherwise the page shows
the best matching excerpts. GitHub Pages serves this file (see .github/workflows).
"""
import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DIST = ROOT / "dist"


def main() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    kb = (ROOT / "data" / "kb.json").read_text(encoding="utf-8")
    json.loads(kb)  # fail early on a broken file

    def inline_css(m):
        return "<style>\n" + (WEB / m.group(1)).read_text(encoding="utf-8") + "\n</style>"

    def inline_js(m):
        return "<script>\n" + (WEB / m.group(1)).read_text(encoding="utf-8").replace("</script", "<\\/script") + "\n</script>"

    html = re.sub(r'<link rel="stylesheet" href="([\w.]+)">', inline_css, html)
    html = re.sub(r'<script src="([\w.]+)"></script>', inline_js, html)
    icon = base64.b64encode((WEB / "icon.svg").read_bytes()).decode()
    html = html.replace('href="icon.svg"', f'href="data:image/svg+xml;base64,{icon}"')
    html = html.replace('<link rel="manifest" href="manifest.webmanifest">\n', "")
    if "--embedded" in sys.argv:
        html = re.sub(r"kbUrl: '[^']*'", "kbUrl: ''", html)
    kb_script = "<script>window.YAKOV_KB = " + kb.replace("</", "<\\/") + ";</script>\n"
    html = html.replace("</head>", kb_script + "</head>", 1)

    DIST.mkdir(exist_ok=True)
    (DIST / "index.html").write_text(html, encoding="utf-8")
    (DIST / "kb.json").write_text(kb, encoding="utf-8")
    print(f"dist/index.html · {len(html.encode()) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
