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
