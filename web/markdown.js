/* A small, safe Markdown renderer for streamed answers.
 * Everything is HTML-escaped first; only the constructs below become markup.
 * Citations like [1] or [1, 3] become buttons that open the cited source. */
(function (root) {
  'use strict';

  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const KEYWORDS = new Set(('def class return if elif else for while in not and or import from as with try except finally raise ' +
    'lambda yield async await pass break continue None True False self function const let var new this export default ' +
    'interface type enum extends implements public private protected static readonly null undefined true false switch case ' +
    'throw catch typeof instanceof void of do').split(' '));

  // One pass over the raw code; each piece is escaped on its own, so the highlighter can never inject markup.
  function highlight(code, lang) {
    const hashComments = /^(py|python|sh|bash|yaml|yml|toml|ini|dockerfile|rb)$/i.test(lang || '');
    const re = hashComments
      ? /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|\b(\d+(?:\.\d+)?)\b|\b([A-Za-z_]\w*)\b/g
      : /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|(`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|\b(\d+(?:\.\d+)?)\b|\b([A-Za-z_$][\w$]*)\b/g;
    let out = '', last = 0, m;
    while ((m = re.exec(code))) {
      out += esc(code.slice(last, m.index));
      if (m[1]) out += `<span class="tk-c">${esc(m[1])}</span>`;
      else if (m[2]) out += `<span class="tk-s">${esc(m[2])}</span>`;
      else if (m[3]) out += `<span class="tk-n">${esc(m[3])}</span>`;
      else if (m[4]) out += KEYWORDS.has(m[4]) ? `<span class="tk-k">${esc(m[4])}</span>` : esc(m[4]);
      last = re.lastIndex;
    }
    return out + esc(code.slice(last));
  }

  // Some models still emit LaTeX math ($\\le 5$). Turn the common symbols into plain characters.
  const TEX = { le: '≤', leq: '≤', ge: '≥', geq: '≥', times: '×', to: '→', rightarrow: '→', leftarrow: '←', approx: '≈',
    neq: '≠', ne: '≠', pm: '±', cdot: '·', deg: '°', circ: '°', infty: '∞', sim: '~', ldots: '…', dots: '…' };
  function untex(s) {
    return s.replace(/\$([^$\n]{1,80})\$/g, (whole, body) => {
      if (!/\\[a-z]+|\^|_\{/.test(body)) return whole;            // a plain dollar amount, leave it
      return body.replace(/\^\{?\\circ\}?/g, '°').replace(/\\(?:text|mathrm|mathbf)\{([^}]*)\}/g, '$1')
        .replace(/\\([a-z]+)/g, (m, w) => TEX[w] || m)
        .replace(/[{}]/g, '').replace(/\s+/g, ' ').trim();
    });
  }

  function inline(s, ctx) {
    s = untex(s);
    // protect inline code first
    const codes = [];
    s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
    s = esc(s);
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?=[^*\w]|$)/g, '$1<em>$2</em>');
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>`);
    // citations: [1] [2, 3] [1][2]
    s = s.replace(/\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g, (whole, nums) => nums.split(',').map((n) => {
      n = n.trim();
      const src = ctx && ctx.sources && ctx.sources[+n - 1];
      if (!src) return `[${n}]`;
      const label = src.path === '(overview)' ? src.repo : src.path.split('/').pop();
      return `<button class="cite" data-src="${+n - 1}" title="${esc(src.repo + ' › ' + src.path + ' · ' + src.start + '–' + src.end)}">${n}<span class="sr-only"> ${esc(label)}</span></button>`;
    }).join(''));
    s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
    return s;
  }

  function render(md, ctx) {
    const lines = md.replace(/\r\n/g, '\n').split('\n');
    const out = [];
    let i = 0;
    let para = [];
    const flushPara = () => { if (para.length) { out.push(`<p dir="auto">${inline(para.join(' '), ctx)}</p>`); para = []; } };

    while (i < lines.length) {
      const line = lines[i];
      const fence = line.match(/^\s*(```+|~~~+)\s*([\w+#.-]*)/);
      if (fence) {
        flushPara();
        const mark = fence[1], lang = fence[2] || '';
        const body = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith(mark)) body.push(lines[i++]);
        const closed = i < lines.length;
        i++;
        const code = body.join('\n');
        out.push(`<div class="codeblock"><header><span>${esc(lang || 'code')}</span>` +
          `<button class="copy-btn" data-copy>${ICON_COPY}<span>העתק</span></button></header>` +
          `<pre><code>${highlight(code, lang)}${closed ? '' : ''}</code></pre></div>`);
        continue;
      }
      if (/^\s*$/.test(line)) { flushPara(); i++; continue; }
      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) { flushPara(); out.push(`<h${h[1].length} dir="auto">${inline(h[2], ctx)}</h${h[1].length}>`); i++; continue; }
      if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) { flushPara(); out.push('<hr>'); i++; continue; }
      if (/^\s*>/.test(line)) {
        flushPara();
        const q = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ''));
        out.push(`<blockquote dir="auto">${render(q.join('\n'), ctx)}</blockquote>`);
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        flushPara();
        const row = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
        const head = row(line);
        i += 2;
        let html = '<table dir="auto"><thead><tr>' + head.map((c) => `<th>${inline(c, ctx)}</th>`).join('') + '</tr></thead><tbody>';
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          html += '<tr>' + row(lines[i++]).map((c) => `<td>${inline(c, ctx)}</td>`).join('') + '</tr>';
        }
        out.push(html + '</tbody></table>');
        continue;
      }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        flushPara();
        out.push(list(lines, i, ctx, (n) => { i = n; }));
        continue;
      }
      para.push(line.trim());
      i++;
    }
    flushPara();
    return out.join('');
  }

  function list(lines, start, ctx, done) {
    const indentOf = (l) => l.match(/^\s*/)[0].replace(/\t/g, '    ').length;
    const base = indentOf(lines[start]);
    const ordered = /^\s*\d+[.)]/.test(lines[start]);
    const startNum = ordered ? parseInt(lines[start].trim(), 10) : 1;
    let html = ordered ? `<ol dir="auto"${startNum !== 1 ? ` start="${startNum}"` : ''}>` : '<ul dir="auto">';
    let i = start;
    let item = null;
    const close = () => { if (item !== null) { html += `<li>${item}</li>`; item = null; } };
    while (i < lines.length) {
      const l = lines[i];
      if (/^\s*$/.test(l)) {
        // a blank line ends the list unless the next line continues it
        const nx = lines[i + 1];
        if (nx && /^\s*([-*+]|\d+[.)])\s+/.test(nx) && indentOf(nx) >= base) { i++; continue; }
        break;
      }
      const ind = indentOf(l);
      const m = l.match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
      if (m && ind === base) {
        close();
        item = inline(m[2], ctx);
        i++;
      } else if (m && ind > base) {
        item = (item || '') + list(lines, i, ctx, (n) => { i = n; });
      } else if (ind > base && item !== null) {
        item += ' ' + inline(l.trim(), ctx);
        i++;
      } else break;
    }
    close();
    done(i);
    return html + (ordered ? '</ol>' : '</ul>');
  }

  const ICON_COPY = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';

  const api = { render, highlight, esc };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.YakovMarkdown = api;
})(typeof window !== 'undefined' ? window : globalThis);
