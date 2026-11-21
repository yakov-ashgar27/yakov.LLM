"""Code facts: what every project, file, function and class is, extracted from the code itself.

The search over raw code finds the right lines when a question uses the code's own words.
These facts cover the questions people ask in their own words:

* a **symbol card** for every function, class, method, React component, API route and DB table:
  its signature, docstring, where it is (file and lines), what it calls and where it is used;
* a **file card** for every source file: its role (first docstring or comment), what it defines,
  what it imports, its size;
* **project facts**: dependencies, how to run it, tests, CI, API endpoints, database tables,
  environment variables and the folder structure.

Every card names its file and lines, so answers built on it still cite the real code.
Python is parsed with the ``ast`` module; JavaScript, TypeScript and Java with careful regexes.
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

PY_EXT = {".py", ".pyw"}
JS_EXT = {".js", ".mjs", ".jsx", ".ts", ".tsx"}
JAVA_EXT = {".java", ".kt"}
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "websocket", "api_route")
KIND_HE = {"function": "פונקציה", "method": "מתודה", "class": "מחלקה", "component": "קומפוננטה",
           "hook": "הוק", "interface": "ממשק", "type": "טיפוס", "route": "נקודת קצה (API)", "table": "טבלה"}
MAX_CARD = 1600


# ---------------------------------------------------------------- Python
def _doc_first(node) -> str:
    doc = ast.get_docstring(node) or ""
    return re.sub(r"\s+", " ", doc.strip().split("\n\n")[0])[:300]


def _sig(node) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:
        args = "..."
    ret = ""
    if getattr(node, "returns", None) is not None:
        try:
            ret = " -> " + ast.unparse(node.returns)
        except Exception:
            ret = ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({args}){ret}"[:220]


def _calls(node) -> list[str]:
    names = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name and not name.startswith("_") and name not in ("print", "len", "str", "int", "float", "list",
                                                                   "dict", "set", "range", "isinstance", "super"):
                names.append(name)
    return list(dict.fromkeys(names))[:12]


def python_symbols(path: str, text: str) -> tuple[list[dict], dict]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [], {}
    syms: list[dict] = []
    imports: list[str] = []
    tables: list[dict] = []

    def visit(node, owner: str | None) -> None:
        for n in getattr(node, "body", []):
            if isinstance(n, (ast.Import, ast.ImportFrom)) and owner is None:
                mod = n.module if isinstance(n, ast.ImportFrom) else ", ".join(a.name for a in n.names)
                if mod:
                    imports.append(mod)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                routes = []
                for d in n.decorator_list:
                    if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in HTTP_METHODS:
                        arg = d.args[0] if d.args else None
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            routes.append(f"{d.func.attr.upper()} {arg.value}")
                kind = "method" if owner else "function"
                syms.append({"name": n.name, "qual": f"{owner}.{n.name}" if owner else n.name, "kind": kind,
                             "start": n.lineno, "end": getattr(n, "end_lineno", n.lineno), "sig": _sig(n),
                             "doc": _doc_first(n), "calls": _calls(n), "owner": owner, "routes": routes})
                for r in routes:
                    syms.append({"name": r, "qual": r, "kind": "route", "start": n.lineno,
                                 "end": getattr(n, "end_lineno", n.lineno), "sig": f"{r}  ->  {n.name}()",
                                 "doc": _doc_first(n), "calls": [n.name], "owner": None, "routes": []})
            elif isinstance(n, ast.ClassDef):
                bases = []
                for b in n.bases:
                    try:
                        bases.append(ast.unparse(b))
                    except Exception:
                        pass
                fields = []
                table = None
                for item in n.body:
                    if isinstance(item, (ast.Assign, ast.AnnAssign)):
                        target = item.targets[0] if isinstance(item, ast.Assign) else item.target
                        if isinstance(target, ast.Name):
                            if target.id == "__tablename__" and isinstance(getattr(item, "value", None), ast.Constant):
                                table = item.value.value
                            elif not target.id.startswith("_"):
                                fields.append(target.id)
                syms.append({"name": n.name, "qual": n.name, "kind": "class", "start": n.lineno,
                             "end": getattr(n, "end_lineno", n.lineno),
                             "sig": f"class {n.name}({', '.join(bases)})" if bases else f"class {n.name}",
                             "doc": _doc_first(n), "calls": [], "owner": None, "routes": [],
                             "fields": fields[:20]})
                if table:
                    tables.append({"table": table, "model": n.name, "fields": fields[:25], "line": n.lineno})
                    syms.append({"name": table, "qual": f"table {table}", "kind": "table", "start": n.lineno,
                                 "end": getattr(n, "end_lineno", n.lineno), "sig": f"table {table} (model {n.name})",
                                 "doc": _doc_first(n), "calls": [], "owner": None, "routes": [], "fields": fields[:25]})
                visit(n, n.name)

    visit(tree, None)
    module_doc = re.sub(r"\s+", " ", (ast.get_docstring(tree) or "").strip().split("\n\n")[0])[:300]
    return syms, {"imports": list(dict.fromkeys(imports))[:20], "doc": module_doc, "tables": tables}


# ---------------------------------------------------------------- JavaScript / TypeScript
JS_PATTERNS = [
    ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Z_$][\w$]*)", re.M)),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*(\([^)]*\))?", re.M)),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]{1,80})?=\s*(?:async\s*)?(?:\(([^)]*)\)|[A-Za-z_$][\w$]*)\s*(?::[^=]{1,60})?=>", re.M)),
    ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Z][\w$]*)", re.M)),
    ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Z][\w$]*)\s*(?:<[^>]*>)?\s*=", re.M)),
]
JS_METHOD = re.compile(r"^\s{2,}(?:public\s+|private\s+|protected\s+|static\s+|async\s+)*([a-z_$][\w$]*)\s*\(([^)]*)\)\s*(?::[^{]{1,60})?\{", re.M)
JS_ROUTE = re.compile(r"""\b(?:app|router|api)\.(get|post|put|patch|delete)\(\s*['"`]([^'"`]+)['"`]""")
JS_FETCH = re.compile(r"""fetch\(\s*[`'"]([^`'"]*?/api/[^`'"]*)""")
JS_IMPORT = re.compile(r"""^\s*import\s+(?:[^'"]+\s+from\s+)?['"]([^'"]+)['"]""", re.M)
JS_COMMENT_DOC = re.compile(r"/\*\*?([\s\S]*?)\*/")
NOT_METHODS = {"if", "for", "while", "switch", "catch", "function", "return", "constructor"}


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _block_end(lines: list[str], start: int) -> int:
    """Rough end line of a block that starts at `start` (1-based): match braces, cap at 400 lines."""
    depth, seen = 0, False
    for i in range(start - 1, min(len(lines), start + 400)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
        if seen and depth <= 0:
            return i + 1
        if not seen and i > start + 2 and lines[i].rstrip().endswith(";"):
            return i + 1
    return min(len(lines), start + 40)


def _jsdoc_before(text: str, pos: int) -> str:
    before = text[max(0, pos - 600):pos]
    m = list(JS_COMMENT_DOC.finditer(before))
    if m and before[m[-1].end():].strip() in ("", "export"):
        doc = re.sub(r"^\s*\*\s?", "", m[-1].group(1), flags=re.M)
        return re.sub(r"\s+", " ", doc).strip()[:300]
    comment = re.findall(r"(?m)^\s*//\s?(.*)$", before.split("\n\n")[-1])
    return " ".join(comment).strip()[:300]


def js_symbols(path: str, text: str) -> tuple[list[dict], dict]:
    lines = text.split("\n")
    syms: list[dict] = []
    seen: set[tuple[str, int]] = set()
    is_tsx = path.endswith((".tsx", ".jsx"))
    for kind, rx in JS_PATTERNS:
        for m in rx.finditer(text):
            name = m.group(1)
            start = _line_of(text, m.start(1))
            if (name, start) in seen:
                continue
            seen.add((name, start))
            k = kind
            if kind == "function" and name[:1].isupper() and (is_tsx or "<" in "\n".join(lines[start - 1:start + 30])):
                k = "component"
            elif kind == "function" and re.match(r"use[A-Z]", name):
                k = "hook"
            end = _block_end(lines, start)
            sig = lines[start - 1].strip()[:200]
            body = "\n".join(lines[start - 1:end])
            calls = list(dict.fromkeys(c for c in re.findall(r"\b([a-zA-Z_$][\w$]{2,})\s*\(", body)[1:]
                                       if c not in NOT_METHODS and c != name))[:12]
            syms.append({"name": name, "qual": name, "kind": k, "start": start, "end": end, "sig": sig,
                         "doc": _jsdoc_before(text, m.start()), "calls": calls, "owner": None, "routes": []})
    # methods inside classes
    for cls in [s for s in syms if s["kind"] == "class"]:
        body = "\n".join(lines[cls["start"]:cls["end"]])
        for m in JS_METHOD.finditer(body):
            name = m.group(1)
            if name in NOT_METHODS:
                continue
            start = cls["start"] + _line_of(body, m.start(1))
            syms.append({"name": name, "qual": f"{cls['name']}.{name}", "kind": "method", "start": start,
                         "end": _block_end(lines, start), "sig": lines[start - 1].strip()[:200],
                         "doc": "", "calls": [], "owner": cls["name"], "routes": []})
    for m in JS_ROUTE.finditer(text):
        r = f"{m.group(1).upper()} {m.group(2)}"
        start = _line_of(text, m.start())
        syms.append({"name": r, "qual": r, "kind": "route", "start": start, "end": _block_end(lines, start),
                     "sig": lines[start - 1].strip()[:200], "doc": "", "calls": [], "owner": None, "routes": []})
    imports = list(dict.fromkeys(JS_IMPORT.findall(text)))[:20]
    head = re.match(r"\s*(?:/\*\*?([\s\S]*?)\*/|((?:\s*//.*\n)+))", text)
    doc = ""
    if head:
        doc = re.sub(r"(?m)^\s*(\*|//)\s?", "", head.group(1) or head.group(2) or "")
        doc = re.sub(r"\s+", " ", doc).strip()[:300]
    return syms, {"imports": imports, "doc": doc, "api_calls": list(dict.fromkeys(JS_FETCH.findall(text)))[:15]}


# ---------------------------------------------------------------- Java / Kotlin
JAVA_CLASS = re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|final\s+|abstract\s+)*(?:class|interface|enum|object)\s+([A-Z]\w*)", re.M)
JAVA_METHOD = re.compile(r"^\s+(?:@\w+\s+)*(?:public|private|protected|static|final|override|suspend|fun|\s)+[\w<>\[\],.? ]*?\b([a-z]\w*)\s*\(([^)]*)\)\s*(?::\s*[\w<>?]+\s*)?(?:throws [\w, .]+)?\s*\{", re.M)


def java_symbols(path: str, text: str) -> tuple[list[dict], dict]:
    lines = text.split("\n")
    syms = []
    for m in JAVA_CLASS.finditer(text):
        start = _line_of(text, m.start(1))
        syms.append({"name": m.group(1), "qual": m.group(1), "kind": "class", "start": start,
                     "end": _block_end(lines, start), "sig": lines[start - 1].strip()[:200],
                     "doc": _jsdoc_before(text, m.start()), "calls": [], "owner": None, "routes": []})
    owner = syms[0]["name"] if syms else None
    for m in JAVA_METHOD.finditer(text):
        if m.group(1) in NOT_METHODS:
            continue
        start = _line_of(text, m.start(1))
        syms.append({"name": m.group(1), "qual": f"{owner}.{m.group(1)}" if owner else m.group(1), "kind": "method",
                     "start": start, "end": _block_end(lines, start), "sig": lines[start - 1].strip()[:200],
                     "doc": _jsdoc_before(text, m.start()), "calls": [], "owner": owner, "routes": []})
    imports = re.findall(r"^\s*import\s+([\w.]+)", text, re.M)[:20]
    return syms, {"imports": imports, "doc": ""}


def symbols_for(path: str, text: str) -> tuple[list[dict], dict]:
    ext = Path(path).suffix.lower()
    if ext in PY_EXT:
        return python_symbols(path, text)
    if ext in JS_EXT and not path.endswith((".min.js", ".d.ts")):
        return js_symbols(path, text)
    if ext in JAVA_EXT:
        return java_symbols(path, text)
    return [], {}


# ---------------------------------------------------------------- project facts
def _read(p: Path, limit: int = 200_000) -> str:
    try:
        return p.read_text(encoding="utf-8")[:limit] if p.is_file() and p.stat().st_size <= limit else ""
    except (UnicodeDecodeError, OSError):
        return ""


def dependencies(root: Path, skip) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if not p.is_file() or skip(rel):
            continue
        name = p.name.lower()
        if name.startswith("requirements") and name.endswith(".txt"):
            pkgs = [re.split(r"[<>=!~\[; ]", ln.strip())[0] for ln in _read(p).splitlines()
                    if ln.strip() and not ln.strip().startswith(("#", "-"))]
            if pkgs:
                deps[rel] = pkgs[:60]
        elif name == "package.json":
            try:
                data = json.loads(_read(p))
            except ValueError:
                continue
            pkgs = list((data.get("dependencies") or {}).keys()) + [f"{d} (dev)" for d in (data.get("devDependencies") or {})]
            if pkgs:
                deps[rel] = pkgs[:60]
        elif name == "pyproject.toml":
            m = re.search(r"dependencies\s*=\s*\[([^\]]*)\]", _read(p))
            if m:
                pkgs = [re.split(r"[<>=!~\[; ]", x.strip(" '\"\n"))[0] for x in m.group(1).split(",") if x.strip(" '\"\n")]
                if pkgs:
                    deps[rel] = pkgs[:60]
        elif name in ("build.gradle", "build.gradle.kts"):
            pkgs = re.findall(r"implementation\s*\(?\s*['\"]([^'\"]+)['\"]", _read(p))
            if pkgs:
                deps[rel] = pkgs[:40]
    return deps


def run_instructions(root: Path, skip) -> list[str]:
    out = []
    for p in sorted(root.rglob("package.json")):
        rel = p.relative_to(root).as_posix()
        if skip(rel):
            continue
        try:
            scripts = json.loads(_read(p)).get("scripts") or {}
        except ValueError:
            continue
        for k, v in list(scripts.items())[:12]:
            out.append(f"{rel}: npm run {k}  ->  {v}"[:200])
    for p in sorted(list(root.rglob("Dockerfile*")) + list(root.rglob("docker-compose*.yml")) + list(root.rglob("compose*.yml"))):
        rel = p.relative_to(root).as_posix()
        if skip(rel):
            continue
        text = _read(p)
        cmd = re.findall(r"^(?:CMD|ENTRYPOINT)\s+(.+)$", text, re.M)
        services = re.findall(r"^  ([a-zA-Z0-9_-]+):\s*$", text, re.M) if "compose" in p.name else []
        out.append(f"{rel}" + (f": CMD {cmd[-1][:120]}" if cmd else "") + (f": services {', '.join(services[:10])}" if services else ""))
    for p in sorted(list(root.rglob("*.bat")) + list(root.rglob("*.sh")) + list(root.rglob("*.ps1")) + list(root.rglob("Makefile"))):
        rel = p.relative_to(root).as_posix()
        if not skip(rel):
            out.append(f"script: {rel}")
    return out[:40]


def tests_summary(files: dict[str, str]) -> dict:
    py = sum(len(re.findall(r"^\s*(?:async\s+)?def test_\w+", t, re.M)) for f, t in files.items() if f.endswith(".py"))
    js = sum(len(re.findall(r"^\s*(?:it|test)(?:\.each\([^)]*\))?\(\s*['\"`]", t, re.M))
             for f, t in files.items() if f.endswith((".ts", ".tsx", ".js", ".mjs")))
    java = sum(len(re.findall(r"@Test\b", t)) for f, t in files.items() if f.endswith((".java", ".kt")))
    test_files = [f for f in files if re.search(r"(^|/)(tests?|e2e|__tests__)/|test_[^/]+\.py$|\.(test|spec)\.[jt]sx?$", f)]
    frameworks = []
    blob = "\n".join(t[:3000] for f, t in files.items() if f in test_files)
    for name, rx in (("pytest", r"\bpytest\b|def test_"), ("Vitest", r"from ['\"]vitest"), ("Jest", r"\bjest\b"),
                     ("Playwright", r"@playwright/test"), ("unittest", r"\bunittest\b"), ("JUnit", r"org\.junit")):
        if re.search(rx, blob):
            frameworks.append(name)
    return {"python_tests": py, "js_tests": js, "java_tests": java, "files": len(test_files), "frameworks": frameworks}


def ci_summary(root: Path) -> list[str]:
    out = []
    for p in sorted((root / ".github" / "workflows").glob("*.y*ml")) if (root / ".github" / "workflows").exists() else []:
        text = _read(p)
        name = re.search(r"^name:\s*(.+)$", text, re.M)
        jobs = re.findall(r"^  ([a-zA-Z0-9_-]+):\s*$", text.split("jobs:", 1)[-1], re.M) if "jobs:" in text else []
        on = re.search(r"^on:\s*(.*)$", text, re.M)
        out.append(f"{p.name}: {name.group(1).strip() if name else ''} (jobs: {', '.join(jobs[:8])})"
                   + (f" on {on.group(1).strip()}" if on and on.group(1).strip() else ""))
    return out


def env_vars(root: Path, files: dict[str, str], skip) -> list[str]:
    names: list[str] = []
    for p in sorted(root.rglob(".env*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not skip(rel) and "example" in p.name or p.name == ".env.sample":
            names += re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]{2,})\s*=", _read(p), re.M)
    for f, t in files.items():
        names += re.findall(r"os\.(?:environ\.get|getenv|environ\[)\(?\s*['\"]([A-Z][A-Z0-9_]{2,})['\"]", t)
        names += re.findall(r"import\.meta\.env\.([A-Z][A-Z0-9_]{2,})", t)
        names += re.findall(r"process\.env\.([A-Z][A-Z0-9_]{2,})", t)
    return list(dict.fromkeys(names))[:60]


def sql_tables(files: dict[str, str]) -> list[str]:
    out = []
    for f, t in files.items():
        for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?(\w+)", t, re.I):
            out.append(f"{m.group(1)} ({f})")
        for m in re.finditer(r"op\.create_table\(\s*['\"](\w+)['\"]", t):
            out.append(f"{m.group(1)} ({f})")
    return list(dict.fromkeys(out))[:60]


def structure(paths: list[str]) -> list[str]:
    top = Counter()
    second = Counter()
    for p in paths:
        parts = p.split("/")
        top[parts[0] + ("/" if len(parts) > 1 else "")] += 1
        if len(parts) > 2:
            second[f"{parts[0]}/{parts[1]}/"] += 1
    lines = [f"{k} ({v} files)" for k, v in sorted(top.items())]
    lines += [f"  {k} ({v} files)" for k, v in sorted(second.items()) if v >= 2][:40]
    return lines[:70]


# ---------------------------------------------------------------- cards
def _ident_words(name: str) -> str:
    """find_path_step / findPathStep -> 'find path step' so natural-language questions match."""
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", name).replace("_", " ").replace(".", " ")
    return re.sub(r"\s+", " ", words).strip().lower()


def build(repo_key: str, title: str, root: Path, files: dict[str, str], skip) -> tuple[list[dict], dict]:
    """Fact chunks for one repo, plus a summary dict for the repo's metadata."""
    per_file: dict[str, tuple[list[dict], dict]] = {}
    for rel, text in files.items():
        syms, info = symbols_for(rel, text)
        if syms or info:
            per_file[rel] = (syms, info)

    # where each name is used (word match in other files), for "who calls X?" questions
    names = {s["name"] for syms, _ in per_file.values() for s in syms
             if s["kind"] not in ("route", "table") and len(s["name"]) >= 4}
    used: dict[str, list[str]] = defaultdict(list)
    word = re.compile(r"[A-Za-z_$][\w$]*")
    for rel, text in files.items():
        for w in set(word.findall(text)) & names:
            used[w].append(rel)

    chunks: list[dict] = []
    counts = Counter()
    routes, tables_py = [], []
    for rel, (syms, info) in per_file.items():
        n_lines = files[rel].count("\n") + 1
        defined = [s for s in syms if s["kind"] != "method"]
        # file card
        text = [f"File {rel} in {title} ({n_lines} lines). קובץ {Path(rel).name} בפרויקט {title}."]
        if info.get("doc"):
            text.append(f"Purpose: {info['doc']}")
        if defined:
            text.append("Defines: " + ", ".join(f"{s['kind']} {s['qual']} (line {s['start']})" for s in defined[:30]))
        if info.get("imports"):
            text.append("Imports: " + ", ".join(info["imports"]))
        if info.get("api_calls"):
            text.append("Calls the API: " + ", ".join(info["api_calls"]))
        chunks.append({"id": f"{repo_key}:{rel}#file", "repo": repo_key, "path": rel, "start": 1, "end": n_lines,
                       "title": f"{Path(rel).name} › file card", "kind": "file", "text": "\n".join(text)[:MAX_CARD]})
        # symbol cards
        for s in syms:
            counts[s["kind"]] += 1
            if s["kind"] == "route":
                routes.append(f"{s['name']} ({rel}:{s['start']})")
            if s["kind"] == "table":
                tables_py.append(f"{s['name']} ({rel}:{s['start']})")
            elsewhere = [u for u in used.get(s["name"], []) if u != rel][:8]
            body = [f"{s['kind']} {s['qual']} — {rel} lines {s['start']}–{s['end']} ({title}).",
                    f"{KIND_HE.get(s['kind'], s['kind'])} {s['qual']} ({_ident_words(s['name'])}) בקובץ {Path(rel).name} בפרויקט {title}.",
                    f"Signature: {s['sig']}"]
            if s.get("doc"):
                body.append(f"Description: {s['doc']}")
            if s.get("owner"):
                body.append(f"Inside class: {s['owner']}")
            if s.get("fields"):
                body.append("Fields: " + ", ".join(s["fields"]))
            if s.get("routes"):
                body.append("Serves: " + ", ".join(s["routes"]))
            if s.get("calls"):
                body.append("Calls: " + ", ".join(s["calls"]))
            if elsewhere:
                body.append("Used in: " + ", ".join(elsewhere))
            chunks.append({"id": f"{repo_key}:{rel}#{s['kind']}:{s['qual']}:{s['start']}", "repo": repo_key, "path": rel,
                           "start": s["start"], "end": s["end"], "title": f"{Path(rel).name} › {s['qual']}",
                           "kind": "symbol", "text": "\n".join(body)[:MAX_CARD]})

    # project facts, split into a few cards so each stays focused
    paths = list(files)
    deps = dependencies(root, skip)
    tests = tests_summary(files)
    sections = []
    sections.append(("Overview of the code / סקירת הקוד",
                     [f"{len(paths)} files read. Symbols: " + ", ".join(f"{v} {k}s" for k, v in counts.most_common()),
                      "Folder structure / מבנה תיקיות:"] + structure(paths)))
    if deps:
        sections.append(("Dependencies and libraries / תלויות וספריות",
                         [f"{f}: {', '.join(p)}" for f, p in deps.items()]))
    run = run_instructions(root, skip)
    if run:
        sections.append(("How to run, build and deploy / איך מריצים, בונים ופורסים", run))
    total_tests = tests["python_tests"] + tests["js_tests"] + tests["java_tests"]
    ci = ci_summary(root)
    sections.append(("Tests and CI / בדיקות ו-CI",
                     [f"About {total_tests} automated test cases ({tests['python_tests']} Python, {tests['js_tests']} JS/TS, "
                      f"{tests['java_tests']} Java) in {tests['files']} test files. Frameworks: {', '.join(tests['frameworks']) or 'none found'}."]
                     + ([f"CI workflows: {c}" for c in ci] or ["No GitHub Actions workflows."])))
    if routes:
        sections.append(("API endpoints / נקודות קצה של ה-API", routes[:80]))
    tables = tables_py + sql_tables(files)
    if tables:
        sections.append(("Database tables / טבלאות במסד הנתונים", list(dict.fromkeys(tables))[:80]))
    envs = env_vars(root, files, skip)
    if envs:
        sections.append(("Configuration and environment variables / הגדרות ומשתני סביבה", [", ".join(envs)]))
    for i, (head, lines) in enumerate(sections):
        text = f"{title} — {head}\n" + "\n".join(lines)
        chunks.append({"id": f"{repo_key}:(project facts):{i + 1}", "repo": repo_key, "path": "(project facts)",
                       "start": i + 1, "end": i + 1, "title": f"{title} › {head.split(' / ')[0]}", "kind": "facts",
                       "text": text[:3000]})
    summary = {"symbols": dict(counts), "tests": total_tests, "test_frameworks": tests["frameworks"],
               "endpoints": len(routes), "tables": len(tables), "dependencies": sum(len(v) for v in deps.values())}
    return chunks, summary
