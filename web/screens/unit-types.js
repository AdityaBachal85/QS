// Unit types, their rooms, and the quantities each room produces.
//
// This is where "a flat with four bathrooms and a flat with one" is just a
// different number of rows: add a room and it is a row, delete one and it is
// gone. The room type is a dropdown, not free text, so the same room cannot be
// spelled two ways -- which is exactly what happened in the workbook, where
// `C.Bedroom` and `C. Bedroom` are one room typed twice.

import { api, fmt, openPanel, refresh, route } from '../app.js';
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
        showDerivation(`${row.code} — total carpet area`, row.total_sqft,
          row.derivation, {
            unit: 'sq.ft',
            extra: `<div class="deriv-note">Every room in this type added, then
              multiplied by the ${row.count} of them the building holds —
              counted from the floor matrix in Room Config, never typed. Click
              the type to see the rooms it is made of.</div>`,
          });
        return true;
      }
      if (col.key === 'area_sqm' || col.key === 'area_sqft') {
        showDerivation(`${row.code} — carpet area of one unit`, row[col.key],
          row.derivation, {
            unit: col.key === 'area_sqm' ? 'sq.m' : 'sq.ft',
            extra: `<div class="deriv-note">The rooms in this type, added. In
              square feet it is converted with the project's own factor of
              10.764 — a named parameter, not a number typed into a
              formula.</div>`,
          });
        return true;
      }
      if (col.key === 'rooms' || col.key === 'count') {
        openPanel(`${row.code} — ${col.key === 'rooms' ? 'rooms' : 'units'}`, `
          <div class="deriv-value">${row[col.key]}</div>
          <div class="deriv-note">${col.key === 'rooms'
            ? `Rows in this type's room list. A flat with four bathrooms and a
               flat with one are just different numbers of rows — nothing here
               assumes a shape.`
            : `Counted from the floor matrix in Room Config: every floor that
               carries this type, added. Change a cell there and this moves,
               along with every quantity measured for it.`}</div>`);
        return true;
      }
      return false;
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
      ${heightNote(data)}
    </div>
    <div class="card">
      <h2>Rooms <span class="sub">enter area in sq.m and perimeter; the rest is computed</span></h2>
      <div id="grid"></div>
    </div>
    <div class="card" id="kitchenCard" hidden>
      <h2>Kitchen platforms
        <span class="sub">the counters a kitchen's tiling is measured along</span></h2>
      <div class="card-body" style="padding-top:6px">
        <p class="muted" style="margin-top:0">A kitchen's dado does not run round
        the room — it runs along the counters. Enter the four figures and the two
        dado areas appear beside them:
        <strong>above = (main × above) + (service × above)</strong>,
        <strong>below = (main × below) + (service × below)</strong>. One term per
        counter, added — not (main + service) × height, so a service counter can
        take its own height. They carry straight into
        <em>Finishes, quantities and cost</em> below.</p>
      </div>
      <div id="kitchen"></div>
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
      { key: 'category', label: 'Category', kind: 'note', width: '92px', align: 'left',
        render: v => `<span class="tag">${escapeHtml(v)}</span>` },
      { key: 'count_per_unit', label: 'Nos', kind: 'input', dp: 0, width: '54px' },
      { key: 'carpet_area_sqm', label: 'Area', unit: 'sq.m', kind: 'input', dp: 2, width: '84px' },
      { key: 'perimeter_m', label: 'Perimeter', unit: 'm', kind: 'input', dp: 2, width: '90px' },
      { key: 'clear_height_m', label: 'Clear ht', unit: 'm', kind: 'input', dp: 2,
        width: '96px', nullable: true,
        title: 'Blank inherits this floor\u2019s height from Room Config. Type here '
             + 'only for a room that is genuinely a different height \u2014 a '
             + 'double-height gym.',
        render: (v, row) => (v !== null && v !== undefined
          ? fmt.n(v, 2)
          : `<span class="muted" title="inherited from the floor">${
              fmt.n(data.floor_height_m, 2)}</span>`) },
      { key: 'area_sqft', label: 'Area', unit: 'sq.ft', kind: 'derived', dp: 4, width: '100px',
        title: 'Derived. There is no field, no column and no endpoint to overwrite this.' },
      { key: 'total_sqft', label: 'Total', unit: 'sq.ft', kind: 'derived', dp: 4, width: '104px' },
      // The quantities a QS is actually looking for, beside the inputs they
      // come from. Clicking one opens the working -- which is where the height
      // formula was hiding.
      { key: '_wall', label: 'Wall', unit: 'sq.m', kind: 'derived', width: '92px',
        title: 'perimeter x (floor height - slab), less the room\u2019s own door '
             + 'and window openings. Click for the working.',
        get: row => qty(row, 'wall_finish'),
        render: v => (v === null ? '<span class="muted">\u2014</span>' : fmt.n(v, 2)) },
      { key: '_dado', label: 'Dado', unit: 'sq.m', kind: 'derived', width: '88px',
        title: 'perimeter x dado height, less the part of each opening below it.',
        get: row => qty(row, 'dado'),
        render: v => (v === null ? '<span class="muted">\u2014</span>' : fmt.n(v, 2)) },
      { key: '_skirting', label: 'Skirting', unit: 'RM', kind: 'derived', width: '90px',
        title: 'perimeter, less the WIDTH of each door \u2014 not its area (C-35).',
        get: row => qty(row, 'skirting'),
        render: v => (v === null ? '<span class="muted">\u2014</span>' : fmt.n(v, 2)) },
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
        showDerivation(`${row.label} — area`, row.area_sqft, row.derivation,
          { unit: 'sq.ft' });
        return true;
      }
      if (col.key === 'total_sqft') {
        showDerivation(`${row.label} — all ${row.count_per_unit} of them`,
          row.total_sqft, row.derivation, {
            unit: 'sq.ft',
            extra: `<div class="deriv-expr">${fmt.n(row.area_sqft, 4)} sq.ft ×
              ${row.count_per_unit} in this unit = ${fmt.n(row.total_sqft, 4)}</div>
              <div class="deriv-note">Per unit of ${escapeHtml(u.code)}. The
              building has ${u.count} of them, and the take-off multiplies
              again there rather than here.</div>`,
          });
        return true;
      }
      const rule = { _wall: 'wall_finish', _dado: 'dado', _skirting: 'skirting' }[col.key];
      if (rule) { showQuantity(row, rule, data); return true; }
      return false;
    },
  });

  // -- the counters, between the rooms and their openings -----------------
  //
  // Only shown where something in this unit type is priced off a counter, so a
  // unit type with no kitchen does not grow an empty card. The two dado areas
  // beside the entries are computed by the engine and come down with the
  // payload -- the browser multiplies nothing (non-negotiable 8).
  await renderKitchen(id, u);

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
    onDerivedClick: (row, col) => {
      if (col.key !== 'width_m' && col.key !== 'height_m') return false;
      openPanel(`${row.code} in ${row.room_label} — ${
        col.key === 'width_m' ? 'width' : 'height'}`, `
        <div class="deriv-value">${fmt.n(row[col.key], 2)}
          <span class="muted" style="font-size:13px">m</span></div>
        <div class="deriv-expr">${fmt.n(row.width_m, 2)} × ${fmt.n(row.height_m, 2)}
          = ${fmt.n(row.width_m * row.height_m, 4)} sq.m per leaf</div>
        <div class="deriv-note">From the opening type
          <strong>${escapeHtml(row.code)}</strong>, not typed here — change it on
          <a href="#/openings">Doors &amp; Windows</a> and every room carrying
          this type moves together. That is what stops the same door being
          1.20 m wide in one room and 1.2 in another.</div>
        <div class="deriv-note">Wall finishes deduct the full area × ${row.count};
          skirting deducts the <strong>width</strong> alone, because a running
          metre takes a running-metre deduction (C-35).</div>`);
      return true;
    },
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
      <tbody>${data.rooms.flatMap((room, ri) => {
        const rows = (room.costs || []).length
          ? room.costs.map(c => ({ ...c, _label: c.finish }))
          : room.quantities.filter(q => q.gross || q.error)
              .map(q => ({ _label: q.rule, unit: q.unit, gross: q.gross,
                           deduction: q.deduction, net: q.net, rate: null,
                           amount_per_unit: 0, total_amount: 0,
                           status: 'no_rate', deduction_rule: q.deduction_rule,
                           message: q.error || 'this room type has no finish schedule' }));
        return rows.map((r, i) => {
          const dedRule = r.deduction_rule
            || (room.quantities.find(q => q.rule === r.rule) || {}).deduction_rule;
          // Every figure below is calculated, so every one of them opens its
          // working: what rule, what expression, which inputs and where each
          // came from, what the deduction is folded from opening by opening,
          // and the workbook cell it replaces.
          const at = (what) => `data-cost="${ri}:${i}:${what}"`;
          const cell = (what, inner, cls) =>
            `<td class="derived clickable ${cls || ''}" ${at(what)}
                title="Click for the working">${inner}</td>`;
          return `
          <tr>
            <td class="label left">${i === 0 ? escapeHtml(room.label) : ''}</td>
            <td class="label left">${escapeHtml(r._label)}</td>
            ${cell('gross', r.gross === null ? '—' : fmt.n(r.gross, 2))}
            ${cell('deduction', r.deduction ? '−' + fmt.n(r.deduction, 2) : '—')}
            <td class="derived left"><span class="muted">${escapeHtml(DEDUCTS[dedRule] || '—')}</span></td>
            ${cell('net', r.net === null ? '—' : fmt.n(r.net, 2))}
            <td class="derived left">${escapeHtml(r.unit || '')}</td>
            ${cell('rate', r.rate === null
              ? '<span class="tag bad">no rate</span>' : '₹' + fmt.n(r.rate, 2),
              r.rate === null ? 'missing' : '')}
            ${cell('amount_per_unit',
              r.status === 'priced' ? fmt.money(r.amount_per_unit) : '—', 'total')}
            ${cell('total_amount',
              r.status === 'priced' ? fmt.money(r.total_amount) : '—', 'total')}
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

  // Every calculated cell on this table opens its working. The table is built
  // as HTML rather than through createGrid -- nothing here is editable -- so
  // the clicks are delegated from the card.
  const costRows = data.rooms.map(room => {
    const rows = (room.costs || []).length
      ? room.costs.map(c => ({ ...c, _label: c.finish }))
      : room.quantities.filter(q => q.gross || q.error)
          .map(q => ({ _label: q.rule, rule: q.rule, unit: q.unit, gross: q.gross,
                       deduction: q.deduction, net: q.net, rate: null,
                       gross_derivation: q.gross_derivation,
                       deduction_derivation: q.deduction_derivation,
                       status: 'no_rate', deduction_rule: q.deduction_rule,
                       message: q.error || 'this room type has no finish schedule' }));
    return { room, rows };
  });

  document.getElementById('qty').addEventListener('click', (e) => {
    const td = e.target.closest('[data-cost]');
    if (!td) return;
    const [ri, i, what] = td.dataset.cost.split(':');
    const entry = costRows[Number(ri)];
    if (!entry) return;
    showCostWorking(entry.room, entry.rows[Number(i)], what, u, data);
  });
}


// The working behind one figure on "Finishes, quantities and cost".
//
// Which working depends on which cell: the gross has its own derivation, the
// deduction is a fold over this room's openings, the rate is a build-up from
// the library, and the two money columns are a multiplication of things that
// each have their own working -- so those show the multiplication and name
// both sides.
function showCostWorking(room, r, what, u, data) {
  if (!r) return;
  const where = `${room.label} — ${r._label}`;
  const note = r.message
    ? `<div class="deriv-note">${escapeHtml(r.message)}</div>` : '';
  const usage = `
    <h4 class="deriv-h">Where this goes</h4>
    <div class="deriv-note">Into the finishing take-off for ${escapeHtml(u.code)},
      ${r.unit_count ?? u.count} unit${(r.unit_count ?? u.count) === 1 ? '' : 's'}
      of it, and from there into the project total. Change the room's area,
      perimeter or openings above and this figure moves by itself — nothing here
      is stored.</div>`;

  if (what === 'gross') {
    showDerivation(`${where} — gross`, r.gross, r.gross_derivation,
      { unit: r.unit, extra: note + usage });
    return;
  }

  if (what === 'deduction') {
    const d = r.deduction_derivation;
    if (!d || !r.deduction) {
      openPanel(`${where} — deduction`, `<div class="deriv-note">Nothing is
        deducted from this quantity. ${escapeHtml(r._label)} is measured as
        built.</div>`);
      return;
    }
    showDerivation(`${where} — deduction`, r.deduction, d, {
      unit: r.unit,
      extra: `<div class="deriv-note">A fold over the openings actually in this
        room, not a hand-picked list of cells (C-13). Each one is named above
        with the count it contributes.</div>` + usage,
    });
    return;
  }

  if (what === 'net') {
    showDerivation(`${where} — net`, r.net, r.gross_derivation, {
      unit: r.unit,
      extra: `
        <h4 class="deriv-h">Less this room's own openings</h4>
        <div class="deriv-expr">${fmt.n(r.gross, 3)} − ${fmt.n(r.deduction || 0, 3)}
          = ${fmt.n(r.net, 3)} ${escapeHtml(r.unit || '')}</div>` + note + usage,
    });
    return;
  }

  if (what === 'rate') {
    if (r.rate === null || r.rate === undefined) {
      openPanel(`${where} — rate`, `<div class="deriv-note">${escapeHtml(
        r.message || 'This finish is measured but carries no price, so it '
        + 'reaches no total. It is listed at zero rather than left out, '
        + 'because measured work presented as absent is how Rs 65.5 lakh of '
        + 'false ceiling disappeared from the workbook (C-11).')}</div>`);
      return;
    }
    showDerivation(`${where} — rate`, r.rate, r.rate_derivation, {
      format: v => '₹' + fmt.n(v, 2),
      extra: `<div class="deriv-note">${escapeHtml(r.rate_description || '')} —
        from the <a href="#/rates">Rate Library</a>, linked to this room type by
        <a href="#/mapping">room type pricing</a>. Change the build-up there and
        every room priced on it moves.</div>`,
    });
    return;
  }

  // The two money columns: a multiplication, with both sides named.
  //
  // The count is the LINE's, not the unit type's. A type sitting on floors of
  // more than one height splits into a line per height, each covering only the
  // units at that height — showing the type's total here would print a
  // multiplication that is not the one that produced the figure.
  const perUnit = what === 'amount_per_unit';
  const value = perUnit ? r.amount_per_unit : r.total_amount;
  const count = r.unit_count ?? u.count;
  const split = count !== u.count;
  openPanel(`${where} — ${perUnit ? 'per unit' : `${count} unit${
      count === 1 ? '' : 's'}`}`, `
    <div class="deriv-value">${fmt.money(value)}</div>
    <div class="muted">${perUnit ? 'quantity x rate'
      : 'quantity x rate x units this line covers'}</div>
    <div class="deriv-expr">${fmt.n(r.net, 3)} ${escapeHtml(r.unit || '')} ×
      ₹${fmt.n(r.rate || 0, 2)}${perUnit ? '' : ` × ${count}`} = ${
      fmt.money(value)}</div>
    ${split ? `<div class="deriv-note">${escapeHtml(u.code)} has ${u.count}
      units in the building, and this line covers ${count} of them${
      r.floor_scope ? ` — ${escapeHtml(r.floor_scope)}` : ''}${
      r.floor_height_m ? `, measured at ${fmt.n(r.floor_height_m, 2)} m
      floor-to-floor` : ''}. The rest sit on floors of a different height and
      are measured separately rather than averaged into one wall.</div>` : ''}
    <h4 class="deriv-h">Built from</h4>
    <div class="deriv-inputs">
      <div class="deriv-input">
        <div><div class="n">net quantity</div>
          <div class="deriv-src">${escapeHtml(r.gross_derivation
            ? r.gross_derivation.expression : 'measured on this room')}, less
            this room's openings</div></div>
        <div class="v">${fmt.n(r.net, 3)}</div>
      </div>
      <div class="deriv-input">
        <div><div class="n">rate</div>
          <div class="deriv-src">${escapeHtml(r.rate_description || 'rate library')}</div></div>
        <div class="v">${fmt.n(r.rate || 0, 2)}</div>
      </div>
      ${perUnit ? '' : `
      <div class="deriv-input">
        <div><div class="n">units of ${escapeHtml(u.code)} this line covers</div>
          <div class="deriv-src">from the floor matrix in Room Config, counted —
            never typed${r.floor_scope ? `; ${escapeHtml(r.floor_scope)}` : ''}</div></div>
        <div class="v">${count}</div>
      </div>`}
    </div>
    <div class="deriv-note">The multiplication goes through the unit system: a
      rate per Nos. meeting a square-metre quantity raises rather than producing
      a plausible number (C-35).</div>` + usage);
}


async function renderKitchen(unitTypeId, u) {
  const data = await api.get(
    `/unit-types/${encodeURIComponent(unitTypeId)}/kitchen-platforms`);
  if (!data.rooms.length) return;
  document.getElementById('kitchenCard').hidden = false;

  const entered = (v) => (v === null || v === undefined
    ? '<span class="muted" title="not entered">—</span>' : fmt.n(v, 2));

  createGrid(document.getElementById('kitchen'), {
    columns: [
      { key: 'room_label', label: 'Room', kind: 'label', width: '170px' },
      { key: 'main_platform_m', label: 'Main platform', unit: 'm', kind: 'input',
        dp: 2, width: '120px', nullable: true, render: entered,
        title: 'The main counter run, measured. Entered, not derived.' },
      { key: 'service_platform_m', label: 'Service platform', unit: 'm',
        kind: 'input', dp: 2, width: '132px', nullable: true, render: entered,
        title: 'The workbook derives this as main − 0.9. That is a habit frozen '
             + 'into a formula, and an L-shaped service run does not obey it, '
             + 'so here it is entered.' },
      { key: 'dado_above_m', label: 'Above ht', unit: 'm', kind: 'input',
        dp: 2, width: '104px', nullable: true, render: entered,
        title: 'Tiling height above the counter.' },
      { key: 'dado_below_m', label: 'Below ht', unit: 'm', kind: 'input',
        dp: 2, width: '104px', nullable: true, render: entered,
        title: 'Tiling height below it — the counter\u2019s own height.' },
      { key: 'dado_above', label: 'Dado above', unit: 'sq.m', kind: 'derived',
        dp: 2, width: '116px',
        title: '(main × above) + (service × above). Click for the working.',
        render: v => (v === null || v === undefined
          ? '<span class="muted">—</span>' : fmt.n(v, 2)) },
      { key: 'dado_below', label: 'Dado below', unit: 'sq.m', kind: 'derived',
        dp: 2, width: '116px',
        title: '(main × below) + (service × below). Click for the working.',
        render: v => (v === null || v === undefined
          ? '<span class="muted">—</span>' : fmt.n(v, 2)) },
    ],
    rows: data.rooms,
    rowKey: r => r.unit_type_room_id,
    reload: refresh,
    emptyMessage: 'Nothing in this unit type is priced off a counter.',
    rowName: row => `the counters in ${row.room_label}`,
    // A room has the counters it has; there is no second set to add, and
    // deleting one would make the kitchen unmeasured rather than free.
    onCommit: async (row, col, value) => {
      if (row.id) {
        return api.send('PATCH', `/collections/kitchen-platforms/${row.id}`,
                        { [col.key]: value });
      }
      // First figure typed against a room that has none yet.
      return api.post('/collections/kitchen-platforms', {
        unit_type_room_id: row.unit_type_room_id, [col.key]: value });
    },
    onDerivedClick: (row, col) => {
      const which = col.key === 'dado_above' ? 'above' : 'below';
      const derivation = row[`${col.key}_derivation`];
      if (!derivation) {
        openPanel(`${row.room_label} — dado ${which} the counter`,
          `<div class="deriv-note">${escapeHtml(row.message
            || 'No counters entered for this room yet.')}</div>`);
        return true;
      }
      showDerivation(`${row.room_label} — dado ${which} the counter`,
        row[col.key], derivation, {
          unit: 'sq.m',
          extra: `<div class="deriv-note">Each counter is measured and the
            results added. Written <strong>(main × height) + (service × height)</strong>
            rather than (main + service) × height: the two agree today, and only
            the first survives a service counter taking a different height.
            This quantity is what <em>Dado${which === 'below'
              ? ' Below Kitchen Platform' : ''}</em> costs in the table below,
            and the plaster on this wall is what is left once both dado areas
            are taken off — you do not plaster behind the tiles.</div>`,
        });
      return true;
    },
  });
}


// Where the wall height comes from.
//
// Wall and dado are perimeter x (floor-to-floor height - slab), and the height
// belongs to the floor, not to the project. A type that sits on floors of more
// than one height genuinely has more than one wall quantity -- the take-off
// splits it, and this line says so rather than letting one figure stand in for
// several.
function heightNote(data) {
  const heights = data.heights || [];
  if (!heights.length) return '';

  const shown = fmt.n(data.floor_height_m, 2);
  if (heights.length === 1) {
    return `<p class="muted">Walls measured at ${shown} m floor-to-floor,
      from Room Config, less the slab allowance.</p>`;
  }
  const total = heights.reduce((a, h) => a + h.count, 0);
  const here = heights.find(h => h.height_m === data.floor_height_m);
  const others = heights
    .filter(h => h.height_m !== data.floor_height_m)
    .map(h => `${fmt.n(h.height_m, 2)} m × ${h.count}`)
    .join(', ');
  return `<p class="muted">Rooms shown at ${shown} m floor-to-floor, which is
    ${here ? here.count : 0} of this type's ${total} placements. It also sits on
    floors of ${others} — the take-off measures those walls separately rather
    than averaging them.</p>`;
}


/** One room quantity, from what the API already computed for this screen. */
function qty(room, rule) {
  const q = (room.quantities || []).find(x => x.rule === rule);
  return q && q.net !== null && q.net !== undefined ? q.net : null;
}

/** The working behind a room quantity, including the deduction it carries. */
function showQuantity(room, rule, data) {
  const q = (room.quantities || []).find(x => x.rule === rule);
  if (!q) return;
  if (q.error) {
    openPanel(`${room.label} — ${rule}`,
      `<div class="deriv-note">${escapeHtml(q.error)}</div>`);
    return;
  }

  const ded = q.deduction_derivation;
  const openings = (ded && ded.inputs || []).map(i => `
    <div class="deriv-input">
      <div><div class="n">${escapeHtml(i.name)}</div>
        ${i.source ? `<div class="deriv-src">${escapeHtml(i.source)}</div>` : ''}</div>
      <div class="v">−${fmt.n(i.value, 3)}</div>
    </div>`).join('');

  showDerivation(`${room.label} — ${escapeHtml(q.gross_derivation.rule)}`,
    q.gross, q.gross_derivation, {
      unit: q.unit,
      extra: `
        ${openings ? `<h4 class="deriv-h">Less this room's own openings</h4>
          <div class="muted" style="font-size:12px;margin-bottom:6px">
            ${escapeHtml(q.deduction_rule)} — a fold over the openings actually in
            this room, not a hand-picked list of cells (C-13).</div>
          <div class="deriv-inputs">${openings}</div>` : ''}
        <h4 class="deriv-h">Net</h4>
        <div class="deriv-expr">${fmt.n(q.gross, 3)} − ${fmt.n(q.deduction, 3)}
          = ${fmt.n(q.net, 3)} ${escapeHtml(q.unit)}</div>
        ${data.heights && data.heights.length > 1 ? `
          <div class="deriv-note">This unit type sits on floors of more than one
          height, so the take-off measures each separately. Shown here at
          ${fmt.n(data.floor_height_m, 2)} m.</div>` : ''}`,
    });
}
