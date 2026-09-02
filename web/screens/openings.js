// Doors, windows and railings.
//
// The schedule here is a query over the openings actually placed in rooms, not a
// VLOOKUP bounded to `Doors!D146:H149`. A fifth door type appears because it
// exists, not because somebody widened a range.

import { api, fmt, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml } from '../panel.js';

route('/openings', async (main) => {
  const data = await api.get('/openings');

  main.innerHTML = `
    <div class="screen-head">
      <h1>Doors &amp; Windows</h1>
      <p>The type master is what you enter — a code and its size. The schedule below is counted
         from the openings placed in rooms, multiplied by how many of each unit the building has.
         Railings are measured in running metres, not the square metres the workbook labels them.</p>
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

  createGrid(document.getElementById('types'), {
    columns: [
      { key: 'code', label: 'Code', kind: 'label', width: '130px' },
      { key: 'kind', label: 'Kind', kind: 'derived', width: '104px', align: 'left',
        render: v => `<span class="tag">${escapeHtml(v.replace('_', ' '))}</span>` },
      { key: 'width_m', label: 'Width', unit: 'm', kind: 'input', dp: 2, width: '80px' },
      { key: 'height_m', label: 'Height', unit: 'm', kind: 'input', dp: 2, width: '80px' },
      { key: 'area_sqm', label: 'Area', unit: 'sq.m', kind: 'derived', dp: 4, width: '96px' },
      { key: 'specification', label: 'Source', kind: 'derived', width: '260px', align: 'left',
        render: v => `<span class="muted">${escapeHtml(v || '')}</span>` },
    ],
    rows: data.types,
    reload: refresh,
    onCommit: (row, col, value) => api.put(`/opening-types/${row.id}`, { [col.key]: value }),
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
