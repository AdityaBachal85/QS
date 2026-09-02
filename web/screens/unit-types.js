// Unit types, their rooms, and the quantities each room produces.
//
// This is where "a flat with four bathrooms and a flat with one" is just a
// different number of rows, and where the deduction rules become visible: every
// finish shows its gross, what the room's own openings take off it, and the net.

import { api, fmt, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml } from '../panel.js';
import { showDerivation } from '../panel.js';

route('/unit-types', async (main, hash) => {
  const selected = new URLSearchParams(hash.split('?')[1] || '').get('id');
  const types = await api.get('/unit-types');
  if (!selected) return renderList(main, types);
  return renderRooms(main, types, selected);
});

function renderList(main, types) {
  main.innerHTML = `
    <div class="screen-head">
      <h1>Unit Types &amp; Rooms</h1>
      <p>A unit type owns as many rooms as it has — five or ten, four bathrooms or one, balcony
         or none. Nothing counts them and nothing assumes a maximum. Areas in square feet are
         computed from the square metres you enter; there is no square-foot cell to overwrite.</p>
    </div>
    <div class="card">
      <h2>All unit types <span class="sub">${types.length} types</span></h2>
      <div id="grid"></div>
    </div>`;

  createGrid(document.getElementById('grid'), {
    columns: [
      { key: 'code', label: 'Type', kind: 'label', width: '170px',
        render: (v, r) => `<a href="#/unit-types?id=${encodeURIComponent(r.id)}">${escapeHtml(v)}</a>` },
      { key: 'classification', label: 'Class', kind: 'derived', width: '90px', align: 'left',
        render: v => `<span class="tag">${escapeHtml(v)}</span>` },
      { key: 'rooms', label: 'Rooms', kind: 'derived', dp: 0, width: '64px' },
      { key: 'count', label: 'Units', kind: 'derived', dp: 0, width: '64px',
        title: 'Summed from the floor matrix, not typed.' },
      { key: 'area_sqm', label: 'Carpet', unit: 'sq.m', kind: 'derived', dp: 2, width: '86px' },
      { key: 'area_sqft', label: 'Carpet', unit: 'sq.ft', kind: 'derived', dp: 2, width: '96px' },
      { key: 'total_sqft', label: 'All units', unit: 'sq.ft', kind: 'derived', dp: 2,
        width: '112px', total: true },
    ],
    rows: types,
    onDerivedClick: (row, col) => {
      if (col.key === 'total_sqft') {
        showDerivation(`${row.code} — total carpet area`, row.total_sqft, row.derivation,
          { unit: 'sq.ft' });
      }
    },
  });
}

async function renderRooms(main, types, id) {
  const data = await api.get(`/unit-types/${encodeURIComponent(id)}/rooms`);
  const u = data.unit_type;

  main.innerHTML = `
    <div class="screen-head">
      <h1>${escapeHtml(u.code)} <span class="tag">${escapeHtml(u.classification)}</span></h1>
      <p><a href="#/unit-types">← all unit types</a> ·
         ${data.rooms.length} rooms · ${u.count} units in the building ·
         ${fmt.n(data.area_sqft, 2)} sq.ft each, ${fmt.n(data.total_sqft, 2)} sq.ft in total</p>
    </div>
    <div class="card">
      <h2>Rooms <span class="sub">enter area in sq.m and perimeter; the rest is computed</span></h2>
      <div id="grid"></div>
    </div>
    <div class="card">
      <h2>Quantities per room
        <span class="sub">gross, what the room's own openings deduct, and the net</span></h2>
      <div class="card-body" style="padding-top:6px">
        <p class="muted" style="margin-top:0">Skirting deducts each door's <strong>width</strong>,
        not its area — a running-metre quantity takes a running-metre deduction. Wall finishes
        deduct the full opening area. Add a door to a room and both move by themselves.</p>
      </div>
      <div id="qty"></div>
    </div>`;

  createGrid(document.getElementById('grid'), {
    columns: [
      { key: 'label', label: 'Room', kind: 'label', width: '190px' },
      { key: 'category', label: 'Category', kind: 'derived', width: '92px', align: 'left',
        render: v => `<span class="tag">${escapeHtml(v)}</span>` },
      { key: 'count_per_unit', label: 'Nos', kind: 'input', dp: 0, width: '54px' },
      { key: 'carpet_area_sqm', label: 'Area', unit: 'sq.m', kind: 'input', dp: 2, width: '84px' },
      { key: 'perimeter_m', label: 'Perimeter', unit: 'm', kind: 'input', dp: 2, width: '90px' },
      { key: 'clear_height_m', label: 'Clear ht', unit: 'm', kind: 'input', dp: 2, width: '82px',
        nullable: true, title: 'Blank uses the project default.' },
      { key: 'area_sqft', label: 'Area', unit: 'sq.ft', kind: 'derived', dp: 4, width: '100px',
        title: 'Derived. There is no field, no column and no endpoint to overwrite this.' },
      { key: 'total_sqft', label: 'Total', unit: 'sq.ft', kind: 'derived', dp: 4, width: '104px' },
      { key: 'openings', label: 'Openings', kind: 'derived', width: '150px', align: 'left',
        render: list => list.length
          ? list.map(o => `<span class="tag">${escapeHtml(o.code)}${o.count > 1 ? `×${o.count}` : ''}</span>`).join(' ')
          : '<span class="muted">none</span>' },
    ],
    rows: data.rooms,
    reload: refresh,
    onCommit: (row, col, value) => api.put(`/rooms/${row.id}`, { [col.key]: value }),
    onDerivedClick: (row, col) => {
      if (col.key === 'area_sqft') {
        showDerivation(`${row.label} — area`, row.area_sqft, row.derivation, { unit: 'sq.ft' });
      }
    },
  });

  // -- quantities, one block per room ------------------------------------
  const NAMES = {
    floor_area: 'Flooring', skirting: 'Skirting', wall_finish: 'Wall plaster / paint',
    dado: 'Dado', ceiling_area: 'Ceiling', door_frame: 'Door frames',
    window_frame: 'Window frames',
  };
  const DEDUCTS = {
    door_width: 'door widths', door_and_window_area: 'door + window areas',
    openings_within_dado: 'openings below the dado line', none: '—',
  };

  document.getElementById('qty').innerHTML = `
    <div class="grid-wrap"><table class="grid">
      <thead><tr>
        <th class="left" style="min-width:180px">Room</th>
        <th class="left" style="min-width:150px">Finish</th>
        <th style="min-width:52px">Unit</th>
        <th style="min-width:92px">Gross</th>
        <th style="min-width:92px">Deducts</th>
        <th class="left" style="min-width:170px">What is deducted</th>
        <th class="total" style="min-width:96px">Net</th>
      </tr></thead>
      <tbody>${data.rooms.flatMap(room =>
        room.quantities.filter(q => q.gross || q.error).map((q, i) => `
          <tr>
            <td class="label left">${i === 0 ? escapeHtml(room.label) : ''}</td>
            <td class="label left">${escapeHtml(NAMES[q.rule] || q.rule)}</td>
            <td class="derived">${escapeHtml(q.unit || '')}</td>
            ${q.error
              ? `<td class="derived missing" colspan="3">${escapeHtml(q.error)}</td>`
              : `<td class="derived">${fmt.n(q.gross, 3)}</td>
                 <td class="derived">${q.deduction ? '−' + fmt.n(q.deduction, 3) : '—'}</td>
                 <td class="derived left"><span class="muted">${escapeHtml(DEDUCTS[q.deduction_rule] || '—')}</span></td>`}
            <td class="derived total">${q.net === null ? '—' : fmt.n(q.net, 3)}</td>
          </tr>`)).join('')}
      </tbody>
    </table></div>`;
}
