// The change log.
//
// The workbook has no equivalent: two shuttering rates sit one sheet apart,
// ₹1.25 Cr different, with nothing recording who set either or when.

import { api, route } from '../app.js';
import { escapeHtml } from '../panel.js';

route('/audit', async (main) => {
  const rows = await api.get('/audit');
  main.innerHTML = `
    <div class="screen-head">
      <h1>Change log</h1>
      <p>Every edit, with its old and new value. Written on the way through, not reconstructed.</p>
    </div>
    <div class="card">
      ${rows.length ? `<div class="grid-wrap"><table class="grid">
        <thead><tr>
          <th class="left" style="min-width:160px">When</th>
          <th class="left" style="min-width:130px">Entity</th>
          <th class="left" style="min-width:230px">Record</th>
          <th class="left" style="min-width:120px">Field</th>
          <th style="min-width:110px">From</th>
          <th style="min-width:110px">To</th>
        </tr></thead>
        <tbody>${rows.map(r => `
          <tr>
            <td class="label left mono" style="font-size:11px">${escapeHtml(r.at)}</td>
            <td class="label left">${escapeHtml(r.entity)}</td>
            <td class="label left mono" style="font-size:11px">${escapeHtml(r.entity_id)}</td>
            <td class="label left">${escapeHtml(r.field)}</td>
            <td class="derived">${escapeHtml(r.old_value ?? '—')}</td>
            <td class="derived">${escapeHtml(r.new_value ?? '—')}</td>
          </tr>`).join('')}</tbody>
      </table></div>`
      : '<div class="card-body muted">No changes yet. Edit something and it will appear here.</div>'}
    </div>`;
});
