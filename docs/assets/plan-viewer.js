/*
 * Renders a markdown plan file into the shared docs shell. Reads ?file=
 * from the query string, fetches /plans/<file>, parses with marked.js
 * (vendored), injects into <main>. Page title is set from the first H1
 * if present.
 *
 * Only markdown plans flow through this viewer. HTML plans are
 * full-shell pages and are linked directly from the plans index.
 */

(function () {
  const params = new URLSearchParams(window.location.search);
  const file = params.get('file');
  const main = document.querySelector('main');
  if (!main) return;

  // Allow nested plans: ?file=big-plan/phase-1.md works as long as every
  // segment is safe (no .., no leading dot, alphanumeric+dot+dash+underscore).
  // The fetch URL is /plans/<file>; the regex prevents path traversal.
  if (!file || !/^[A-Za-z0-9_][A-Za-z0-9._-]*(\/[A-Za-z0-9_][A-Za-z0-9._-]*)*\.md$/.test(file)) {
    main.innerHTML = `<h1>Plan viewer</h1><p>Open this page via the <a href="/plans/index.html">plans index</a> — direct visits need a <code>?file=&lt;name&gt;.md</code> query.</p>`;
    return;
  }

  fetch(`/plans/${file}`, { cache: 'no-store' })
    .then(r => r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`)))
    .then(md => {
      if (typeof marked === 'undefined') {
        main.innerHTML = `<pre style="white-space:pre-wrap">${md.replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c]))}</pre>`;
        return;
      }
      marked.setOptions({
        gfm: true,
        breaks: false,
        headerIds: true,
        mangle: false,
      });
      const html = marked.parse(md);
      main.innerHTML = html;

      const h1 = main.querySelector('h1');
      if (h1) document.title = `${h1.textContent} — podhaus docs`;

      // Re-trigger TOC build now that headings exist (nav.js already ran
      // before content landed). Dispatch a custom event nav.js can listen
      // for — easier: just re-run the document-level scan by reloading
      // nav.js's exposed re-render. Since nav.js doesn't expose one, we
      // post-process here: ensure headings have ids and rebuild #toc.
      const headings = Array.from(main.querySelectorAll('h2, h3'));
      headings.forEach(h => {
        if (!h.id) {
          h.id = h.textContent.toLowerCase()
            .replace(/[^\w\s-]/g, '')
            .trim()
            .replace(/\s+/g, '-');
        }
      });
      const tocEl = document.getElementById('toc');
      if (tocEl && headings.length) {
        tocEl.innerHTML = `
          <div class="scroll-area pt-6 pr-4 text-sm">
            <div class="text-xs font-bold uppercase tracking-wider text-text-muted mb-2">On this page</div>
            <div>${headings.map(h => {
              const cls = h.tagName === 'H3' ? 'toc-link h3' : 'toc-link';
              return `<a class="${cls}" href="#${h.id}" data-target="${h.id}">${h.textContent}</a>`;
            }).join('')}</div>
          </div>
        `;
        const links = Array.from(tocEl.querySelectorAll('.toc-link'));
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
    })
    .catch(err => {
      main.innerHTML = `<h1>Plan not found</h1><p>Could not load <code>${file}</code>: ${err.message}.</p><p><a href="/plans/index.html">← Back to plans index</a></p>`;
    });
})();
