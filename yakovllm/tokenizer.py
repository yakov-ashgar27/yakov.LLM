"""Bilingual (Hebrew + English) tokenizer that also understands code.

The same rules are implemented in web/engine.js, so search results in the
browser demo match the Python server exactly. Keep the two in sync: the test
suite checks a shared set of examples against both.

Rules, in order:
1. Unicode NFKC, lower-case, Hebrew niqqud and cantillation marks removed.
2. Tokens are runs of Latin letters/digits/underscore, or runs of Hebrew letters.
3. Code identifiers are split: ``findPathStep`` -> findpathstep, find, path, step;
   ``chase_range`` -> chase_range, chase, range.
4. Hebrew words also yield a variant without a one- or two-letter prefix
   (ו ה ב ל מ ש כ) and without a plural suffix (ים / ות), because Hebrew glues
   these onto the word: "והאויבים" -> והאויבים, האויבים, אויבים, ...
5. Stop words are dropped.
"""
from __future__ import annotations

import re
import unicodedata

TOKEN_RE = re.compile(r"[a-z0-9_]+|[א-ת]+")
NIQQUD_RE = re.compile(r"[֑-ׇ]")
CAMEL_RE = re.compile(r"[a-z]+|[0-9]+")

HE_PREFIX_1 = set("ובהלמשכ")
HE_PREFIX_2 = {"וה", "וב", "ול", "ומ", "וש", "שה", "שב", "של", "מה", "כש", "לה", "בה", "כה"}

STOPWORDS = {
    # English
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was",
    "be", "it", "its", "this", "that", "with", "as", "at", "by", "from", "if", "not",
    "do", "does", "how", "what", "which", "where", "when", "why", "who", "can", "you",
    "i", "me", "my", "we", "our", "your", "there", "into", "about", "so", "than",
    # Hebrew
    "של", "את", "על", "עם", "זה", "זו", "זאת", "הוא", "היא", "הם", "הן", "אני", "אתה",
    "מה", "איך", "למה", "מי", "איפה", "מתי", "יש", "אין", "כל", "גם", "רק", "או", "אם",
    "כי", "לא", "כן", "אבל", "אחרי", "לפני", "כמו", "בין", "עד", "שלי", "שלו", "שלה",
    "שלך", "אותו", "אותה", "הזה", "הזאת", "ה", "ו", "ב", "ל", "מ", "ש", "כ", "תסביר",
    "הסבר", "ספר", "תספר", "תגיד", "עובד", "עובדת", "בפרויקט", "פרויקט", "הפרויקט",
}

# Query-time expansion from Hebrew to the English words used in code and docs.
# A Hebrew question about English code ("how does the enemy chase the player")
# would otherwise share no words with the code it is about.
GLOSSARY = {
    "אויב": ["enemy", "enemies"], "אויבים": ["enemy", "enemies"],
    "שחקן": ["player"], "השחקן": ["player"],
    "פצצה": ["bomb"], "פצצות": ["bomb", "bombs"],
    "פיצוץ": ["explosion", "explode", "flame"], "פיצוצים": ["explosion", "chain"],
    "שרשרת": ["chain", "reaction"], "תגובת": ["reaction"],
    "רודף": ["chase", "bfs"], "רדיפה": ["chase", "bfs"], "מסלול": ["path"],
    "שלב": ["level"], "שלבים": ["level", "levels"],
    "ניקוד": ["score", "scoring"], "נקודות": ["score", "points"],
    "שיא": ["highscore", "highscores"], "שיאים": ["highscores"],
    "צליל": ["sound"], "צלילים": ["sound", "synth"], "מוזיקה": ["music"],
    "שפה": ["language", "i18n"], "תרגום": ["i18n", "translation"], "עברית": ["hebrew", "rtl"],
    "בדיקה": ["test"], "בדיקות": ["test", "tests", "pytest"],
    "מפה": ["map", "minimap"], "מינימפה": ["minimap"], "שקר": ["lie"], "שקרים": ["lie", "lies"],
    "מחולל": ["generator"], "יצירה": ["generate", "generator"], "פרוצדורלי": ["procedural"],
    "ערפל": ["fog"], "פנס": ["lantern"], "מלכודת": ["trap"], "מלכודות": ["trap", "traps"],
    "אוצר": ["treasure"], "יציאה": ["exit"], "זרע": ["seed", "rng"],
    "חזרה": ["rep"], "חזרות": ["rep", "reps", "repetition"], "ספירה": ["count", "counter"],
    "שלד": ["skeleton", "pose", "landmarks"], "תנוחה": ["pose"], "מצלמה": ["camera"],
    "זווית": ["angle"], "זוויות": ["angle", "angles"], "מפרק": ["joint"],
    "מאמן": ["trainer", "coach"], "מתאמן": ["trainee"], "אימון": ["workout", "session"],
    "תרגיל": ["exercise"], "תרגילים": ["exercise", "exercises"], "סקוואט": ["squat"],
    "דוח": ["report"], "דוחות": ["report", "reports"], "הרשאות": ["rbac", "role", "permission"],
    "תפקיד": ["role"], "התחברות": ["login", "auth"], "סיסמה": ["password", "argon2"],
    "משתמש": ["user"], "משתמשים": ["user", "users"], "מנהל": ["admin"],
    "מסד": ["database", "db"], "נתונים": ["data", "database"], "טבלאות": ["table", "tables"],
    "שרת": ["server", "api", "fastapi"], "לקוח": ["client"], "ממשק": ["ui", "interface"],
    "לא מקוון": ["offline"], "מקוון": ["offline", "sync"], "סנכרון": ["sync"], "ניתוק": ["offline"],
    "התקנה": ["install", "pwa"], "אפליקציה": ["app", "pwa"], "הרצה": ["run", "start"],
    "פריסה": ["deploy", "render"], "ענן": ["cloud", "render"], "דוקר": ["docker"],
    "ארכיטקטורה": ["architecture"], "דרישות": ["requirements", "srs"], "אפיון": ["srs", "spec"],
    "סיכונים": ["risk", "risks"], "תוכנית": ["plan"], "עבודה": ["work"],
    "שליטה": ["controls"], "מקשים": ["controls", "key"], "חיים": ["lives"], "זמן": ["timer", "time"],
    "בונוס": ["bonus", "power"], "שדרוג": ["powerup"], "שדרוגים": ["powerup", "powerups"],
    "קיר": ["wall"], "קירות": ["wall", "walls"], "לבנה": ["brick"], "לבנים": ["brick", "bricks"],
    "רשת": ["grid"], "אתר": ["portfolio", "site"], "תיק": ["portfolio"],
    "טכנולוגיות": ["stack", "technologies"], "כלים": ["tools", "stack"],
    "דיוק": ["accuracy"], "מטמון": ["cache", "redis"], "תור": ["queue", "rq"],
    "פרויקטים": ["projects", "project"], "יעקב": ["yakov"], "מריצים": ["run", "install", "setup", "start"],
    "להריץ": ["run", "install", "setup", "start"], "קשה": ["challenge", "challenges", "hard"],
    "אתגרים": ["challenges", "challenge"], "אתגר": ["challenge"], "חדש": ["new", "latest"],
    "ביותר": [], "מסמכים": ["documents", "docs"], "מסמך": ["document"], "אבטחה": ["security"],
    "אנומליות": ["anomaly", "anomalies"], "חריגות": ["anomaly", "anomalies"], "ניטור": ["monitoring"],
    "אינטרנט": ["offline", "network", "sync"], "רשת": ["network", "grid"],
    "ווירטואלי": ["coach", "virtual"], "הערות": ["feedback", "cue", "coach"], "הערה": ["feedback", "cue"],
    "טכניקה": ["technique", "form"], "רקע": ["background", "job", "worker"], "תזכורות": ["reminder", "reminders"],
    "משימות": ["job", "jobs", "task", "tasks"], "מיגרציה": ["migration", "alembic"], "מיגרציות": ["migration", "alembic"],
    "מימין": ["rtl", "bidi"], "לשמאל": ["rtl", "bidi"], "קול": ["sound", "speech"], "הקראה": ["speech", "tts"],
    # English synonyms: question words that differ from the words used in the code
    "migrations": ["alembic", "migration"], "background": ["job", "worker", "rq"],
    "hashed": ["argon2", "hash"], "hashing": ["argon2", "hash"], "shortest": ["bfs"],
}

REPO_ALIASES = {  # extra names people use; repo names and titles are added automatically (repo_aliases)
    "bomberman": ["bomberman", "בומברמן", "בומבמן", "pygame"],
    "fitvision-ai": ["fitvision", "פיטוויזן", "פיטויז'ן", "פיטוויז", "כושר", "mediapipe", "פרויקט הגמר"],
    "the-map-lies": ["map lies", "המפה משקרת", "מפה משקרת"],
    "yakov-ashgar27.github.io": ["portfolio", "פורטפוליו", "תיק עבודות", "github.io"],
    "yakov-ashgar27": ["profile readme", "פרופיל"],
    "yakov.llm": ["yakov.llm", "yakovllm", "יעקב llm"],
}
GENERIC_NAME_PARTS = {"the", "yakov", "ashgar", "app", "project", "web", "api", "ai", "tool", "system", "analytics",
                      "github", "io", "feature", "safe", "radar"}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = NIQQUD_RE.sub("", text)
    return text


def _split_identifier(raw: str) -> list[str]:
    """findPathStep / chase_range / HTTP2Server -> its lower-case parts."""
    parts: list[str] = []
    for piece in raw.split("_"):
        if not piece:
            continue
        # Boundaries: lower->Upper, letter<->digit, UPPER->Upper+lower (HTTPServer).
        piece = re.sub(r"([a-z])([A-Z])", r"\1 \2", piece)
        piece = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", piece)
        piece = re.sub(r"([A-Za-z])([0-9])|([0-9])([A-Za-z])", lambda m: " ".join(g for g in m.groups() if g), piece)
        parts.extend(p.lower() for p in piece.split() if p)
    return parts


def _hebrew_variants(word: str) -> list[str]:
    out = [word]
    stems = [word]
    if len(word) >= 5 and word[:2] in HE_PREFIX_2:
        stems.append(word[2:])
    if len(word) >= 4 and word[0] in HE_PREFIX_1:
        stems.append(word[1:])
    for s in stems[1:]:
        out.append(s)
    for s in stems:
        if len(s) >= 5 and (s.endswith("ים") or s.endswith("ות")):
            out.append(s[:-2])
    # keep order, drop duplicates
    seen: set[str] = set()
    return [w for w in out if not (w in seen or seen.add(w))]


def tokenize(text: str) -> list[str]:
    """Tokens for indexing and for queries. Duplicates are kept (they carry term frequency)."""
    text = _normalize(text)
    tokens: list[str] = []
    # Identifiers are split before lower-casing, so camelCase boundaries survive.
    for m in re.finditer(r"[A-Za-z0-9_]+|[א-ת]+", text):
        raw = m.group(0)
        if "א" <= raw[0] <= "ת":
            for w in _hebrew_variants(raw):
                if w not in STOPWORDS and len(w) > 1:
                    tokens.append(w)
            continue
        low = raw.lower()
        if low in STOPWORDS or len(low) < 2 or len(low) > 40:
            continue
        tokens.append(low)
        parts = _split_identifier(raw)
        if len(parts) > 1:
            tokens.extend(p for p in parts if len(p) > 1 and p not in STOPWORDS)
    return tokens


def expand_query(query: str) -> list[str]:
    """Query tokens plus English equivalents of Hebrew words (from GLOSSARY)."""
    norm = _normalize(query).lower()
    tokens = tokenize(query)
    extra: list[str] = []
    for he, en in GLOSSARY.items():
        if " " in he:
            if he in norm:
                extra.extend(en)
    for t in tokens:
        if t in GLOSSARY:
            extra.extend(GLOSSARY[t])
    return tokens + [e for e in extra if e not in tokens]


def squash(text: str) -> str:
    """Lower-case letters and digits only: "WiFi-Doctor" and "wifi doctor" both become "wifidoctor"."""
    return re.sub(r"[^a-z0-9\u05d0-\u05ea]", "", _normalize(text).lower())


def repo_aliases(repos: list[dict]) -> dict[str, list[str]]:
    """Names a question may use for each repo: its key, its title, the distinctive word in them,
    plus the hand-written REPO_ALIASES. Stored in kb.json so the browser engine uses the same list."""
    out: dict[str, list[str]] = {}
    for r in repos:
        key = r["key"]
        names = list(REPO_ALIASES.get(key, []))
        names.append(key)
        parts = [p for p in re.split(r"[-_.\s]+", key) if p]
        if parts and len(parts[0]) >= 4 and parts[0] not in GENERIC_NAME_PARTS:
            names.append(parts[0])
        title = re.sub(r"[^\w\s'.-]", " ", r.get("title") or "").strip()
        title = re.split(r"\s[—–:|·-]\s|:", title)[0].strip()
        if title and title.lower() not in ("profile readme", "portfolio website"):
            names.append(title)
            first = re.split(r"\s+", title)[0]
            if len(squash(first)) >= 5 and first.lower() not in GENERIC_NAME_PARTS:
                names.append(first)
        seen, uniq = set(), []
        for n in names:
            k = squash(n)
            if len(k) >= 3 and k not in seen:
                seen.add(k)
                uniq.append(n.lower())
        out[key] = uniq
    return out


def detect_repos(query: str, aliases: dict[str, list[str]] | None = None) -> list[str]:
    """Repos the question names explicitly ("in Bomberman, ...", "wifi doctor")."""
    q = squash(query)
    found = []
    for repo, names in (aliases if aliases is not None else REPO_ALIASES).items():
        if any(len(squash(a)) >= 3 and squash(a) in q for a in names):
            found.append(repo)
    return found
