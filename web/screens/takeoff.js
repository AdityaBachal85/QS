// The finishing take-off -- where the rupees are.
//
// This replaces `Internal Finishes Flats`: 1,451 hand-written rows and 9,472
// formulas, one block per room, each re-anchored to the rate list by a
// hand-counted row offset. Here every line is a fold over the room's own
// finishes, and every total is a filter rather than a SUM over a range.

import { api, fmt, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml, showDerivation } from '../panel.js';

const STATUS = {
  priced: '', no_rate: 'bad', no_rule: 'warn', error: 'bad',
};

route('/takeoff', async (main) => {
  main.innerHTML = '<div class="loading">Measuring every room and pricing it…</div>';
  const t = await api.get('/takeoff');

  main.innerHTML = `
    <div class="screen-head">
      <h1>Finishing take-off</h1>
      <p>Every finish, in every room, of every unit type — measured, deducted, priced and
         multiplied by how many of that unit the building has. Nothing here was typed.</p>
    </div>

    <div class="tile-row">
      <div class="tile"><div class="k">Finishing cost</div>
        <div class="v">${fmt.money(t.total)}</div>
        <div class="s">${fmt.int(t.priced_count)} priced lines</div></div>
      <div class="tile"><div class="k">Take-off lines</div>
        <div class="v">${fmt.int(t.line_count)}</div>
        <div class="s">was 1,451 rows in the workbook</div></div>
      <div class="tile"><div class="k">Measured, unpriced</div>
        <div class="v" style="color:${t.unpriced.length ? 'var(--bad)' : 'inherit'}">
          ${fmt.int(t.unpriced.length)}</div>
        <div class="s">${t.unpriced.length ? 'work showing nothing' : 'none'}</div></div>
      <div class="tile"><div class="k">Finish types</div>
        <div class="v">${fmt.int(t.by_finish.length)}</div>
        <div class="s">across ${t.by_unit_type.length} unit types</div></div>
    </div>

    ${t.unpriced.length ? `
    <div class="card" style="margin-top:16px;border-color:#f3caca">
      <h2>Measured but not priced
        <span class="sub">quantity known, rate missing — this is not zero-cost work</span></h2>
      <div id="unpriced"></div>
    </div>` : ''}

    <div class="card" style="margin-top:16px">
      <h2>By finish <span class="sub">click a blended rate to see what it is made of</span></h2>
      <div id="byFinish"></div>
    </div>
    <div class="card">
      <h2>By unit type</h2>
      <div id="byUnit"></div>
    </div>
    <div class="card">
      <h2>All lines <span class="sub">${fmt.int(t.line_count)} — filter to narrow</span></h2>
      <div class="card-body" style="padding-bottom:0">
        <input class="text-input" id="q" placeholder="Filter by unit type, room or finish…"
               style="min-width:320px">
        <span class="muted" id="count"></span>
      </div>
      <div id="lines"></div>
    </div>`;

  if (t.unpriced.length) {
    createGrid(document.getElementById('unpriced'), {
      columns: [
        { key: 'unit_type', label: 'Unit type', kind: 'label', width: '140px' },
        { key: 'room', label: 'Room', kind: 'label', width: '170px' },
        { key: 'finish', label: 'Finish', kind: 'derived', width: '160px', align: 'left' },
        { key: 'total_qty', label: 'Quantity', kind: 'derived', dp: 2, width: '110px' },
        { key: 'unit', label: 'Unit', kind: 'derived', width: '60px', align: 'left' },
        { key: 'message', label: 'Why', kind: 'derived', width: '380px', align: 'left',
          render: v => `<span class="muted">${escapeHtml(v)}</span>` },
      ],
      rows: t.unpriced,
    });
  }

  createGrid(document.getElementById('byFinish'), {
    columns: [
      { key: 'label', label: 'Finish', kind: 'label', width: '230px' },
      { key: 'quantity', label: 'Quantity', kind: 'derived', dp: 2, width: '124px' },
      { key: 'unit', label: 'Unit', kind: 'derived', width: '60px', align: 'left' },
      { key: 'blended_rate', label: 'Blended rate', kind: 'derived', dp: 2, width: '116px',
        title: 'Amount ÷ quantity. The workbook prices its cost sheet on exactly this '
             + 'figure — a weighted average that exists in no rate list.' },
      { key: 'lines', label: 'Lines', kind: 'derived', dp: 0, width: '68px' },
      { key: 'amount', label: 'Amount', kind: 'derived', width: '134px', total: true,
        render: v => fmt.money(v) },
    ],
    // Slots that no room measures would be a page of zeros. They are counted
    // below rather than listed, because a zero with no quantity behind it says
    // nothing -- and a zero *with* a quantity is the unpriced table above.
    rows: t.by_finish.filter(g => g.quantity || g.amount),
    footer: rows => ['<strong>Total</strong>', '', '', '', '',
                     `<strong>${fmt.money(rows.reduce((a, r) => a + r.amount, 0))}</strong>`],
  });

  const empty = t.by_finish.filter(g => !g.quantity && !g.amount);
  if (empty.length) {
    document.getElementById('byFinish').insertAdjacentHTML('beforeend', `
      <div class="card-body muted" style="border-top:1px solid var(--line)">
        ${empty.length} finish slot${empty.length === 1 ? '' : 's'} exist in the rate library
        but no room measures ${empty.length === 1 ? 'it' : 'them'}:
        ${empty.map(g => escapeHtml(g.label)).join(' · ')}.
        Look for near-duplicates here — a slot spelled two ways splits one finish in two.
      </div>`);
  }

  createGrid(document.getElementById('byUnit'), {
    columns: [
      { key: 'label', label: 'Unit type', kind: 'label', width: '200px' },
      { key: 'lines', label: 'Lines', kind: 'derived', dp: 0, width: '76px' },
      { key: 'unpriced', label: 'Unpriced', kind: 'derived', dp: 0, width: '84px' },
      { key: 'amount', label: 'Amount', kind: 'derived', width: '150px', total: true,
        render: v => fmt.money(v) },
    ],
    rows: t.by_unit_type.filter(g => g.amount > 0 || g.unpriced),
  });

  // -- every line, filterable ---------------------------------------------
  function drawLines() {
    const q = document.getElementById('q').value.trim().toLowerCase();
    const rows = t.lines.filter(l => !q ||
      `${l.unit_type} ${l.room} ${l.finish} ${l.rate_description}`.toLowerCase().includes(q));
    document.getElementById('count').textContent =
      `  ${rows.length} of ${t.lines.length} lines`;

    const host = document.getElementById('lines');
    host.innerHTML = '';
    createGrid(host, {
      columns: [
        { key: 'unit_type', label: 'Unit type', kind: 'label', width: '130px' },
        { key: 'room', label: 'Room', kind: 'label', width: '160px' },
        { key: 'finish', label: 'Finish', kind: 'derived', width: '150px', align: 'left' },
        { key: 'net', label: 'Net / unit', kind: 'derived', dp: 3, width: '96px' },
        { key: 'unit', label: 'Unit', kind: 'derived', width: '56px', align: 'left' },
        { key: 'unit_count', label: '× units', kind: 'derived', dp: 0, width: '70px' },
        { key: 'total_qty', label: 'Total qty', kind: 'derived', dp: 2, width: '104px' },
        { key: 'rate', label: 'Rate', kind: 'derived', dp: 2, width: '96px',
          flagMissing: true,
          render: (v, r) => v === null
            ? `<span class="tag ${STATUS[r.status] || 'warn'}">no rate</span>`
            : `₹${fmt.n(v, 2)}` },
        { key: 'total_amount', label: 'Amount', kind: 'derived', width: '124px',
          total: true, render: (v, r) => r.status === 'priced' ? fmt.money(v) : '—' },
      ],
      rows: rows.slice(0, 400),
      emptyMessage: 'Nothing matches that filter.',
      onDerivedClick: (row, col) => {
        if (col.key === 'total_qty' || col.key === 'net') {
          showDerivation(`${row.room} — ${row.finish}`, row.net, row.gross_derivation, {
            unit: row.unit,
            extra: row.deduction_derivation ? `
              <h4 class="deriv-h">Less, for this room's own openings</h4>
              <div class="deriv-expr">${escapeHtml(row.deduction_derivation.expression)}</div>
              ${(row.deduction_derivation.inputs || []).map(i => `
                <div class="deriv-input"><div class="n">${escapeHtml(i.name)}</div>
                  <div class="v">−${fmt.n(i.value, 3)}</div></div>`).join('')}
              ${row.deduction_derivation.note
                ? `<div class="deriv-note">${escapeHtml(row.deduction_derivation.note)}</div>` : ''}
              <h4 class="deriv-h">Then</h4>
              <div class="deriv-expr">${fmt.n(row.net, 3)} ${escapeHtml(row.unit)}
                × ${row.unit_count} units = ${fmt.n(row.total_qty, 2)}</div>` : '',
          });
        } else if (col.key === 'rate' || col.key === 'total_amount') {
          showDerivation(row.rate_description || row.finish, row.rate, row.rate_derivation, {
            unit: `per ${row.unit}`,
            format: v => v === null ? '— no rate' : `₹${fmt.n(v, 4)}`,
            extra: row.status === 'priced' ? `
              <h4 class="deriv-h">Amount</h4>
              <div class="deriv-expr">${fmt.n(row.total_qty, 2)} ${escapeHtml(row.unit)}
                × ₹${fmt.n(row.rate, 2)} = ${fmt.money(row.total_amount)}</div>`
              : `<div class="deriv-note">${escapeHtml(row.message)}</div>`,
          });
        }
      },
    });
  }
  document.getElementById('q').addEventListener('input', drawLines);
  drawLines();
});
