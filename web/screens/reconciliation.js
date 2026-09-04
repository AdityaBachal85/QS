// Excel versus platform, line by line.
//
// PASS is identical to the paisa. EXPLAINED is a difference of exactly the size
// a named defect predicts -- so a bug cannot hide inside a correction. Anything
// else is FAIL and blocks acceptance.

import { api, fmt, openPanel, route } from '../app.js';
import { escapeHtml } from '../panel.js';

const STATUS = { PASS: 'ok', EXPLAINED: 'warn', FAIL: 'bad' };

route('/reconciliation', async (main) => {
  main.innerHTML = '<div class="loading">Reading the workbook and recomputing…</div>';
  const r = await api.get('/reconciliation');

  const sections = [];
  let current = null;
  for (const line of r.lines) {
    if (!current || current.name !== line.section) {
      current = { name: line.section, lines: [] };
      sections.push(current);
    }
    current.lines.push(line);
  }

  main.innerHTML = `
    <div class="screen-head">
      <h1>Reconciliation</h1>
      <p>Every figure the platform computes, beside the workbook's own cached value.
         <span class="mono">${escapeHtml(r.workbook)}</span></p>
    </div>
    <div class="toolbar">
      <span class="chip ok">${r.pass} PASS</span>
      <span class="chip warn">${r.explained} EXPLAINED</span>
      <span class="chip ${r.fail ? 'bad' : 'mute'}">${r.fail} FAIL</span>
      <span class="muted">${r.fail ? 'Acceptance is blocked.' : 'Acceptance granted.'}</span>
    </div>

    ${sections.map(s => `
      <div class="card">
        <h2>${escapeHtml(s.name)}</h2>
        <div class="grid-wrap"><table class="grid">
          <thead><tr>
            <th class="left" style="min-width:250px">Line</th>
            <th style="min-width:130px">Excel</th>
            <th style="min-width:130px">Platform</th>
            <th style="min-width:110px">Difference</th>
            <th class="left" style="min-width:90px">Status</th>
          </tr></thead>
          <tbody>${s.lines.map((l, i) => `
            <tr>
              <td class="label left">${escapeHtml(l.label)}
                <div class="muted mono" style="font-size:10.5px">${escapeHtml(l.excel_ref)}</div></td>
              <td class="derived clickable" data-line="${escapeHtml(s.name)}|${i}"
                  title="Click for the working">${fmt.n(l.excel, 2)}</td>
              <td class="derived clickable" data-line="${escapeHtml(s.name)}|${i}"
                  title="Click for the working">${fmt.n(l.platform, 2)}</td>
              <td class="derived clickable ${Math.abs(l.difference) > 0.01 ? 'missing' : ''}"
                  data-line="${escapeHtml(s.name)}|${i}" title="Click for the working">${
                Math.abs(l.difference) < 0.005 ? '—' : fmt.n(l.difference, 2)}</td>
              <td class="left"><span class="chip ${STATUS[l.status]}">${l.status}</span></td>
            </tr>
            ${l.explanation ? `<tr><td colspan="5" class="explain">${escapeHtml(l.explanation)}</td></tr>` : ''}
          `).join('')}</tbody>
        </table></div>
      </div>`).join('')}

    ${r.warnings.length ? `
      <div class="card">
        <h2>Import notes <span class="sub">${r.warnings.length}</span></h2>
        <div class="card-body">
          <p class="muted" style="margin-top:0">Nothing is auto-corrected. Anything the importer
          could not resolve cleanly is recorded here rather than quietly dropped.</p>
          ${r.warnings.map(w => `<div class="explain" style="padding-left:0">• ${escapeHtml(w)}</div>`).join('')}
        </div>
      </div>` : ''}`;

  // Every figure on this screen opens its working. A reconciliation line is
  // where the platform and the workbook are put side by side, so "why are
  // these two numbers different" is precisely the question being asked, and
  // clicking one should answer it rather than nothing.
  const bySection = Object.fromEntries(sections.map(s => [s.name, s.lines]));

  main.addEventListener('click', (e) => {
    const td = e.target.closest('[data-line]');
    if (!td) return;
    const [section, index] = td.dataset.line.split('|');
    const l = (bySection[section] || [])[Number(index)];
    if (!l) return;

    const agrees = Math.abs(l.difference) <= 0.01;
    openPanel(`${l.label} — ${section}`, `
      <div class="deriv-value">${fmt.n(l.platform, 2)}</div>
      <div class="muted">what the platform computes</div>
      <table class="kv" style="margin-top:10px"><tbody>
        <tr><td>The workbook</td>
            <td class="right mono">${fmt.n(l.excel, 2)}</td></tr>
        <tr><td>The platform</td>
            <td class="right mono">${fmt.n(l.platform, 2)}</td></tr>
        <tr class="total-row"><td><strong>Difference</strong></td>
            <td class="right mono"><strong>${fmt.n(l.difference, 2)}</strong></td></tr>
        ${l.expected_delta !== null && l.expected_delta !== undefined ? `
        <tr><td>Predicted difference</td>
            <td class="right mono">${fmt.n(l.expected_delta, 2)}</td></tr>` : ''}
      </tbody></table>
      ${l.excel_ref ? `<div class="deriv-excel">In the workbook:
        ${escapeHtml(l.excel_ref)}</div>` : ''}
      ${l.explanation ? `<h4 class="deriv-h">Why they differ</h4>
        <div class="deriv-note">${escapeHtml(l.explanation)}</div>` : ''}
      <div class="deriv-note">${agrees
        ? `<strong>PASS</strong> — identical to the paisa. The platform computes
           this from the model rather than reading the cell, so agreeing is a
           result, not a copy.`
        : l.expected_delta !== null && l.expected_delta !== undefined
          ? `<strong>EXPLAINED</strong> — the difference is exactly the size a
             named defect predicts. An explained difference of the wrong size
             fails as loudly as an unexplained one, so a bug cannot hide inside
             this line.`
          : `<strong>FAIL</strong> — a difference nobody predicted. Either the
             platform is wrong, or the workbook is and the reason has not been
             written down yet. Acceptance is blocked while this stands.`}</div>`);
  });
});
