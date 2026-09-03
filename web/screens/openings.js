// Doors, windows and railings.
//
// The schedule here is a query over the openings actually placed in rooms, not a
// VLOOKUP bounded to `Doors!D146:H149`. A fifth door type appears because it
// exists, not because somebody widened a range.

import { api, fmt, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml } from '../panel.js';

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
      <div class="tile"><div class="k">Doors &amp; windows cost</div>
        <div class="v">${fmt.money(costs.total)}</div>
        <div class="s">${fmt.int(costs.total_count)} openings in the building</div></div>
      ${costs.bands.map(b => `
      <div class="tile"><div class="k">${escapeHtml(b.label)}</div>
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

  // A door is bought by the leaf and glazing by the square metre, so the
  // "priced on" column says which of the two figures beside it was multiplied.
  createGrid(document.getElementById('costs'), {
    columns: [
      { key: 'code', label: 'Code', kind: 'label', width: '110px' },
      { key: 'kind', label: 'Kind', kind: 'derived', width: '112px', align: 'left',
        render: v => escapeHtml(String(v).replace('_', ' ')) },
      { key: 'count', label: 'Count', kind: 'derived', dp: 0, width: '92px' },
      { key: 'quantity', label: 'Quantity', kind: 'derived', dp: 2, width: '112px' },
      { key: 'unit', label: 'Unit', kind: 'derived', width: '56px', align: 'left' },
      { key: 'rate', label: 'Rate', kind: 'derived', width: '112px',
        render: (v, row) => (v === null || v === undefined ? '<span class="muted">—</span>'
          : `₹${fmt.n(v, 2)}<span class="muted"> /${escapeHtml(row.rate_unit)}</span>`) },
      { key: 'rate_unit', label: 'Priced on', kind: 'derived', width: '96px', align: 'left',
        title: 'A rate per Nos. prices the count; a rate per sq.m or RM prices the '
             + 'measured quantity. Mixing the two raises rather than multiplying.',
        render: v => `<span class="muted">${v === 'NOS' ? 'count' : 'quantity'}</span>` },
      { key: 'amount', label: 'Amount', kind: 'derived', width: '134px', total: true,
        render: (v, row) => (row.status === 'priced' ? fmt.money(v)
          : `<span class="warn-text" title="${escapeHtml(row.message)}">not counted</span>`) },
    ],
    // Money first; the priced-but-never-measured types fall to the bottom
    // where they read as the gap they are, rather than heading the table.
    rows: [...costs.lines].sort((a, b) => b.amount - a.amount),
    rowKey: r => r.code,
    footer: rows => ['<strong>Total</strong>', '', '', '', '', '', '',
                     `<strong>${fmt.money(rows.reduce((a, r) => a + r.amount, 0))}</strong>`],
  });

  if (costs.unpriced.length) {
    document.getElementById('costs').insertAdjacentHTML('beforeend', `
      <div class="card-body muted" style="border-top:1px solid var(--line)">
        <strong>${costs.unpriced.length} type${costs.unpriced.length === 1 ? '' : 's'}
        carr${costs.unpriced.length === 1 ? 'ies' : 'y'} a rate but reach
        no total:</strong>
        ${costs.unpriced.map(u => escapeHtml(u.code)).join(' · ')}.
        These are priced and unmeasured — work someone costed and nobody counted.
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
  });

  const scheduleColumns = [
    { key: 'code', label: 'Type', kind: 'label', width: '110px' },
    { key: 'width_m', label: 'Width', unit: 'm', kind: 'derived', dp: 2, width: '76px' },
    { key: 'height_m', label: 'Height', unit: 'm', kind: 'derived', dp: 2, width: '76px' },
    { key: 'count', label: 'Nos', kind: 'derived', dp: 0, width: '82px' },
    { key: 'quantity', label: 'Quantity', kind: 'derived', dp: 2, width: '112px', total: true },
    { key: 'unit', label: 'Unit', kind: 'derived', width: '64px', align: 'left' },
  ];
  for (const [id, rows] of [['doors', data.doors], ['windows', data.windows],
                            ['railings', data.railings], ['curtain', data.curtain_wall]]) {
    const host = document.getElementById(id);
    if (host) createGrid(host, { columns: scheduleColumns, rows, emptyMessage: 'None scheduled.' });
  }
});
