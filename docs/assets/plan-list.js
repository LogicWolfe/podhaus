/*
 * Populates the plans index by fetching nginx's autoindex JSON view of
 * the plans directory. New .md / .html files dropped into docs/plans/
 * appear here on next page load — no manifest, no rebuild.
 *
 * The JSON listing is served from /plans-listing.json (see nginx.conf in
 * docs-server/). Each plan-viewer URL routes .md files through
 * /plans/plan-viewer.html?file=... and .html files directly to their own
 * URL (full pages using the shared shell).
 */

(function () {
  const target = document.getElementById('plans-list');
  if (!target) return;

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, ch => ({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
    }[ch]));
  }

  function formatDate(s) {
    if (!s) return '';
    // nginx autoindex_localtime emits e.g. "2026-05-11T09:30:00+08:00"
    try {
      const d = new Date(s);
      if (Number.isNaN(d.getTime())) return s;
      return d.toISOString().slice(0, 10);
    } catch (_) { return s; }
  }

  function formatSize(n) {
    if (typeof n !== 'number') return '';
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n/1024).toFixed(1)} KB`;
    return `${(n/(1024*1024)).toFixed(1)} MB`;
  }

  function titleFromFilename(name) {
    return name
      .replace(/\.(md|html?)$/i, '')
      .replace(/[-_]+/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }

  async function resolveDirPlan(name) {
    // Directory plan: pick its index file (index.md preferred) and use
    // that as the entry point. Falls back to first .md alphabetically.
    try {
      const r = await fetch(`/_listing/plans/${encodeURIComponent(name)}/`, { cache: 'no-store' });
      if (!r.ok) return null;
      const children = await r.json();
      const docs = children
        .filter(e => e.type === 'file' && /\.(md|html)$/i.test(e.name));
      const idx = docs.find(f => /^index\.md$/i.test(f.name))
        || docs.find(f => /^index\.html$/i.test(f.name))
        || docs.sort((a, b) => a.name.localeCompare(b.name))[0];
      return {
        indexFile: idx ? idx.name : null,
        pageCount: docs.length,
      };
    } catch (_) { return null; }
  }

  fetch('/_listing/plans/', { cache: 'no-store' })
    .then(r => r.ok ? r.json() : Promise.reject(new Error('listing fetch failed')))
    .then(async (entries) => {
      const fileEntries = entries
        .filter(e => e.type === 'file' && /\.(md|html?)$/i.test(e.name))
        .filter(e => e.name !== 'index.html' && e.name !== 'plan-viewer.html')
        .map(e => ({ kind: 'file', e }));
      const dirEntries = entries
        .filter(e => e.type === 'directory')
        .map(e => ({ kind: 'dir', e }));

      // Resolve each dir to its index file + child count, in parallel.
      const resolvedDirs = await Promise.all(dirEntries.map(async (d) => {
        const info = await resolveDirPlan(d.e.name);
        return info ? { ...d, info } : null;
      }));

      const plans = [
        ...fileEntries,
        ...resolvedDirs.filter(Boolean),
      ].sort((a, b) => (b.e.mtime || '').localeCompare(a.e.mtime || ''));

      if (plans.length === 0) {
        target.innerHTML = `<p class="text-text-muted italic">No plans yet — drop a .md file into <code>docs/plans/</code>.</p>`;
        return;
      }

      target.innerHTML = plans.map(p => {
        if (p.kind === 'file') {
          const ext = p.e.name.toLowerCase().endsWith('.md') ? 'MD' : 'HTML';
          const href = ext === 'MD'
            ? `/plans/plan-viewer.html?file=${encodeURIComponent(p.e.name)}`
            : `/plans/${encodeURIComponent(p.e.name)}`;
          return `<a class="plan-row" href="${href}">
            <span class="plan-badge">${ext}</span>
            <span class="plan-name">${escapeHtml(titleFromFilename(p.e.name))}</span>
            <span class="plan-meta">${formatSize(p.e.size)} · ${formatDate(p.e.mtime)}</span>
          </a>`;
        }
        // Directory plan
        const idx = p.info.indexFile;
        const href = idx
          ? (/\.html$/i.test(idx)
              ? `/plans/${encodeURIComponent(p.e.name)}/${encodeURIComponent(idx)}`
              : `/plans/plan-viewer.html?file=${encodeURIComponent(p.e.name)}/${encodeURIComponent(idx)}`)
          : `/plans/${encodeURIComponent(p.e.name)}/`;
        const sub = p.info.pageCount > 1 ? ` · ${p.info.pageCount} pages` : '';
        return `<a class="plan-row" href="${href}">
          <span class="plan-badge">DIR</span>
          <span class="plan-name">${escapeHtml(titleFromFilename(p.e.name))}</span>
          <span class="plan-meta">${formatDate(p.e.mtime)}${sub}</span>
        </a>`;
      }).join('');
    })
    .catch(err => {
      target.innerHTML = `<p class="text-text-muted">Could not load plan list (${escapeHtml(err.message)}). When viewed via <code>file://</code> the autoindex JSON isn't available — open <code>https://docs.pod.haus/plans/</code> instead.</p>`;
    });
})();
