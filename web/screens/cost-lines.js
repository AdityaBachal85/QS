// Cost lines -- Infra, Amenities, Preliminaries and the cost sheets.
//
// Four sheets with one shape: Description, Unit, Quantity, Rate, Amount. The
// amount is never stored; it is quantity × rate, computed, through the same
// unit-safe path the take-off uses. `Infra!E5` and `E12` were typed amounts in
// a column where every neighbour was a formula — here they are `1 LS × rate`,
// which is the same money written so the arithmetic shows.

import { api, fmt, openPanel, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml, showDerivation, wireTiles } from '../panel.js';

route('/cost-lines', async (main) => {
  main.innerHTML = '<div class="loading">Pricing the cost sheets…</div>';
  const data = await api.get('/cost-lines');

  main.innerHTML = `
    <div class="screen-head">
      <h1>Cost lines</h1>
      <p>The flat cost sheets — Preliminaries, Amenities, External Development and
         the detailed estimate. Every amount is quantity × rate; none is typed.</p>
    </div>
    <div class="tile-row">
      <div class="tile" data-tile="all"><div class="k">All cost lines</div>
        <div class="v">${fmt.money(data.total)}</div>
        <div class="s">${data.sections.reduce((a, s) => a + s.lines.length, 0)} lines
          in ${data.sections.length} sections</div></div>
      ${data.unpriced.length ? `<div class="tile" data-tile="unpriced"><div class="k">Measured, unpriced</div>
        <div class="v" style="color:var(--bad)">${data.unpriced.length}</div>
        <div class="s">quantity known, rate missing</div></div>` : ''}
      ${data.excluded.length ? `<div class="tile" data-tile="excluded"><div class="k">Excluded</div>
        <div class="v">${data.excluded.length}</div>
        <div class="s">kept, with a reason</div></div>` : ''}
    </div>
    ${data.sections.map(s => `
      <div class="card" style="margin-top:16px">
        <h2>${escapeHtml(s.name)}
          <span class="sub">${fmt.money(s.amount)} · ${escapeHtml(s.excel_ref || '')}</span></h2>
        <div id="sec-${s.id}"></div>
      </div>`).join('')}`;

  wireTiles(main, {
    all: {
      title: 'Every cost line',
      value: fmt.money(data.total),
      subtitle: `${data.sections.length} sections`,
      rows: data.sections.map(s => [escapeHtml(s.name), fmt.money(s.amount)]),
      note: `Each amount is quantity × rate — none is typed. Sections are
        filters over the lines that name them, so a line added at the foot of
        a band is counted because it names the band, never because somebody
        widened a SUM (C-38).`,
    },
    unpriced: {
      title: 'Measured, and reaching no rate',
      value: String(data.unpriced.length),
      rows: data.unpriced.slice(0, 12).map(l =>
        [escapeHtml(l.description), `${fmt.n(l.qty, 2)} ${escapeHtml(l.unit || '')}`]),
      note: `The quantity is real; the amount is missing, not zero. Listing
        them is the point — the workbook shows ₹0 against 4,508 sq.m of false
        ceiling while the cell beside it works out ₹65.5 lakh (C-11).`,
    },
    excluded: {
      title: 'Excluded, and kept',
      value: String(data.excluded.length),
      rows: data.excluded.slice(0, 12).map(l =>
        [escapeHtml(l.description),
         escapeHtml(l.exclusion_reason || 'no reason recorded')]),
      note: `Excluded by name and by reason, never by multiplying by zero.
        <span class="mono">Electrical!G4 = G104*0</span> is a perfectly good
        formula that means "not this one" and says so nowhere — an exclusion
        you cannot see is one nobody can question.`,
    },
  });

  for (const section of data.sections) {
    createGrid(document.getElementById(`sec-${section.id}`), {
      columns: [
        { key: 'description', label: 'Description', kind: 'label', width: '300px',
          render: (v, r) => (r.is_heading
            ? `<strong>${escapeHtml(v)}</strong>`
            : `<span style="padding-left:${r.depth * 14}px">${escapeHtml(v)}</span>`) },
        { key: 'unit', label: 'Unit', kind: 'note', width: '64px', align: 'left',
          render: v => escapeHtml(v || '') },
        { key: 'qty', label: 'Quantity', kind: 'input', dp: 2, width: '110px',
          nullable: true,
          render: (v, r) => (r.is_heading ? ''
            : v === null || v === undefined ? '<span class="muted">—</span>'
            : fmt.n(v, 2)) },
        { key: 'rate', label: 'Rate', kind: 'derived', width: '116px',
          render: (v, r) => (r.is_heading ? ''
            : v === null ? '<span class="warn-text">no rate</span>'
            : `₹${fmt.n(v, 2)}`) },
        { key: '_src', label: 'Quantity from', kind: 'note', width: '150px',
          align: 'left',
          title: 'Carried means the figure came from a sheet not modelled here '
               + 'yet, with its source cell attached.',
          get: row => (row.is_heading ? '' : row.qty_carried ? 'carried' : 'derived'),
          render: (v, r) => (!v ? ''
            : v === 'carried'
              ? `<span class="tag warn" title="${escapeHtml(r.source_ref)}">carried</span>`
              : '<span class="tag ok">derived</span>') },
        { key: 'amount', label: 'Amount', kind: 'derived', width: '140px', total: true,
          render: (v, r) => (r.status === 'excluded'
            ? `<span class="warn-text" title="${escapeHtml(r.exclusion_reason)}">excluded</span>`
            : fmt.money(v)) },
      ],
      rows: section.lines,
      rowKey: r => r.id,
      reload: refresh,
      onCommit: (row, col, value) =>
        api.send('PATCH', `/collections/cost-lines/${row.id}`, { [col.key]: value }),
      onDerivedClick: (row, col) => {
        if (col.key === 'rate') {
          if (row.rate === null || row.rate === undefined) {
            openPanel(`${row.description} — rate`, `<div class="deriv-note">${
              escapeHtml(row.message || 'This line carries no rate, so it '
                + 'reaches no total. Listed rather than dropped: priced work '
                + 'nobody measured is a gap worth seeing.')}</div>`);
            return true;
          }
          showDerivation(`${row.description} — rate`, row.rate,
            row.rate_derivation, {
              format: v => `₹${fmt.n(v, 2)}`,
              extra: `<div class="deriv-note">${row.rate_item_id
                ? `From the <a href="#/rates">Rate Library</a> — change the
                   build-up there and every line priced on it moves.`
                : `Typed against this line rather than taken from the library.
                   A rate that lives in one place cannot be checked against
                   anything, which is how the workbook ended up with two
                   shuttering rates ₹1.25 crore apart (C-7).`}</div>`,
            });
          return true;
        }
        if (col.key === 'amount' && row.qty_derivation) {
          showDerivation(row.description, row.amount, row.qty_derivation, {
            format: v => fmt.money(v),
            unit: row.unit,
            extra: `<h4 class="deriv-h">Amount</h4>
              <div class="deriv-expr">${fmt.n(row.qty, 2)} ${escapeHtml(row.unit)}
                × ₹${fmt.n(row.rate ?? 0, 2)} = ${fmt.money(row.amount)}</div>
              ${row.source_ref ? `<div class="deriv-excel">In the workbook:
                ${escapeHtml(row.source_ref)}</div>` : ''}`,
          });
          return true;
        }
        return false;
      },
      footer: rows => ['<strong>Total</strong>', '', '', '', '',
        `<strong>${fmt.money(rows.filter(r => !r.is_heading && r.status !== 'excluded')
          .reduce((a, r) => a + r.amount, 0))}</strong>`],
    });
  }
});
