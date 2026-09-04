// Router, API access and the live headline.
//
// The headline recomputes after every write, because every write endpoint
// returns fresh totals. That is the automation made visible: change one number
// and the figures that depend on it move on their own, with no linking step.

export const api = {
  async get(path) {
    const r = await fetch(`/api${path}`);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    return r.json();
  },
  async send(method, path, body) {
    const r = await fetch(`/api${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || data.error || r.statusText);
    if (data.headline) setHeadline(data.headline);
    return data;
  },
  put: (path, body) => api.send('PUT', path, body),
  post: (path, body) => api.send('POST', path, body),
};

// ---------------------------------------------------------------- formatting

export const fmt = {
  n(v, dp = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    return Number(v).toLocaleString('en-IN', {
      minimumFractionDigits: dp, maximumFractionDigits: dp,
    });
  },
  int(v) { return v === null || v === undefined ? '—' : Math.round(v).toLocaleString('en-IN'); },
  // Indian money, because a QS reads lakh and crore, not millions.
  money(v) {
    if (v === null || v === undefined) return '—';
    const n = Number(v);
    if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
    if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
    return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  },
  rate(v) { return v === null || v === undefined ? '—' : `₹${fmt.n(v, 2)}`; },
};

export function toast(message, bad = false) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = bad ? 'bad' : '';
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, bad ? 6000 : 2600);
}

// ---------------------------------------------------------------- headline

let lastHeadline = null;

export function setHeadline(h) {
  const prev = lastHeadline;
  lastHeadline = h;
  document.getElementById('projectName').textContent = h.project.name;
  document.getElementById('projectSub').textContent =
    `${h.project.city || ''}${h.project.city ? ' · ' : ''}${h.floors} floors · ${h.rooms} rooms`;

  const stats = [
    ['Flats', fmt.int(h.flats)],
    ['Offices', fmt.int(h.offices)],
    ['Carpet area', `${fmt.int(h.carpet_area_sqft)} sq.ft`],
    ['Doors', fmt.int(h.doors)],
    ['Height', `${h.building_height_m} m`],
  ];
  const bar = document.getElementById('headline');
  bar.innerHTML = stats.map(([k, v], i) =>
    `<div class="stat" data-i="${i}"><div class="v">${v}</div><div class="k">${k}</div></div>`
  ).join('');

  // Flash whatever moved, so a change is never silent.
  if (prev) {
    const before = [prev.flats, prev.offices, Math.round(prev.carpet_area_sqft),
                    prev.doors, prev.building_height_m];
    const after = [h.flats, h.offices, Math.round(h.carpet_area_sqft),
                   h.doors, h.building_height_m];
    after.forEach((v, i) => {
      if (v !== before[i]) bar.querySelector(`[data-i="${i}"]`)?.classList.add('changed');
    });
  }

  const chip = document.getElementById('healthChip');
  const { blocking, warnings, score } = h.health;
  const cls = blocking ? 'bad' : warnings ? 'warn' : 'ok';
  chip.innerHTML =
    `<a href="#/validation" class="chip ${cls}" style="text-decoration:none">
       ${blocking ? `⛔ ${blocking} blocking` : warnings ? `⚠ ${warnings} warnings` : '✓ clear'}
     </a>
     <span class="chip mute">health ${score}</span>`;
}

export function headline() { return lastHeadline; }

// ---------------------------------------------------------------- routing

const routes = {};
export function route(path, loader) { routes[path] = loader; }

async function render() {
  const { clearUndo } = await import('./grid.js');
  const hash = location.hash.replace(/^#/, '') || '/overview';
  const [path] = hash.split('?');
  const base = '/' + (path.split('/')[1] || 'overview');
  // Undo history belongs to the screen you are on, not to the whole session.
  if (base !== render._lastBase) { clearUndo(); render._lastBase = base; }
  document.querySelectorAll('[data-nav]').forEach(a =>
    a.classList.toggle('active', a.getAttribute('href') === `#${base}`));
  closePanel();

  const main = document.getElementById('main');
  const loader = routes[base];
  if (!loader) { main.innerHTML = `<div class="loading">Nothing at ${base}</div>`; return; }
  main.innerHTML = '<div class="loading">Loading…</div>';
  try {
    await loader(main, hash);
  } catch (err) {
    main.innerHTML = `<div class="card"><div class="card-body">
      <strong>Could not load this screen.</strong>
      <p class="muted">${err.message}</p></div></div>`;
  }
}

export function go(hash) { location.hash = hash; }
export function refresh() { return render(); }

// ---------------------------------------------------------------- panel

export function openPanel(title, html) {
  document.getElementById('panelTitle').textContent = title;
  document.getElementById('panelBody').innerHTML = html;
  document.getElementById('panel').hidden = false;
}
export function closePanel() { document.getElementById('panel').hidden = true; }

document.getElementById('panelClose').onclick = closePanel;
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });
window.addEventListener('hashchange', render);

// ---------------------------------------------------------------- boot

// Screens are imported dynamically, not with a static `import`. Static imports
// are hoisted and run before this module's own body, so a screen calling
// route() at the top level would reach `routes` before it exists. Loading them
// here makes the ordering explicit instead of accidental.
const SCREENS = [
  'overview', 'room-config', 'unit-types', 'openings', 'rates', 'mapping',
  'takeoff', 'finish-totals', 'cost-lines', 'summary', 'parameters',
  'validation', 'reconciliation', 'audit', 'projects',
];

// Which build is on screen.
//
// The UI is served with `Cache-Control: no-store` so a reload always fetches
// current code -- before that, a browser could reuse an old `app.js` for hours
// and a pulled change simply would not appear. This stamp makes that visible
// rather than something to be trusted.
// Signing in is switched off (`server.ACCOUNTS_REQUIRED`), so there is nobody
// to name and nothing to ask for. The slot stays in the header, empty, because
// the accounts underneath are intact and this is where they will show again.
async function showWho() {
  try {
    const me = await api.get('/me');
    const el = document.getElementById('whoami');
    if (!el) return;
    el.innerHTML = me.accounts_required && me.signed_in
      ? `<span class="chip mute" title="${escapeAttr(me.user.email)}"
          >${escapeAttr(me.user.name)}</span>`
      : '';
  } catch { /* never block the app on this */ }
}

function escapeAttr(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function showBuild() {
  try {
    const v = await api.get('/version');
    const el = document.getElementById('buildStamp');
    if (!el || !v.commit || v.commit === 'unknown') return;
    el.innerHTML = `<span class="chip mute" title="${v.branch || ''} · ${
      v.committed_at || ''}">build ${v.commit}</span>`;
  } catch { /* a missing stamp must never stop the app */ }
}

(async function boot() {
  await Promise.all(SCREENS.map(name => import(`./screens/${name}.js`)));
  showBuild();
  showWho();
  try {
    setHeadline(await api.get('/headline'));
  } catch (err) {
    document.getElementById('main').innerHTML =
      `<div class="card"><div class="card-body">
        <strong>No project loaded.</strong>
        <p class="muted">Run <code>make seed</code> to import the workbook, then reload.</p>
        <p class="muted">${err.message}</p></div></div>`;
    return;
  }
  await render();
})();
