// The floor x unit-type matrix -- the screen that has to feel exactly like the
// sheet it replaces, because this is where a QS spends the most time.
//
// In the workbook the BHK split beneath this matrix is a hand-typed list of
// columns (`Room Conf!L44 = M40+O40+R40+U40+V40+Y40+Z40+P40`, with P40 appended
// out of sequence). Add a unit type and the split silently stops adding up.
// Here it is a group-by over an attribute, so it cannot go stale.

import { api, fmt, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml } from '../panel.js';

route('/room-config', async (main) => {
  const data = await api.get('/room-config');
  const shown = data.unit_types.filter(u => !u.is_common_area || u.total > 0);

  const columns = [
    { key: 'name', label: 'Floor', kind: 'label', width: '150px' },
    { key: 'floor_to_floor_ht', label: 'Ht', unit: 'm', kind: 'input', dp: 2, width: '54px',
      title: 'Floor-to-floor height. Drives every wall quantity on this floor.' },
    ...shown.map(u => ({
      key: u.id, label: u.code, unit: u.classification, kind: 'input', dp: 0,
      width: '58px', blankZero: true,
      get: row => row.counts[u.id] ?? 0,
      title: `${u.code} — ${u.classification}. Total in the building: ${u.total}`,
    })),
    { key: 'row_total', label: 'Units', kind: 'derived', dp: 0, width: '58px',
      total: true, blankZero: true,
      title: 'Units on this floor. Computed, not typed.' },
  ];

  main.innerHTML = `
    <div class="screen-head">
      <h1>Room Config</h1>
      <p>Which unit types sit on which floors. Type a count, paste a column straight from Excel,
         or use the arrow keys. Every total on this page and in the bar above is computed from
         these cells.</p>
    </div>
    <div class="card">
      <h2>Floor × unit type
        <span class="sub">${data.floors.length} floors · ${shown.length} types ·
        white cells are yours, grey are computed</span></h2>
      <div id="grid"></div>
    </div>
    <div class="card">
      <h2>Unit mix <span class="sub">a group-by over classification, never a typed column list</span></h2>
      <div class="card-body" id="split"></div>
    </div>`;

  createGrid(document.getElementById('grid'), {
    columns,
    rows: data.floors,
    reload: refresh,
    footer: rows => [
      '<strong>Total</strong>', '',
      ...shown.map(u => `<span class="mono">${u.total}</span>`),
      `<span class="mono">${rows.reduce((a, r) => a + r.row_total, 0)}</span>`,
    ],
    onCommit: async (row, col, value) => {
      if (col.key === 'floor_to_floor_ht') {
        await api.put(`/floors/${row.id}`, { floor_to_floor_ht: value });
      } else {
        await api.put('/room-config/cell',
          { floor_id: row.id, unit_type_id: col.key, count: value });
      }
    },
  });

  const total = Object.entries(data.classification)
    .reduce((a, [k, v]) => k === 'Office' ? a : a + v, 0);
  document.getElementById('split').innerHTML = `
    <div class="tile-row">
      ${Object.entries(data.classification).map(([k, v]) => `
        <div class="tile"><div class="k">${escapeHtml(k)}</div>
          <div class="v">${fmt.int(v)}</div>
          <div class="s">${k === 'Office' ? 'offices' : `${(v / total * 100).toFixed(0)}% of flats`}</div>
        </div>`).join('')}
    </div>`;
});
