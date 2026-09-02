// Named parameters -- the fix for roughly forty magic numbers.
//
// `Room Conf!AD44 = AD42*1.12` and `AD45 = AD44*1.08` are live in the workbook
// with no label, no source and no note. They import here with their values
// intact and no description, and the validation engine keeps reporting them
// until somebody says what they are.

import { api, fmt, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml } from '../panel.js';

route('/parameters', async (main) => {
  const params = await api.get('/parameters');
  const unnamed = params.filter(p => !p.is_named).length;

  main.innerHTML = `
    <div class="screen-head">
      <h1>Parameters</h1>
      <p>Every constant the engine uses, named and editable. Change one and every value built on
         it recalculates at once — the conversion factors, the wastage allowance, the slab
         allowance and the uplift percentages are all here rather than typed into formulas.</p>
    </div>
    ${unnamed ? `<div class="card"><div class="card-body">
      <span class="chip warn">${unnamed} unnamed</span>
      <span class="muted" style="margin-left:8px">These came out of the workbook with values but
      no explanation. Until somebody names them, nobody can change them safely.</span>
    </div></div>` : ''}
    <div class="card"><div id="grid"></div></div>`;

  createGrid(document.getElementById('grid'), {
    columns: [
      { key: 'key', label: 'Parameter', kind: 'label', width: '190px' },
      { key: 'value', label: 'Value', kind: 'input', dp: 4, width: '110px' },
      { key: 'unit', label: 'Unit', kind: 'derived', width: '92px', align: 'left' },
      { key: 'description', label: 'What it is', kind: 'derived', width: '420px', align: 'left',
        render: v => v
          ? `<span class="muted">${escapeHtml(v)}</span>`
          : '<span class="tag warn">no description — nobody knows what this is</span>' },
      { key: 'source', label: 'From', kind: 'derived', width: '250px', align: 'left',
        render: v => `<span class="muted mono" style="font-size:11px">${escapeHtml(v || '')}</span>` },
    ],
    rows: params,
    reload: refresh,
    onCommit: (row, col, value) => api.put(`/parameters/${row.key}`, { value }),
  });
});
