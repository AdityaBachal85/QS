// Total Finish -- the whole building, folded up.
//
// The per-room and per-unit-type views answer "what does this flat cost". This
// one answers "how much flooring is there in this building, and what does it
// come to" -- a question the workbook could not be asked, because its totals
// were written per take-off block and never added across them.
//
// Every figure is a filter over the same take-off lines the other screens use,
// so this view cannot disagree with them. Nothing here is computed in the
// browser.

import { api, fmt, openPanel, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml } from '../panel.js';

const DASH = '<span class="muted">—</span>';
// Square metres and running metres do not add. Rather than print a
// confident 0.00, the cell says so.
const QTY_NOT_ADDABLE =
  '<span class="muted" title="mixed units — not addable">—</span>';

route('/finish-totals', async (main) => {
  main.innerHTML = '<div class="loading">Folding every room into one set of totals…</div>';
  const t = await api.get('/finish-totals');

  main.innerHTML = `
    <div class="screen-head">
      <h1>Total finish</h1>
      <p>Every unit type added together — the building's flooring, its skirting, its dado.
         Areas read in square feet as well as square metres; the money is always computed
         from the square-metre figure and the rate that belongs to it.</p>
    </div>

    <div class="tile-row">
      <div class="tile"><div class="k">Finishing cost</div>
        <div class="v">${fmt.money(t.total)}</div>
        <div class="s">${fmt.int(t.line_count)} lines · ${t.unit_types} unit types</div></div>
      <div class="tile"><div class="k">Doors &amp; windows</div>
        <div class="v">${fmt.money(t.openings_total)}</div>
        <div class="s">priced separately — see Doors &amp; Windows</div></div>
      <div class="tile"><div class="k">Finishing + openings</div>
        <div class="v">${fmt.money(t.total + t.openings_total)}</div>
        <div class="s">everything measured room by room</div></div>
      <div class="tile"><div class="k">Per sq ft of carpet</div>
        <div class="v">${t.rate_per_carpet_sqft ? '₹' + fmt.n(t.rate_per_carpet_sqft, 0) : '—'}</div>
        <div class="s">${fmt.int(t.carpet_area_sqft)} sq ft carpet</div></div>
    </div>

    <div class="card" style="margin-top:16px">
      <h2>By finish
        <span class="sub">the whole building — click a row to see which unit types make it up</span></h2>
      <div id="byFinish"></div>
    </div>

    <div class="card">
      <h2>By room type
        <span class="sub">every bedroom in the building, every toilet</span></h2>
      <div id="byRoomType"></div>
    </div>

    <div class="card">
      <h2>Finish by room type
        <span class="sub">one finish, in one kind of room — "total flooring in toilets" is a row here</span></h2>
      <div class="card-body" style="padding-bottom:0">
        <input class="text-input" id="q" placeholder="Filter — try “Flooring” or “Toilet”…"
               style="min-width:320px">
        <span class="muted" id="count"></span>
      </div>
      <div id="matrix"></div>
    </div>`;

  // -- totals per finish, for the whole building --------------------------

  const measured = t.by_finish.filter(g => g.quantity || g.amount);

  createGrid(document.getElementById('byFinish'), {
    columns: [
      { key: 'label', label: 'Finish', kind: 'label', width: '210px' },
      { key: 'quantity', label: 'Quantity', kind: 'derived', width: '124px',
        title: 'Blank when the group mixes units — square metres and running '
             + 'metres are not addable, so no total is offered.',
        render: (v, row) => (row.unit ? fmt.n(v, 2) : QTY_NOT_ADDABLE) },
      { key: 'unit', label: 'Unit', kind: 'derived', width: '56px', align: 'left',
        render: v => v || DASH },
      { key: 'quantity_sqft', label: 'Sq ft', kind: 'derived', width: '118px',
        title: 'Areas only, converted with the project’s own factor of 10.764 — '
             + 'the workbook’s figure, not the exact 10.7639.',
        render: v => (v ? fmt.int(v) : DASH) },
      { key: 'blended_rate', label: 'Rate', kind: 'derived', dp: 2, width: '108px',
        title: 'Amount ÷ quantity, in the finish’s own unit. A weighted average '
             + 'across every room, not a rate from the library.' },
      { key: 'rate_per_sqft', label: '₹/sq ft', kind: 'derived', width: '92px',
        title: 'Amount ÷ square feet. Derived for reading; the money is computed '
             + 'from the square-metre pair.',
        render: v => (v ? '₹' + fmt.n(v, 2) : DASH) },
      { key: 'unpriced', label: 'Unpriced', kind: 'derived', dp: 0, width: '82px',
        title: 'Lines measured here that reach no rate. Their quantity is real; '
             + 'their amount is missing, not zero.',
        render: v => (v ? `<span class="warn-text">${v}</span>` : DASH) },
      { key: 'amount', label: 'Amount', kind: 'derived', width: '134px', total: true,
        render: v => fmt.money(v) },
    ],
    rows: measured,
    rowKey: r => r.key,
    onDerivedClick: row => showContributors(row, t.contributors[row.key] || []),
    footer: rows => [
      '<strong>Total</strong>', '', '', '', '', '', '',
      `<strong>${fmt.money(rows.reduce((a, r) => a + r.amount, 0))}</strong>`,
    ],
  });

  // -- totals per room type ----------------------------------------------

  createGrid(document.getElementById('byRoomType'), {
    columns: [
      { key: 'label', label: 'Room type', kind: 'label', width: '230px' },
      { key: 'quantity', label: 'Quantity', kind: 'derived', width: '124px',
        title: 'A room type carries flooring in square metres and skirting in '
             + 'running metres. Those do not add, so no single quantity is shown.',
        render: (v, row) => (row.unit ? fmt.n(v, 2) : QTY_NOT_ADDABLE) },
      { key: 'unit', label: 'Unit', kind: 'derived', width: '56px', align: 'left',
        render: v => v || DASH },
      { key: 'quantity_sqft', label: 'Sq ft', kind: 'derived', width: '118px',
        render: v => (v ? fmt.int(v) : DASH) },
      { key: 'lines', label: 'Lines', kind: 'derived', dp: 0, width: '76px' },
      { key: 'amount', label: 'Amount', kind: 'derived', width: '150px', total: true,
        render: v => fmt.money(v) },
    ],
    rows: t.by_room_type.filter(g => g.amount > 0 || g.unpriced),
    rowKey: r => r.key,
    footer: rows => ['<strong>Total</strong>', '', '', '', '',
                     `<strong>${fmt.money(rows.reduce((a, r) => a + r.amount, 0))}</strong>`],
  });

  // -- the matrix, filterable --------------------------------------------

  const cells = t.matrix.filter(g => g.quantity || g.amount);
  const box = document.getElementById('matrix');
  const search = document.getElementById('q');
  const count = document.getElementById('count');

  function drawMatrix() {
    const needle = search.value.trim().toLowerCase();
    const rows = needle
      ? cells.filter(c => c.label.toLowerCase().includes(needle))
      : cells;
    count.textContent = `${rows.length} of ${cells.length} shown`
      + (rows.length ? ` · ${fmt.money(rows.reduce((a, r) => a + r.amount, 0))}` : '');
    createGrid(box, {
      columns: [
        { key: 'label', label: 'Finish — room type', kind: 'label', width: '330px' },
        { key: 'quantity', label: 'Quantity', kind: 'derived', width: '124px',
          render: (v, row) => (row.unit ? fmt.n(v, 2) : QTY_NOT_ADDABLE) },
        { key: 'unit', label: 'Unit', kind: 'derived', width: '56px', align: 'left',
          render: v => v || DASH },
        { key: 'quantity_sqft', label: 'Sq ft', kind: 'derived', width: '112px',
          render: v => (v ? fmt.int(v) : DASH) },
        { key: 'rate_per_sqft', label: '₹/sq ft', kind: 'derived', width: '92px',
          render: v => (v ? '₹' + fmt.n(v, 2) : DASH) },
        { key: 'amount', label: 'Amount', kind: 'derived', width: '134px', total: true,
          render: v => fmt.money(v) },
      ],
      rows,
      rowKey: r => r.key,
    });
  }

  search.addEventListener('input', drawMatrix);
  drawMatrix();
});

// Which unit types make up one finish total. The answer to "where does the
// building's 3.5 lakh sq ft of flooring actually sit".
function showContributors(group, rows) {
  const body = rows.map(r => `
    <tr><td>${escapeHtml(r.label)}</td>
        <td class="right mono">${fmt.n(r.quantity, 2)} ${escapeHtml(r.unit || '')}</td>
        <td class="right mono">${fmt.money(r.amount)}</td></tr>`).join('');

  openPanel(`${group.label} — where it comes from`, `
    <div class="deriv-value">${fmt.money(group.amount)}</div>
    <div class="deriv-expr">${fmt.n(group.quantity, 2)} ${escapeHtml(group.unit || '')}${
      group.quantity_sqft ? ` &nbsp;·&nbsp; ${fmt.int(group.quantity_sqft)} sq ft` : ''}</div>
    <table class="kv"><tbody>${body}</tbody></table>
    <div class="deriv-note">Each row is that unit type's share, already multiplied by
      how many of it the building has. They are folds over the same take-off lines as
      the per-room view, so the two always agree.</div>`);
}
