// Unit types, their rooms, and the quantities each room produces.
//
// This is where "a flat with four bathrooms and a flat with one" is just a
// different number of rows: add a room and it is a row, delete one and it is
// gone. The room type is a dropdown, not free text, so the same room cannot be
// spelled two ways -- which is exactly what happened in the workbook, where
// `C.Bedroom` and `C. Bedroom` are one room typed twice.

import { api, fmt, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml, showDerivation } from '../panel.js';

route('/unit-types', async (main, hash) => {
  const selected = new URLSearchParams(hash.split('?')[1] || '').get('id');
  const [types, ref] = await Promise.all([
    api.get('/unit-types'), api.get('/reference'),
  ]);
  if (!selected) return renderList(main, types, ref);
  return renderRooms(main, ref, selected);
});

function renderList(main, types, ref) {
  main.innerHTML = `
    <div class="screen-head">
      <h1>Unit Types &amp; Rooms</h1>
      <p>A unit type owns as many rooms as it has — five or ten, four bathrooms or one, balcony
         or none. Nothing counts them and nothing assumes a maximum. Areas in square feet are
         computed from the square metres you enter; there is no square-foot cell to overwrite.</p>
    </div>
    <div class="card">
      <h2>All unit types <span class="sub">${types.length} types · click one to edit its rooms</span></h2>
      <div id="grid"></div>
    </div>`;

  createGrid(document.getElementById('grid'), {
    columns: [
      { key: 'code', label: 'Type', kind: 'input', text: true, width: '180px',
        align: 'left', title: 'Type over it to rename.' },
      { key: 'classification', label: 'Class', kind: 'input', text: true,
        width: '100px', align: 'left' },
      { key: 'rooms', label: 'Rooms', kind: 'derived', dp: 0, width: '64px',
        render: (v, r) => `<a href="#/unit-types?id=${encodeURIComponent(r.id)}">${v} rooms</a>` },
      { key: 'count', label: 'Units', kind: 'derived', dp: 0, width: '64px',
        title: 'Summed from the floor matrix, not typed.' },
      { key: 'area_sqm', label: 'Carpet', unit: 'sq.m', kind: 'derived', dp: 2, width: '86px' },
      { key: 'area_sqft', label: 'Carpet', unit: 'sq.ft', kind: 'derived', dp: 2, width: '96px' },
      { key: 'total_sqft', label: 'All units', unit: 'sq.ft', kind: 'derived', dp: 2,
        width: '112px', total: true },
      { key: '_del', label: '', kind: 'delete', width: '34px' },
    ],
    rows: types,
    reload: refresh,
    addLabel: 'Add unit type',
    rowName: row => `“${row.code}” and its ${row.rooms} rooms`,
    onAdd: () => api.post('/collections/unit-types',
      { code: `Type ${types.length + 1}`, classification: 'Unassigned' }),
    onDelete: row => api.send('DELETE', `/collections/unit-types/${row.id}`),
    onCommit: (row, col, value) =>
      api.send('PATCH', `/collections/unit-types/${row.id}`, { [col.key]: value }),
    onDerivedClick: (row, col) => {
      if (col.key === 'total_sqft') {
        showDerivation(`${row.code} — total carpet area`, row.total_sqft, row.derivation,
          { unit: 'sq.ft' });
      }
    },
  });
}

async function renderRooms(main, ref, id) {
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
      <h2>Openings per room <span class="sub">what each room's deductions are folded from</span></h2>
      <div id="openings"></div>
    </div>
    <div class="card">
      <h2>Finishes, quantities and cost
        <span class="sub">${fmt.money(data.amount || 0)} for all ${u.count} units</span></h2>
      <div class="card-body" style="padding-top:6px">
        <p class="muted" style="margin-top:0">Skirting deducts each door's <strong>width</strong>,
        not its area — a running-metre quantity takes a running-metre deduction. Wall finishes
        deduct the full opening area. Add a door above and every figure here moves by itself.
        Rates come from the <a href="#/rates">Rate Library</a> via
        <a href="#/mapping">room type pricing</a>.</p>
      </div>
      <div id="qty"></div>
    </div>`;

  createGrid(document.getElementById('grid'), {
    columns: [
      { key: 'label', label: 'Room', kind: 'input', text: true, width: '180px',
        align: 'left' },
      { key: 'room_type_id', label: 'Room type', kind: 'select', width: '170px',
        options: ref.room_types,
        title: 'Chosen from the room-type master — never typed, so the same room '
             + 'cannot be spelled two ways.' },
      { key: 'category', label: 'Category', kind: 'derived', width: '92px', align: 'left',
        render: v => `<span class="tag">${escapeHtml(v)}</span>` },
      { key: 'count_per_unit', label: 'Nos', kind: 'input', dp: 0, width: '54px' },
      { key: 'carpet_area_sqm', label: 'Area', unit: 'sq.m', kind: 'input', dp: 2, width: '84px' },
      { key: 'perimeter_m', label: 'Perimeter', unit: 'm', kind: 'input', dp: 2, width: '90px' },
      { key: 'clear_height_m', label: 'Clear ht', unit: 'm', kind: 'input', dp: 2,
        width: '82px', nullable: true, title: 'Blank uses the project default.' },
      { key: 'area_sqft', label: 'Area', unit: 'sq.ft', kind: 'derived', dp: 4, width: '100px',
        title: 'Derived. There is no field, no column and no endpoint to overwrite this.' },
      { key: 'total_sqft', label: 'Total', unit: 'sq.ft', kind: 'derived', dp: 4, width: '104px' },
      { key: '_del', label: '', kind: 'delete', width: '34px' },
    ],
    rows: data.rooms,
    reload: refresh,
    addLabel: 'Add room',
    rowName: row => `room “${row.label}”`,
    onAdd: () => api.post('/collections/rooms', { unit_type_id: id }),
    onDelete: row => api.send('DELETE', `/collections/rooms/${row.id}`),
    onCommit: (row, col, value) =>
      api.send('PATCH', `/collections/rooms/${row.id}`, { [col.key]: value }),
    onDerivedClick: (row, col) => {
      if (col.key === 'area_sqft') {
        showDerivation(`${row.label} — area`, row.area_sqft, row.derivation, { unit: 'sq.ft' });
      }
    },
  });

  // -- openings, flattened one row per (room, opening) --------------------
  const openingRows = data.rooms.flatMap(room =>
    room.openings.map(o => ({ ...o, room_label: room.label, room_id: room.id })));

  createGrid(document.getElementById('openings'), {
    columns: [
      { key: 'room_label', label: 'Room', kind: 'label', width: '180px' },
      { key: 'opening_type_id', label: 'Opening', kind: 'select', width: '190px',
        options: ref.opening_types },
      { key: 'count', label: 'Nos', kind: 'input', dp: 0, width: '60px' },
      { key: 'width_m', label: 'Width', unit: 'm', kind: 'derived', dp: 2, width: '76px' },
      { key: 'height_m', label: 'Height', unit: 'm', kind: 'derived', dp: 2, width: '76px' },
      { key: '_del', label: '', kind: 'delete', width: '34px' },
    ],
    rows: openingRows,
    reload: refresh,
    emptyMessage: 'No openings in this unit type yet.',
    addLabel: 'Add opening',
    rowName: row => `${row.code} in ${row.room_label}`,
    onAdd: async () => {
      if (!data.rooms.length) throw new Error('add a room first');
      await api.post('/collections/room-openings', {
        unit_type_room_id: data.rooms[0].id,
        opening_type_id: ref.opening_types[0].value, count: 1,
      });
    },
    onDelete: row => api.send('DELETE', `/collections/room-openings/${row.id}`),
    onCommit: (row, col, value) =>
      api.send('PATCH', `/collections/room-openings/${row.id}`, { [col.key]: value }),
  });

  // -- quantities and what they cost --------------------------------------
  //
  // This is the answer to "it should also give the rate". Each finish shows the
  // gross, what this room's own openings deduct, the net, the rate it resolves
  // to from the library, and the amount -- for one unit and for all of them.
  const DEDUCTS = {
    door_width: 'door widths', door_and_window_area: 'door + window areas',
    openings_within_dado: 'openings below the dado line', none: '—',
  };
  const byRoomRule = {};
  for (const room of data.rooms) {
    for (const c of (room.costs || [])) byRoomRule[`${room.id}|${c.rule}`] = c;
  }

  document.getElementById('qty').innerHTML = `
    <div class="grid-wrap"><table class="grid">
      <thead><tr>
        <th class="left" style="min-width:170px">Room</th>
        <th class="left" style="min-width:150px">Finish</th>
        <th style="min-width:80px">Gross</th>
        <th style="min-width:80px">Deducts</th>
        <th class="left" style="min-width:150px">What is deducted</th>
        <th style="min-width:88px">Net</th>
        <th style="min-width:48px">Unit</th>
        <th style="min-width:96px">Rate</th>
        <th class="total" style="min-width:112px">Per unit</th>
        <th class="total" style="min-width:124px">All ${u.count} units</th>
      </tr></thead>
      <tbody>${data.rooms.flatMap(room => {
        const rows = (room.costs || []).length
          ? room.costs.map(c => ({ ...c, _label: c.finish }))
          : room.quantities.filter(q => q.gross || q.error)
              .map(q => ({ _label: q.rule, unit: q.unit, gross: q.gross,
                           deduction: q.deduction, net: q.net, rate: null,
                           amount_per_unit: 0, total_amount: 0,
                           status: 'no_rate', deduction_rule: q.deduction_rule,
                           message: q.error || 'this room type has no finish schedule' }));
        return rows.map((r, i) => {
          const ded = byRoomRule[`${room.id}|${r.rule}`];
          const dedRule = r.deduction_rule
            || (room.quantities.find(q => q.rule === r.rule) || {}).deduction_rule;
          return `
          <tr>
            <td class="label left">${i === 0 ? escapeHtml(room.label) : ''}</td>
            <td class="label left">${escapeHtml(r._label)}</td>
            <td class="derived">${r.gross === null ? '—' : fmt.n(r.gross, 2)}</td>
            <td class="derived">${r.deduction ? '−' + fmt.n(r.deduction, 2) : '—'}</td>
            <td class="derived left"><span class="muted">${escapeHtml(DEDUCTS[dedRule] || '—')}</span></td>
            <td class="derived">${r.net === null ? '—' : fmt.n(r.net, 2)}</td>
            <td class="derived left">${escapeHtml(r.unit || '')}</td>
            <td class="derived ${r.rate === null ? 'missing' : ''}">${
              r.rate === null ? '<span class="tag bad">no rate</span>' : '₹' + fmt.n(r.rate, 2)}</td>
            <td class="derived total">${r.status === 'priced' ? fmt.money(r.amount_per_unit) : '—'}</td>
            <td class="derived total">${r.status === 'priced' ? fmt.money(r.total_amount) : '—'}</td>
          </tr>`;
        });
      }).join('')}
      </tbody>
      <tfoot><tr class="total-row">
        <td class="left"><strong>Total</strong></td>
        <td colspan="7"></td>
        <td>${fmt.money((data.amount || 0) / (u.count || 1))}</td>
        <td>${fmt.money(data.amount || 0)}</td>
      </tr></tfoot>
    </table></div>`;
}
