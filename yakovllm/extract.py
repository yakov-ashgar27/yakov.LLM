"""Text out of files people attach: Word, PowerPoint, Excel, PDF, and anything plain text.

Word / PowerPoint / Excel files are zip archives of XML, read with the standard library.
PDF needs pypdf (installed in the Docker image); without it PDFs are refused with a clear message.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

MAX_TEXT = 400_000
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class ExtractError(ValueError):
    pass


def _docx(z: zipfile.ZipFile) -> str:
    root = ET.fromstring(z.read("word/document.xml"))
    out = []
    for p in root.iter(W + "p"):
        style = p.find(f"{W}pPr/{W}pStyle")
        text = "".join(t.text or "" for t in p.iter(W + "t"))
        if not text.strip():
            continue
        level = re.match(r"Heading(\d)", style.get(W + "val", "")) if style is not None else None
        out.append(("#" * int(level.group(1)) + " " if level else "") + text)
    for tbl in root.iter(W + "tbl"):
        for row in tbl.iter(W + "tr"):
            cells = ["".join(t.text or "" for t in c.iter(W + "t")).strip() for c in row.iter(W + "tc")]
            if any(cells):
                out.append(" | ".join(cells))
    return "\n".join(out)


def _pptx(z: zipfile.ZipFile) -> str:
    slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                    key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))
    out = []
    for i, name in enumerate(slides, 1):
        root = ET.fromstring(z.read(name))
        paras = ["".join(t.text or "" for t in p.iter(A + "t")) for p in root.iter(A + "p")]
        paras = [p for p in paras if p.strip()]
        notes = f"ppt/notesSlides/notesSlide{i}.xml"
        if notes in z.namelist():
            nroot = ET.fromstring(z.read(notes))
            n = " ".join(t.text or "" for t in nroot.iter(A + "t")).strip()
            if n and not n.isdigit():
                paras.append(f"(notes) {n}")
        out.append(f"## Slide {i}\n" + "\n".join(paras))
    return "\n\n".join(out)


def _xlsx(z: zipfile.ZipFile) -> str:
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(S + "t")) for si in root.iter(S + "si")]
    out = []
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    for name in sheets:
        root = ET.fromstring(z.read(name))
        out.append(f"## {name.rsplit('/', 1)[-1][:-4]}")
        for row in list(root.iter(S + "row"))[:2000]:
            vals = []
            for c in row.iter(S + "c"):
                v = c.find(S + "v")
                if c.get("t") == "s" and v is not None:
                    vals.append(shared[int(v.text)] if v.text and int(v.text) < len(shared) else "")
                elif c.get("t") == "inlineStr":
                    vals.append("".join(t.text or "" for t in c.iter(S + "t")))
                else:
                    vals.append(v.text if v is not None and v.text else "")
            if any(vals):
                out.append(" | ".join(vals))
    return "\n".join(out)


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ExtractError("PDF reading isn't installed on this server (pypdf).") from e
    reader = PdfReader(io.BytesIO(data))
    out = []
    for i, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - one bad page shouldn't lose the rest
            text = ""
        if text.strip():
            out.append(f"## Page {i}\n{text.strip()}")
    if not out:
        raise ExtractError("No text found in this PDF (it may be a scanned image).")
    return "\n\n".join(out)


def extract(name: str, data: bytes) -> str:
    low = name.lower()
    try:
        if low.endswith(".pdf") or data[:5] == b"%PDF-":
            text = _pdf(data)
        elif low.endswith((".docx", ".pptx", ".xlsx", ".docm", ".pptm", ".xlsm")):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                text = _docx(z) if "word/document.xml" in z.namelist() else \
                    _pptx(z) if any(n.startswith("ppt/slides/") for n in z.namelist()) else _xlsx(z)
        elif low.endswith((".doc", ".ppt", ".xls")):
            raise ExtractError("Old Office formats (.doc/.ppt/.xls) aren't supported: save as .docx/.pptx/.xlsx.")
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("cp1255", errors="replace")
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as e:
        raise ExtractError(f"Couldn't read {name}: the file looks damaged.") from e
    text = re.sub(r"[‎‏‪-‮⁦-⁩]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ExtractError(f"No text found in {name}.")
    return text[:MAX_TEXT]
