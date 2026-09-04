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
import { escapeHtml, showContributors, wireTiles } from '../panel.js';

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
      <div class="tile" data-tile="finishing"><div class="k">Finishing cost</div>
        <div class="v">${fmt.money(t.total)}</div>
        <div class="s">${fmt.int(t.line_count)} lines · ${t.unit_types} unit types</div></div>
      <div class="tile" data-tile="openings"><div class="k">Doors &amp; windows</div>
        <div class="v">${fmt.money(t.openings_total)}</div>
        <div class="s">priced separately — see Doors &amp; Windows</div></div>
      <div class="tile" data-tile="both"><div class="k">Finishing + openings</div>
        <div class="v">${fmt.money(t.total + t.openings_total)}</div>
        <div class="s">everything measured room by room</div></div>
      <div class="tile" data-tile="persqft"><div class="k">Per sq ft of carpet</div>
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

  wireTiles(main, {
    finishing: {
      title: 'Everything measured room by room',
      value: fmt.money(t.total),
      subtitle: `${fmt.int(t.line_count)} take-off lines across ${t.unit_types} unit types`,
      rows: [...t.by_finish].filter(g => g.amount).sort((a, b) => b.amount - a.amount)
        .slice(0, 10).map(g => [escapeHtml(g.label), fmt.money(g.amount)]),
      note: `Every room in every unit type, priced through the rate library.
        The three tables below are filters over these same lines, so none of
        them can disagree with this figure or with each other.`,
    },
    openings: {
      title: 'Doors, windows, railings and bays',
      value: fmt.money(t.openings_total),
      note: `Measured off the openings placed in rooms rather than off the room
        finishes, which is why they are added here rather than folded in.
        <a href="#/openings">See the schedule</a>.`,
    },
    both: {
      title: 'Finishing and openings together',
      value: fmt.money(t.total + t.openings_total),
      expression: `${fmt.money(t.total)} + ${fmt.money(t.openings_total)}`,
      note: `Everything measured room by room. Civil, MEP, Infra, Amenities and
        Preliminaries are counted separately — see the
        <a href="#/summary">Cost summary</a> for the project total.`,
    },
    persqft: {
      title: 'Finishing per square foot of carpet',
      value: t.rate_per_carpet_sqft ? `₹${fmt.n(t.rate_per_carpet_sqft, 0)}` : '—',
      expression: `${fmt.money(t.total)} ÷ ${fmt.int(t.carpet_area_sqft)} sq ft`,
      note: `Carpet area, not construction area — the two differ by about 2.5×,
        and the workbook's own cost sheet divides by construction area. Reading
        the wrong one gives a rate that looks plausible and is not.`,
    },
  });

  // -- totals per finish, for the whole building --------------------------

  const measured = t.by_finish.filter(g => g.quantity || g.amount);

  createGrid(document.getElementById('byFinish'), {
    columns: [
      { key: 'label', label: 'Finish', kind: 'label', width: '210px' },
      { key: 'quantity', label: 'Quantity', kind: 'derived', width: '124px',
        title: 'Blank when the group mixes units — square metres and running '
             + 'metres are not addable, so no total is offered.',
        render: (v, row) => (row.unit ? fmt.n(v, 2) : QTY_NOT_ADDABLE) },
      { key: 'unit', label: 'Unit', kind: 'note', width: '56px', align: 'left',
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
    onDerivedClick: (row, col) => groupWorking(row, col, 'unit type', t.contributors),
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
      { key: 'unit', label: 'Unit', kind: 'note', width: '56px', align: 'left',
        render: v => v || DASH },
      { key: 'quantity_sqft', label: 'Sq ft', kind: 'derived', width: '118px',
        render: v => (v ? fmt.int(v) : DASH) },
      { key: 'lines', label: 'Lines', kind: 'derived', dp: 0, width: '76px' },
      { key: 'amount', label: 'Amount', kind: 'derived', width: '150px', total: true,
        render: v => fmt.money(v) },
    ],
    rows: t.by_room_type.filter(g => g.amount > 0 || g.unpriced),
    rowKey: r => r.key,
    onDerivedClick: (row, col) => groupWorking(row, col, 'unit type', t.contributors),
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
        { key: 'unit', label: 'Unit', kind: 'note', width: '56px', align: 'left',
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
      onDerivedClick: (row, col) =>
        groupWorking(row, col, 'unit type', t.contributors),
    });
  }

  search.addEventListener('input', drawMatrix);
  drawMatrix();
});

// Which unit types make up one total. The answer to "where does the building's
// 3.5 lakh sq ft of flooring actually sit" -- and to the same question asked of
// a room type, of a unit type, or of one cell of the matrix.
function groupWorking(row, col, brokenDownBy, contributors) {
  const rows = (contributors || {})[row.key] || [];

  if (col.key === 'blended_rate' || col.key === 'rate_per_sqft') {
    const perSqft = col.key === 'rate_per_sqft';
    const value = row[col.key];
    if (value === null || value === undefined) {
      openPanel(`${row.label} — ${perSqft ? '₹/sq ft' : 'rate'}`,
        `<div class="deriv-note">${perSqft
          ? 'No square-foot figure here — this group is not an area, so there is nothing to divide by.'
          : 'This group mixes units. Square metres and running metres do not add, so there is no single quantity to divide the money by.'}</div>`);
      return true;
    }
    showContributors(row, rows, {
      title: perSqft ? '₹ per sq ft' : 'blended rate',
      extra: `<div class="deriv-expr">${fmt.money(row.amount)} ÷ ${
        perSqft ? `${fmt.int(row.quantity_sqft)} sq ft`
                : `${fmt.n(row.quantity, 2)} ${escapeHtml(row.unit || '')}`} = ₹${
        fmt.n(value, 2)}</div>`,
      note: `A weighted average across every room in this group — it exists in no
        rate list. ${perSqft ? `The money is always computed from the
        square-metre pair; this is that same number presented the way a QS
        reads it.` : `Rooms priced at different rates pull it about, which is
        why the rows above are worth reading.`}`,
    });
    return true;
  }

  if (col.key === 'quantity_sqft') {
    if (!row.quantity_sqft) {
      openPanel(`${row.label} — sq ft`, `<div class="deriv-note">Areas only.
        This group is measured in ${escapeHtml(row.unit || 'mixed units')}, and
        a running metre does not convert to a square foot.</div>`);
      return true;
    }
    showContributors(row, rows, {
      title: 'square feet',
      extra: `<div class="deriv-expr">${fmt.n(row.quantity, 2)} sq m × 10.764 = ${
        fmt.int(row.quantity_sqft)} sq ft</div>`,
      note: `Converted with the project's own factor of 10.764 — the workbook's
        figure, not the exact 10.7639 — so this agrees with the sheet. The
        conversion is a named parameter, not a number typed into a formula.`,
    });
    return true;
  }

  if (col.key === 'unpriced') {
    showContributors(row, rows, {
      title: `${row.unpriced} unpriced line${row.unpriced === 1 ? '' : 's'}`,
      note: `Measured here and reaching no rate. The quantity is real; the
        amount is missing, not zero.`,
    });
    return true;
  }

  if (['amount', 'quantity', 'lines'].includes(col.key)) {
    if (col.key === 'quantity' && !row.unit) {
      openPanel(`${row.label} — quantity`, `<div class="deriv-note">This group
        mixes units — square metres and running metres — and those do not add.
        Rather than print a confident 0.00, no total is offered. The money still
        adds, because each line was priced in its own unit before being
        summed.</div>`);
      return true;
    }
    showContributors(row, rows, {
      note: `Broken down by ${brokenDownBy}. Each row is already multiplied by
        how many of that unit type the building has, and these are folds over
        the same take-off lines as the per-room views — so the two always
        agree.`,
    });
    return true;
  }
  return false;
}
