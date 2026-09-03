// Which rate block prices each room type.
//
// The workbook keeps two vocabularies for the same rooms and they overlap by
// six names out of twenty-five: `Flat Sizes` says `M. Bedroom`, the rate list
// calls the block that prices it `M. Bed`; `M. Toilet` is priced by
// `Toilet With M. Bed`; `C.Bedroom` and `C. Bedroom` are one room typed twice.
// Without these links 98 of 154 rooms can be measured and not priced.
//
// The importer proposes; nobody's guess is treated as a decision. Each link
// stays flagged until somebody here agrees with it.

import { api, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml } from '../panel.js';

route('/mapping', async (main) => {
  const { mappings, targets } = await api.get('/room-type-mapping');
  const unconfirmed = mappings.filter(m => !m.confirmed && m.prices_as_id);
  const unmapped = mappings.filter(m => !m.prices_as_id && !m.own_schedule);

  main.innerHTML = `
    <div class="screen-head">
      <h1>Room type pricing</h1>
      <p>Which block of the rate library prices each room. The importer proposed these links
         by name; each one is a guess until you agree with it, and getting one wrong prices a
         bedroom as a toilet.</p>
    </div>
    <div class="toolbar">
      <span class="chip ${unconfirmed.length ? 'warn' : 'ok'}">
        ${unconfirmed.length} awaiting confirmation</span>
      <span class="chip ${unmapped.length ? 'bad' : 'mute'}">${unmapped.length} unpriceable</span>
      ${unconfirmed.length
        ? '<button class="btn primary" id="confirmAll">Confirm all proposals</button>' : ''}
    </div>
    <div class="card"><div id="grid"></div></div>`;

  createGrid(document.getElementById('grid'), {
    columns: [
      { key: 'name', label: 'Room type (sizes sheet)', kind: 'label', width: '210px' },
      { key: 'category', label: 'Category', kind: 'derived', width: '100px', align: 'left',
        render: v => `<span class="tag">${escapeHtml(v)}</span>` },
      { key: 'rooms', label: 'Rooms', kind: 'derived', dp: 0, width: '70px' },
      { key: 'prices_as_id', label: 'Priced as (rate list)', kind: 'select', width: '210px',
        options: [{ value: '', label: '— its own schedule —' }, ...targets] },
      { key: 'finishes', label: 'Finishes', kind: 'derived', dp: 0, width: '80px',
        flagMissing: true,
        render: v => v ? String(v) : '<span class="tag bad">none</span>' },
      { key: 'confirmed', label: 'Agreed', kind: 'derived', width: '130px', align: 'left',
        render: (v, r) => v
          ? '<span class="tag ok">confirmed</span>'
          : (r.prices_as_id
            ? '<span class="tag warn">proposal</span>'
            : '<span class="tag bad">cannot be priced</span>') },
    ],
    rows: mappings,
    reload: refresh,
    onCommit: (row, col, value) =>
      api.put(`/room-type-mapping/${row.id}`,
        { prices_as_id: value || null, confirmed: true }),
  });

  const button = document.getElementById('confirmAll');
  if (button) {
    button.onclick = async () => {
      for (const m of unconfirmed) {
        await api.put(`/room-type-mapping/${m.id}`, { confirmed: true });
      }
      await refresh();
    };
  }
});
