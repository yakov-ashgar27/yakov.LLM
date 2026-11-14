"""Tokenizer, chunker and search: the parts the answers depend on."""
from yakovllm import tokenizer
from yakovllm.chunker import chunk_file
from yakovllm.search import Index, is_test_path


# ---------------------------------------------------------------- tokenizer
def test_identifiers_are_split():
    toks = tokenizer.tokenize("def findPathStep(chase_range): HTTPServer2")
    for t in ("findpathstep", "find", "path", "step", "chase_range", "chase", "range", "httpserver2", "http", "server"):
        assert t in toks
    assert "def" in toks


def test_hebrew_prefixes_and_plurals():
    toks = tokenizer.tokenize("והאויבים")
    assert "והאויבים" in toks and "האויבים" in toks and "אויבים" in toks
    assert "אויב" in tokenizer.tokenize("האויבים") or "האויב" in tokenizer.tokenize("האויבים")


def test_niqqud_and_stopwords_removed():
    assert tokenizer.tokenize("שָׁלוֹם")[0] == "שלום"   # niqqud gone (prefix-stripped variants may follow)
    assert tokenizer.tokenize("what is the") == []
    assert tokenizer.tokenize("מה זה של") == []


def test_glossary_expands_hebrew_to_code_words():
    terms = tokenizer.expand_query("איך האויב רודף אחרי השחקן")
    for t in ("enemy", "chase", "player"):
        assert t in terms


def test_detect_repos():
    assert tokenizer.detect_repos("איך עובד הניקוד בבומברמן?") == ["bomberman"]
    assert "the-map-lies" in tokenizer.detect_repos("what is The Map Lies?")


# ---------------------------------------------------------------- chunker
def test_markdown_chunks_keep_headings_and_lines():
    md = "# Title\nintro\n\n## Install\nrun it\n\n## Usage\n" + "word " * 600 + "\n"
    chunks = chunk_file("r", "README.md", md)
    assert chunks[0].start == 1 and chunks[0].title.startswith("Title")
    lines = md.split("\n")
    for c in chunks:
        assert c.kind == "doc"
        assert c.text.strip().split("\n")[0] in "\n".join(lines[c.start - 1:c.end])
    assert any("Usage" in c.title for c in chunks)


def test_code_chunks_match_source_lines():
    src = "\n".join(f"line_{i} = {i}" for i in range(1, 151))
    chunks = chunk_file("r", "pkg/mod.py", src)
    lines = src.split("\n")
    assert chunks[0].start == 1
    assert chunks[-1].end == 150
    for c in chunks:
        assert c.text == "\n".join(lines[c.start - 1:c.end])
        assert c.id == f"r:pkg/mod.py:{c.start}-{c.end}"


def test_code_chunk_title_is_first_definition():
    src = "import x\n\n\nclass Grid:\n    pass\n" + "\n".join(f"a{i} = 1" for i in range(30))
    assert chunk_file("r", "g.py", src)[0].title == "g.py › Grid"


def test_html_text_is_visible_text_only():
    html = "<html>\n<style>\n.a{color:red}\n</style>\n<body>\n<h1>Hello &amp; welcome</h1>\n<script>var x=1;</script>\n<p>" + "text " * 20 + "</p>\n</body></html>"
    c = chunk_file("r", "index.html", html)[0]
    assert "Hello & welcome" in c.text
    assert "color" not in c.text and "var x" not in c.text


def test_bidi_marks_are_removed():
    c = chunk_file("r", "notes.md", "# כותרת\n‫טקסט עם סימני כיוון‬ " + "מילה " * 20)[0]
    assert "‫" not in c.text and "‬" not in c.text


# ---------------------------------------------------------------- search
def _kb():
    def ch(repo, path, text, title="", kind="code"):
        return {"id": f"{repo}:{path}:1-5", "repo": repo, "path": path, "start": 1, "end": 5,
                "title": title or path, "kind": kind, "text": text}
    chunks = [
        ch("game", "game/ai.py", "def find_path_step(start, goal): breadth first search queue for the enemy chase"),
        ch("game", "tests/test_ai.py", "def test_find_path_step(): enemy chase breadth first search"),
        ch("game", "game/bombs.py", "explode bomb chain reaction flame"),
        ch("game", "game/bombs.py", "another bomb chunk with chain reaction and more chain"),
        ch("game", "game/bombs.py", "third bomb chunk chain reaction"),
        ch("fit", "client/engine.ts", "count reps with a state machine and hysteresis on joint angles"),
        ch("fit", "README.md", "FitVision counts reps from the camera", kind="doc"),
    ]
    tok = {"stopwords": [], "glossary": {}, "aliases": {}, "prefix1": "", "prefix2": []}
    return {"repos": [{"key": "game", "url": "https://github.com/u/game", "branch": "main"},
                      {"key": "fit", "url": "https://github.com/u/fit", "branch": "main"}],
            "chunks": chunks, "tokenizer": tok}


def test_bm25_ranks_the_implementation_first():
    ix = Index(_kb())
    hits = ix.search("how does the enemy chase work", k=3)
    assert hits[0].chunk["path"] == "game/ai.py"   # the test file is penalised


def test_tests_win_when_asked_for():
    ix = Index(_kb())
    assert ix.search("tests for enemy chase", k=1)[0].chunk["path"] == "tests/test_ai.py"


def test_repo_filter_and_per_file_cap():
    ix = Index(_kb())
    assert all(h.chunk["repo"] == "fit" for h in ix.search("reps chain", repo="fit"))
    bombs = [h for h in ix.search("bomb chain reaction", k=10) if h.chunk["path"] == "game/bombs.py"]
    assert len(bombs) == 2


def test_github_url_points_at_lines():
    ix = Index(_kb())
    assert ix.github_url(ix.chunks[0]) == "https://github.com/u/game/blob/main/game/ai.py#L1-L5"


def test_is_test_path():
    assert is_test_path("tests/test_x.py") and is_test_path("src/a.test.ts") and is_test_path("e2e/x.spec.ts")
    assert not is_test_path("src/attestation.py")
