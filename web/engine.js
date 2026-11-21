/* yakov.LLM search engine for the browser: the same tokenizer and BM25 as
 * yakovllm/tokenizer.py and yakovllm/search.py, line for line, so the static
 * demo returns exactly the results the Python server returns.
 * tests/test_parity.py runs both on the evaluation questions and compares. */
(function (root) {
  'use strict';

  const K1 = 1.2, B = 0.75, META_WEIGHT = 3, REPO_BOOST = 3.0, CONTEXT_BOOST = 1.8, README_BOOST = 1.15;
  const TEST_PENALTY = 0.8, MAX_PER_FILE = 2;
  const TEST_WORDS = new Set(['test', 'tests', 'pytest', 'vitest', 'בדיקה', 'בדיקות', 'e2e', 'playwright']);

  function makeTokenizer(cfg) {
    const STOP = new Set(cfg.stopwords);
    const P1 = new Set(cfg.prefix1.split(''));
    const P2 = new Set(cfg.prefix2);
    const GLOSSARY = cfg.glossary;
    const ALIASES = cfg.aliases;

    const normalize = (t) => t.normalize('NFKC').replace(/[֑-ׇ]/g, '');
    const isHebrew = (ch) => ch >= 'א' && ch <= 'ת';

    function splitIdentifier(raw) {
      const parts = [];
      for (let piece of raw.split('_')) {
        if (!piece) continue;
        piece = piece.replace(/([a-z])([A-Z])/g, '$1 $2');
        piece = piece.replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2');
        piece = piece.replace(/([A-Za-z])([0-9])|([0-9])([A-Za-z])/g,
          (m, a, b, c, d) => [a, b, c, d].filter(Boolean).join(' '));
        for (const p of piece.split(/\s+/)) if (p) parts.push(p.toLowerCase());
      }
      return parts;
    }

    function hebrewVariants(word) {
      const out = [word];
      const stems = [word];
      if (word.length >= 5 && P2.has(word.slice(0, 2))) stems.push(word.slice(2));
      if (word.length >= 4 && P1.has(word[0])) stems.push(word.slice(1));
      for (const s of stems.slice(1)) out.push(s);
      for (const s of stems) {
        if (s.length >= 5 && (s.endsWith('ים') || s.endsWith('ות'))) out.push(s.slice(0, -2));
      }
      return [...new Set(out)];
    }

    function tokenize(text) {
      text = normalize(text);
      const tokens = [];
      const re = /[A-Za-z0-9_]+|[א-ת]+/g;
      let m;
      while ((m = re.exec(text))) {
        const raw = m[0];
        if (isHebrew(raw[0])) {
          for (const w of hebrewVariants(raw)) if (!STOP.has(w) && w.length > 1) tokens.push(w);
          continue;
        }
        const low = raw.toLowerCase();
        if (STOP.has(low) || low.length < 2 || low.length > 40) continue;
        tokens.push(low);
        const parts = splitIdentifier(raw);
        if (parts.length > 1) for (const p of parts) if (p.length > 1 && !STOP.has(p)) tokens.push(p);
      }
      return tokens;
    }

    function expandQuery(query) {
      const norm = normalize(query).toLowerCase();
      const tokens = tokenize(query);
      const extra = [];
      for (const he of Object.keys(GLOSSARY)) if (he.includes(' ') && norm.includes(he)) extra.push(...GLOSSARY[he]);
      for (const t of tokens) if (Object.prototype.hasOwnProperty.call(GLOSSARY, t)) extra.push(...GLOSSARY[t]);
      const have = new Set(tokens);
      return tokens.concat(extra.filter((e) => !have.has(e)));
    }

    const squash = (t) => normalize(t).toLowerCase().replace(/[^a-z0-9\u05d0-\u05ea]/g, '');

    function detectRepos(query) {
      const q = squash(query);
      return Object.keys(ALIASES).filter((r) => ALIASES[r].some((a) => squash(a).length >= 3 && q.includes(squash(a))));
    }

    return { tokenize, expandQuery, detectRepos };
  }

  function isTestPath(path) {
    const p = path.toLowerCase();
    const name = p.split('/').pop();
    return p.startsWith('tests/') || p.startsWith('test/') || p.startsWith('e2e/') || p.includes('/tests/') ||
      p.includes('/e2e/') || name.startsWith('test_') || name.includes('.test.') || name.includes('.spec.');
  }

  class Index {
    constructor(kb) {
      this.kb = kb;
      this.tok = makeTokenizer(kb.tokenizer);
      this.repos = Object.fromEntries(kb.repos.map((r) => [r.key, r]));
      this.chunks = kb.chunks;
      this.postings = new Map();
      this.lengths = [];
      this.chunks.forEach((c, i) => {
        const counts = new Map();
        for (const t of this.tok.tokenize(c.text)) counts.set(t, (counts.get(t) || 0) + 1);
        const meta = `${c.repo} ${c.path.split('/').join(' ').split('.').join(' ')} ${c.title}`;
        for (const t of this.tok.tokenize(meta)) counts.set(t, (counts.get(t) || 0) + META_WEIGHT);
        let len = 0;
        for (const [t, tf] of counts) {
          len += tf;
          let pl = this.postings.get(t);
          if (!pl) this.postings.set(t, (pl = []));
          pl.push([i, tf]);
        }
        this.lengths.push(len);
      });
      this.byId = new Map(this.chunks.map((c) => [c.id, c]));
      this.n = this.chunks.length;
      this.avgLen = this.n ? this.lengths.reduce((a, b) => a + b, 0) / this.n : 1;
    }

    idf(term) {
      const df = (this.postings.get(term) || []).length;
      return Math.log(1 + (this.n - df + 0.5) / (df + 0.5));
    }

    search(query, { k = 6, repo = null, expand = true, extraTerms = null, contextRepos = null } = {}) {
      const terms = expand ? this.tok.expandQuery(query) : this.tok.tokenize(query);
      if (extraTerms) for (const t of extraTerms) terms.push(...this.tok.tokenize(t));
      const q = new Map();
      for (const t of terms) q.set(t, (q.get(t) || 0) + 1);
      const focus = new Set(repo ? [] : this.tok.detectRepos(query));
      const context = new Set(repo || focus.size ? [] : (contextRepos || []));
      const wantsTests = terms.some((t) => TEST_WORDS.has(t));
      const scores = new Map();
      const matched = new Map();
      for (const [term, qtf] of q) {
        const pl = this.postings.get(term);
        if (!pl) continue;
        const w = this.idf(term) * (1 + 0.3 * (qtf - 1));
        for (const [i, tf] of pl) {
          const dl = this.lengths[i];
          scores.set(i, (scores.get(i) || 0) + w * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / this.avgLen)));
          if (!matched.has(i)) matched.set(i, []);
          matched.get(i).push(term);
        }
      }
      const ranked = [];
      for (let [i, s] of scores) {
        const c = this.chunks[i];
        if (repo && c.repo !== repo) continue;
        if (focus.has(c.repo)) s *= REPO_BOOST;
        else if (context.has(c.repo)) s *= CONTEXT_BOOST;
        if (c.path.toLowerCase().endsWith('readme.md')) s *= README_BOOST;
        if (!wantsTests && isTestPath(c.path)) s *= TEST_PENALTY;
        ranked.push([s, i]);
      }
      ranked.sort((a, b) => (b[0] - a[0]) || (b[1] - a[1]));
      const out = [];
      const perFile = new Map();
      for (const [s, i] of ranked) {
        const c = this.chunks[i];
        const key = c.repo + '\u0000' + c.path;
        const n = perFile.get(key) || 0;
        if (n >= MAX_PER_FILE) continue;
        perFile.set(key, n + 1);
        out.push({ chunk: c, score: s, terms: [...new Set(matched.get(i))].sort() });
        if (out.length >= k) break;
      }
      return out;
    }

    // Same as Index.answer_context in search.py: pin the fact sheet of the project in play.
    answerContext(query, { k = 6, repo = null, contextRepos = null } = {}) {
      const hits = this.search(query, { k, repo, contextRepos });
      const detected = this.tok.detectRepos(query);
      const targets = repo ? [repo] : (detected.length ? detected : (contextRepos || []));
      const wanted = targets.length ? targets.slice(0, 2).map((t) => `${t}:(overview):1-1`)
        : this.chunks.filter((c) => c.path === '(all projects)').slice(0, 1).map((c) => c.id);
      const have = new Set(hits.map((h) => h.chunk.id));
      const pinned = wanted.filter((id) => this.byId.has(id) && !have.has(id)).map((id) => ({ chunk: this.byId.get(id), score: 0, terms: [] }));
      return pinned.concat(hits).slice(0, k + pinned.length);
    }

    githubUrl(c) {
      const r = this.repos[c.repo] || {};
      if (!r.url) return '';
      if (c.path === '(overview)') return r.url;
      return `${r.url}/blob/${r.branch || 'main'}/${c.path}#L${c.start}-L${c.end}`;
    }
  }

  const api = { Index, makeTokenizer, isTestPath };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.YakovEngine = api;
})(typeof window !== 'undefined' ? window : globalThis);
