/* yakov.LLM web app.
 * Two backends behind one interface:
 *  - ServerBackend: the Python server (/api/chat streams Server-Sent Events).
 *  - BrowserBackend: no server at all. Search runs in the page (engine.js) over
 *    an embedded or downloaded kb.json, and answers come from Claude when the
 *    page runs inside Claude (artifact "sample" capability), else offline excerpts. */
(function () {
  'use strict';

  const CFG = Object.assign({ ownerName: 'Yakov Ashgar', kbUrl: '', apiBase: '' }, window.YAKOV_CONFIG || {});
  const MD = window.YakovMarkdown;
  const $ = (sel, el = document) => el.querySelector(sel);
  const esc = MD.esc;
  const HEBREW = /[א-ת]/;

  const ICON = {
    copy: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
    check: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5L20 7"/></svg>',
    retry: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/></svg>',
    send: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
    stop: '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2.5" fill="currentColor"/></svg>',
    pin: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 17v5M9 3h6l-1 6 4 4H6l4-4z"/></svg>',
    more: '<svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>',
    save: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>',
    up: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 10v11H4V10zM7 10l4-8a2.5 2.5 0 0 1 2.5 2.5V9h5.6a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 17.7 21H7"/></svg>',
    down2: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 14V3h3v11zM17 14l-4 8a2.5 2.5 0 0 1-2.5-2.5V15H4.9a2 2 0 0 1-2-2.3l1.4-8A2 2 0 0 1 6.3 3H17"/></svg>',
    speak: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
    folder: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    edit: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/></svg>',
    clip: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6L15 7.1"/></svg>',
    file: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
    x: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    down: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12l7 7 7-7"/></svg>',
    trash: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  };

  // ---------------------------------------------------------------- storage
  const store = {
    key: 'yakovllm.chats.v1',
    mem: null,
    load() {
      if (this.mem) return this.mem;
      try { this.mem = JSON.parse(localStorage.getItem(this.key) || '[]'); } catch { this.mem = []; }
      return this.mem;
    },
    save() {
      try { localStorage.setItem(this.key, JSON.stringify(this.mem.slice(0, 60))); } catch { /* private mode / quota */ }
    },
    pref(name, value) {
      try {
        if (value === undefined) return localStorage.getItem('yakovllm.' + name);
        localStorage.setItem('yakovllm.' + name, value);
      } catch { return null; }
    },
  };

  // Folders (like Projects in the big chat apps): a name, instructions, many files, and their own chats.
  const folderStore = {
    key: 'yakovllm.folders.v1',
    load() { try { return JSON.parse(localStorage.getItem(this.key) || '[]'); } catch { return []; } },
    save(list) { try { localStorage.setItem(this.key, JSON.stringify(list)); } catch { /* quota */ } },
  };
  const FOLDER_FILES = (id) => 'folder:' + id;

  // The user's profile and preferences, kept on this device.
  const Profile = {
    get() { try { return Object.assign({ name: '', avatar: '', lang: '', size: 'm', enterSends: true, instructions: '' }, JSON.parse(store.pref('profile') || '{}')); } catch { return { name: '', avatar: '', lang: '', size: 'm', enterSends: true }; } },
    set(patch) { const p = Object.assign(this.get(), patch); store.pref('profile', JSON.stringify(p)); return p; },
  };
  function avatarHTML(p) {
    if (p.avatar) return `<img src="${esc(p.avatar)}" alt="">`;
    return p.name ? esc([...p.name.trim()][0].toUpperCase()) : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>';
  }
  // Shrink a chosen photo to a small square, so it fits in local storage.
  function shrinkImage(file, size = 160) {
    return new Promise((res, rej) => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement('canvas');
        c.width = c.height = size;
        const s = Math.min(img.width, img.height);
        c.getContext('2d').drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, size, size);
        URL.revokeObjectURL(img.src);
        res(c.toDataURL('image/jpeg', 0.85));
      };
      img.onerror = () => rej(new Error('לא הצלחתי לקרוא את התמונה'));
      img.src = URL.createObjectURL(file);
    });
  }

  // A random id for this browser, so yakov.LLM can remember earlier conversations with the same person.
  const VISITOR = (() => {
    let v = store.pref('visitor');
    if (!v) { v = 'v' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '') : Date.now().toString(36) + Math.random().toString(36).slice(2)); store.pref('visitor', v); }
    return v;
  })();

  // ---------------------------------------------------------------- backends
  function parseSSE(buffer, onEvent) {
    let idx;
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let event = 'message', data = '';
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      if (data) onEvent(event, JSON.parse(data));
    }
    return buffer;
  }

  const ServerBackend = {
    kind: 'server',
    base: '',
    url(path) { return this.base + path; },
    async init(health, base = '') { this.base = base; this.health = health; const r = await fetch(this.url('api/repos')).then((x) => x.json()); this.repos = r.repos; this.builtAt = r.built_at; this.owner = r.owner; this.tokenizer = r.tokenizer || (BrowserBackend.kb || {}).tokenizer; },
    status() {
      const h = this.health;
      const live = h.mode !== 'offline';
      return { live, modeLabel: live ? (h.provider || 'Claude') + ' · ' + (h.model || '').split('/').pop() : 'חיפוש בלבד', sync: h.sync, builtAt: h.built_at, chunks: h.chunks };
    },
    async refresh() { this.health = await fetch(this.url('api/health')).then((x) => x.json()); await this.init(this.health, this.base); },
    async syncNow() {
      const r = await fetch(this.url('api/sync'), { method: 'POST' });
      if (!r.ok) throw new Error((await r.json()).error || 'sync failed');
    },
    async chat({ messages, repo, signal, onMeta, onDelta, attachments, chatId, temporary, folder }) {
      const res = await fetch(this.url('api/chat'), {
        method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: messages.map(({ role, content }) => ({ role, content })), repo, attachments, visitor: VISITOR, chat: chatId, name: Profile.get().name || undefined, lang: Profile.get().lang || undefined, instructions: Profile.get().instructions || undefined, temporary: !!temporary, folder: folder || undefined }),
      });
      if (res.status === 429) throw new Error('יותר מדי שאלות בזמן קצר. נסה שוב בעוד כמה דקות.');
      if (!res.ok || !res.body) throw new Error('השרת לא הגיב (' + res.status + ').');
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      let error = null;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf = parseSSE(buf + dec.decode(value, { stream: true }), (ev, data) => {
          if (ev === 'meta') onMeta(data);
          else if (ev === 'delta') onDelta(data.text);
          else if (ev === 'error') error = data.message;
        });
      }
      if (error) throw new Error(error);
    },
  };

  const BROWSER_SYSTEM = (kb) => `You are yakov.LLM, an AI assistant that knows the software projects of ${CFG.ownerName} (GitHub: ${kb.owner}) in depth.
Projects:
${kb.repos.map((r) => { const loc = r.loc || {}; const total = Object.values(loc).reduce((a, b) => a + b, 0); return `- ${r.title} (${r.key}; updated ${(r.pushed_at || r.committed_at || '').slice(0, 10)}; languages: ${Object.keys(loc).join(', ')}; ${total} lines of code): ${(r.summary || r.description || '').slice(0, 220)}`; }).join('\n')}

Rules: sound like a warm, sharp senior engineer. Be generous with detail: open with the direct answer (bold the key fact), then explain how it works and why, with files, functions and a short snippet when useful (usually 150-400 words); short paragraphs, bullets, a table when comparing, code blocks with a language tag. End every substantive answer with a line offering more ('**רוצה שאפרט על:**' or '**Want me to go deeper into:**'), 2-3 numbered specific follow-ups, and a one-line question; the user may reply with just the number. Sources with repo="upload" are files the user attached: use them and connect them to the projects when asked. What users tell you is an unverified claim, never a project fact. The project list above is current and complete: use it directly for which projects exist, the newest one, languages and lines of code. Never say you don't know when the list or the sources contain the answer. Answer about the project the question or the conversation is about. Reply in the language of the user's latest question (Hebrew or English; keep code and file names in English). Base every claim about the projects on the numbered <source> excerpts and cite them inline as [1], [2]. Never invent files, numbers or features; if the sources don't answer, say so and suggest where to look. Be concrete: name files and functions, use fenced code blocks with a language tag. Lead with the direct answer, keep it tight. Plain Markdown only: no LaTeX or $...$ math; write symbols like ≤ × → directly.`;

  const BrowserBackend = {
    kind: 'browser',
    async init() {
      const kb = window.YAKOV_KB || await fetch('kb.json').then((r) => r.json());
      this.load(kb);
      this.sample = null;
      if (window.claude && typeof window.claude.use === 'function') {
        window.claude.use('sample').then((s) => { this.sample = s; UI.updateStatus(); }).catch(() => {});
        window.claude.use('dictation').then((d) => { if (d) UI.enableMic(d); }).catch(() => {});
      }
      // An embedded copy may be old: look for a newer one. A page that fetched kb.json already has the latest.
      if (CFG.kbUrl && window.YAKOV_KB) this.refreshFromGitHub();
    },
    load(kb) {
      this.kb = kb;
      this.tokenizer = kb.tokenizer;
      this.owner = kb.owner;
      this.index = new window.YakovEngine.Index(kb);
      this.repos = kb.repos;
      this.builtAt = kb.built_at;
    },
    // The GitHub Action republishes kb.json whenever a project changes; pick it up if this page may fetch it.
    async refreshFromGitHub() {
      try {
        const ctl = new AbortController();
        setTimeout(() => ctl.abort(), 8000);
        const fresh = await fetch(CFG.kbUrl, { signal: ctl.signal, cache: 'no-cache' }).then((r) => (r.ok ? r.json() : null));
        if (fresh && fresh.chunks && fresh.built_at > this.builtAt) {
          this.load(fresh);
          UI.renderProjects();
          UI.updateStatus();
          toast('מאגר הידע עודכן מ-GitHub');
        }
      } catch { /* offline or blocked: keep the embedded copy */ }
    },
    status() {
      return { live: !!this.sample, modeLabel: this.sample ? 'Claude' : 'חיפוש בלבד', sync: null, builtAt: this.builtAt, chunks: this.index.n };
    },
    async refresh() {},
    async syncNow() { throw new Error('בגרסה הזו מאגר הידע מתעדכן אוטומטית על ידי GitHub Action.'); },
    async chat({ messages, repo, signal, onMeta, onDelta, onReplace, attachments, folder }) {
      const users = messages.filter((m) => m.role === 'user');
      const q = users[users.length - 1].content;
      let searchText = q;
      const choice = Dialog.choice(messages);
      if (choice) searchText = choice[1] + ' ' + (users.length > 1 ? users[users.length - 2].content : '');
      else if (users.length > 1 && this.index.tok.tokenize(q).length < 6) searchText = users[users.length - 2].content + ' ' + q;
      const t0 = performance.now();
      const earlier = messages.slice(0, -1).slice(-4).map((m) => String(m.content || '').slice(0, 600)).join(' ');
      const contextRepos = earlier ? this.index.tok.detectRepos(earlier) : [];
      // In a folder, the folder's files are the knowledge; the GitHub projects only when the question names one.
      const skipKb = folder && !repo && !this.index.tok.detectRepos(searchText).length;
      const hits = skipKb ? [] : this.index.answerContext(searchText, { k: attachments && attachments.length ? 6 : 8, repo, contextRepos });
      const files = (attachments || []).map((a) => ({ ...a, id: 'upload:' + a.name + ':' + a.start, repo: 'upload', path: a.name, title: '📎 ' + a.name, kind: 'upload', score: 0, terms: [], url: '' }));
      const sources = files.concat(hits.map((h) => ({ ...h.chunk, score: +h.score.toFixed(3), terms: h.terms, url: this.index.githubUrl(h.chunk) }))).map((x, i) => ({ ...x, n: i + 1 }));
      onMeta({ sources, mode: this.sample ? 'claude' : 'offline', search_ms: +(performance.now() - t0).toFixed(1) });
      if (this.sample) {
        const ctx = sources.map((s) => `<source n="${s.n}" repo="${s.repo}" path="${s.path}" lines="${s.start}-${s.end}">\n${s.text}\n</source>`).join('\n\n');
        const history = messages.slice(-11, -1).filter((m) => m.content).map(({ role, content }) => ({ role, content: content.slice(0, 6000) }));
        while (history.length && history[0].role !== 'user') history.shift();
        const instr = (Profile.get().instructions ? `\n\nThe user's standing preferences for how you answer (never against the rules or the sources): ${Profile.get().instructions}` : '')
          + (folder ? `\n\nThis conversation is in the user's folder "${folder.name}" (${folder.files} files). Answer mainly from the folder's files (sources with repo="upload"); general knowledge is fine when marked as such.${folder.instructions ? ' Folder instructions: ' + folder.instructions : ''}` : '');
        const input = history.concat([{ role: 'user', content: `${BROWSER_SYSTEM(this.kb)}${instr}\n\n<sources>\n${ctx || '(no matching excerpts)'}\n</sources>\n\nQuestion: ${q}${choice ? `\n(The user picked option ${choice[0]} from your previous message: "${choice[1]}". Answer that option fully now; don't ask again.)` : ''}\n(Reply in ${Profile.get().lang === 'en' ? 'English' : Profile.get().lang === 'he' ? 'Hebrew' : Dialog.lang(messages)}${Profile.get().name ? `; the user's name is ${Profile.get().name}` : ''}, the language of the user's latest message, unless the user asked for a specific language.)` }]);
        // sample() reports the WHOLE answer so far on every update, so we replace rather than append.
        const show = (text) => { if (text && !/^Thinking\.*$/.test(text.trim())) onReplace(text); };
        try {
          const res = await this.sample(input, { signal, cache: false, onText: ({ text }) => show(text) });
          if (res && res.text) show(res.text);
          return;
        } catch (e) {
          if (signal.aborted) return;
          if (e && e.code === 'not_granted') { this.sample = null; UI.updateStatus(); }
          else throw new Error(e && e.code === 'rate_limited' ? 'יותר מדי שאלות בזמן קצר. נסה שוב בעוד דקה.' : (e && e.message) || 'Claude לא זמין כרגע.');
        }
      }
      offlineAnswer(q, sources, onDelta);
    },
  };

  function offlineAnswer(q, sources, onDelta) {
    if (!sources.length) { onDelta('לא מצאתי במאגרים קטע שעונה על השאלה. נסה לנסח אחרת או לבחור פרויקט.'); return; }
    let s = 'אלה הקטעים הכי רלוונטיים שמצאתי בקוד ובתיעוד:\n\n';
    for (const h of sources.slice(0, 3)) {
      const ext = (h.path.split('.').pop() || '').toLowerCase();
      const body = h.text.split('\n').slice(0, 16).join('\n');
      s += `**${h.repo} › ${h.path}** · שורות \u2066${h.start}–${h.end}\u2069 [${h.n}]\n\n`;
      s += PROSE.has(h.kind) ? '> ' + body.split('\n').join('\n> ') + '\n\n' : '```' + ext + '\n' + body + '\n```\n\n';
    }
    onDelta(s + 'לחץ על מספר מקור כדי לראות את הקטע המלא.');
  }

  // Same rules as yakovllm/dialog.py: reply in the user's language; "2" picks option 2 of the last answer.
  const Dialog = {
    lang(messages) {
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (m.role !== 'user') continue;
        const he = (String(m.content).match(/[\u05d0-\u05ea]/g) || []).length, en = (String(m.content).match(/[A-Za-z]/g) || []).length;
        if (he >= 2) return 'Hebrew';
        if (en) return 'English';
      }
      return 'Hebrew';
    },
    options(text) {
      const groups = []; let cur = [];
      for (const line of String(text || '').split('\n')) {
        const m = line.match(/^\s*(?:[-*]\s*)?(\d{1,2})[.)]\s+(.+)$/);
        if (m) { const n = +m[1]; if (cur.length && n !== cur[cur.length - 1][0] + 1) { groups.push(cur); cur = []; } cur.push([n, m[2]]); }
        else if (line.trim() && cur.length && !/^[ \t]/.test(line)) { groups.push(cur); cur = []; }
      }
      if (cur.length) groups.push(cur);
      const ok = groups.filter((g) => g.length >= 2 && g[0][0] === 1);
      return ok.length ? ok[ok.length - 1].map(([, t]) => t.replace(/\*\*|__|`|\[\d+(?:,\s*\d+)*\]/g, '').trim()) : [];
    },
    ORD: { first: 1, second: 2, third: 3, fourth: 4, last: -1, one: 1, two: 2, three: 3, four: 4, 'ראשון': 1, 'הראשון': 1, 'הראשונה': 1, 'שני': 2, 'השני': 2, 'השנייה': 2, 'השניה': 2, 'שלישי': 3, 'השלישי': 3, 'השלישית': 3, 'רביעי': 4, 'הרביעי': 4, 'האחרון': -1, 'האחרונה': -1, 'אחת': 1, 'שתיים': 2, 'שלוש': 3, 'ארבע': 4 },
    choice(messages) {
      const last = messages[messages.length - 1];
      if (!last || last.role !== 'user') return null;
      const prev = [...messages.slice(0, -1)].reverse().find((m) => m.role === 'assistant' && m.content);
      if (!prev) return null;
      const m = String(last.content).match(/^\s*(?:the\s+)?(?:(?:option|choice|number|no\.?|#|אפשרות|מספר|סעיף|את|ה|בחרתי(?: ב)?|i choose|i pick|go with)\s*)?([0-9]{1,2}|[א-תa-z']+)(?:\s*(?:one|please|בבקשה|תודה))?\s*[.!)]?\s*$/i);
      if (!m) return null;
      let n = /^\d+$/.test(m[1]) ? +m[1] : this.ORD[m[1].toLowerCase()];
      const opts = this.options(prev.content);
      if (!n || !opts.length) return null;
      if (n === -1) n = opts.length;
      return n >= 1 && n <= opts.length ? [n, opts[n - 1]] : null;
    },
  };

  const PROSE = new Set(['doc', 'page', 'overview', 'facts', 'symbol', 'file', 'upload']);
  const isEnglish = (t) => !HEBREW.test(t || '');
  function srcLabel(s) {
    if (s.kind === 'upload') return s.path.split('/').pop();
    if (s.path === '(overview)') return 'overview';
    if (s.path === '(project facts)') return 'project facts';
    if (s.path === '(all projects)') return 'all projects';
    if (s.kind === 'symbol') return s.title.split('›').pop().trim();
    return s.path.split('/').pop();
  }
  function fmtSize(n) { return n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 1024) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }

  // Follow-up ideas under the latest answer, about the project the answer was about.
  function followUps(chat, m) {
    const users = chat.messages.filter((x) => x.role === 'user');
    const lastQ = (users[users.length - 1] || {}).content || '';
    const asked = new Set(users.map((u) => u.content.trim()));
    const en = isEnglish(lastQ);
    const repoKey = chat.repo || ((m.sources || []).find((s) => s.repo && s.repo !== 'upload' && !s.path.startsWith('(all')) || {}).repo;
    const r = (UI.backend.repos || []).find((x) => x.key === repoKey);
    const hasFiles = (m.sources || []).some((s) => s.kind === 'upload');
    // The answer offered numbered options: show them as one-tap choices.
    const opts = Dialog.options(m.content);
    const tail = String(m.content).trim().split('\n').slice(-3).join(' ');
    if (opts.length >= 2 && opts.length <= 5 && /[?？]/.test(tail)) return opts.map((t, i) => ({ opt: i + 1, text: t.length > 70 ? t.slice(0, 68).replace(/\s+\S*$/, '') + '…' : t, send: t }));
    let ideas;
    if (chat.folder) ideas = en ? ['Summarize the key ideas of this material', 'Give me 5 exam-style practice questions with answers', 'Explain the hardest concept here with an example']
      : ['סכם את הרעיונות המרכזיים בחומר', 'תן לי 5 שאלות תרגול בסגנון מבחן, עם תשובות', 'הסבר את המושג הכי קשה כאן עם דוגמה'];
    else if (hasFiles) ideas = en ? ['Summarize the attached file in 5 bullets', 'Which of the projects best matches this file?', 'What is missing in the file compared to the projects?']
      : ['סכם את הקובץ המצורף ב-5 נקודות', 'איזה מהפרויקטים הכי מתאים למה שכתוב בקובץ?', 'מה חסר בקובץ לעומת מה שיש בפרויקטים?'];
    else if (r && r.key !== UI.backend.owner) {
      const t = shortTitle(r);
      ideas = en ? [`How do I run ${t} locally?`, `What was the hardest engineering problem in ${t}?`, `Which tests does ${t} have?`, `What does ${t} depend on?`, `Show me the main entry point of ${t}`]
        : [`איך מריצים את ${t}?`, `מה האתגר ההנדסי הכי קשה ב-${t}?`, `אילו בדיקות יש ב-${t}?`, `על אילו ספריות ${t} מבוסס?`, `מה נקודת הכניסה הראשית של ${t}?`];
    } else {
      ideas = en ? ['Which project is the most impressive, and why?', 'What technologies does Yakov use most?', 'What is the newest project?']
        : ['איזה פרויקט הכי מרשים, ולמה?', 'באילו טכנולוגיות יעקב משתמש הכי הרבה?', 'מה הפרויקט הכי חדש?'];
    }
    return ideas.filter((q) => !asked.has(q)).slice(0, 3).map((q) => ({ text: q, send: q }));
  }

  // ---------------------------------------------------------------- UI
  const UI = {
    backend: null,
    chats: [],
    current: null,
    streaming: null,
    repo: '',
    files: [],          // attachments of the open chat (kept in IndexedDB)
    folders: [],        // folders, like Projects
    folder: null,       // the folder in view, or of the open chat
    folderFiles: [],    // that folder's files
    pendingFiles: [],   // attached before the chat has an id

    async start() {
      this.applyTheme(store.pref('theme') || 'system');
      matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if ((store.pref('theme') || 'system') === 'system') this.applyTheme('system'); });
      this.applyProfile();
      this.chats = store.load();
      this.folders = folderStore.load();
      this.bind();
      this.backend = await pickBackend();
      this.renderProjects();
      this.updateStatus();
      this.renderHistory();
      this.renderFolders();
      const last = this.chats[0];
      if (last && last.messages.length && store.pref('reopen') === last.id) this.open(last.id); else this.newChat();
      if (this.backend.kind === 'server') setInterval(() => this.backend.refresh().then(() => { this.updateStatus(); this.renderProjects(); }).catch(() => {}), 60000);
    },

    bind() {
      const ta = $('#input');
      ta.addEventListener('input', () => this.autosize());
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && Profile.get().enterSends) { e.preventDefault(); this.submit(); }
      });
      this.bindSettings();
      this.enableBrowserMic();
      $('#temp-btn').addEventListener('click', () => this.toggleTemporary());
      $('#new-folder').addEventListener('click', () => this.newFolder());
      $('#crumb').addEventListener('click', () => { if (this.folder) this.openFolder(this.folder.id); });
      // select text in an answer -> "ask about this"
      const quote = document.createElement('button');
      quote.className = 'quote-btn'; quote.hidden = true;
      quote.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg><span>שאל על זה</span>';
      document.body.appendChild(quote);
      let picked = '';
      document.addEventListener('selectionchange', () => {
        clearTimeout(this._selT);
        this._selT = setTimeout(() => {
          const sel = getSelection();
          const node = sel && sel.rangeCount && sel.anchorNode;
          const inAnswer = node && (node.nodeType === 1 ? node : node.parentElement).closest('.answer');
          picked = sel ? sel.toString().trim() : '';
          if (!inAnswer || picked.length < 3) { quote.hidden = true; return; }
          const r = sel.getRangeAt(0).getBoundingClientRect();
          quote.style.top = Math.max(8, r.top - 44) + 'px';
          quote.style.left = Math.min(innerWidth - 130, Math.max(8, r.left + r.width / 2 - 60)) + 'px';
          quote.hidden = false;
        }, 120);
      });
      quote.addEventListener('pointerdown', (e) => e.preventDefault());
      document.addEventListener('pointerdown', (e) => { if (e.target !== quote && !quote.contains(e.target)) quote.hidden = true; }, true);
      $('#scroller').addEventListener('scroll', () => { quote.hidden = true; }, { passive: true });
      quote.addEventListener('click', () => {
        const ta = $('#input');
        ta.value = `> ${picked.replace(/\s+/g, ' ').slice(0, 400)}\n\n`;
        quote.hidden = true;
        getSelection().removeAllRanges();
        this.autosize(); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
      });
      $('#chat-search').addEventListener('input', (e) => this.filterHistory(e.target.value));
      // keep an unsent draft if the app is closed
      ta.value = store.pref('draft') || '';
      ta.addEventListener('input', () => store.pref('draft', ta.value));
      ta.addEventListener('paste', (e) => {
        const files = [...((e.clipboardData && e.clipboardData.files) || [])];
        if (files.length) { e.preventDefault(); this.addFiles(files); return; }
        // a very long paste (a whole file or document) becomes an attachment instead of flooding the chat
        const text = e.clipboardData && e.clipboardData.getData('text/plain');
        if (text && text.length > 4000) {
          e.preventDefault();
          const n = this.allFiles().filter((f) => /^הדבקה/.test(f.name)).length + 1;
          this.addFiles([new File([text], `הדבקה ${n}.txt`, { type: 'text/plain' })]);
        }
      });
      $('#attach').addEventListener('click', (e) => { e.stopPropagation(); this.toggleAttachMenu(); });
      $('#pick-files').addEventListener('click', () => { this.toggleAttachMenu(false); $('#file-input').click(); });
      $('#pick-folder').addEventListener('click', () => { this.toggleAttachMenu(false); $('#folder-input').click(); });
      for (const id of ['#file-input', '#folder-input']) $(id).addEventListener('change', (e) => { this.addFiles([...e.target.files]); e.target.value = ''; });
      document.addEventListener('click', (e) => { if (!e.target.closest('#attach-menu')) this.toggleAttachMenu(false); });
      $('#attachments').addEventListener('click', (e) => {
        if (e.target.closest('[data-toggle-sent]')) { this.showSent = !this.showSent; this.renderFiles(); return; }
        const rm = e.target.closest('[data-rm]');
        if (rm) this.removeFile(rm.dataset.rm);
        const open = e.target.closest('[data-open-file]');
        if (open) { const f = this.allFiles().find((x) => x.name === open.dataset.openFile); if (f && f.text) this.openDrawer({ repo: '📎', path: f.name, start: 1, end: 1, kind: 'upload', text: f.text.slice(0, 60000), url: '' }); }
      });
      const main = $('.main');
      let depth = 0;
      main.addEventListener('dragenter', (e) => { if ([...(e.dataTransfer.types || [])].includes('Files')) { depth++; main.classList.add('dropping'); } });
      main.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; main.classList.remove('dropping'); } });
      main.addEventListener('dragover', (e) => e.preventDefault());
      main.addEventListener('drop', async (e) => { e.preventDefault(); depth = 0; main.classList.remove('dropping'); this.addFiles(await window.YakovFiles.fromDrop(e.dataTransfer)); });
      $('#chat-title').addEventListener('click', () => this.current && this.startRename(this.current.id, $('#chat-title')));
      $('#chat-title').addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === 'F2') && this.current) { e.preventDefault(); this.startRename(this.current.id, $('#chat-title')); } });
      if (window.YAKOV_EMBEDDED) $('#export').hidden = true;  // sandboxed hosts block downloads
      $('#export').addEventListener('click', () => this.exportChat());
      $('#sheet-body').addEventListener('submit', (e) => e.preventDefault(), true);
      $('#to-bottom').addEventListener('click', () => { $('#scroller').scrollTo({ top: 1e9, behavior: 'smooth' }); });
      $('#scroller').addEventListener('scroll', () => { const s = $('#scroller'); $('#to-bottom').classList.toggle('show', s.scrollHeight - s.scrollTop - s.clientHeight > 400); }, { passive: true });
      $('#send').addEventListener('click', () => (this.streaming ? this.stop() : this.submit()));
      $('#new-chat').addEventListener('click', () => { this.newChat(); this.closeSidebar(); });
      $('#scope').addEventListener('change', (e) => { this.repo = e.target.value; if (this.current) { this.current.repo = this.repo; this.persist(); } });
      $('#theme').addEventListener('click', () => this.applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
      $('#menu').addEventListener('click', () => this.openSidebar());
      $('#overlay').addEventListener('click', () => { if ($('#overlay').classList.contains('for-sheet')) { this.closeSheet(); return; } this.closeSidebar(); this.closeDrawer(); this.closeModal(); this.closeSettings(); });
      $('#drawer-close').addEventListener('click', () => this.closeDrawer());
      $('#projects-btn').addEventListener('click', () => this.openModal());
      $('#sync-btn').addEventListener('click', () => this.openModal());
      $('#modal-close').addEventListener('click', () => this.closeModal());
      $('#sync-now').addEventListener('click', () => this.syncNow());
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { if (!$('#sheet').hidden) { this.closeSheet(); return; } this.closeDrawer(); this.closeModal(); this.closeSettings(); this.closeSidebar(); this.toggleAttachMenu(false); }
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'o') { e.preventDefault(); this.newChat(); }
        if (e.key === '/' && !e.target.closest('input, textarea, [contenteditable="true"]')) { e.preventDefault(); $('#input').focus(); }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); this.openSidebar(); $('#chat-search').focus(); $('#chat-search').select(); }
      });
      $('#thread').addEventListener('click', (e) => this.onThreadClick(e));
      $('#welcome').addEventListener('click', (e) => {
        const b = e.target.closest('[data-ask]');
        if (b) { if (b.dataset.repo !== undefined) this.setScope(b.dataset.repo); this.ask(b.dataset.ask); }
      });
    },

    applyTheme(t) {
      const real = t === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : t;
      document.documentElement.dataset.theme = real;
      store.pref('theme', t);
      $('#theme').setAttribute('aria-label', real === 'dark' ? 'מעבר למצב בהיר' : 'מעבר למצב כהה');
      document.querySelectorAll('[data-theme-set]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.themeSet === t)));
    },

    // ---- profile and settings
    applyProfile() {
      const p = Profile.get();
      document.documentElement.dataset.size = p.size;
      $('#side-avatar').innerHTML = avatarHTML(p);
      $('#side-name').textContent = p.name || 'אורח';
      $('#avatar-pick').innerHTML = avatarHTML(p);
      $('#avatar-remove').hidden = !p.avatar;
      const hello = $('#hello') || (() => { const e = document.createElement('p'); e.id = 'hello'; e.className = 'hello'; e.dir = 'auto'; $('#welcome h1').before(e); return e; })();
      const h = new Date().getHours();
      hello.textContent = p.name ? `${h < 12 ? 'בוקר טוב' : h < 18 ? 'צהריים טובים' : 'ערב טוב'}, ${p.name}` : '';
      hello.hidden = !p.name;
      document.querySelectorAll('[data-size]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.size === p.size)));
    },
    openSettings() {
      const p = Profile.get();
      $('#set-name').value = p.name;
      $('#set-lang').value = p.lang;
      $('#set-enter').checked = p.enterSends;
      $('#set-instr').value = p.instructions || '';
      $('#mem-box').innerHTML = '<button class="btn" id="mem-show">מה אתה זוכר עליי?</button>';
      $('#mem-show').addEventListener('click', () => this.showMemory());
      this.applyProfile();
      this.applyTheme(store.pref('theme') || 'system');
      this.closeSidebar();
      $('#settings').classList.add('show');
      $('#overlay').classList.add('show');
      $('#settings-close').focus();
    },
    closeSettings() {
      if (!$('#settings').classList.contains('show')) return;
      Profile.set({ name: $('#set-name').value.replace(/\s+/g, ' ').trim().slice(0, 40) });
      this.applyProfile();
      $('#settings').classList.remove('show');
      if (!$('#drawer').classList.contains('open') && !$('#modal').classList.contains('show')) $('#overlay').classList.remove('show');
    },
    bindSettings() {
      $('#profile-btn').addEventListener('click', () => this.openSettings());
      $('#settings-close').addEventListener('click', () => this.closeSettings());
      $('#set-name').addEventListener('change', () => { Profile.set({ name: $('#set-name').value.replace(/\s+/g, ' ').trim().slice(0, 40) }); this.applyProfile(); });
      $('#set-lang').addEventListener('change', (e) => { Profile.set({ lang: e.target.value }); toast('נשמר'); });
      $('#set-enter').addEventListener('change', (e) => Profile.set({ enterSends: e.target.checked }));
      $('#set-instr').addEventListener('change', (e) => { Profile.set({ instructions: e.target.value.trim().slice(0, 1500) }); toast('ההוראות נשמרו'); });
      $('#mem-show').addEventListener('click', () => this.showMemory());
      document.querySelectorAll('[data-theme-set]').forEach((b) => b.addEventListener('click', () => this.applyTheme(b.dataset.themeSet)));
      document.querySelectorAll('[data-size]').forEach((b) => b.addEventListener('click', () => { Profile.set({ size: b.dataset.size }); this.applyProfile(); }));
      const pick = () => $('#avatar-input').click();
      $('#avatar-pick').addEventListener('click', pick);
      $('#avatar-change').addEventListener('click', pick);
      $('#avatar-remove').addEventListener('click', () => { Profile.set({ avatar: '' }); this.applyProfile(); });
      $('#avatar-input').addEventListener('change', async (e) => {
        const f = e.target.files[0];
        e.target.value = '';
        if (!f) return;
        try { Profile.set({ avatar: await shrinkImage(f) }); this.applyProfile(); toast('התמונה עודכנה'); } catch (err) { toast(err.message); }
      });
      $('#clear-all').addEventListener('click', () => {
        this.closeSettings();
        this.sheet('למחוק את כל השיחות?', `<p>${this.chats.length} שיחות והקבצים שצורפו אליהן יימחקו מהמכשיר. אי אפשר לבטל את זה.</p>
          <div class="row"><button class="btn" data-sheet-close>ביטול</button><button class="btn danger solid" id="confirm-clear">מחיקת הכל</button></div>`);
        $('#confirm-clear').addEventListener('click', () => {
          this.chats.forEach((c) => window.YakovFiles.DB.del(c.id));
          this.chats = []; store.mem = []; store.save();
          this.closeSheet(); this.newChat(); toast('כל השיחות נמחקו');
        });
      });
    },

    // ---- feedback, read aloud
    vote(idx, vote, el) {
      const c = this.current, m = c.messages[idx];
      m.vote = m.vote === vote ? null : vote;
      this.fillBot(el, m, false);
      if (!c.temporary) this.persist();
      if (m.vote && this.backend.kind === 'server') {
        const q = (c.messages.slice(0, idx).reverse().find((x) => x.role === 'user') || {}).content || '';
        fetch(this.backend.url('api/feedback'), { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ visitor: VISITOR, chat: c.id, vote: m.vote, question: q, answer: m.content.slice(0, 600) }) }).catch(() => {});
      }
      if (m.vote) toast(m.vote === 'up' ? 'תודה! שמחתי לעזור' : 'תודה, זה עוזר לי להשתפר');
    },
    speak(m, btn) {
      const synth = window.speechSynthesis;
      if (synth.speaking) { synth.cancel(); document.querySelectorAll('.speaking').forEach((b) => b.classList.remove('speaking')); if (btn.classList.contains('was')) { btn.classList.remove('was'); return; } }
      const text = m.content.replace(/```[\s\S]*?```/g, ' (קוד) ').replace(/\[\d+(?:,\s*\d+)*\]/g, '').replace(/[#*_`>|]/g, '').replace(/\n+/g, '. ');
      const u = new SpeechSynthesisUtterance(text.slice(0, 6000));
      u.lang = isEnglish(m.content) ? 'en-US' : 'he-IL';
      const voice = synth.getVoices().find((v) => v.lang.toLowerCase().startsWith(u.lang.slice(0, 2)));
      if (voice) u.voice = voice;
      u.onend = u.onerror = () => btn.classList.remove('speaking', 'was');
      btn.classList.add('speaking', 'was');
      synth.speak(u);
    },

    // ---- temporary chat: not saved on the device, not remembered by the server
    toggleTemporary() {
      if (this.current && this.current.messages.length) return;
      this.temporary = !this.temporary;
      this.updateTempUI();
      toast(this.temporary ? 'שיחה זמנית: לא תישמר ולא תיזכר' : 'שיחה רגילה');
    },
    updateTempUI() {
      const b = $('#temp-btn');
      b.hidden = !!(this.current && this.current.messages.length && !this.current.temporary);
      b.setAttribute('aria-pressed', String(!!this.temporary));
      let note = $('#temp-note');
      if (this.temporary && !(this.current && this.current.messages.length)) {
        if (!note) { note = document.createElement('p'); note.id = 'temp-note'; note.className = 'temp-note'; $('#welcome h1').after(note); }
        note.textContent = 'שיחה זמנית: היא לא תופיע בהיסטוריה, ו-yakov.LLM לא יזכור אותה.';
      } else if (note) note.remove();
    },

    // ---- search in chats (titles and content)
    filterHistory(q) {
      this.query = q.trim().toLowerCase();
      this.renderHistory();
    },

    // ---- what the server remembers about me
    async showMemory() {
      const box = $('#mem-box');
      if (this.backend.kind !== 'server') { box.innerHTML = '<span>הזיכרון זמין כשהשרת מחובר.</span>'; return; }
      box.innerHTML = '<span>טוען…</span>';
      try {
        const r = await fetch(this.backend.url('api/memory/me'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ visitor: VISITOR }) }).then((x) => x.json());
        if (!r.known) { box.innerHTML = '<span>אני עוד לא זוכר עליך כלום.</span>'; return; }
        box.innerHTML = `<span>${r.conversations === 1 ? 'דיברנו פעם אחת' : `דיברנו ${r.conversations} פעמים`}, מאז ${esc(r.first)}.${r.names.length ? ' קראת לעצמך ' + esc(r.names.join(', ')) + '.' : ''}</span>
          ${r.projects.length ? `<span>שאלת על: ${r.projects.map(esc).join(', ')}</span>` : ''}
          ${r.notes.length ? `<span>דברים שסיפרת לי (לא מאומתים):</span><ul>${r.notes.map((n) => `<li dir="auto">${esc(n)}</li>`).join('')}</ul>` : ''}
          <div class="row"><button class="btn danger" id="mem-forget">מחיקת הזיכרון שלי</button></div>`;
        $('#mem-forget').addEventListener('click', async () => {
          await fetch(this.backend.url('api/memory/forget'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ visitor: VISITOR }) }).catch(() => {});
          box.innerHTML = '<span>הזיכרון נמחק. מעכשיו אני מתחיל מחדש.</span>';
        });
      } catch { box.innerHTML = '<span>לא הצלחתי לטעון את הזיכרון.</span>'; }
    },

    // ---- folders
    saveFolders() { folderStore.save(this.folders); this.renderFolders(); },
    saveFolderFiles(f) {
      const ready = this.folderFiles.filter((x) => x.status === 'ready');
      f.fileCount = ready.length;
      f.updated = Date.now();
      window.YakovFiles.DB.put(FOLDER_FILES(f.id), ready.map((x) => ({ ...x })));
      this.saveFolders();
      if (this.inFolderView()) this.renderFolderView();
    },
    renderFolders() {
      const box = $('#folders');
      if (!this.folders.length) { box.innerHTML = '<p class="empty-folders">קבצים ושיחות של נושא אחד, במקום אחד.</p>'; return; }
      const list = [...this.folders].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || (b.updated || 0) - (a.updated || 0));
      box.innerHTML = list.map((f) => {
        const n = this.chats.filter((c) => c.folder === f.id).length;
        return `<div class="chat-item folder-item" role="listitem" data-folder-row="${f.id}" ${this.folder && this.folder.id === f.id ? 'aria-current="true"' : ''}>
          <span class="ico">${ICON.folder}</span>
          <button class="chat-open" style="all:unset;flex:1;min-width:0;cursor:pointer"><span style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" dir="auto">${esc(f.name)}</span></button>
          ${f.pinned ? `<span class="pin" aria-hidden="true">${ICON.pin}</span>` : ''}<span class="cnt">${n || ''}</span>
          <button class="more" data-fmore="${f.id}" aria-label="אפשרויות לתיקייה ${esc(f.name)}" title="אפשרויות">${ICON.more}</button></div>`;
      }).join('');
      box.querySelectorAll('[data-folder-row]').forEach((row) => this.bindLongPress(row, () => this.folderActions(row.dataset.folderRow), () => { this.openFolder(row.dataset.folderRow); this.closeSidebar(); }));
      box.querySelectorAll('[data-fmore]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); this.folderActions(b.dataset.fmore); }));
    },
    newFolder() {
      this.sheet('תיקייה חדשה', `<form id="folder-form"><input type="text" id="folder-name" maxlength="60" dir="auto" placeholder="למשל: תקשורת, מבחנים, קורות חיים" aria-label="שם התיקייה">
        <div class="row"><button type="button" class="btn" data-sheet-close>ביטול</button><button class="btn primary">יצירה</button></div></form>`);
      $('#folder-form').onsubmit = (e) => {
        e.preventDefault();
        const name = $('#folder-name').value.replace(/\s+/g, ' ').trim();
        if (!name) return;
        const f = { id: 'f' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5), name, created: Date.now(), updated: Date.now(), instructions: '', fileCount: 0 };
        this.folders.push(f);
        this.saveFolders();
        this.closeSheet();
        this.openFolder(f.id);
        this.closeSidebar();
      };
    },
    async openFolder(id, keepChat) {
      const f = this.folders.find((x) => x.id === id);
      if (!f) return;
      if (!keepChat) { this.current = null; this.files = []; this.pendingFiles = []; this.temporary = false; }
      const switching = !this.folder || this.folder.id !== f.id;
      this.folder = f;
      if (switching) this.folderFiles = [];
      if (switching && f.fileCount) {
        const files = await window.YakovFiles.DB.get(FOLDER_FILES(f.id));
        if (this.folder === f) this.folderFiles = files;
      }
      this.updateCrumb();
      if (!keepChat) {
        this.setScope('');
        $('#thread').innerHTML = '';
        $('#welcome').hidden = true;
        $('#chat-title').textContent = '';
        this.renderFolderView();
        this.updateTempUI();
        $('#scroller').scrollTop = 0;
      }
      this.renderFolders();
      this.renderHistory();
    },
    leaveFolder() {
      this.folder = null;
      this.folderFiles = [];
      $('#folder-view').hidden = true;
      this.updateCrumb();
      this.renderFolders();
    },
    updateCrumb() {
      const inFolder = !!this.folder;
      $('#scope').hidden = inFolder;  // project scope means nothing inside a folder
      $('#input').placeholder = this.inFolderView() ? `שיחה חדשה בתיקייה "${this.folder.name}"…` : inFolder ? `שאל על החומר של "${this.folder.name}"…` : 'שאל על הקוד, על ההחלטות או איך להריץ…';
      const c = $('#crumb');
      c.hidden = !(this.folder && this.current);
      if (!c.hidden) c.innerHTML = `${ICON.folder}<span dir="auto">${esc(this.folder.name)}</span>`;
    },
    renderFolderView() {
      const f = this.folder, v = $('#folder-view');
      v.hidden = false;
      const chats = this.chats.filter((c) => c.folder === f.id);
      v.innerHTML = `<div class="fv-head"><span class="fv-icon">${ICON.folder}</span><div><h1 dir="auto">${esc(f.name)}</h1>
          <p>${f.fileCount || 0} קבצים · ${chats.length} שיחות · כל שיחה כאן עונה מתוך הקבצים של התיקייה</p></div></div>
        <div class="fv-card"><h2>${ICON.clip}<span class="grow">קבצים ומקורות</span>
          <button class="btn small" data-fv="files">הוספת קבצים</button><button class="btn small" data-fv="dir">הוספת תיקייה</button></h2>
          <div class="fv-files" id="fv-files"></div></div>
        <div class="fv-card"><h2><span class="grow">הוראות לתיקייה</span></h2>
          <textarea id="fv-instr" rows="2" maxlength="1500" dir="auto" placeholder="למשל: אלה ההרצאות בקורס תקשורת. תסביר כמו מתרגל, ותן דוגמאות למבחן.">${esc(f.instructions || '')}</textarea></div>
        <div class="fv-card"><h2><span class="grow">שיחות בתיקייה</span></h2>
          <div class="fv-chats">${chats.length ? chats.map((c) => `<button class="fv-chat" data-fv-chat="${c.id}">${c.pinned ? ICON.pin : ''}<span class="t" dir="auto">${esc(c.title)}</span><span class="w">${ago(new Date(c.updated || c.created).toISOString())}</span></button>`).join('')
            : '<p class="fv-empty">עדיין אין שיחות. כתוב שאלה למטה כדי לפתוח שיחה ראשונה בתיקייה.</p>'}</div></div>`;
      this.renderFolderFiles();
      v.onclick = (e) => {
        const b = e.target.closest('[data-fv]');
        if (b) $(b.dataset.fv === 'dir' ? '#folder-input' : '#file-input').click();
        const c = e.target.closest('[data-fv-chat]');
        if (c) this.open(c.dataset.fvChat);
        const rm = e.target.closest('[data-rm]');
        if (rm) this.removeFile(rm.dataset.rm);
        const op = e.target.closest('[data-open-file]');
        if (op) { const x = this.folderFiles.find((y) => y.name === op.dataset.openFile); if (x && x.text) this.openDrawer({ repo: '📎', path: x.name, start: 1, end: 1, kind: 'upload', text: x.text.slice(0, 60000), url: '' }); }
      };
      $('#fv-instr').onchange = (e) => { f.instructions = e.target.value.trim().slice(0, 1500); this.saveFolders(); toast('ההוראות נשמרו'); };
    },
    renderFolderFiles() {
      const box = $('#fv-files');
      if (!box) return;
      const files = this.folderFiles;
      box.innerHTML = files.length ? files.map((x) => `<span class="att ${x.status || 'ready'}" title="${esc(x.error || x.name)}">
        <button class="att-open" data-open-file="${esc(x.name)}" ${x.status && x.status !== 'ready' ? 'disabled' : ''}>${x.status === 'reading' ? '<i class="spin"></i>' : ICON.file}
        <span class="nm" dir="auto">${esc(x.name.split('/').pop())}</span><span class="sz" dir="ltr">${x.status === 'error' ? esc(x.error) : fmtSize(x.size || 0)}</span></button>
        <button class="att-x" data-rm="${esc(x.name)}" aria-label="הסרת ${esc(x.name)}">${ICON.x}</button></span>`).join('')
        : '<p class="fv-empty">גרור לכאן הרצאות, תרגולים, סיכומים או תיקייה שלמה: PDF, Word, PowerPoint, Excel, טקסט, קוד ו-ZIP. עד 200 קבצים.</p>';
    },
    folderActions(id) {
      const f = this.folders.find((x) => x.id === id);
      if (!f) return;
      if (navigator.vibrate) try { navigator.vibrate(12); } catch { /* ignore */ }
      this.sheet(f.name, `
        <button class="act" data-a="rename">${ICON.edit}<span>שינוי שם</span></button>
        <button class="act" data-a="pin">${ICON.pin}<span>${f.pinned ? 'ביטול הצמדה' : 'הצמדה למעלה'}</span></button>
        <button class="act danger" data-a="delete">${ICON.trash}<span>מחיקת התיקייה</span></button>`);
      $('#sheet-body').onclick = (e) => {
        const a = e.target.closest('[data-a]');
        if (!a) return;
        if (a.dataset.a === 'rename') {
          this.sheet('שינוי שם לתיקייה', `<form id="rename-form"><input type="text" id="rename-input" maxlength="60" dir="auto" value="${esc(f.name)}" aria-label="שם התיקייה">
            <div class="row"><button type="button" class="btn" data-sheet-close>ביטול</button><button class="btn primary">שמירה</button></div></form>`);
          setTimeout(() => $('#rename-input').select(), 80);
          $('#rename-form').onsubmit = (ev) => {
            ev.preventDefault();
            const name = $('#rename-input').value.replace(/\s+/g, ' ').trim();
            if (name) { f.name = name; this.saveFolders(); this.updateCrumb(); if (this.inFolderView()) this.renderFolderView(); toast('השם נשמר'); }
            this.closeSheet();
          };
        }
        if (a.dataset.a === 'pin') { f.pinned = !f.pinned; this.saveFolders(); this.closeSheet(); toast(f.pinned ? 'התיקייה הוצמדה' : 'ההצמדה בוטלה'); }
        if (a.dataset.a === 'delete') {
          const n = this.chats.filter((c) => c.folder === f.id).length;
          this.sheet('למחוק את התיקייה?', `<p dir="auto">"${esc(f.name)}" תימחק עם ${f.fileCount || 0} הקבצים ו-${n} השיחות שבה. אי אפשר לבטל את זה.</p>
            <div class="row"><button class="btn" data-sheet-close>ביטול</button><button class="btn danger solid" data-a="really-delete">מחיקה</button></div>`);
        }
        if (a.dataset.a === 'really-delete') {
          this.chats.filter((c) => c.folder === f.id).forEach((c) => window.YakovFiles.DB.del(c.id));
          this.chats = this.chats.filter((c) => c.folder !== f.id); store.mem = this.chats; store.save();
          window.YakovFiles.DB.del(FOLDER_FILES(f.id));
          this.folders = this.folders.filter((x) => x.id !== f.id);
          const here = this.folder && this.folder.id === f.id;
          this.saveFolders(); this.closeSheet();
          if (here) { this.leaveFolder(); this.newChat(); } else this.renderHistory();
          toast('התיקייה נמחקה');
        }
      };
    },

    // ---- action sheet (long press on a chat, like the big chat apps)
    sheet(title, html) {
      const sh = $('#sheet');
      $('#sheet-title').textContent = title;
      $('#sheet-body').innerHTML = html;
      sh.hidden = false;
      $('#overlay').classList.add('show', 'for-sheet');
      requestAnimationFrame(() => sh.classList.add('show'));
      $('#sheet-body').querySelectorAll('[data-sheet-close]').forEach((b) => b.addEventListener('click', () => this.closeSheet()));
      const first = $('#sheet-body input, #sheet-body button');
      if (first) setTimeout(() => first.focus(), 60);
    },
    closeSheet() {
      const sh = $('#sheet');
      if (sh.hidden) return;
      sh.classList.remove('show');
      setTimeout(() => { sh.hidden = true; }, 200);
      $('#overlay').classList.remove('for-sheet');
      if (!$('#sidebar').classList.contains('open') && !$('#drawer').classList.contains('open') && !$('#modal').classList.contains('show') && !$('#settings').classList.contains('show')) $('#overlay').classList.remove('show');
    },
    chatActions(id) {
      const c = this.chats.find((x) => x.id === id);
      if (!c) return;
      if (navigator.vibrate) try { navigator.vibrate(12); } catch { /* ignore */ }
      this.sheet(c.title, `
        <button class="act" data-a="rename">${ICON.edit}<span>שינוי שם</span></button>
        <button class="act" data-a="pin">${ICON.pin}<span>${c.pinned ? 'ביטול הצמדה' : 'הצמדה למעלה'}</span></button>
        ${this.folders.length ? `<button class="act" data-a="move">${ICON.folder}<span>העברה לתיקייה</span></button>` : ''}
        ${window.YAKOV_EMBEDDED ? '' : `<button class="act" data-a="export">${ICON.save}<span>שמירה כקובץ</span></button>`}
        <button class="act danger" data-a="delete">${ICON.trash}<span>מחיקה</span></button>`);
      $('#sheet-body').onclick = (e) => {
        const a = e.target.closest('[data-a]');
        if (!a) return;
        if (a.dataset.a === 'rename') this.renameSheet(c);
        if (a.dataset.a === 'pin') { c.pinned = !c.pinned; store.mem = this.chats; store.save(); this.renderHistory(); this.closeSheet(); toast(c.pinned ? 'השיחה הוצמדה' : 'ההצמדה בוטלה'); }
        if (a.dataset.a === 'export') { this.exportChat(c); this.closeSheet(); }
        if (a.dataset.a === 'move') this.sheet('העברה לתיקייה', [...this.folders.map((f) => `<button class="act" data-a="to" data-to="${f.id}">${ICON.folder}<span dir="auto">${esc(f.name)}${c.folder === f.id ? ' ✓' : ''}</span></button>`),
          c.folder ? `<button class="act" data-a="to" data-to="">${ICON.x}<span>הוצאה מהתיקייה</span></button>` : ''].join(''));
        if (a.dataset.a === 'to') {
          c.folder = a.dataset.to || undefined; store.mem = this.chats; store.save();
          this.closeSheet(); this.renderHistory(); this.renderFolders();
          if (this.current === c) this.open(c.id); else if (this.inFolderView()) this.renderFolderView();
          toast(c.folder ? 'השיחה הועברה לתיקייה' : 'השיחה הוצאה מהתיקייה');
        }
        if (a.dataset.a === 'delete') this.sheet('למחוק את השיחה?', `<p dir="auto">"${esc(c.title)}" תימחק מהמכשיר. אי אפשר לבטל את זה.</p>
          <div class="row"><button class="btn" data-sheet-close>ביטול</button><button class="btn danger solid" data-a="really-delete">מחיקה</button></div>`);
        if (a.dataset.a === 'really-delete') { this.remove(c.id); this.closeSheet(); toast('השיחה נמחקה'); }
      };
    },
    renameSheet(c) {
      this.sheet('שינוי שם', `<form id="rename-form"><input type="text" id="rename-input" maxlength="80" dir="auto" value="${esc(c.title)}" aria-label="שם השיחה">
        <div class="row"><button type="button" class="btn" data-sheet-close>ביטול</button><button class="btn primary">שמירה</button></div></form>`);
      const input = $('#rename-input');
      setTimeout(() => input.select(), 80);
      $('#rename-form').onsubmit = (e) => {
        e.preventDefault();
        const name = input.value.replace(/\s+/g, ' ').trim();
        if (name) { c.title = name; c.renamed = true; store.mem = this.chats; store.save(); if (this.current && this.current.id === c.id) $('#chat-title').textContent = name; this.renderHistory(); toast('השם נשמר'); }
        this.closeSheet();
      };
    },

    autosize() {
      const ta = $('#input');
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, innerHeight * 0.4) + 'px';
      $('#send').disabled = !this.streaming && !ta.value.trim();
    },

    // ---- chats
    newChat() {
      if (this.folder) this.leaveFolder();
      this.current = null;
      this.temporary = false;
      setTimeout(() => this.updateTempUI());
      this.files = [];
      this.pendingFiles = [];
      this.renderFiles();
      this.setScope('');
      $('#thread').innerHTML = '';
      $('#welcome').hidden = false;
      $('#chat-title').textContent = '';
      this.renderHistory();
      $('#input').focus({ preventScroll: true });
    },
    open(id) {
      const c = this.chats.find((x) => x.id === id);
      if (!c) return;
      this.current = c;
      this.temporary = !!c.temporary;
      setTimeout(() => this.updateTempUI());
      this.setScope(c.repo || '');
      this.files = [];
      this.pendingFiles = [];
      this.renderFiles();
      if (c.fileCount) window.YakovFiles.DB.get(c.id).then((f) => { if (this.current === c) { this.files = f; this.renderFiles(); } });
      $('#folder-view').hidden = true;
      if (c.folder && this.folders.some((x) => x.id === c.folder)) this.openFolder(c.folder, true);
      else if (this.folder) this.leaveFolder();
      $('#welcome').hidden = true;
      $('#chat-title').textContent = c.title;
      const th = $('#thread');
      th.innerHTML = '';
      c.messages.forEach((m, i) => th.appendChild(m.role === 'user' ? this.userEl(m, i) : this.botEl(m, i)));
      this.renderFollowUps();
      this.renderHistory();
      store.pref('reopen', c.id);
      requestAnimationFrame(() => { $('#scroller').scrollTop = 1e9; });
    },
    remove(id) {
      window.YakovFiles.DB.del(id);
      this.chats = this.chats.filter((x) => x.id !== id);
      store.mem = this.chats;
      store.save();
      const gone = this.chats.length;  // eslint: keep for clarity
      if (this.current && this.current.id === id) {
        const fid = this.current.folder;
        if (fid && this.folders.some((f) => f.id === fid)) this.openFolder(fid); else this.newChat();
      } else { this.renderHistory(); if (this.inFolderView()) this.renderFolderView(); }
      this.renderFolders();
      void gone;
    },
    persist() {
      if (!this.current) return;
      if (this.current.temporary) { this.updateTempUI(); return; }  // a temporary chat stays in memory only
      this.current.updated = Date.now();
      this.chats = [this.current, ...this.chats.filter((x) => x.id !== this.current.id)];
      store.mem = this.chats;
      store.save();
      store.pref('reopen', this.current.id);
    },
    setScope(repo) {
      this.repo = repo || '';
      $('#scope').value = this.repo;
    },

    renderHistory() {
      const box = $('#history');
      if (!this.chats.length) { box.innerHTML = '<p class="empty-history">השיחות שלך יופיעו כאן.</p>'; return; }
      if (this.query && !this.chats.some((c) => c.title.toLowerCase().includes(this.query) || c.messages.some((m) => String(m.content || '').toLowerCase().includes(this.query)))) { box.innerHTML = '<p class="empty-history">לא נמצאו שיחות.</p>'; return; }
      const day = 864e5, now = Date.now();
      const groups = [['מוצמדות', (t, c) => c.pinned], ['היום', (t) => now - t < day], ['השבוע', (t) => now - t < 7 * day], ['קודם', () => true]];
      let html = '';
      const used = new Set();
      for (const [label, test] of groups) {
        const q = this.query || '';
        const match = (c) => !q || c.title.toLowerCase().includes(q) || c.messages.some((m) => String(m.content || '').toLowerCase().includes(q));
        const items = this.chats.filter((c) => !used.has(c.id) && (!c.folder || q) && match(c) && test(c.updated || c.created, c));
        if (!items.length) continue;
        html += `<h3>${label}</h3>`;
        for (const c of items) {
          used.add(c.id);
          html += `<div class="chat-item" role="listitem" data-chat="${c.id}" ${this.current && this.current.id === c.id ? 'aria-current="true"' : ''}>
            ${c.pinned ? `<span class="pin" aria-hidden="true">${ICON.pin}</span>` : ''}
            <button class="chat-open" data-id="${c.id}" style="all:unset;flex:1;min-width:0;cursor:pointer"><span style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" dir="auto">${esc(c.title)}</span></button>
            <button class="more" data-more="${c.id}" aria-label="אפשרויות לשיחה ${esc(c.title)}" title="אפשרויות">${ICON.more}</button></div>`;
        }
      }
      box.innerHTML = html;
      box.querySelectorAll('.chat-item').forEach((row) => this.bindLongPress(row));
      box.querySelectorAll('[data-more]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); this.chatActions(b.dataset.more); }));
    },

    // Tap opens the chat; a long press (or right click) opens its actions. Nothing destructive happens on a tap.
    bindLongPress(row, onLong, onTap) {
      const id = row.dataset.chat;
      onLong = onLong || (() => this.chatActions(id));
      onTap = onTap || (() => { this.open(id); this.closeSidebar(); });
      let timer = 0, fired = false, x = 0, y = 0;
      const cancel = () => { clearTimeout(timer); row.classList.remove('pressing'); };
      row.addEventListener('pointerdown', (e) => {
        if (e.button !== 0 || e.target.closest('[data-more]')) return;
        fired = false; x = e.clientX; y = e.clientY;
        row.classList.add('pressing');
        timer = setTimeout(() => { fired = true; row.classList.remove('pressing'); onLong(); }, 480);
      });
      row.addEventListener('pointermove', (e) => { if (Math.abs(e.clientX - x) > 8 || Math.abs(e.clientY - y) > 8) cancel(); });
      ['pointerup', 'pointerleave', 'pointercancel'].forEach((ev) => row.addEventListener(ev, cancel));
      row.addEventListener('contextmenu', (e) => { e.preventDefault(); cancel(); if (!fired) { fired = true; onLong(); } });
      row.querySelector('.chat-open').addEventListener('click', (e) => {
        if (fired) { e.preventDefault(); fired = false; return; }
        onTap();
      });
    },

    // Rename a chat in place: an input takes the title's place; Enter saves, Escape cancels.
    startRename(id, el) {
      const c = this.chats.find((x) => x.id === id);
      if (!c || !el || el.dataset.renaming) return;
      el.dataset.renaming = '1';
      const input = document.createElement('input');
      input.className = 'rename';
      input.value = c.title;
      input.maxLength = 80;
      input.dir = 'auto';
      input.setAttribute('aria-label', 'שם חדש לשיחה');
      const host = el.closest('.chat-item') || el;
      if (host !== el) host.classList.add('editing');
      el.hidden = true;
      el.after(input);
      input.focus();
      input.select();
      let finished = false;
      const done = (save) => {
        if (finished) return;
        finished = true;
        const name = input.value.replace(/\s+/g, ' ').trim();
        input.remove();
        el.hidden = false;
        delete el.dataset.renaming;
        host.classList.remove('editing');
        if (save && name && name !== c.title) {
          c.title = name; c.renamed = true;
          store.mem = this.chats; store.save();
          toast('השם נשמר');
        }
        if (this.current && this.current.id === id) $('#chat-title').textContent = c.title;
        this.renderHistory();
      };
      input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); done(true); } if (e.key === 'Escape') { e.preventDefault(); done(false); } });
      input.addEventListener('click', (e) => e.stopPropagation());
      input.addEventListener('blur', () => done(true));
    },

    // ---- attachments
    allFiles() { return this.current ? this.files : (this.folder ? this.folderFiles : this.pendingFiles); },
    inFolderView() { return !this.current && !!this.folder; },
    toggleAttachMenu(force) {
      const m = $('#attach-menu');
      const open = force === undefined ? m.hidden : force;
      m.hidden = !open;
      $('#attach').setAttribute('aria-expanded', String(open));
    },
    async addFiles(list) {
      const Files = window.YakovFiles;
      // archives: open them and add what's inside
      const zips = list.filter((f) => /\.zip$/i.test(f.name));
      if (zips.length) {
        list = list.filter((f) => !zips.includes(f));
        for (const z of zips) { try { list = list.concat(await Files.expandZip(z)); } catch { toast(`לא הצלחתי לפתוח את ${z.name}`); } }
      }
      const target = this.allFiles();
      const fresh = list.filter((f) => !Files.SKIP_DIRS.test((f.webkitRelativePath || f.name)) && !/(^|\/)\./.test(f.webkitRelativePath || f.name));
      const ok = fresh.filter((f) => Files.supported(f.webkitRelativePath || f.name));
      const skipped = fresh.length - ok.length;
      if (!ok.length) { toast(skipped ? 'הקבצים האלה לא נתמכים. אפשר לצרף טקסט, קוד, Word, PowerPoint, Excel ו-PDF.' : 'לא נמצאו קבצים'); return; }
      const room = Files.MAX_FILES - target.length;
      const batch = ok.slice(0, Math.max(0, room));
      if (ok.length > batch.length) toast(`אפשר עד ${Files.MAX_FILES} קבצים ${this.inFolderView() ? 'בתיקייה' : 'בשיחה'}`);
      const folderTarget = this.inFolderView() ? this.folder : null;
      const base = this.backend.kind === 'server' ? this.backend.base : null;
      const placeholders = batch.map((f) => ({ name: f.webkitRelativePath || f.name, size: f.size, status: 'reading' }));
      for (const p of placeholders) { const i = target.findIndex((x) => x.name === p.name); if (i >= 0) target.splice(i, 1); target.push(p); }
      this.renderFiles();
      let done = 0, failed = 0;
      const work = batch.map((f, i) => async () => {
        try { Object.assign(placeholders[i], await Files.read(f, { apiBase: base }), { status: 'ready' }); done++; }
        catch (e) { Object.assign(placeholders[i], { status: 'error', error: (e && e.message) || 'שגיאה' }); failed++; }
        this.renderFiles();
      });
      for (let i = 0; i < work.length; i += 4) await Promise.all(work.slice(i, i + 4).map((w) => w()));
      if (this.current && target === this.files) this.saveFiles();
      if (folderTarget && target === this.folderFiles) this.saveFolderFiles(folderTarget);
      toast(failed ? `צורפו ${done} קבצים, ${failed} לא נקראו` : (done === 1 ? 'הקובץ צורף. אפשר לשאול עליו.' : `צורפו ${done} קבצים. אפשר לשאול עליהם.`) + (skipped ? ` (${skipped} דולגו)` : ''));
    },
    removeFile(name) {
      const t = this.allFiles();
      const i = t.findIndex((x) => x.name === name);
      if (i >= 0) t.splice(i, 1);
      this.renderFiles();
      if (this.current) this.saveFiles();
      else if (this.folder && t === this.folderFiles) this.saveFolderFiles(this.folder);
    },
    saveFiles() {
      const ready = this.files.filter((f) => f.status === 'ready');
      this.current.fileCount = ready.length;
      if (!this.current.temporary) window.YakovFiles.DB.put(this.current.id, ready.map((f) => ({ ...f })));
      this.persist();
    },
    renderFiles() {
      if (this.inFolderView()) { $('#attachments').hidden = true; this.renderFolderFiles(); return; }
      const files = this.allFiles();
      const box = $('#attachments');
      // Files already sent stay with the chat as sources: one compact pill; new ones show as chips.
      const sent = files.filter((f) => f.sent && f.status === 'ready');
      const fresh = files.filter((f) => !(f.sent && f.status === 'ready'));
      const list = this.showSent ? files : fresh;
      box.hidden = !files.length;
      const shown = list.length > 12 ? list.slice(-11) : list;
      const pill = sent.length ? `<button class="files-pill" data-toggle-sent aria-expanded="${!!this.showSent}">${ICON.clip}<span>${sent.length === 1 ? 'קובץ אחד' : sent.length + ' קבצים'} בשיחה</span></button>` : '';
      box.innerHTML = pill + (list.length > 12 ? `<span class="att more">+${list.length - 11} קבצים</span>` : '') + shown.map((f) => `<span class="att ${f.status}" title="${esc(f.error || f.name)}">
        <button class="att-open" data-open-file="${esc(f.name)}" ${f.status !== 'ready' ? 'disabled' : ''}>${f.status === 'reading' ? '<i class="spin"></i>' : ICON.file}
        <span class="nm" dir="auto">${esc(f.name.split('/').pop())}</span><span class="sz" dir="${f.status === 'error' ? 'auto' : 'ltr'}">${f.status === 'error' ? esc(f.error) : fmtSize(f.size || 0)}</span></button>
        <button class="att-x" data-rm="${esc(f.name)}" aria-label="הסרת ${esc(f.name)}">${ICON.x}</button></span>`).join('');
    },

    // ---- projects / welcome
    renderProjects() {
      const repos = this.backend.repos || [];
      const sel = $('#scope');
      const keep = this.repo;
      sel.innerHTML = '<option value="">כל הפרויקטים</option>' + repos.map((r) => `<option value="${esc(r.key)}">${esc(shortTitle(r))}</option>`).join('');
      sel.value = keep;
      $('#projects').innerHTML = repos.filter((r) => r.key !== (this.backend.kb || {}).owner && r.files > 1).map((r) =>
        `<button class="project" data-repo="${esc(r.key)}" data-ask="ספר לי על ${esc(shortTitle(r))}: מה הוא עושה, איך הוא בנוי ומה הכי מעניין בקוד?">
          <span class="t" dir="auto">${esc(shortTitle(r))}</span>
          <span class="s" dir="auto">${esc(r.summary || r.description || '')}</span>
          <span class="f">${r.files} files · ${ago(r.pushed_at || r.committed_at)}</span>
        </button>`).join('');
      $('#repo-count').textContent = repos.length;
      this.renderModal();
    },

    renderModal() {
      const repos = this.backend.repos || [];
      $('#repo-list').innerHTML = repos.map((r) => `<div class="repo-row">
        <span class="t" dir="auto">${esc(shortTitle(r))}</span>
        <span class="when">עודכן ${ago(r.pushed_at || r.committed_at)}</span>
        <span class="s" dir="auto">${esc(r.summary || r.description || '')}</span>
        <span class="f">${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.owner + '/' + r.name)}</a> · ` : ''}${r.files} files · ${r.chunks} chunks${r.commit ? ' · ' + esc(r.commit) : ''}</span>
      </div>`).join('');
      const st = this.backend.status();
      const how = this.backend.kind === 'server'
        ? `השרת בודק את GitHub כל ${Math.round((st.sync && st.sync.interval_min) || 30)} דקות. פרויקט חדש נוסף אוטומטית, ופרויקט ששונה מתעדכן בלי השבתה. ${st.sync && st.sync.last_check ? 'בדיקה אחרונה: ' + ago(new Date(st.sync.last_check * 1000).toISOString()) + '.' : ''}${st.sync && st.sync.last_error ? ' שגיאה אחרונה: ' + esc(st.sync.last_error) : ''}`
        : `מאגר הידע נבנה ${ago(st.builtAt)}. GitHub Action בונה אותו מחדש מכל הפרויקטים שלך כמה פעמים ביום.`;
      $('#how').innerHTML = how;
      $('#sync-now').hidden = this.backend.kind !== 'server' || !(st.sync && st.sync.enabled);
    },

    updateStatus() {
      if (!this.backend) return;
      const st = this.backend.status();
      const pill = $('#mode');
      pill.textContent = st.modeLabel;
      pill.classList.toggle('live', st.live);
      const busy = st.sync && st.sync.running;
      $('#sync-dot').className = 'dot' + (busy ? ' busy' : (st.sync && st.sync.last_error) ? ' off' : '');
      $('#sync-text').textContent = busy ? 'מסנכרן עם GitHub…' : (st.sync && st.sync.enabled ? 'מחובר ל-GitHub · ' : 'מאגר הידע · ') + 'עודכן ' + ago(st.builtAt);
      this.renderModal();
    },

    async syncNow() {
      const btn = $('#sync-now');
      btn.disabled = true;
      try {
        await this.backend.syncNow();
        toast('בודק את GitHub עכשיו…');
        setTimeout(async () => { await this.backend.refresh(); this.updateStatus(); this.renderProjects(); btn.disabled = false; }, 4000);
      } catch (e) { toast(e.message); btn.disabled = false; }
    },

    // ---- messages
    userEl(m, idx) {
      const el = document.createElement('div');
      el.className = 'msg user';
      el.dataset.idx = idx;
      const files = (m.files || []).length ? `<div class="sent-files">${m.files.slice(0, 6).map((n) => `<span class="sent-file">${ICON.file}<span dir="auto">${esc(n.split('/').pop())}</span></span>`).join('')}${m.files.length > 6 ? `<span class="sent-file">+${m.files.length - 6}</span>` : ''}</div>` : '';
      el.innerHTML = `<div class="user-col">${files}<div class="bubble" dir="auto">${esc(m.content)}</div>
        <div class="user-tools"><button class="icon-btn" data-uact="copy" aria-label="העתקת ההודעה">${ICON.copy}</button><button class="icon-btn" data-uact="edit" aria-label="עריכת ההודעה ושליחה מחדש">${ICON.edit}</button></div></div>`;
      return el;
    },
    // Edit a sent question (like ChatGPT): the answers after it are replaced by a new one.
    editUser(idx, el) {
      if (this.streaming) return;
      const m = this.current.messages[idx];
      const bubble = $('.bubble', el);
      bubble.outerHTML = `<div class="edit-box"><textarea dir="auto" rows="3">${esc(m.content)}</textarea><div class="edit-row"><button class="btn" data-uact="cancel">ביטול</button><button class="btn primary" data-uact="save">שליחה</button></div></div>`;
      const ta = $('.edit-box textarea', el);
      ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
      ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('[data-uact="save"]', el).click(); } if (e.key === 'Escape') $('[data-uact="cancel"]', el).click(); });
    },
    botEl(m, idx) {
      const el = document.createElement('div');
      el.className = 'msg bot';
      el.dataset.idx = idx;
      el.innerHTML = `${LOGO(26, 'bot-mark')}<div><div class="answer" dir="auto"></div><div class="sources" hidden></div><div class="msg-tools"></div></div>`;
      this.fillBot(el, m, false);
      return el;
    },
    fillBot(el, m, live) {
      const ans = $('.answer', el);
      if (m.error) {
        ans.innerHTML = `<div class="error-box">${esc(m.error)}</div>`;
      } else if (!m.content && live) {
        const n = (this.backend.repos || []).length;
        const files = this.files.filter((f) => f.status === 'ready').length + (this.current && this.current.folder && this.folder ? this.folderFiles.filter((f) => f.status === 'ready').length : 0);
        const status = m.sources ? 'כותב תשובה…' : (files ? `קורא ${files === 1 ? 'קובץ אחד' : files + ' קבצים'} ומחפש ב-${n} פרויקטים…` : `מחפש ב-${n} פרויקטים…`);
        ans.innerHTML = `<div class="thinking" role="status"><span class="bars"><i></i><i></i><i></i></span>${status}</div>`;
      } else {
        ans.innerHTML = MD.render(m.content, { sources: m.sources });
        if (live) { const last = ans.lastElementChild; if (last && !last.classList.contains('codeblock')) last.classList.add('caret'); }
      }
      const src = $('.sources', el);
      src.innerHTML = (m.sources || []).map((s, i) => `<button class="src-chip" data-src="${i}" title="${esc(s.repo + ' › ' + s.path)}">
        <span class="n">${i + 1}</span><span class="p" dir="auto">${s.kind === 'upload' ? '📎 ' : ''}${esc(srcLabel(s))}</span><span class="r">${esc(s.kind === 'upload' ? 'קובץ מצורף' : s.repo)}</span></button>`).join('');
      const tools = $('.msg-tools', el);
      tools.innerHTML = live ? '' : `<button class="icon-btn" data-act="copy" aria-label="העתקת התשובה" title="העתקה">${ICON.copy}</button>
        <button class="icon-btn" data-act="retry" aria-label="תשובה חדשה" title="תשובה חדשה">${ICON.retry}</button>
        ${m.content && !m.error ? `${'speechSynthesis' in window ? `<button class="icon-btn" data-act="speak" aria-label="הקראה בקול" title="הקראה">${ICON.speak}</button>` : ''}
        <button class="icon-btn ${m.vote === 'up' ? 'on' : ''}" data-act="up" aria-label="תשובה טובה" aria-pressed="${m.vote === 'up'}" title="תשובה טובה">${ICON.up}</button>
        <button class="icon-btn ${m.vote === 'down' ? 'on' : ''}" data-act="down" aria-label="תשובה לא טובה" aria-pressed="${m.vote === 'down'}" title="תשובה לא טובה">${ICON.down2}</button>` : ''}
        ${(m.sources || []).length && !m.error ? `<button class="src-toggle" data-act="sources" aria-expanded="false">${isEnglish(m.content) ? 'Sources' : 'מקורות'} · ${m.sources.length}<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>` : ''}`;
    },
    renderFollowUps() {
      document.querySelectorAll('.followups').forEach((n) => n.remove());
      const c = this.current;
      if (!c || this.streaming) return;
      const last = c.messages[c.messages.length - 1];
      if (!last || last.role !== 'assistant' || last.error || !last.content) return;
      const ideas = followUps(c, last);
      const el = [...document.querySelectorAll('.msg.bot')].pop();
      if (!ideas.length || !el) return;
      const box = document.createElement('div');
      box.className = 'followups';
      box.innerHTML = ideas.map((q) => `<button class="starter${q.opt ? ' opt' : ''}" data-follow="${esc(q.send)}" dir="auto">${q.opt ? `<b>${q.opt}</b>` : ''}${esc(q.text)}</button>`).join('');
      $('.msg-tools', el).after(box);
    },

    onThreadClick(e) {
      const follow = e.target.closest('[data-follow]');
      if (follow) { this.ask(follow.dataset.follow); return; }
      const uEl = e.target.closest('.msg.user');
      const uact = e.target.closest('[data-uact]');
      if (uEl && uact && this.current) {
        const idx = +uEl.dataset.idx;
        const m = this.current.messages[idx];
        if (uact.dataset.uact === 'copy') copyText(m.content).then(() => { uact.innerHTML = ICON.check; setTimeout(() => (uact.innerHTML = ICON.copy), 1500); });
        if (uact.dataset.uact === 'edit') this.editUser(idx, uEl);
        if (uact.dataset.uact === 'cancel') uEl.replaceWith(this.userEl(m, idx));
        if (uact.dataset.uact === 'save') {
          const text = $('.edit-box textarea', uEl).value.trim();
          if (!text) return;
          this.current.messages = this.current.messages.slice(0, idx).concat([{ ...m, content: text }]);
          const th = $('#thread');
          [...th.querySelectorAll('.msg')].slice(idx).forEach((n) => n.remove());
          th.appendChild(this.userEl(this.current.messages[idx], idx));
          this.persist();
          this.run();
        }
        return;
      }
      const msgEl = e.target.closest('.msg.bot');
      if (!msgEl || !this.current) return;
      const m = this.current.messages[+msgEl.dataset.idx];
      const cite = e.target.closest('[data-src]');
      if (cite && m && m.sources) { this.openDrawer(m.sources[+cite.dataset.src], m.sources); return; }
      const copy = e.target.closest('[data-copy]');
      if (copy) {
        const code = copy.closest('.codeblock').querySelector('code').innerText;
        copyText(code).then(() => { copy.querySelector('span').textContent = 'הועתק'; setTimeout(() => (copy.querySelector('span').textContent = 'העתק'), 1500); });
        return;
      }
      const act = e.target.closest('[data-act]');
      if (!act || !m) return;
      if (act.dataset.act === 'copy') copyText(m.content).then(() => { act.innerHTML = ICON.check; setTimeout(() => (act.innerHTML = ICON.copy), 1500); });
      if (act.dataset.act === 'retry' && !this.streaming) this.regenerate(+msgEl.dataset.idx);
      if (act.dataset.act === 'speak') this.speak(m, act);
      if (act.dataset.act === 'up' || act.dataset.act === 'down') this.vote(+msgEl.dataset.idx, act.dataset.act, msgEl);
      if (act.dataset.act === 'sources') { const box = $('.sources', msgEl); box.hidden = !box.hidden; act.setAttribute('aria-expanded', String(!box.hidden)); }
    },

    ask(text) { $('#input').value = text; this.submit(); },

    submit() {
      const ta = $('#input');
      const text = ta.value.trim();
      if (!text || this.streaming) return;
      ta.value = '';
      store.pref('draft', '');
      this.autosize();
      if (this.allFiles().some((f) => f.status === 'reading')) { toast('רגע, הקבצים עדיין נקראים…'); ta.value = text; return; }
      if (!this.current) {
        this.current = { id: 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), title: chatTitle(text), created: Date.now(), updated: Date.now(), repo: this.repo, messages: [], temporary: !!this.temporary };
        if (this.folder) { this.current.folder = this.folder.id; this.folder.updated = Date.now(); this.saveFolders(); }
        $('#folder-view').hidden = true;
        this.updateCrumb();
        $('#welcome').hidden = true;
        $('#thread').innerHTML = '';
        $('#chat-title').textContent = this.current.title;
        if (this.pendingFiles.length) { this.files = this.pendingFiles; this.pendingFiles = []; this.saveFiles(); }
      }
      const um = { role: 'user', content: text };
      const fresh = this.files.filter((f) => f.status === 'ready' && !f.sent);
      if (fresh.length) { um.files = fresh.map((f) => f.name); fresh.forEach((f) => (f.sent = true)); this.showSent = false; this.saveFiles(); this.renderFiles(); }
      this.current.messages.push(um);
      $('#thread').appendChild(this.userEl(um, this.current.messages.length - 1));
      this.persist();
      this.renderHistory();
      this.updateTempUI();
      this.run();
    },

    regenerate(idx) {
      this.current.messages = this.current.messages.slice(0, idx);
      const th = $('#thread');
      [...th.querySelectorAll('.msg')].slice(idx).forEach((n) => n.remove());
      this.run();
    },

    async run() {
      const chat = this.current;
      const bm = { role: 'assistant', content: '' };
      const idx = chat.messages.length;
      const history = chat.messages.slice();
      chat.messages.push(bm);
      const el = this.botEl(bm, idx);
      $('.msg-tools', el).innerHTML = '';
      this.fillBot(el, bm, true);
      $('#thread').appendChild(el);
      this.scrollDown(true);

      document.querySelectorAll('.followups').forEach((n) => n.remove());
      const users = history.filter((m) => m.role === 'user');
      const q = (users[users.length - 1] || {}).content || '';
      const searchQ = users.length > 1 && q.split(/\s+/).length < 6 ? users[users.length - 2].content + ' ' + q : q;
      const ready = this.files.filter((f) => f.status === 'ready');
      const inFolder = chat.folder && this.folder && this.folder.id === chat.folder;
      const folderReady = inFolder ? this.folderFiles.filter((f) => f.status === 'ready') : [];
      const own = window.YakovFiles.pick(ready, searchQ, folderReady.length ? 3 : 6, this.backend.tokenizer);
      const fromFolder = folderReady.length ? window.YakovFiles.pick(folderReady, searchQ, 8 - own.length, this.backend.tokenizer) : [];
      const attachments = own.concat(fromFolder).map((c) => ({ name: c.path, start: c.start, end: c.end, text: c.text }));
      const folder = inFolder ? { name: this.folder.name, files: folderReady.length, instructions: this.folder.instructions || '' } : null;
      const ctl = new AbortController();
      this.streaming = ctl;
      // Watchdog: if no text arrives for 110 s (the server tries up to three models), stop waiting.
      let lastText = Date.now();
      let timedOut = false;
      const watchdog = setInterval(() => {
        if (Date.now() - lastText > 110000) { timedOut = true; ctl.abort(); }
      }, 2000);
      this.setSending(true);
      let frame = 0;
      const paint = () => { frame = 0; this.fillBot(el, bm, true); this.scrollDown(); };
      try {
        await this.backend.chat({
          messages: history, repo: this.repo || null, signal: ctl.signal, attachments, chatId: chat.id, temporary: chat.temporary, folder,
          onMeta: (meta) => { bm.sources = meta.sources; bm.meta = { sources: meta.sources.length, search_ms: meta.search_ms, mode: meta.mode }; paint(); },
          onDelta: (t) => { lastText = Date.now(); bm.content += t; if (!frame) frame = requestAnimationFrame(paint); },
          onReplace: (t) => { lastText = Date.now(); bm.content = t; if (!frame) frame = requestAnimationFrame(paint); },
        });
        if (!bm.content && !ctl.signal.aborted) bm.error = 'המודל לא החזיר תשובה. נסה שוב בעוד רגע.';
      } catch (e) {
        if (!ctl.signal.aborted) {
          const msg = (e && e.message) || '';
          bm.error = /network|failed to fetch|load failed|networkerror/i.test(msg)
            ? 'החיבור לשרת נקטע באמצע (אולי הוא התעדכן או התעורר משינה). לחץ על ⟳ כדי לנסות שוב.'
            : msg || 'משהו השתבש.';
        }
      } finally {
        clearInterval(watchdog);
        if (timedOut && !bm.content) bm.error = 'המודל לא הגיב בזמן (אולי השרת התעורר משינה או שהמודל החינמי עמוס). לחץ על ⟳ כדי לנסות שוב.';
        if (frame) cancelAnimationFrame(frame);
        if (ctl.signal.aborted && !bm.content && !bm.error) bm.content = '_(נעצר)_';
        this.streaming = null;
        this.setSending(false);
        this.fillBot(el, bm, false);
        this.persist();
        if (this.current === chat) this.renderFollowUps();
      }
    },

    exportChat(chat) {
      const c = chat || this.current;
      if (!c) { toast('אין עדיין שיחה לייצא'); return; }
      let md = `# ${c.title}\n\n_yakov.LLM · ${new Date(c.created).toLocaleString('he-IL')}_\n\n`;
      for (const m of c.messages) {
        if (m.role === 'user') md += `## 🙋 ${m.content}\n\n`;
        else {
          md += (m.error ? `> ${m.error}` : m.content) + '\n\n';
          if (m.sources && m.sources.length) md += m.sources.map((s, i) => `${i + 1}. ${s.repo} › ${s.path}${s.url ? ` (${s.url})` : ''}`).join('\n') + '\n\n';
        }
      }
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([md], { type: 'text/markdown' }));
      a.download = (c.title.replace(/[\\/:*?"<>|]+/g, ' ').trim() || 'yakov-llm') + '.md';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    },

    stop() { if (this.streaming) this.streaming.abort(); },

    setSending(on) {
      const b = $('#send');
      b.innerHTML = on ? ICON.stop : ICON.send;
      b.setAttribute('aria-label', on ? 'עצירה' : 'שליחה');
      b.disabled = !on && !$('#input').value.trim();
    },

    scrollDown(force) {
      const s = $('#scroller');
      if (force || s.scrollHeight - s.scrollTop - s.clientHeight < 160) s.scrollTop = s.scrollHeight;
    },

    // ---- drawer
    openDrawer(src) {
      if (!src) return;
      const d = $('#drawer');
      $('#d-repo').textContent = src.repo;
      $('#d-repo').textContent = src.kind === 'upload' ? '📎 קובץ מצורף' : src.repo;
      $('#d-path').textContent = src.path.startsWith('(') ? srcLabel(src) : src.path;
      $('#d-lines').textContent = src.path.startsWith('(') || (src.kind === 'upload' && src.start === 1 && src.end === 1) ? '' : `${src.kind === 'upload' ? 'שורות' : 'lines'} ${src.start}–${src.end}`;
      const body = $('#d-body');
      if (PROSE.has(src.kind)) {
        body.innerHTML = `<div class="prose-src">${esc(src.text)}</div>`;
      } else {
        const ext = src.path.split('.').pop();
        const lines = src.text.split('\n');
        body.innerHTML = '<div class="gutter-code">' + lines.map((l, i) =>
          `<span class="ln">${src.start + i}</span><span class="tx">${MD.highlight(l, ext) || ' '}</span>`).join('') + '</div>';
      }
      body.scrollTop = 0;
      const gh = $('#d-github');
      gh.hidden = !src.url;
      if (src.url) gh.href = src.url;
      $('#d-terms').textContent = src.terms && src.terms.length ? 'matched: ' + src.terms.slice(0, 8).join(', ') : '';
      d.classList.add('open');
      d.setAttribute('aria-hidden', 'false');
      $('#overlay').classList.add('show');
      $('#drawer-close').focus();
    },
    closeDrawer() {
      const d = $('#drawer');
      if (!d.classList.contains('open')) return;
      d.classList.remove('open');
      d.setAttribute('aria-hidden', 'true');
      if (!$('#sidebar').classList.contains('open') && !$('#modal').classList.contains('show')) $('#overlay').classList.remove('show');
    },
    openSidebar() { $('#sidebar').classList.add('open'); $('#overlay').classList.add('show'); },
    closeSidebar() { $('#sidebar').classList.remove('open'); if (!$('#drawer').classList.contains('open')) $('#overlay').classList.remove('show'); },
    openModal() { this.renderModal(); $('#modal').classList.add('show'); $('#overlay').classList.add('show'); $('#modal-close').focus(); },
    closeModal() { $('#modal').classList.remove('show'); if (!$('#drawer').classList.contains('open') && !$('#sidebar').classList.contains('open')) $('#overlay').classList.remove('show'); },

    // Voice typing with the browser's own speech recognition (Chrome, Edge, Safari).
    enableBrowserMic() {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR || window.YAKOV_EMBEDDED) return;
      const mic = $('#mic');
      mic.classList.add('on');
      let rec = null;
      mic.addEventListener('click', () => {
        if (rec) { rec.stop(); return; }
        rec = new SR();
        const ta = $('#input');
        rec.lang = Profile.get().lang === 'en' ? 'en-US' : 'he-IL';
        rec.interimResults = true;
        rec.continuous = false;
        const before = ta.value ? ta.value.trim() + ' ' : '';
        rec.onresult = (e) => { ta.value = before + [...e.results].map((r) => r[0].transcript).join(''); this.autosize(); };
        rec.onend = () => { rec = null; mic.classList.remove('listening'); store.pref('draft', ta.value); };
        rec.onerror = (e) => { if (e.error === 'not-allowed') toast('צריך לאשר גישה למיקרופון'); };
        mic.classList.add('listening');
        rec.start();
      });
    },

    enableMic(d) {
      const mic = $('#mic');
      mic.classList.add('on');
      let on = false;
      d.onFinal(({ text }) => { const ta = $('#input'); ta.value = (ta.value + ' ' + text).trim(); this.autosize(); });
      d.onState(({ state }) => { on = state === 'listening'; mic.classList.toggle('listening', on); });
      mic.addEventListener('click', () => { (on ? d.stop() : d.start()).catch(() => mic.classList.remove('on')); });
    },
  };

  // ---------------------------------------------------------------- helpers
  // A short title from the first question, like the big chat apps do.
  function chatTitle(text) {
    let t = text.replace(/\s+/g, ' ').trim().replace(/^(?:היי|שלום|הי|hey|hi|hello)[,!.\s]+/i, '').replace(/^(?:תגיד(?: לי)?|תסביר(?: לי)?|ספר(?: לי)?|can you|could you|please)\s+/i, '');
    t = t.replace(/[?!.]+$/, '');
    if (t.length > 48) t = t.slice(0, 48).replace(/\s+\S*$/, '') + '…';
    return t ? t[0].toUpperCase() + t.slice(1) : text.slice(0, 48);
  }
  function shortTitle(r) {
    return (r.title || r.name).replace(/\s+[—-]\s+.*$/, '').replace(/^.*·\s*/, '');
  }
  function ago(iso) {
    if (!iso) return '';
    const t = Date.parse(iso);
    if (isNaN(t)) return '';
    const s = (t - Date.now()) / 1000;
    const rtf = new Intl.RelativeTimeFormat('he', { numeric: 'auto' });
    const units = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
    for (const [u, sec] of units) if (Math.abs(s) >= sec) return rtf.format(Math.round(s / sec), u);
    return 'הרגע';
  }
  function copyText(t) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(t).catch(() => fallbackCopy(t));
    return Promise.resolve(fallbackCopy(t));
  }
  function fallbackCopy(t) {
    const a = document.createElement('textarea');
    a.value = t; a.style.position = 'fixed'; a.style.opacity = '0';
    document.body.appendChild(a); a.select();
    try { document.execCommand('copy'); } catch { /* ignore */ }
    a.remove();
  }
  let toastTimer = 0;
  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
  }
  function LOGO(size, cls) {
    return `<svg class="${cls || ''}" width="${size}" height="${size}" viewBox="0 0 32 32" aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="9" fill="var(--accent)"/>
      <path d="M9.5 9l6.5 8.2L22.5 9M16 17.2V24" stroke="var(--accent-ink)" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="9.5" cy="9" r="2.1" fill="var(--accent-ink)"/><circle cx="22.5" cy="9" r="2.1" fill="var(--accent-ink)"/><circle cx="16" cy="24" r="2.1" fill="var(--accent-ink)"/>
    </svg>`;
  }
  window.YakovLogo = LOGO;

  async function pingServer(base, ms) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), ms);
    try {
      const h = await fetch(base + 'api/health', { signal: ctl.signal }).then((r) => (r.ok ? r.json() : null));
      return h && h.name === 'yakov.LLM' ? h : null;
    } catch { return null; } finally { clearTimeout(t); }
  }

  async function pickBackend() {
    // 1. Served by the Python server itself.
    if (!window.YAKOV_KB && location.protocol.startsWith('http')) {
      const h = await pingServer('', 2500);
      if (h) { await ServerBackend.init(h); return ServerBackend; }
    }
    // 2. Static page: start searching in the browser right away...
    await BrowserBackend.init();
    // 3. ...and switch to the hosted server (Claude answers) once it wakes up. A free host can take ~50 s.
    if (CFG.apiBase) {
      const base = CFG.apiBase.replace(/\/?$/, '/');
      pingServer(base, 75000).then(async (h) => {
        if (!h) return;
        try {
          await ServerBackend.init(h, base);
          UI.backend = ServerBackend;
          UI.renderProjects();
          UI.updateStatus();
          if (h.mode !== 'offline') toast('המודל מחובר: התשובות יהיו כתובות');
        } catch { /* stay in browser mode */ }
      });
    }
    return BrowserBackend;
  }

  // ---------------------------------------------------------------- installable app (PWA)
  function setupInstall() {
    if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost') && !window.YAKOV_EMBEDDED) {
      navigator.serviceWorker.register('sw.js').catch(() => { /* sandboxed host: no offline cache */ });
    }
    let deferred = null;
    const btn = document.getElementById('install-btn');
    window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferred = e; btn.hidden = false; });
    window.addEventListener('appinstalled', () => { btn.hidden = true; toast('yakov.LLM הותקן'); });
    btn.addEventListener('click', async () => {
      if (!deferred) return;
      deferred.prompt();
      await deferred.userChoice.catch(() => null);
      deferred = null;
      btn.hidden = true;
    });
  }

  window.YakovUI = UI;
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-logo]').forEach((n) => (n.outerHTML = LOGO(+n.dataset.logo)));
    setupInstall();
    UI.start().catch((e) => {
      document.getElementById('welcome').innerHTML = `<div class="error-box">yakov.LLM לא הצליח לטעון את מאגר הידע: ${esc(String(e && e.message || e))}</div>`;
    });
  });
})();
