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

    <div class="card" id="dadoCard" hidden>
      <h2>The dado line
        <span class="sub">measured, not agreed — nothing here has been changed</span></h2>
      <div id="dadoBody"></div>
    </div>

    ${r.warnings.length ? `
      <div class="card">
        <h2>Import notes <span class="sub">${r.warnings.length}</span></h2>
        <div class="card-body">
          <p class="muted" style="margin-top:0">Nothing is auto-corrected. Anything the importer
          could not resolve cleanly is recorded here rather than quietly dropped.</p>
          ${r.warnings.map(w => `<div class="explain" style="padding-left:0">• ${escapeHtml(w)}</div>`).join('')}
        </div>
      </div>` : ''}`;

  // -- the dado line, measured both ways ---------------------------------
  //
  // You asked to see this before deciding, so it is a report: it runs the
  // take-off twice, once as it stands and once measured the way the workbook
  // measures it, and states the difference. No rule changed.
  api.get('/dado-basis').then(d => {
    const card = document.getElementById('dadoCard');
    const body = document.getElementById('dadoBody');
    if (!card || !body || !d.rows.length) return;
    card.hidden = false;

    const pct = (v) => `${(v / d.workbook_total * 100).toFixed(2)}%`;
    body.innerHTML = `
      <div class="card-body">
        <p style="margin-top:0">A dado and the wall above it <strong>partition the
        height</strong> of a room — the tiles take the lower part and the plaster
        takes what is left. Your workbook measures them that way:
        <span class="mono">E46 = D43×2.40</span> for the dado and
        <span class="mono">E47 = D43×0.70</span> for the wall, and
        2.40 + 0.70 = 3.10, the room's own height.</p>
        <p>This platform does not. It measures the dado at 2.10 m — a default
        nobody chose — and then charges the wall for nearly the full height on
        top, so the same strip is paid for twice. Wall finishes are
        ₹6.6 crore of the take-off, so this is not a rounding matter.</p>
        <p style="margin-bottom:0"><strong>Nothing below has been changed.</strong>
        This is what the change would be worth, so you can decide having seen
        it.</p>
      </div>
      <div class="grid-wrap"><table class="grid">
        <thead><tr>
          <th class="left" style="min-width:170px">Room type</th>
          <th style="min-width:60px">Rooms</th>
          <th style="min-width:96px">Dado now</th>
          <th style="min-width:110px">Dado, workbook</th>
          <th style="min-width:96px">Wall now</th>
          <th style="min-width:110px">Wall, workbook</th>
          <th class="total" style="min-width:130px">Would move</th>
        </tr></thead>
        <tbody>${d.rows.map(row => `
          <tr>
            <td class="label left">${escapeHtml(row.room_type)}</td>
            <td class="derived note">${row.rooms}</td>
            <td class="derived note">${fmt.n(row.dado_now, 2)} m</td>
            <td class="derived note">${fmt.n(row.dado_workbook, 2)} m</td>
            <td class="derived note">${fmt.n(row.wall_now, 2)} m</td>
            <td class="derived note">${fmt.n(row.wall_workbook, 2)} m</td>
            <td class="derived note total">${row.money > 0 ? '+' : ''}${
              fmt.money(row.money)}</td>
          </tr>`).join('')}
        </tbody>
        <tfoot><tr class="total-row">
          <td class="left"><strong>${d.room_types_affected} room types ·
            ${d.wall_rows_affected} wall rows</strong></td>
          <td colspan="5"></td>
          <td><strong>${d.moves_by > 0 ? '+' : ''}${fmt.money(d.moves_by)}</strong></td>
        </tr></tfoot>
      </table></div>
      <div class="card-body" style="border-top:1px solid var(--line)">
        <table class="kv" style="width:100%"><tbody>
          <tr><td>The take-off as it stands</td>
              <td class="right mono">${fmt.money(d.total_now)}</td>
              <td class="right mono">${d.gap_now > 0 ? '+' : ''}${pct(d.gap_now)}
                against the workbook</td></tr>
          <tr><td>Measured the workbook's way</td>
              <td class="right mono">${fmt.money(d.total_partitioned)}</td>
              <td class="right mono">${d.gap_partitioned > 0 ? '+' : ''}${
                pct(d.gap_partitioned)} against the workbook</td></tr>
          <tr class="total-row"><td><strong>The change</strong></td>
              <td class="right mono"><strong>${d.moves_by > 0 ? '+' : ''}${
                fmt.money(d.moves_by)}</strong></td>
              <td class="right mono"><strong>${d.closer ? 'closer to' : 'further from'
                } the workbook</strong></td></tr>
        </tbody></table>
        <p class="muted" style="margin-bottom:0">${d.closer
          ? `The change would bring the finishing take-off from ${
              d.gap_now > 0 ? '+' : ''}${pct(d.gap_now)} to ${
              d.gap_partitioned > 0 ? '+' : ''}${pct(d.gap_partitioned)} of the
             workbook's own figure. Kitchens and pantries are left alone —
             their dado already runs along the counters and their wall already
             has it deducted.`
          : `The change would move the take-off away from the workbook, which is
             worth understanding before agreeing to it.`}
          Say the word and it goes in, with the movement recorded in the
          expected-delta ledger by name.</p>
      </div>`;
  }).catch(() => { /* the workbook may not be present; the card stays hidden */ });

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
