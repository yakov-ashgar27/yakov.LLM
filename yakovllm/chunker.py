"""Split source files into chunks that keep their file path and line numbers.

Every chunk remembers where it came from (repo, path, first and last line), so
an answer can cite "bomberman/ai.py lines 24-58" and link straight to GitHub.
"""
from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass

CODE_WINDOW = 60      # lines per code chunk
CODE_OVERLAP = 8      # lines repeated between neighbouring code chunks
MD_TARGET = 1500      # characters per markdown chunk (soft)
MD_MAX = 2400         # a section longer than this is split by paragraphs
HTML_WINDOW = 40

DEF_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:def|class|function|const|let|interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)")


@dataclass
class Chunk:
    id: str
    repo: str
    path: str
    start: int          # 1-based first line
    end: int            # 1-based last line
    title: str          # heading path for docs, first definition for code
    kind: str           # "doc" | "code" | "page" | "config"
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _kind_for(path: str) -> str:
    low = path.lower()
    if low.endswith((".md", ".txt", ".rst")):
        return "doc"
    if low.endswith((".html", ".htm")):
        return "page"
    if low.endswith((".yml", ".yaml", ".toml", ".json", ".ini", ".cfg", ".bat", ".sh")) or low.endswith("dockerfile") or "/dockerfile" in low:
        return "config"
    return "code"


def _strip_html(lines: list[str]) -> list[str]:
    """Visible text of an HTML page, one output line per input line."""
    joined = "\n".join(lines)
    # Drop script/style bodies but keep their newlines so line numbers stay true.
    joined = re.sub(r"(?is)<(script|style)\b.*?</\1>", lambda m: "\n" * m.group(0).count("\n"), joined)
    joined = re.sub(r"(?s)<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), joined)
    joined = re.sub(r"<[^>\n]*>", " ", joined)
    joined = html.unescape(joined)
    return [re.sub(r"\s+", " ", ln).strip() for ln in joined.split("\n")]


def _chunk_markdown(repo: str, path: str, lines: list[str]) -> list[Chunk]:
    sections: list[tuple[str, int, list[str]]] = []  # (heading path, start line, lines)
    stack: list[str] = []
    cur: list[str] = []
    cur_start = 1
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else HEADING_RE.match(line)
        if m:
            if any(s.strip() for s in cur):
                sections.append((" › ".join(stack), cur_start, cur))
            level = len(m.group(1))
            stack = stack[: level - 1] + [m.group(2).strip().strip("*")]
            cur, cur_start = [line], i
        else:
            cur.append(line)
    if any(s.strip() for s in cur):
        sections.append((" › ".join(stack), cur_start, cur))

    # Merge small neighbouring sections; split very long ones by paragraph.
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_start, buf_title = 1, ""

    def flush(end_line: int) -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        if text:
            chunks.append(Chunk("", repo, path, buf_start, end_line, buf_title or path, "doc", text))
        buf = []

    for title, start, sec in sections:
        sec_text = "\n".join(sec)
        if len(sec_text) > MD_MAX:
            if buf:
                flush(start - 1)
            # paragraph split, still tracking line numbers
            para: list[str] = []
            p_start = start
            for j, ln in enumerate(sec):
                para.append(ln)
                size = sum(len(x) + 1 for x in para)
                if (not ln.strip() and size >= MD_TARGET) or size >= MD_MAX:
                    buf, buf_start, buf_title = para, p_start, title
                    flush(start + j)
                    para, p_start = [], start + j + 1
            if para:
                buf, buf_start, buf_title = para, p_start, title
                flush(start + len(sec) - 1)
            continue
        if buf and sum(len(x) + 1 for x in buf) + len(sec_text) > MD_TARGET:
            flush(start - 1)
        if not buf:
            buf_start, buf_title = start, title
        buf.extend(sec)
    if buf:
        flush(len(lines))
    return chunks


def _windows(n: int, size: int, overlap: int, lines: list[str]) -> list[tuple[int, int]]:
    """0-based [start, end) windows; a window prefers to end on a blank line."""
    out = []
    start = 0
    while start < n:
        end = min(n, start + size)
        if end < n:
            for k in range(end, max(start + size // 2, end - 15), -1):
                if not lines[k - 1].strip():
                    end = k
                    break
        out.append((start, end))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out


def _chunk_lines(repo: str, path: str, lines: list[str], kind: str, view: list[str], size: int) -> list[Chunk]:
    chunks = []
    for s, e in _windows(len(lines), size, CODE_OVERLAP if kind == "code" else 4, lines):
        body = [ln for ln in view[s:e]]
        text = "\n".join(body).strip("\n")
        if kind == "page":
            text = "\n".join(ln for ln in body if ln)
        if len(text.strip()) < 40:
            continue
        title = path.rsplit("/", 1)[-1]
        for ln in lines[s:e]:
            m = DEF_RE.match(ln)
            if m:
                title = f"{title} › {m.group(1)}"
                break
        chunks.append(Chunk("", repo, path, s + 1, e, title, kind, text))
    return chunks


BIDI_RE = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def chunk_file(repo: str, path: str, content: str) -> list[Chunk]:
    content = BIDI_RE.sub("", content)
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kind = _kind_for(path)
    if kind == "doc" and path.lower().endswith(".md"):
        chunks = _chunk_markdown(repo, path, lines)
    elif kind == "page":
        chunks = _chunk_lines(repo, path, lines, kind, _strip_html(lines), HTML_WINDOW)
    else:
        chunks = _chunk_lines(repo, path, lines, kind, lines, CODE_WINDOW)
    for i, c in enumerate(chunks):
        c.id = f"{repo}:{path}:{c.start}-{c.end}"
    return chunks
