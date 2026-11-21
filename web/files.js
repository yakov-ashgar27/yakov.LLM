/* yakov.LLM attachments: read files and folders the user adds, keep them with the chat,
 * and pick the excerpts that answer each question.
 *  - text, Markdown, code, CSV, JSON, HTML: read in the browser;
 *  - Word / PowerPoint / Excel (.docx .pptx .xlsx): unzipped in the browser (DecompressionStream);
 *  - PDF: sent to the server's /api/extract (pypdf), since reading PDF text needs a real parser.
 * Excerpts are found with the same BM25 engine the projects use (engine.js). */
(function (root) {
  'use strict';

  const TEXT_EXT = new Set(('txt md markdown rst csv tsv json yml yaml toml ini cfg log xml html htm css scss js mjs cjs jsx ts tsx py java kt c h cpp hpp cs go rs ' +
    'rb php swift sql sh bat ps1 r ipynb vue svelte dart lua pl gradle properties env gitignore dockerfile makefile').split(' '));
  const OFFICE_EXT = new Set(['docx', 'pptx', 'xlsx', 'docm', 'pptm', 'xlsm']);
  const SKIP_DIRS = /(^|\/)(node_modules|\.git|dist|build|\.venv|venv|__pycache__|\.next|coverage)\//;
  const MAX_FILE = 15 * 1024 * 1024;   // bytes read per file
  const MAX_TEXT = 400000;             // characters kept per file
  const MAX_FILES = 200;               // per chat (a folder can be big)
  const CHUNK = 1400;

  const ext = (name) => { const n = name.toLowerCase(); const b = n.split('/').pop(); return b.includes('.') ? b.split('.').pop() : b; };
  const kind = (name) => { const e = ext(name); return e === 'pdf' ? 'pdf' : OFFICE_EXT.has(e) ? 'office' : TEXT_EXT.has(e) ? 'text' : 'other'; };
  const supported = (name) => kind(name) !== 'other';

  // ------------------------------------------------------------ zip (Office files)
  async function inflate(bytes) {
    const ds = new DecompressionStream('deflate-raw');
    const out = new Response(new Blob([bytes]).stream().pipeThrough(ds));
    return new Uint8Array(await out.arrayBuffer());
  }
  async function unzip(buf, want) {
    const v = new DataView(buf);
    let eocd = -1;
    for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 66000); i--) if (v.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error('הקובץ פגום');
    const count = v.getUint16(eocd + 10, true);
    let p = v.getUint32(eocd + 16, true);
    const dec = new TextDecoder();
    const files = {};
    for (let n = 0; n < count; n++) {
      const method = v.getUint16(p + 10, true), size = v.getUint32(p + 20, true);
      const nameLen = v.getUint16(p + 28, true), extraLen = v.getUint16(p + 30, true), commentLen = v.getUint16(p + 32, true);
      const local = v.getUint32(p + 42, true);
      const name = dec.decode(new Uint8Array(buf, p + 46, nameLen));
      p += 46 + nameLen + extraLen + commentLen;
      if (!want(name)) continue;
      const lnl = v.getUint16(local + 26, true), lel = v.getUint16(local + 28, true);
      const data = new Uint8Array(buf, local + 30 + lnl + lel, size);
      files[name] = dec.decode(method === 0 ? data : await inflate(data));
    }
    return files;
  }
  const xmlText = (xml, tag) => [...xml.matchAll(new RegExp(`<${tag}[^>]*>([^<]*)</${tag}>`, 'g'))].map((m) => m[1]);
  const unxml = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&');

  async function readOffice(buf, name) {
    const e = ext(name);
    if (e.startsWith('doc')) {
      const f = await unzip(buf, (n) => n === 'word/document.xml');
      const xml = f['word/document.xml'] || '';
      return unxml(xml.split(/<\/w:p>/).map((p) => xmlText(p, 'w:t').join('')).filter((t) => t.trim()).join('\n'));
    }
    if (e.startsWith('ppt')) {
      const f = await unzip(buf, (n) => /^ppt\/(slides\/slide|notesSlides\/notesSlide)\d+\.xml$/.test(n));
      const nums = Object.keys(f).filter((n) => n.startsWith('ppt/slides/')).map((n) => +n.match(/(\d+)\.xml$/)[1]).sort((a, b) => a - b);
      return unxml(nums.map((i) => {
        const body = f[`ppt/slides/slide${i}.xml`].split(/<\/a:p>/).map((p) => xmlText(p, 'a:t').join('')).filter((t) => t.trim()).join('\n');
        const notes = (f[`ppt/notesSlides/notesSlide${i}.xml`] ? xmlText(f[`ppt/notesSlides/notesSlide${i}.xml`], 'a:t').join(' ').trim() : '');
        return `## Slide ${i}\n${body}${notes && !/^\d+$/.test(notes) ? '\n(notes) ' + notes : ''}`;
      }).join('\n\n'));
    }
    const f = await unzip(buf, (n) => n === 'xl/sharedStrings.xml' || /^xl\/worksheets\/sheet\d+\.xml$/.test(n));
    const shared = f['xl/sharedStrings.xml'] ? f['xl/sharedStrings.xml'].split('</si>').map((si) => xmlText(si, 't').join('')) : [];
    return unxml(Object.keys(f).filter((n) => n.includes('worksheets')).sort().map((n) => {
      const rows = f[n].split('</row>').slice(0, 2000).map((row) => [...row.matchAll(/<c([^>]*)>(?:<f>[^<]*<\/f>)?<v>([^<]*)<\/v>/g)]
        .map((m) => (/t="s"/.test(m[1]) ? shared[+m[2]] || '' : m[2])).join(' | ')).filter((r) => r.trim());
      return `## ${n.split('/').pop().replace('.xml', '')}\n` + rows.join('\n');
    }).join('\n\n'));
  }

  // ------------------------------------------------------------ reading one file
  async function read(file, { apiBase = null } = {}) {
    const name = file.webkitRelativePath || file.name;
    if (file.size > MAX_FILE) throw new Error('הקובץ גדול מדי (עד 15MB)');
    const k = kind(name);
    if (k === 'other') throw new Error('סוג קובץ שלא נתמך');
    let text;
    if (k === 'text') {
      text = await file.text();
    } else if (apiBase !== null && (k === 'pdf' || k === 'office')) {
      try {
        const r = await fetch(apiBase + 'api/extract', { method: 'POST', headers: { 'X-Filename': encodeURIComponent(name) }, body: file });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.error || 'השרת לא הצליח לקרוא את הקובץ');
        text = j.text;
      } catch (e) {
        if (k === 'pdf') throw e;
        text = await readOffice(await file.arrayBuffer(), name);
      }
    } else if (k === 'office') {
      text = await readOffice(await file.arrayBuffer(), name);
    } else {
      throw new Error('קריאת PDF דורשת חיבור לשרת. נסה שוב בעוד רגע.');
    }
    text = String(text || '').replace(/[‎‏‪-‮⁦-⁩]/g, '').replace(/\n{3,}/g, '\n\n').trim();
    if (!text) throw new Error('לא נמצא טקסט בקובץ');
    return { name, size: file.size, kind: k, text: text.slice(0, MAX_TEXT), truncated: text.length > MAX_TEXT, added: Date.now() };
  }

  // ------------------------------------------------------------ chunks and search
  function chunks(f) {
    const lines = f.text.split('\n');
    const out = [];
    let start = 0, buf = [], size = 0;
    const flush = (end) => { if (buf.join('').trim()) out.push({ id: `upload:${f.name}:${start + 1}`, repo: 'upload', path: f.name, start: start + 1, end, title: '📎 ' + f.name.split('/').pop(), kind: 'upload', text: buf.join('\n') }); };
    lines.forEach((ln, i) => {
      if (size + ln.length > CHUNK && buf.length) { flush(i); const keep = buf.slice(-2); start = i - keep.length; buf = keep; size = keep.join('').length; }
      buf.push(ln.length > CHUNK * 2 ? ln.slice(0, CHUNK * 2) : ln);
      size += ln.length;
    });
    flush(lines.length);
    return out;
  }

  const cache = new WeakMap();
  /** The excerpts of the attached files that best answer `query` (at most `k`). */
  function pick(files, query, k = 6, tokenizer = null) {
    if (!files || !files.length || !root.YakovEngine || !tokenizer) return [];
    let ix = cache.get(files);
    if (!ix || ix.count !== files.length) {
      const all = files.flatMap(chunks);
      ix = { count: files.length, index: new root.YakovEngine.Index({ owner: '', repos: [], chunks: all, tokenizer: { ...tokenizer, aliases: {} } }), all };
      cache.set(files, ix);
    }
    const hits = ix.index.search(query, { k }).map((h) => h.chunk);
    const firsts = [];
    // "summarise this file" matches nothing in particular: give the start of each (few) file(s)
    if (hits.length < k) for (const f of files.slice(-3)) { const c = ix.all.find((x) => x.path === f.name); if (c) firsts.push(c); }
    const seen = new Set();
    return [...firsts.slice(0, Math.max(0, k - hits.length)), ...hits].filter((c) => !seen.has(c.id) && seen.add(c.id)).slice(0, k);
  }

  // ------------------------------------------------------------ IndexedDB (localStorage is too small for documents)
  const DB = {
    db: null,
    open() {
      if (this.db) return this.db;
      this.db = new Promise((res, rej) => {
        if (!root.indexedDB) return rej(new Error('no indexedDB'));
        const r = indexedDB.open('yakovllm', 1);
        r.onupgradeneeded = () => r.result.createObjectStore('files');
        r.onsuccess = () => res(r.result);
        r.onerror = () => rej(r.error);
      });
      return this.db;
    },
    async get(chatId) {
      try { const db = await this.open(); return await new Promise((res) => { const q = db.transaction('files').objectStore('files').get(chatId); q.onsuccess = () => res(q.result || []); q.onerror = () => res([]); }); } catch { return []; }
    },
    async put(chatId, files) {
      try { const db = await this.open(); db.transaction('files', 'readwrite').objectStore('files').put(files, chatId); } catch { /* private mode: keep in memory only */ }
    },
    async del(chatId) {
      try { const db = await this.open(); db.transaction('files', 'readwrite').objectStore('files').delete(chatId); } catch { /* ignore */ }
    },
  };

  /** Files from a drop event, folders included (recursively). */
  async function fromDrop(dt) {
    const items = [...(dt.items || [])].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    if (!items.length) return [...(dt.files || [])];
    const out = [];
    const walk = async (entry, path) => {
      if (out.length >= MAX_FILES) return;
      if (entry.isFile) {
        const f = await new Promise((res) => entry.file(res, () => res(null)));
        if (f) { try { Object.defineProperty(f, 'webkitRelativePath', { value: path + f.name }); } catch { /* read-only */ } out.push(f); }
      } else if (entry.isDirectory && !SKIP_DIRS.test(path + entry.name + '/')) {
        const reader = entry.createReader();
        for (;;) {
          const batch = await new Promise((res) => reader.readEntries(res, () => res([])));
          if (!batch.length) break;
          for (const e of batch) await walk(e, path + entry.name + '/');
        }
      }
    };
    for (const e of items) await walk(e, '');
    return out;
  }

  const api = { read, pick, chunks, supported, kind, DB, fromDrop, MAX_FILES, SKIP_DIRS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.YakovFiles = api;
})(typeof window !== 'undefined' ? window : globalThis);
