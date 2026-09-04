// Doors, windows and railings.
//
// The schedule here is a query over the openings actually placed in rooms, not a
// VLOOKUP bounded to `Doors!D146:H149`. A fifth door type appears because it
// exists, not because somebody widened a range.

import { api, fmt, openPanel, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml, showDerivation, wireTiles } from '../panel.js';

route('/openings', async (main) => {
  const [data, ref, costs] = await Promise.all([
    api.get('/openings'), api.get('/reference'), api.get('/opening-totals'),
  ]);

  main.innerHTML = `
    <div class="screen-head">
      <h1>Doors &amp; Windows</h1>
      <p>The type master is what you enter — a code and its size. The schedule below is counted
         from the openings placed in rooms, multiplied by how many of each unit the building has.
         Railings are measured in running metres, not the square metres the workbook labels them.</p>
    </div>
    <div class="tile-row">
      <div class="tile" data-tile="total"><div class="k">Doors &amp; windows cost</div>
        <div class="v">${fmt.money(costs.total)}</div>
        <div class="s">${fmt.int(costs.total_count)} openings in the building</div></div>
      ${costs.bands.map(b => `
      <div class="tile" data-tile="band:${escapeHtml(b.key)}"><div class="k">${escapeHtml(b.label)}</div>
        <div class="v">${fmt.money(b.amount)}</div>
        <div class="s">${fmt.int(b.count)} nos${
          b.unit && b.quantity ? ` · ${fmt.n(b.quantity, 2)} ${escapeHtml(b.unit)}` : ''}${
          b.unpriced ? ` · <span class="warn-text">${b.unpriced} unpriced</span>` : ''}</div></div>`)
        .join('')}
    </div>

    <div class="card" style="margin-top:16px">
      <h2>Total quantity and cost
        <span class="sub">every type, counted from the rooms and priced from D&amp;W Schedule</span></h2>
      <div id="costs"></div>
    </div>

    <div class="card">
      <h2>Opening types <span class="sub">${data.types.length} types · no row limit</span></h2>
      <div id="types"></div>
    </div>
    <div class="card">
      <h2>Door schedule <span class="sub">${fmt.int(data.total_doors)} doors in the building</span></h2>
      <div id="doors"></div>
    </div>
    <div class="card">
      <h2>Window &amp; ventilator schedule</h2>
      <div id="windows"></div>
    </div>
    ${data.railings.length ? `
    <div class="card"><h2>Railings <span class="sub">measured in running metres</span></h2>
      <div id="railings"></div></div>` : ''}
    ${data.curtain_wall.length ? `
    <div class="card"><h2>Curtain wall
      <span class="sub">quantity pending Q-1 — the ×32 multiplier is unconfirmed</span></h2>
      <div id="curtain"></div></div>` : ''}`;

  wireTiles(main, Object.fromEntries([
    ['total', {
      title: 'Every door, window, railing and bay',
      value: fmt.money(costs.total),
      subtitle: `${fmt.int(costs.total_count)} openings`,
      rows: costs.bands.map(b => [escapeHtml(b.label), fmt.money(b.amount)]),
      note: `Each band priced on what it is bought by. This was zero until
        column F of <span class="mono">D&amp;W Schedule</span> was read —
        doors and windows had quantities and no cost at all.`,
    }],
    ...costs.bands.map(b => [`band:${b.key}`, {
      title: `${b.label} — ${fmt.int(b.count)} in the building`,
      value: fmt.money(b.amount),
      subtitle: b.unit && b.quantity
        ? `${fmt.n(b.quantity, 2)} ${b.unit}` : `${b.lines} type(s)`,
      rows: (b.amount_derivation ? b.amount_derivation.inputs : [])
        .map(i => [escapeHtml(i.name), fmt.money(i.value)]),
      note: (b.amount_derivation ? escapeHtml(b.amount_derivation.note) : '')
        + ` <a href="#/openings">The table below</a> breaks each type down
        further — click any figure in it.`,
    }]),
  ]));

  // A door is bought by the leaf and glazing by the square metre, so the
  // "priced on" column says which of the two figures beside it was multiplied.
  createGrid(document.getElementById('costs'), {
    columns: [
      { key: 'code', label: 'Code', kind: 'label', width: '110px' },
      { key: 'kind', label: 'Kind', kind: 'note', width: '112px', align: 'left',
        render: v => escapeHtml(String(v).replace('_', ' ')) },
      { key: 'count', label: 'Count', kind: 'derived', dp: 0, width: '92px' },
      { key: 'quantity', label: 'Quantity', kind: 'derived', dp: 2, width: '112px' },
      { key: 'unit', label: 'Unit', kind: 'note', width: '56px', align: 'left' },
      { key: 'rate', label: 'Rate', kind: 'derived', width: '112px',
        render: (v, row) => (v === null || v === undefined ? '<span class="muted">—</span>'
          : `₹${fmt.n(v, 2)}<span class="muted"> /${escapeHtml(row.rate_unit)}</span>`) },
      { key: 'rate_unit', label: 'Priced on', kind: 'note', width: '96px', align: 'left',
        title: 'A rate per Nos. prices the count; a rate per sq.m or RM prices the '
             + 'measured quantity. Mixing the two raises rather than multiplying.',
        render: v => `<span class="muted">${v === 'NOS' ? 'count' : 'quantity'}</span>` },
      { key: 'amount', label: 'Amount', kind: 'derived', width: '178px', total: true,
        render: (v, row) => (row.status === 'priced' ? fmt.money(v) : whyNot(row)) },
    ],
    // Money first; the priced-but-never-measured types fall to the bottom
    // where they read as the gap they are, rather than heading the table.
    rows: [...costs.lines].sort((a, b) => b.amount - a.amount),
    rowKey: r => r.code,
    onDerivedClick: (row, col) => openingWorking(row, col.key),
    footer: rows => ['<strong>Total</strong>', '', '', '', '', '', '',
                     `<strong>${fmt.money(rows.reduce((a, r) => a + r.amount, 0))}</strong>`],
  });

  if (costs.unpriced.length) {
    const bays = costs.unpriced.filter(u => u.code.startsWith('CW '));
    const rest = costs.unpriced.filter(u => !u.code.startsWith('CW '));
    document.getElementById('costs').insertAdjacentHTML('beforeend', `
      <div class="card-body muted" style="border-top:1px solid var(--line)">
        <strong>Why some rows show no amount.</strong> These types carry a rate
        and no measured quantity, so there is nothing to multiply. They are listed
        rather than hidden, because priced work that nobody measured is a gap worth
        seeing — not a zero.
        ${bays.length ? `<p style="margin:8px 0 0">
          <strong>${bays.length} curtain-wall bays</strong> (${bays.map(u => escapeHtml(u.code.slice(3))).join(', ')})
          — the workbook multiplies these by 32 (<span class="mono">D&amp;W Schedule!E32</span>)
          where the building has 4 office floors. That is question <strong>Q-1</strong>,
          worth ₹2.89 Cr, and still open. Rather than guess a count, they stay
          measured-at-nothing until it is settled.</p>` : ''}
        ${rest.length ? `<p style="margin:8px 0 0">
          <strong>${rest.map(u => escapeHtml(u.code)).join(', ')}</strong>
          — in the schedule with a rate, but not placed in any room. The workbook's
          own window summary (<span class="mono">Windows!D166:D177</span>) leaves
          ${rest.length === 1 ? 'it' : 'them'} out too.</p>` : ''}
      </div>`);
  }

  createGrid(document.getElementById('types'), {
    columns: [
      { key: 'code', label: 'Code', kind: 'input', text: true, width: '130px',
        align: 'left' },
      { key: 'kind', label: 'Kind', kind: 'select', width: '124px',
        options: ref.opening_kinds },
      { key: 'width_m', label: 'Width', unit: 'm', kind: 'input', dp: 2, width: '80px' },
      { key: 'height_m', label: 'Height', unit: 'm', kind: 'input', dp: 2, width: '80px' },
      { key: 'area_sqm', label: 'Area', unit: 'sq.m', kind: 'derived', dp: 4, width: '96px' },
      { key: 'specification', label: 'Notes', kind: 'input', text: true,
        width: '260px', align: 'left' },
      { key: '_del', label: '', kind: 'delete', width: '34px' },
    ],
    rows: data.types,
    reload: refresh,
    addLabel: 'Add opening type',
    rowName: row => `opening type “${row.code}”`,
    onAdd: () => api.post('/collections/opening-types',
      { code: 'NEW', kind: 'door', width_m: 0.9, height_m: 2.1 }),
    onDelete: row => api.send('DELETE', `/collections/opening-types/${row.id}`),
    onCommit: (row, col, value) =>
      api.send('PATCH', `/collections/opening-types/${row.id}`, { [col.key]: value }),
    onDerivedClick: (row, col) => {
      if (col.key !== 'area_sqm') return false;
      const line = costs.lines.find(l => l.code === row.code);
      showDerivation(`${row.code} — area of one leaf`, row.area_sqm,
        line ? line.area_derivation : null, { unit: 'sq.m' });
      return !!(line && line.area_derivation);
    },
  });

  const scheduleColumns = [
    { key: 'code', label: 'Type', kind: 'label', width: '110px' },
    { key: 'width_m', label: 'Width', unit: 'm', kind: 'derived', dp: 2, width: '76px' },
    { key: 'height_m', label: 'Height', unit: 'm', kind: 'derived', dp: 2, width: '76px' },
    { key: 'count', label: 'Nos', kind: 'derived', dp: 0, width: '82px' },
    { key: 'quantity', label: 'Quantity', kind: 'derived', dp: 2, width: '112px', total: true },
    { key: 'unit', label: 'Unit', kind: 'note', width: '64px', align: 'left' },
  ];
  for (const [id, rows] of [['doors', data.doors], ['windows', data.windows],
                            ['railings', data.railings], ['curtain', data.curtain_wall]]) {
    const host = document.getElementById(id);
    if (host) createGrid(host, {
      columns: scheduleColumns, rows, rowKey: r => r.code,
      emptyMessage: 'None scheduled.',
      onDerivedClick: (row, col) => scheduleWorking(row, col.key),
    });
  }

  // -- the workings -------------------------------------------------------

  /** One line of the priced schedule: count, quantity, rate or amount. */
  function openingWorking(row, key) {
    const where = `${row.code} — ${String(row.kind).replace('_', ' ')}`;

    if (key === 'count') {
      showDerivation(`${where} — count`, row.count, row.count_derivation, {
        format: v => `${fmt.int(v)} nos`,
        extra: `<div class="deriv-note">Every room that carries this type,
          folded up through the unit types that contain it. Add one to a room
          and this moves by itself — nothing links the two by hand.</div>`,
      });
      return true;
    }
    if (key === 'quantity') {
      showDerivation(`${where} — quantity`, row.quantity, row.quantity_derivation,
        { unit: row.unit });
      return true;
    }
    if (key === 'rate') {
      if (row.rate === null || row.rate === undefined) {
        openPanel(`${where} — rate`, `<div class="deriv-note">${escapeHtml(
          row.message || 'No rate reaches this type.')}</div>`);
        return true;
      }
      showDerivation(`${where} — rate`, row.rate, row.rate_derivation, {
        format: v => `₹${fmt.n(v, 2)}`,
        extra: `<div class="deriv-note">${escapeHtml(row.rate_description || '')}
          — per ${escapeHtml(row.rate_unit)}, from <span class="mono">D&amp;W
          Schedule</span> column F. Nothing was reading that column, which is
          why doors and windows had quantities and no cost.</div>`,
      });
      return true;
    }
    if (key === 'amount') {
      if (row.status !== 'priced') {
        openPanel(`${where} — amount`, `<div class="deriv-note">${escapeHtml(
          row.message || 'This type reaches no total.')}</div>
          <div class="deriv-note">Listed at nothing rather than left out: priced
          work nobody measured, or measured work nobody priced, is a gap worth
          seeing (C-11).</div>`);
        return true;
      }
      showDerivation(`${where} — amount`, row.amount, row.amount_derivation, {
        format: v => fmt.money(v),
      });
      return true;
    }
    return false;
  }

  /** A row of one of the per-kind schedules, which carry no money. */
  function scheduleWorking(row, key) {
    if (key === 'count') {
      showDerivation(`${row.code} — count`, row.count, row.count_derivation,
        { format: v => `${fmt.int(v)} nos` });
      return true;
    }
    if (key === 'quantity') {
      showDerivation(`${row.code} — quantity`, row.quantity,
        row.quantity_derivation, { unit: row.unit });
      return true;
    }
    if (key === 'width_m' || key === 'height_m') {
      showDerivation(`${row.code} — one leaf`, row.width_m * row.height_m,
        row.area_derivation, { unit: 'sq.m' });
      return true;
    }
    return false;
  }
});


// Why a line reaches no amount, said in the cell rather than on hover.
// Meaning never rides on colour alone.
function whyNot(row) {
  const reason = row.status === 'no_quantity'
    ? (row.code.startsWith('CW ') ? 'priced, count unsettled (Q-1)'
                                  : 'priced, not in any room')
    : 'no rate';
  return `<span class="warn-text" title="${escapeHtml(row.message)}">`
       + `<span aria-hidden="true">⚠ </span>${reason}</span>`;
}
