// The rate library.
//
// In the workbook the overall rate is a formula with four constants written into
// its text -- `=+(E6*1.1+F6)*10.764` -- and the wastage among them is not one
// number: 1.1 for flooring, 1.15 for toilet dado, 1.05 for back-coat plaster.
// Here each is a field you can see and change, and the working is one click away.

import { api, fmt, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml, showDerivation } from '../panel.js';

const METHOD_LABEL = {
  area_with_wastage: 'area + wastage', area_simple: 'area, no wastage',
  linear_with_wastage: 'linear + wastage', frame: 'frame', area_sum: 'area sum',
  passthrough: 'as quoted', link: 'mirrors another', constant: 'entered',
};

route('/rates', async (main) => {
  const all = await api.get('/rates');

  main.innerHTML = `
    <div class="screen-head">
      <h1>Rate Library</h1>
      <p>Enter the basic rate, the laying rate and the wastage. The overall rate is computed —
         click it to see exactly how. Every take-off line references a rate by identity, so rows
         can be added, deleted or re-sorted and nothing downstream moves.</p>
    </div>
    <div class="toolbar">
      <input class="text-input" id="q" placeholder="Filter by description or specification…" style="min-width:280px">
      <select class="sel-input" id="cat"><option value="">All categories</option></select>
      <label class="muted"><input type="checkbox" id="unpriced"> unpriced only</label>
      <span class="muted" id="count"></span>
    </div>
    <div class="card"><div id="grid"></div></div>`;

  const cats = [...new Set(all.map(r => r.category).filter(Boolean))].sort();
  document.getElementById('cat').innerHTML +=
    cats.map(c => `<option>${escapeHtml(c)}</option>`).join('');

  const columns = [
    { key: 'description', label: 'Item', kind: 'label', width: '210px' },
    { key: 'specification', label: 'Specification', kind: 'derived', width: '210px',
      align: 'left',
      render: v => `<span class="muted">${escapeHtml(v || '—')}</span>` },
    { key: 'basic_rate', label: 'Basic', unit: '₹', kind: 'input', dp: 2, width: '86px', nullable: true },
    { key: 'laying_rate', label: 'Laying', unit: '₹', kind: 'input', dp: 2, width: '86px', nullable: true },
    { key: 'wastage_pct', label: 'Wastage', kind: 'input', dp: 3, width: '84px', nullable: true,
      render: v => v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`,
      title: 'Per rate, not a global constant. The sheet uses 1.03, 1.05, 1.1 and 1.15.' },
    { key: 'method', label: 'Build-up', kind: 'derived', width: '140px', align: 'left',
      render: v => `<span class="tag">${escapeHtml(METHOD_LABEL[v] || v || '—')}</span>` },
    { key: 'unit', label: 'Unit', kind: 'derived', width: '62px', align: 'left' },
    { key: 'overall_rate', label: 'Overall rate', kind: 'derived', dp: 2, width: '116px',
      total: true, flagMissing: true,
      render: (v, r) => v === null || v === undefined
        ? '<span class="tag bad">no rate</span>'
        : (!r.is_priced ? '<span class="tag bad">no rate</span>' : `₹${fmt.n(v, 2)}`) },
  ];

  function draw() {
    const q = document.getElementById('q').value.trim().toLowerCase();
    const cat = document.getElementById('cat').value;
    const onlyUnpriced = document.getElementById('unpriced').checked;
    const rows = all.filter(r =>
      (!q || `${r.description} ${r.specification}`.toLowerCase().includes(q)) &&
      (!cat || r.category === cat) &&
      (!onlyUnpriced || !r.is_priced));

    document.getElementById('count').textContent =
      `${rows.length} of ${all.length} rates · ${all.filter(r => !r.is_priced).length} unpriced`;

    const host = document.getElementById('grid');
    host.innerHTML = '';
    createGrid(host, {
      columns, rows, reload: refresh,
      emptyMessage: 'No rates match that filter.',
      onCommit: (row, col, value) => {
        // Wastage is typed as a percentage and stored as a ratio.
        const v = col.key === 'wastage_pct' && value !== null && value > 1 ? value / 100 : value;
        return api.put(`/rates/${row.id}`, { [col.key]: v });
      },
      onDerivedClick: (row, col) => {
        if (col.key !== 'overall_rate') return;
        showDerivation(row.description, row.overall_rate, row.derivation, {
          unit: `per ${row.unit}`,
          format: v => v === null ? '— no rate' : `₹${fmt.n(v, 4)}`,
          extra: row.is_priced ? '' : `<div class="deriv-note">
            This item has no price components. It computes to zero, which is not the same as
            costing nothing — the estimate cannot be issued while it stays this way.</div>`,
        });
      },
    });
  }

  ['q', 'cat', 'unpriced'].forEach(id =>
    document.getElementById(id).addEventListener('input', draw));
  draw();
});
