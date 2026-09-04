// The derivation panel: click any grey figure and see exactly how it was reached.
//
// Nothing is reconstructed here. Every derived value already carries its rule,
// its expression and its inputs from the moment the engine computed it, so this
// only has to render what came with the number.

import { fmt, openPanel } from './app.js';

export function showDerivation(title, value, derivation, opts = {}) {
  if (!derivation) {
    openPanel(title, `<p class="muted">No derivation recorded for this value.</p>`);
    return;
  }
  const shown = opts.format ? opts.format(value) : fmt.n(value, 4);
  const unit = opts.unit ? ` <span class="muted" style="font-size:13px">${opts.unit}</span>` : '';

  const inputs = (derivation.inputs || []).map(i => `
    <div class="deriv-input">
      <div>
        <div class="n">${escapeHtml(i.name)}</div>
        ${i.source ? `<div class="deriv-src">${escapeHtml(i.source)}</div>` : ''}
      </div>
      <div class="v">${typeof i.value === 'number' ? fmt.n(i.value, 4) : escapeHtml(String(i.value))}</div>
    </div>`).join('');

  openPanel(title, `
    <div class="deriv-value">${shown}${unit}</div>
    <div class="muted">${escapeHtml(derivation.rule || '')}</div>
    <div class="deriv-expr">${escapeHtml(derivation.expression || '')}</div>
    ${inputs ? `<h4 class="deriv-h">Built from</h4><div class="deriv-inputs">${inputs}</div>` : ''}
    ${derivation.note ? `<div class="deriv-note">${escapeHtml(derivation.note)}</div>` : ''}
    ${derivation.excel_ref
      ? `<div class="deriv-excel">In the workbook: ${escapeHtml(derivation.excel_ref)}</div>` : ''}
    ${opts.extra || ''}
  `);
}

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}


/** Make the headline tiles on a screen open their working.
 *
 * The tiles are the first figures anybody reads and they were the last ones
 * that could not be questioned. `workings` maps a tile's key to the panel it
 * should open -- `{ title, value, expression, note, rows }` -- and anything
 * with no entry stays a plain tile rather than a click that does nothing.
 */
export function wireTiles(host, workings) {
  host.querySelectorAll('[data-tile]').forEach(tile => {
    const working = workings[tile.dataset.tile];
    if (!working) return;
    tile.classList.add('clickable');
    tile.setAttribute('title', 'Click for the working');
    tile.addEventListener('click', () => {
      const w = typeof working === 'function' ? working() : working;
      openPanel(w.title, `
        <div class="deriv-value">${w.value}</div>
        ${w.subtitle ? `<div class="muted">${escapeHtml(w.subtitle)}</div>` : ''}
        ${w.expression ? `<div class="deriv-expr">${w.expression}</div>` : ''}
        ${w.rows && w.rows.length ? `<table class="kv"><tbody>${w.rows.map(
          ([a, b]) => `<tr><td>${a}</td><td class="right mono">${b}</td></tr>`)
          .join('')}</tbody></table>` : ''}
        ${w.note ? `<div class="deriv-note">${w.note}</div>` : ''}`);
    });
  });
}


/** What a group total is made of.
 *
 * Every fold on a totals screen is a filter over the same take-off lines, so
 * "what is this ₹1.15 crore" has an exact answer: the lines that matched, and
 * what each contributed. Shared by the take-off, Total finish and room-type
 * screens so all three tell the same story in the same shape.
 */
export function showContributors(group, rows, opts = {}) {
  const body = (rows || []).map(r => `
    <tr><td>${escapeHtml(r.label)}</td>
        <td class="right mono">${r.quantity
          ? `${fmt.n(r.quantity, 2)} ${escapeHtml(r.unit || '')}`
          : '<span class="muted">—</span>'}</td>
        <td class="right mono">${fmt.money(r.amount)}</td></tr>`).join('');

  openPanel(`${group.label} — ${opts.title || 'where it comes from'}`, `
    <div class="deriv-value">${fmt.money(group.amount)}</div>
    <div class="deriv-expr">${group.quantity
      ? `${fmt.n(group.quantity, 2)} ${escapeHtml(group.unit || '')}` : ''}${
      group.quantity_sqft ? ` &nbsp;·&nbsp; ${fmt.int(group.quantity_sqft)} sq ft` : ''}${
      group.lines ? ` &nbsp;·&nbsp; ${group.lines} line${group.lines === 1 ? '' : 's'}` : ''}</div>
    ${body ? `<table class="kv"><tbody>${body}</tbody></table>` : ''}
    ${opts.extra || ''}
    <div class="deriv-note">${opts.note || `Each row is already multiplied by how
      many of that unit type the building has. These are folds over the same
      take-off lines as the per-room views, so the two always agree.`}</div>
    ${group.unpriced ? `<div class="deriv-note">${group.unpriced} line${
      group.unpriced === 1 ? '' : 's'} here ${group.unpriced === 1 ? 'is' : 'are'}
      measured and carry no rate. Their quantity is real; their amount is
      missing, not zero.</div>` : ''}`);
}


//: Which usage lookup is the current one. Bumped on every ask so a reply
//: that arrives after you moved on is dropped rather than shown.
let usageRequest = 0;


/** Where a value is used -- provenance, run backwards.
 *
 * "If I change this, what moves?" is the question a QS actually asks, and the
 * workbook cannot answer it: 10.764 is typed into hundreds of formulas with
 * nothing linking them, which is why nobody dares touch one.
 */
export async function showUsage(kind, subject, label) {
  const { api, fmt, openPanel } = await import('./app.js');
  const asked = ++usageRequest;
  openPanel(label || subject, '<p class="muted">Working out what depends on this…</p>');

  // Only the newest question gets to answer, and only if the panel is still
  // open. Otherwise a slow lookup pops the panel back open after you have
  // closed it, or a second click is overwritten by the first one's reply.
  const stillWanted = () =>
    asked === usageRequest && !document.getElementById('panel').hidden;

  let u;
  try {
    u = await api.get(`/usage/${kind}/${encodeURIComponent(subject)}`);
  } catch (err) {
    if (stillWanted()) {
      openPanel(label || subject,
        `<p class="muted">Could not work that out: ${escapeHtml(err.message)}</p>`);
    }
    return;
  }
  if (!stillWanted()) return;

  const rows = u.uses.map(x => `
    <tr>
      <td>${escapeHtml(x.where)}<div class="deriv-src">${escapeHtml(x.detail || '')}</div></td>
      <td class="right mono">${x.quantity && x.unit
        ? `${fmt.n(x.quantity, 2)} ${escapeHtml(x.unit)}` : '—'}</td>
      <td class="right mono">${x.amount ? fmt.money(x.amount) : '—'}</td>
    </tr>`).join('');

  openPanel(`Where ${label || u.subject} is used`, `
    <div class="deriv-value">${fmt.money(u.total_amount)}</div>
    <div class="deriv-expr">${fmt.int(u.total_lines)} line${
      u.total_lines === 1 ? '' : 's'} depend on it</div>
    ${u.description ? `<div class="muted">${escapeHtml(u.description)}</div>` : ''}
    ${rows ? `<h4 class="deriv-h">Broken down</h4>
      <table class="kv"><tbody>${rows}</tbody></table>` : ''}
    ${u.note ? `<div class="deriv-note">${escapeHtml(u.note)}</div>` : ''}`);
}
