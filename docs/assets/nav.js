/*
 * Auto-discovering navigation for the podhaus docs site.
 *
 * Source of truth = the filesystem. New .html files dropped into /docs/ or
 * /docs/runbooks/ appear in the sidebar on the next page load — no manifest,
 * no rebuild. Each page can declare its position via meta tags in <head>:
 *
 *     <meta name="doc-group" content="Platform">
 *     <meta name="doc-order" content="2">
 *     <meta name="doc-title" content="Komodo">     (optional override)
 *
 * Missing tags fall back to: group inferred from the directory
 * (top-level → "Docs"; /runbooks/ → "Service runbooks"; etc.), title from
 * <title> or filename, order from filename's leading number or 999.
 *
 * nginx exposes JSON directory listings via the autoindex_format directive:
 *   /_listing/             → root of /docs/ (top-level pages)
 *   /_listing/runbooks/    → service runbooks
 *   /_listing/plans/       → top-level plans (files + directory plans)
 *   /_listing/plans/<dir>/ → sub-pages of a nested plan
 *
 * On file:// nav.js falls back to a hardcoded list of the canonical pages
 * (kept in sync below) so local-disk previews still have a working sidebar.
 */

(function () {
  const THEME_KEY = 'podhaus-docs-theme';

  // Group display order (anything not listed falls in at the end alphabetically).
  const GROUP_ORDER = [
    'Getting started',
    'Platform',
    'Operations',
    'Service runbooks',
    'Plans',
  ];

  // Fallback list of documents — used when nginx autoindex isn't available
  // (file:// preview, dev mode without docs-server). Kept here rather than
  // in a separate manifest so the file:// experience never silently breaks.
  const FALLBACK_DOCS = [
    { path: '/index.html',                            group: 'Getting started',  order: 0, title: 'Overview' },
    { path: '/architecture.html',                     group: 'Getting started',  order: 1, title: 'Architecture' },
    { path: '/hosts.html',                            group: 'Getting started',  order: 2, title: 'Hosts' },
    { path: '/storage.html',                          group: 'Getting started',  order: 3, title: 'Storage' },
    { path: '/networking.html',                       group: 'Getting started',  order: 4, title: 'Networking' },
    { path: '/komodo.html',                           group: 'Platform',         order: 1, title: 'Komodo' },
    { path: '/secrets.html',                          group: 'Platform',         order: 2, title: 'Secrets & variables' },
    { path: '/stack-conventions.html',                group: 'Platform',         order: 3, title: 'Stack conventions' },
    { path: '/backup-and-recovery.html',              group: 'Operations',       order: 1, title: 'Backup & recovery' },
    { path: '/monitoring.html',                       group: 'Operations',       order: 2, title: 'Monitoring' },
    { path: '/scheduling.html',                       group: 'Operations',       order: 3, title: 'Scheduling' },
    { path: '/disaster-recovery.html',                group: 'Operations',       order: 4, title: 'Disaster recovery' },
    { path: '/runbooks/plex.html',                    group: 'Service runbooks', order: 1, title: 'Plex' },
    { path: '/runbooks/plex-maintenance.html',        group: 'Service runbooks', order: 2, title: 'Plex maintenance log' },
    { path: '/runbooks/paperless.html',               group: 'Service runbooks', order: 3, title: 'Paperless' },
    { path: '/runbooks/syncthing.html',               group: 'Service runbooks', order: 4, title: 'Syncthing' },
    { path: '/runbooks/flood.html',                   group: 'Service runbooks', order: 5, title: 'Flood + RAR pipeline' },
    { path: '/plans/index.html',                      group: 'Plans',            order: 0, title: 'All plans' },
  ];

  // ---------- theme handling ----------
  const root = document.documentElement;

  function currentTheme()    { return localStorage.getItem(THEME_KEY) || 'system'; }
  function nextTheme(t)      { return t === 'system' ? 'light' : t === 'light' ? 'dark' : 'system'; }
  function themeIcon(t)      { return t === 'dark' ? '🌙' : t === 'light' ? '☀' : '◐'; }
  function applyTheme(t) {
    const resolved = t === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : t;
    root.classList.toggle('dark', resolved === 'dark');
  }
  applyTheme(currentTheme());
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (currentTheme() === 'system') applyTheme('system');
  });

  // ---------- helpers ----------
  function normalize(href) {
    try { return new URL(href, window.location.origin).pathname; }
    catch (_) { return href; }
  }

  // Pathname + query — used for active-link comparison so that
  // /plans/plan-viewer.html?file=test-plan.md and
  // /plans/plan-viewer.html?file=foo.md are distinguished.
  function urlKey(href) {
    try {
      const u = new URL(href, window.location.origin);
      return u.pathname + u.search;
    } catch (_) { return href; }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, ch => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[ch]));
  }

  function titleFromFilename(name) {
    return name
      .replace(/\.(md|html?)$/i, '')
      .replace(/^[0-9]+[-_]/, '')
      .replace(/[-_]+/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }

  function inferGroup(path) {
    if (path.startsWith('/runbooks/'))  return 'Service runbooks';
    if (path.startsWith('/plans/'))     return 'Plans';
    return 'Docs';
  }

  function inferOrder(name) {
    const m = name.match(/^([0-9]+)[-_]/);
    return m ? parseInt(m[1], 10) : 999;
  }

  // ---------- discovery ----------
  // `cache: 'no-store'` on every fetch — nav rebuilds on every page load
  // from a fresh network read, no localStorage cache. Combined with the
  // nginx-side `Cache-Control: no-store` headers this site sends, no
  // version of a response is ever stored client-side.
  async function fetchListing(url) {
    try {
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) return null;
      return r.json();
    } catch (_) { return null; }
  }

  // Decode the small set of HTML entities that show up in <title> and
  // <meta content="..."> extracts (regex matches raw source, so &amp;,
  // &lt;, etc. come back literal — re-escaping later would render
  // "&amp;" in the sidebar instead of "&").
  function decodeEntities(s) {
    if (!s) return s;
    return s
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'");
  }

  async function extractMetas(path) {
    try {
      const r = await fetch(path, { cache: 'no-store' });
      if (!r.ok) return {};
      const text = await r.text();
      // Look only in the first ~4 KB. Saves bandwidth on long pages.
      const head = text.slice(0, 4096);
      const get = (name) => {
        const m = head.match(new RegExp(`<meta\\s+name=["']${name}["']\\s+content=["']([^"']+)["']`, 'i'));
        return m ? decodeEntities(m[1]) : null;
      };
      const titleMatch = head.match(/<title>([^<]+)<\/title>/i);
      return {
        group: get('doc-group'),
        order: get('doc-order'),
        title: get('doc-title') || (titleMatch ? decodeEntities(titleMatch[1]).split('—')[0].trim() : null),
      };
    } catch (_) { return {}; }
  }

  async function discover() {
    const [docsList, runbooksList, plansList] = await Promise.all([
      fetchListing('/_listing/'),
      fetchListing('/_listing/runbooks/'),
      fetchListing('/_listing/plans/'),
    ]);

    if (!docsList) {
      // We're probably on file:// — use the fallback table.
      return FALLBACK_DOCS.slice();
    }

    function fileEntries(list, dirPath) {
      return (list || [])
        .filter(e => e.type === 'file' && /\.html$/i.test(e.name))
        .filter(e => !e.name.startsWith('_') && e.name !== 'plan-viewer.html')
        .map(e => ({
          path: dirPath + e.name,
          name: e.name,
          group: null,
          order: null,
          title: null,
          mtime: e.mtime,
        }));
    }

    const candidates = [
      ...fileEntries(docsList, '/'),
      ...fileEntries(runbooksList, '/runbooks/'),
    ];

    // Plans group: "All plans" index first, then each individual plan
    // (.md goes via /plans/plan-viewer.html?file=..., .html links direct,
    // a directory becomes a parent entry pointing at its index.md with
    // its sub-pages as `children`). Sorted by mtime desc so newest work
    // surfaces at the top.
    candidates.push({ path: '/plans/index.html', name: 'index.html', group: 'Plans', order: 0, title: 'All plans', mtime: '' });
    if (plansList) {
      // First the flat files, sorted newest first.
      const planFiles = plansList
        .filter(e => e.type === 'file' && /\.(md|html)$/i.test(e.name))
        .filter(e => e.name !== 'index.html' && e.name !== 'plan-viewer.html')
        .sort((a, b) => Date.parse(b.mtime || 0) - Date.parse(a.mtime || 0));
      planFiles.forEach((e, i) => {
        const isHtml = /\.html$/i.test(e.name);
        const href = isHtml
          ? `/plans/${encodeURIComponent(e.name)}`
          : `/plans/plan-viewer.html?file=${encodeURIComponent(e.name)}`;
        candidates.push({
          path: href,
          name: e.name,
          group: 'Plans',
          order: 100 + i,
          title: titleFromFilename(e.name),
          mtime: e.mtime,
        });
      });

      // Then the directory plans. Each becomes a parent entry whose
      // children are discovered via /_listing/plans/<dir>/.
      const planDirs = plansList
        .filter(e => e.type === 'directory')
        .sort((a, b) => Date.parse(b.mtime || 0) - Date.parse(a.mtime || 0));
      const childPromises = planDirs.map(async (dir, i) => {
        const sub = await fetchListing(`/_listing/plans/${dir.name}/`);
        const childFiles = (sub || [])
          .filter(e => e.type === 'file' && /\.(md|html)$/i.test(e.name))
          .sort((a, b) => a.name.localeCompare(b.name, 'en', { numeric: true }));
        // Pick the index entry — prefer index.md, then index.html, then
        // fall back to the first file alphabetically.
        const indexFile =
          childFiles.find(f => /^index\.md$/i.test(f.name)) ||
          childFiles.find(f => /^index\.html$/i.test(f.name)) ||
          childFiles[0];
        const parentHref = indexFile
          ? (/\.html$/i.test(indexFile.name)
              ? `/plans/${encodeURIComponent(dir.name)}/${encodeURIComponent(indexFile.name)}`
              : `/plans/plan-viewer.html?file=${encodeURIComponent(dir.name)}/${encodeURIComponent(indexFile.name)}`)
          : `/plans/${encodeURIComponent(dir.name)}/`;
        const children = childFiles
          .filter(f => f !== indexFile)
          .map(f => {
            const isHtml = /\.html$/i.test(f.name);
            const href = isHtml
              ? `/plans/${encodeURIComponent(dir.name)}/${encodeURIComponent(f.name)}`
              : `/plans/plan-viewer.html?file=${encodeURIComponent(dir.name)}/${encodeURIComponent(f.name)}`;
            return {
              path: href,
              title: titleFromFilename(f.name),
              parentDir: dir.name,
            };
          });
        candidates.push({
          path: parentHref,
          name: dir.name,
          group: 'Plans',
          order: 200 + i,
          title: titleFromFilename(dir.name),
          mtime: dir.mtime,
          children,
          parentDir: dir.name,
        });
      });
      await Promise.all(childPromises);
    }

    // Hydrate metas in parallel — bounded concurrency would be nice for
    // huge sites but with ~17 files this is fine.
    await Promise.all(candidates.map(async (c) => {
      if (c.title && c.group) return; // /plans/ index pre-populated above
      const m = await extractMetas(c.path);
      c.group = m.group || inferGroup(c.path);
      c.title = m.title || titleFromFilename(c.name);
      c.order = m.order != null ? parseInt(m.order, 10) : inferOrder(c.name);
    }));

    return candidates;
  }

  function groupAndSort(docs) {
    const byGroup = new Map();
    docs.forEach(d => {
      if (!byGroup.has(d.group)) byGroup.set(d.group, []);
      byGroup.get(d.group).push(d);
    });
    byGroup.forEach(arr => arr.sort((a, b) => (a.order ?? 999) - (b.order ?? 999) || a.title.localeCompare(b.title)));

    const groups = [];
    GROUP_ORDER.forEach(label => {
      if (byGroup.has(label)) {
        groups.push({ label, links: byGroup.get(label) });
        byGroup.delete(label);
      }
    });
    [...byGroup.keys()].sort().forEach(label => {
      groups.push({ label, links: byGroup.get(label) });
    });
    return groups;
  }

  // ---------- rendering ----------
  function renderTopbar() {
    const el = document.getElementById('topbar');
    if (!el) return;
    el.innerHTML = `
      <header class="sticky top-0 z-30 h-14 bg-bg/85 backdrop-blur border-b border-border">
        <div class="max-w-screen-2xl mx-auto h-full px-4 sm:px-6 flex items-center justify-between gap-4">
          <a href="/index.html" class="flex items-center gap-2.5 text-text hover:text-primary-700 dark:hover:text-primary-300 transition-colors">
            <span class="inline-flex h-7 w-7 items-center justify-center rounded-md bg-primary-700 text-white font-bold text-sm">P</span>
            <span class="font-semibold tracking-tight">podhaus docs</span>
          </a>
          <div class="flex items-center gap-1">
            <button id="sidebar-toggle" class="lg:hidden inline-flex h-9 w-9 items-center justify-center rounded-md text-text-muted hover:bg-bg-soft" aria-label="Toggle sidebar">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
            </button>
            <button id="theme-toggle" class="inline-flex h-9 min-w-9 items-center justify-center rounded-md text-text-muted hover:bg-bg-soft px-2 text-base" aria-label="Toggle theme">
              ${themeIcon(currentTheme())}
            </button>
            <a href="https://github.com/LogicWolfe/podhaus" target="_blank" rel="noopener" class="inline-flex h-9 w-9 items-center justify-center rounded-md text-text-muted hover:bg-bg-soft" aria-label="GitHub">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.92.58.1.79-.25.79-.56 0-.27-.01-1-.02-1.96-3.2.69-3.87-1.54-3.87-1.54-.52-1.33-1.27-1.69-1.27-1.69-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.76 2.69 1.25 3.34.96.1-.74.4-1.25.72-1.54-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.18-3.1-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.15 1.18a10.94 10.94 0 0 1 5.74 0c2.19-1.49 3.15-1.18 3.15-1.18.62 1.58.23 2.75.11 3.04.74.81 1.18 1.84 1.18 3.1 0 4.42-2.69 5.39-5.25 5.68.41.35.78 1.05.78 2.11 0 1.52-.01 2.75-.01 3.13 0 .31.21.67.79.55C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z"/></svg>
            </a>
          </div>
        </div>
      </header>
    `;
    document.getElementById('theme-toggle').addEventListener('click', (e) => {
      const next = nextTheme(currentTheme());
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
      e.currentTarget.textContent = themeIcon(next);
    });
    const sbToggle = document.getElementById('sidebar-toggle');
    if (sbToggle) {
      sbToggle.addEventListener('click', () => {
        const sb = document.getElementById('sidebar');
        if (sb) sb.classList.toggle('!block');
      });
    }
  }

  function renderSidebar(groups) {
    const el = document.getElementById('sidebar');
    if (!el) return;
    // Use pathname + search so plan-viewer.html?file=foo distinguishes
    // between different plans (they share the same pathname).
    const here = urlKey(window.location.pathname + window.location.search);
    // What plan-dir (if any) is the current page in? Used to decide
    // whether to expand a parent entry's children.
    const hereFile = (new URLSearchParams(window.location.search)).get('file') || '';
    const hereParentDir = hereFile.includes('/') ? hereFile.split('/')[0] : null;

    const html = groups.map(g => {
      const links = g.links.map(l => {
        const active = urlKey(l.path) === here ? ' active' : '';
        const hasChildren = Array.isArray(l.children) && l.children.length > 0;
        const expand = hasChildren && (active || (l.parentDir && l.parentDir === hereParentDir));
        const childrenHtml = expand
          ? l.children.map(c => {
              const cActive = urlKey(c.path) === here ? ' active' : '';
              return `<a class="nav-link nav-link-child${cActive}" href="${c.path}">${escapeHtml(c.title)}</a>`;
            }).join('')
          : '';
        return `<a class="nav-link${active}" href="${l.path}">${escapeHtml(l.title)}</a>${childrenHtml}`;
      }).join('');
      return `<div><span class="nav-group-label">${escapeHtml(g.label)}</span>${links}</div>`;
    }).join('');
    el.innerHTML = `<nav class="scroll-area px-3 py-6 text-sm">${html}</nav>`;
  }

  function renderToc() {
    const el = document.getElementById('toc');
    if (!el) return;
    const main = document.querySelector('main');
    if (!main) return;
    const headings = Array.from(main.querySelectorAll('h2, h3'));
    if (headings.length === 0) { el.innerHTML = ''; return; }
    headings.forEach(h => {
      if (!h.id) {
        h.id = h.textContent.toLowerCase().replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '-');
      }
    });
    const items = headings.map(h => {
      const cls = h.tagName === 'H3' ? 'toc-link h3' : 'toc-link';
      return `<a class="${cls}" href="#${h.id}" data-target="${h.id}">${escapeHtml(h.textContent)}</a>`;
    }).join('');
    el.innerHTML = `
      <div class="scroll-area pt-6 pr-4 text-sm">
        <div class="text-xs font-bold uppercase tracking-wider text-text-muted mb-2">On this page</div>
        <div>${items}</div>
      </div>
    `;
    const links = Array.from(el.querySelectorAll('.toc-link'));
    const map = new Map(links.map(a => [a.dataset.target, a]));
    const obs = new IntersectionObserver(entries => {
      entries.forEach(en => {
        const link = map.get(en.target.id);
        if (!link) return;
        if (en.isIntersecting) {
          links.forEach(l => l.classList.remove('active'));
          link.classList.add('active');
        }
      });
    }, { rootMargin: '-70px 0px -70% 0px' });
    headings.forEach(h => obs.observe(h));
  }

  // ---------- bootstrap ----------
  renderTopbar();
  renderToc();
  discover().then(docs => renderSidebar(groupAndSort(docs)));
})();
