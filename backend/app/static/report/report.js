/* Optional enhancements. All sections and the new layout also work without JS. */
(function () {
  'use strict';
  var publication = document.querySelector('[data-konverter-publication]');
  if (!publication) return;
  publication.dataset.enhanced = 'true';
  var byId = function (id) { return document.getElementById(id); };
  var reduceMotion = function () { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; };
  function focusTarget(target) {
    if (!target) return;
    target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: 'start', behavior: reduceMotion() ? 'auto' : 'smooth' });
  }
  function currentTitle(reader) {
    var title = reader && reader.querySelector('.vlrc-reader-content > h1');
    return title ? title.textContent.trim() : '';
  }
  function setView(inputId, targetId, push) {
    var input = byId(inputId);
    if (!input || !input.classList.contains('vlrc-view-toggle')) return;
    input.checked = true;
    var reader = byId(input.dataset.reader || '');
    var current = publication.querySelector('.breadcrumb-publication-current');
    var link = publication.querySelector('.breadcrumb-publication-link');
    var section = publication.querySelector('.breadcrumb-section-item');
    var sectionTitle = publication.querySelector('.breadcrumb-section-current');
    if (current && link && section && sectionTitle) {
      current.hidden = Boolean(reader); link.hidden = !reader; section.hidden = !reader;
      sectionTitle.textContent = currentTitle(reader);
    }
    publication.querySelectorAll('.vlrc-reader-nav a[aria-current]').forEach(function (a) { a.removeAttribute('aria-current'); });
    if (reader && targetId) reader.querySelectorAll('.vlrc-reader-nav a').forEach(function (a) {
      if (a.getAttribute('href') === '#' + targetId) a.setAttribute('aria-current', 'location');
    });
    if (push) {
      try {
        var url = new URL(window.location.href);
        url.hash = targetId || (reader ? reader.id : 'report-contents');
        window.history.pushState({}, '', url);
      } catch (_) { /* Sandboxed inline preview has no writable address bar. */ }
    }
    window.requestAnimationFrame(function () {
      focusTarget(byId(targetId || (reader ? reader.querySelector('h1').id : 'contents-heading')));
    });
  }
  function readerInput(reader) {
    return Array.from(publication.querySelectorAll('.vlrc-view-toggle')).find(function (input) { return input.dataset.reader === reader.id; });
  }
  publication.addEventListener('click', function (event) {
    var label = event.target.closest('label.vlrc-view-label');
    if (label) {
      event.preventDefault();
      setView(label.htmlFor, label.dataset.headingId, true);
      return;
    }
    var anchor = event.target.closest('a[href^="#"]');
    if (!anchor) return;
    var id;
    try { id = decodeURIComponent(anchor.getAttribute('href').slice(1)); } catch (_) { return; }
    var target = byId(id);
    if (!target) return;
    event.preventDefault();
    var reader = target.closest('.vlrc-reader');
    if (reader) {
      var input = readerInput(reader);
      if (input) setView(input.id, id, true);
      var notes = target.closest('details');
      if (notes) notes.open = true;
    } else if (anchor.classList.contains('breadcrumb-publication-link')) {
      setView('vlrc-view-landing', 'contents-heading', true);
    } else if (target.closest('#publication-landing')) { setView('vlrc-view-landing', id, true); } else { focusTarget(target); }
  });
  publication.addEventListener('keydown', function (event) {
    var label = event.target.closest('label.vlrc-view-label');
    if (label && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); label.click(); }
  });
  publication.querySelectorAll('.vlrc-reader-nav').forEach(function (nav) {
    var list = nav.querySelector('ul');
    if (!list || !list.children.length) { nav.hidden = true; return; }
    var button = document.createElement('button');
    button.type = 'button'; button.className = 'reader-nav-toggle';
    button.textContent = 'In this section ⌄';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', list.id);
    nav.insertBefore(button, list);
    button.addEventListener('click', function () { button.setAttribute('aria-expanded', String(nav.classList.toggle('is-open'))); });
    list.addEventListener('click', function () { nav.classList.remove('is-open'); button.setAttribute('aria-expanded', 'false'); });
  });
  var copy = publication.querySelector('.report-copy-citation');
  // In a sandboxed iframe without allow-same-origin (how the app previews
  // this same document), the page has an opaque origin: no permission can
  // ever be granted to it, so navigator.clipboard.writeText neither
  // resolves nor rejects — it just hangs forever, silently skipping the
  // execCommand fallback below. Racing it against a short timeout is what
  // actually lets that fallback run in that context.
  function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { reject(new Error('Clipboard API timed out')); }, ms);
      promise.then(
        function (value) { clearTimeout(timer); resolve(value); },
        function (error) { clearTimeout(timer); reject(error); },
      );
    });
  }
  if (copy) copy.addEventListener('click', async function () {
    var text = (copy.getAttribute('data-citation') || '').trim();
    var status = publication.querySelector('.citation-copy-status');
    if (!text || !status) return;
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await withTimeout(navigator.clipboard.writeText(text), 800);
      status.textContent = 'Citation copied.';
    } catch (_) {
      var textarea = document.createElement('textarea');
      textarea.value = text; textarea.style.position = 'fixed'; textarea.style.left = '-9999px';
      document.body.appendChild(textarea); textarea.select();
      try {
        if (!document.execCommand('copy')) throw new Error('Copy unavailable');
        status.textContent = 'Citation copied.';
      } catch (_) { status.textContent = 'Citation could not be copied. Please try again.'; focusTarget(copy); }
      textarea.remove();
    }
  });
  var topButton = document.createElement('button');
  topButton.type = 'button'; topButton.className = 'back-to-top'; topButton.textContent = 'Back to top ↑';
  publication.appendChild(topButton);
  function updateTop() {
    var visible = window.scrollY > Math.max(420, window.innerHeight*.55);
    topButton.classList.toggle('is-visible', visible); topButton.tabIndex = visible ? 0 : -1;
    topButton.setAttribute('aria-hidden', String(!visible));
  }
  topButton.addEventListener('click', function () { window.scrollTo({top:0, behavior:reduceMotion()?'auto':'smooth'}); });
  window.addEventListener('scroll', updateTop, {passive:true}); updateTop();
  function applyHash() {
    var target;
    try { target = byId(decodeURIComponent(window.location.hash.slice(1))); } catch (_) { return; }
    var reader = target && target.closest('.vlrc-reader');
    if (reader) { var input = readerInput(reader); if (input) setView(input.id, target.id, false); }
    else if (target) setView('vlrc-view-landing', target.id, false);
    else setView('vlrc-view-landing', null, false);
  }
  window.addEventListener('popstate', applyHash);
  window.addEventListener('hashchange', applyHash);
  if (window.location.hash) applyHash();
})();
