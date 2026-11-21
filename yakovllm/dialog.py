"""Small conversation rules that a weak model gets wrong on its own.

* reply_language: answer in the language of the user's latest message ("Yes" -> English,
  "כן" -> Hebrew); a message with no letters ("2") keeps the language of the one before.
* resolve_choice: when the previous answer offered numbered options and the user replies with
  just a number ("2", "option 2", "אפשרות 2", "the second one"), that reply means the option's text.
web/app.js has the same rules for the in-browser mode.
"""
from __future__ import annotations

import re

HEBREW = re.compile(r"[א-ת]")
LATIN = re.compile(r"[A-Za-z]")
ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": -1,
    "ראשון": 1, "הראשון": 1, "ראשונה": 1, "הראשונה": 1, "שני": 2, "השני": 2, "שנייה": 2, "השנייה": 2, "שניה": 2,
    "השניה": 2, "שלישי": 3, "השלישי": 3, "שלישית": 3, "השלישית": 3, "רביעי": 4, "הרביעי": 4, "רביעית": 4,
    "הרביעית": 4, "אחרון": -1, "האחרון": -1, "האחרונה": -1,
    "אחת": 1, "אחד": 1, "שתיים": 2, "שתים": 2, "שלוש": 3, "ארבע": 4, "one": 1, "two": 2, "three": 3, "four": 4,
}
PICK = re.compile(
    r"^\s*(?:the\s+)?(?:(?:option|choice|number|no\.?|#|אפשרות|מספר|סעיף|את|ה|בחרתי(?: ב)?|i choose|i pick|let'?s go with|go with)\s*)?"
    r"([0-9]{1,2}|[א-תa-z']+)(?:\s*(?:one|please|בבקשה|תודה|אחד|אחת))?\s*[.!)]?\s*$", re.I)
LIST_ITEM = re.compile(r"^\s*(?:[-*]\s*)?(\d{1,2})[.)]\s+(.+)$")


def reply_language(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        text = str(m.get("content", ""))
        he, en = len(HEBREW.findall(text)), len(LATIN.findall(text))
        if he >= 2:  # Hebrew writers mix in English terms ("ה-API של guardstream"); English writers don't mix in Hebrew
            return "Hebrew"
        if en:
            return "English"
    return "Hebrew"


def numbered_options(text: str) -> list[str]:
    """The last numbered list in a message: ["Joint angles in real time — how ...", ...]."""
    groups: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for line in str(text).split("\n"):
        m = LIST_ITEM.match(line)
        if m:
            n = int(m.group(1))
            if current and n != current[-1][0] + 1:
                groups.append(current)
                current = []
            current.append((n, m.group(2)))
        elif line.strip() and current and not line.startswith((" ", "\t")):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    groups = [g for g in groups if len(g) >= 2 and g[0][0] == 1]
    if not groups:
        return []
    return [re.sub(r"\*\*|__|`|\[\d+\]", "", t).strip() for _, t in groups[-1]]


def resolve_choice(messages: list[dict]) -> tuple[int, str] | None:
    """(option number, option text) when the latest user message just picks a numbered option."""
    if len(messages) < 2 or messages[-1].get("role") != "user":
        return None
    prev = next((m for m in reversed(messages[:-1]) if m.get("role") == "assistant" and m.get("content")), None)
    if not prev:
        return None
    m = PICK.match(str(messages[-1].get("content", "")))
    if not m:
        return None
    word = m.group(1).lower()
    n = int(word) if word.isdigit() else ORDINALS.get(word)
    if n is None:
        return None
    options = numbered_options(prev["content"])
    if not options:
        return None
    if n == -1:
        n = len(options)
    if not 1 <= n <= len(options):
        return None
    return n, options[n - 1]
