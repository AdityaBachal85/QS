// The floor x unit-type matrix -- the screen that has to feel exactly like the
// sheet it replaces, because this is where a QS spends the most time.
//
// In the workbook the BHK split beneath this matrix is a hand-typed list of
// columns (`Room Conf!L44 = M40+O40+R40+U40+V40+Y40+Z40+P40`, with P40 appended
// out of sequence). Add a unit type and the split silently stops adding up.
// Here it is a group-by over an attribute, so it cannot go stale.

import { api, fmt, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml, showDerivation } from '../panel.js';

route('/room-config', async (main) => {
  const [data, ref] = await Promise.all([
    api.get('/room-config'), api.get('/reference'),
  ]);
  const shown = data.unit_types.filter(u => !u.is_common_area || u.total > 0);

  const columns = [
    { key: 'name', label: 'Floor', kind: 'input', text: true, width: '150px',
      align: 'left', title: 'Rename a floor by typing over it.' },
    { key: 'floor_type', label: 'Type', kind: 'select', width: '100px',
      options: ref.floor_types },
    { key: 'floor_to_floor_ht', label: 'Ht', unit: 'm', kind: 'input', dp: 2,
      width: '56px',
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
    { key: '_del', label: '', kind: 'delete', width: '34px' },
  ];

  main.innerHTML = `
    <div class="screen-head">
      <h1>Room Config</h1>
      <p>Which unit types sit on which floors. Type a count, paste a column straight from Excel,
         or use the arrow keys. Add floors and unit types here — every total on this page and in
         the bar above follows from these cells.</p>
    </div>
    <div class="toolbar">
      <button class="btn primary" id="addUnitType">+ Add unit type</button>
      <span class="muted">${shown.length} types · ${data.floors.length} floors</span>
    </div>
    <div class="card">
      <h2>Floor × unit type
        <span class="sub">white cells are yours, grey are computed</span></h2>
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
    addLabel: 'Add floor',
    rowName: row => `floor “${row.name}”`,
    onAdd: () => api.post('/collections/floors', {
      name: `Floor ${data.floors.length + 1}`, floor_to_floor_ht: 3.0,
    }),
    onDelete: row => api.send('DELETE', `/collections/floors/${row.id}`),
    footer: rows => [
      '<strong>Total</strong>', '', '',
      ...shown.map(u => `<span class="mono">${u.total}</span>`),
      `<span class="mono">${rows.reduce((a, r) => a + r.row_total, 0)}</span>`, '',
    ],
    onDerivedClick: (row, col) => {
      if (col.key !== 'row_total') return false;
      showDerivation(`${row.name} — units on this floor`, row.row_total,
        row.row_total_derivation, {
          format: v => `${v} unit${v === 1 ? '' : 's'}`,
          extra: `<div class="deriv-note">Change a cell in this row and the
            figure moves, along with the BHK split at the top of the screen and
            every quantity measured for a unit on this floor. Nothing here is
            stored — it is counted from the matrix each time it is asked
            for.</div>`,
        });
      return true;
    },
    onCommit: async (row, col, value) => {
      if (['name', 'floor_to_floor_ht', 'floor_type'].includes(col.key)) {
        await api.send('PATCH', `/collections/floors/${row.id}`, { [col.key]: value });
      } else {
        await api.put('/room-config/cell',
          { floor_id: row.id, unit_type_id: col.key, count: value });
      }
    },
  });

  document.getElementById('addUnitType').onclick = async () => {
    const code = prompt('New unit type code, e.g. "Flat 11" or "Shop 1"');
    if (!code) return;
    const classification = prompt(
      'Classification (1BHK, 2BHK, 3BHK, Office, Shop…)', '2BHK') || 'Unassigned';
    try {
      await api.post('/collections/unit-types', { code, classification });
      await refresh();
    } catch (err) { alert(err.message); }
  };

  const total = Object.entries(data.classification)
    .reduce((a, [k, v]) => k === 'Office' ? a : a + v, 0);
  document.getElementById('split').innerHTML = `
    <div class="tile-row">
      ${Object.entries(data.classification).map(([k, v]) => `
        <div class="tile"><div class="k">${escapeHtml(k)}</div>
          <div class="v">${fmt.int(v)}</div>
          <div class="s">${k === 'Office' ? 'offices'
            : `${total ? (v / total * 100).toFixed(0) : 0}% of flats`}</div>
        </div>`).join('')}
    </div>`;
});
