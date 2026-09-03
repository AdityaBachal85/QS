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


/** Where a value is used -- provenance, run backwards.
 *
 * "If I change this, what moves?" is the question a QS actually asks, and the
 * workbook cannot answer it: 10.764 is typed into hundreds of formulas with
 * nothing linking them, which is why nobody dares touch one.
 */
export async function showUsage(kind, subject, label) {
  const { api, fmt, openPanel } = await import('./app.js');
  openPanel(label || subject, '<p class="muted">Working out what depends on this…</p>');

  let u;
  try {
    u = await api.get(`/usage/${kind}/${encodeURIComponent(subject)}`);
  } catch (err) {
    openPanel(label || subject,
      `<p class="muted">Could not work that out: ${escapeHtml(err.message)}</p>`);
    return;
  }

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
