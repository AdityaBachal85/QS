// Internal finishes -- the take-off in the shape of the workbook's own sheet.
//
// Every other costing screen folds these lines up: by finish, by room type, by
// unit type. Those answer different questions, and none of them is "show me
// the take-off the way I read it". `Internal Finishes Flats` lays it out one
// block per room, under a heading per unit type carrying its count, and a QS
// reads down it -- so this is the same lines in the same order.
//
// Computed by the engine, never read out of the workbook. That is the point:
// it can be put beside the sheet and checked line for line.

import { api, fmt, openPanel, route } from '../app.js';
import { escapeHtml, showDerivation } from '../panel.js';

const DASH = '<span class="muted">—</span>';

route('/internal-finishes', async (main) => {
  main.innerHTML = '<div class="loading">Measuring every room…</div>';
  const d = await api.get('/internal-finishes');

  // Flat index, so a click can find its line without walking the tree.
  const index = [];
  for (const unit of d.unit_types) {
    for (const room of unit.rooms) {
      for (const line of room.lines) index.push({ unit, room, line });
    }
  }

  main.innerHTML = `
    <div class="screen-head">
      <h1>Internal finishes</h1>
      <p>The whole building, room by room, in the order the workbook's
         <span class="mono">Internal Finishes</span> sheet reads. Every figure is
         computed here rather than copied across, so this page can sit beside the
         sheet and be checked line for line. Click any of them for its working.</p>
    </div>

    <div class="tile-row">
      <div class="tile" data-tile="total"><div class="k">Internal finishes</div>
        <div class="v">${fmt.money(d.total)}</div>
        <div class="s">${fmt.int(d.line_count)} lines · ${d.unit_types.length} unit types</div></div>
      <div class="tile" data-tile="unpriced"><div class="k">Measured, unpriced</div>
        <div class="v" style="${d.unpriced ? 'color:var(--bad)' : ''}">${d.unpriced}</div>
        <div class="s">quantity real, amount missing</div></div>
      <div class="tile"><div class="k">Rooms measured</div>
        <div class="v">${fmt.int(d.unit_types.reduce((a, u) => a + u.rooms.length, 0))}</div>
        <div class="s">across every unit type</div></div>
    </div>

    <div class="card-body" style="padding-bottom:0">
      <input class="text-input" id="q" style="min-width:340px"
             placeholder="Filter — a unit type, a room, or a finish…">
      <span class="muted" id="count"></span>
    </div>

    <div id="sheet"></div>

    <div class="card" style="margin-top:16px">
      <h2>Summary
        <span class="sub">the foot of the sheet — one row per rate, folded from the
          same lines above</span></h2>
      <div id="summary"></div>
    </div>`;

  const host = document.getElementById('sheet');
  const search = document.getElementById('q');
  const count = document.getElementById('count');

  function draw() {
    const q = search.value.trim().toLowerCase();
    let shown = 0;

    const blocks = d.unit_types.map((unit, ui) => {
      const rooms = unit.rooms.filter(room => !q
        || `${unit.code} ${room.label} ${room.room_type}`.toLowerCase().includes(q)
        || room.lines.some(l => `${l.finish} ${l.rate_description}`.toLowerCase().includes(q)));
      if (!rooms.length) return '';
      shown += rooms.length;

      return `
      <div class="card" style="margin-top:16px">
        <h2>${escapeHtml(unit.code)}
          <span class="sub">${unit.units} unit${unit.units === 1 ? '' : 's'} ·
            ${escapeHtml(unit.classification || (unit.is_common_area ? 'common area' : ''))} ·
            ${fmt.money(unit.amount_per_unit)} each · ${fmt.money(unit.total_amount)} in all</span></h2>
        ${rooms.map(room => {
          const ri = unit.rooms.indexOf(room);
          return `
          <div class="card-body" style="padding-bottom:4px;border-top:1px solid var(--line)">
            <strong>${escapeHtml(room.label)}</strong>
            <span class="muted" style="margin-left:10px">
              ${fmt.n(room.carpet_area_sqm, 2)} sq.m carpet ·
              ${fmt.n(room.perimeter_m, 2)} m perimeter${room.count_per_unit !== 1
                ? ` · ${room.count_per_unit} of them` : ''}</span>
            <span style="float:right">
              <span class="muted">${room.rate_per_sqft
                ? `₹${fmt.n(room.rate_per_sqft, 2)} / sq.ft of carpet` : ''}</span>
              &nbsp;&nbsp;<strong>${fmt.money(room.amount_per_unit)}</strong></span>
          </div>
          <div class="grid-wrap"><table class="grid">
            <thead><tr>
              <th class="left" style="min-width:190px">Finish</th>
              <th style="min-width:88px">Gross</th>
              <th style="min-width:88px">Deducts</th>
              <th style="min-width:88px">Net</th>
              <th style="min-width:52px">Unit</th>
              <th class="left" style="min-width:210px">Priced as</th>
              <th style="min-width:96px">Rate</th>
              <th class="total" style="min-width:110px">Per unit</th>
              <th style="min-width:60px">× units</th>
              <th class="total" style="min-width:126px">Total</th>
            </tr></thead>
            <tbody>${room.lines.map(line => {
              const i = index.findIndex(e => e.line === line);
              const at = w => `data-line="${i}:${w}"`;
              const cell = (w, inner, cls) =>
                `<td class="derived clickable ${cls || ''}" ${at(w)}
                    title="Click for the working">${inner}</td>`;
              return `
              <tr>
                <td class="label left">${escapeHtml(line.finish)}</td>
                ${cell('gross', line.gross === null ? DASH : fmt.n(line.gross, 2))}
                ${cell('deduction', line.deduction ? '−' + fmt.n(line.deduction, 2) : DASH)}
                ${cell('net', line.net === null ? DASH : fmt.n(line.net, 2))}
                <td class="derived note left">${escapeHtml(line.unit || '')}</td>
                <td class="derived note left"><span class="muted">${
                  escapeHtml(line.rate_description || '—')}</span></td>
                ${cell('rate', line.rate === null || line.rate === undefined
                  ? '<span class="tag bad">no rate</span>' : '₹' + fmt.n(line.rate, 2),
                  line.rate === null ? 'missing' : '')}
                ${cell('amount_per_unit', line.status === 'priced'
                  ? fmt.money(line.amount_per_unit) : DASH, 'total')}
                <td class="derived note">${line.unit_count}</td>
                ${cell('total_amount', line.status === 'priced'
                  ? fmt.money(line.total_amount) : DASH, 'total')}
              </tr>`;
            }).join('')}</tbody>
          </table></div>`;
        }).join('')}
      </div>`;
    }).join('');

    count.textContent = q
      ? `  ${shown} room block${shown === 1 ? '' : 's'} shown`
      : `  ${shown} room blocks`;
    host.innerHTML = blocks || `<div class="card"><div class="card-body muted">
      Nothing matches that filter.</div></div>`;
  }

  search.addEventListener('input', draw);
  draw();

  // -- the foot of the sheet ----------------------------------------------

  document.getElementById('summary').innerHTML = `
    <div class="grid-wrap"><table class="grid">
      <thead><tr>
        <th class="left" style="min-width:300px">Description</th>
        <th style="min-width:130px">Quantity</th>
        <th style="min-width:56px">Unit</th>
        <th style="min-width:110px">Rate</th>
        <th style="min-width:76px">Lines</th>
        <th class="total" style="min-width:150px">Amount</th>
      </tr></thead>
      <tbody>${d.summary.map(e => `
        <tr>
          <td class="label left">${escapeHtml(e.description)}</td>
          <td class="derived note">${fmt.n(e.quantity, 2)}</td>
          <td class="derived note left">${escapeHtml(e.unit || '')}</td>
          <td class="derived note">${e.rate ? '₹' + fmt.n(e.rate, 2) : DASH}</td>
          <td class="derived note">${e.lines}</td>
          <td class="derived note total">${fmt.money(e.amount)}</td>
        </tr>`).join('')}</tbody>
      <tfoot><tr class="total-row">
        <td class="left"><strong>Total</strong></td>
        <td colspan="4"></td>
        <td><strong>${fmt.money(d.total)}</strong></td>
      </tr></tfoot>
    </table></div>
    <div class="card-body muted" style="border-top:1px solid var(--line)">
      A fold over the same lines above, not a second reading of them — so this
      total and the blocks it came from cannot drift apart. The workbook's own
      summary is a <span class="mono">SUMIF</span> over a bounded range, which is
      how <span class="mono">Internal Finishes Flats!F2040</span> ends up counting
      row 2010 twice (C-15).
    </div>`;

  // -- the working behind any figure --------------------------------------

  host.addEventListener('click', async (e) => {
    const td = e.target.closest('[data-line]');
    if (!td) return;
    const [i, what] = td.dataset.line.split(':');
    const entry = index[Number(i)];
    if (!entry) return;
    await showWorking(entry, what);
  });

  const cache = new Map();
  async function full(line) {
    const key = `${line.room_id}|${line.finish_slot_id}|${line.floor_height_m ?? ''}`;
    if (!cache.has(key)) {
      const query = new URLSearchParams({
        room_id: line.room_id, finish_slot_id: line.finish_slot_id,
      });
      if (line.unit_type_id) query.set('unit_type_id', line.unit_type_id);
      if (line.floor_height_m != null) query.set('floor_height_m', line.floor_height_m);
      try { cache.set(key, await api.get(`/takeoff/derivation?${query}`)); }
      catch { cache.set(key, line); }
    }
    return cache.get(key);
  }

  async function showWorking({ unit, room, line }, what) {
    const where = `${unit.code} · ${room.label} — ${line.finish}`;
    const w = await full(line);

    if (what === 'gross' || what === 'net') {
      const deducted = w.deduction_derivation && line.deduction;
      showDerivation(where, line[what], w.gross_derivation, {
        unit: line.unit,
        extra: `
          ${deducted ? `<h4 class="deriv-h">Less this room's own openings</h4>
            <div class="deriv-expr">${escapeHtml(w.deduction_derivation.expression)}</div>
            ${(w.deduction_derivation.inputs || []).map(i => `
              <div class="deriv-input"><div class="n">${escapeHtml(i.name)}</div>
                <div class="v">−${fmt.n(i.value, 3)}</div></div>`).join('')}
            <div class="deriv-expr">${fmt.n(line.gross, 3)} − ${fmt.n(line.deduction, 3)}
              = ${fmt.n(line.net, 3)} ${escapeHtml(line.unit)}</div>` : ''}
          <div class="deriv-note">Measured on one ${escapeHtml(room.label)}
            (${fmt.n(room.carpet_area_sqm, 2)} sq.m,
            ${fmt.n(room.perimeter_m, 2)} m round). The building has
            ${line.unit_count} of this unit type${line.floor_scope
              ? ` at this height — ${escapeHtml(line.floor_scope)}` : ''}.</div>`,
      });
      return;
    }

    if (what === 'deduction') {
      if (!line.deduction) {
        openPanel(where, `<div class="deriv-note">Nothing is deducted from this
          quantity. ${escapeHtml(line.finish)} is measured as built.</div>`);
        return;
      }
      showDerivation(`${where} — deduction`, line.deduction,
        w.deduction_derivation, { unit: line.unit });
      return;
    }

    if (what === 'rate') {
      if (line.rate === null || line.rate === undefined) {
        openPanel(`${where} — rate`, `<div class="deriv-note">${escapeHtml(
          line.message || 'Measured here, and no rate reaches it. The quantity '
          + 'is real; the amount is missing rather than zero.')}</div>`);
        return;
      }
      showDerivation(`${where} — rate`, line.rate, w.rate_derivation, {
        format: v => `₹${fmt.n(v, 2)}`,
        extra: `<div class="deriv-note">${escapeHtml(line.rate_description || '')}
          — from the <a href="#/rates">Rate Library</a>, reaching this room through
          <a href="#/mapping">room type pricing</a>.</div>`,
      });
      return;
    }

    // The money: the multiplication, with both sides named.
    const perUnit = what === 'amount_per_unit';
    const value = perUnit ? line.amount_per_unit : line.total_amount;
    if (line.status !== 'priced') {
      openPanel(where, `<div class="deriv-note">${escapeHtml(
        line.message || 'This line reaches no total.')}</div>`);
      return;
    }
    openPanel(`${where} — ${perUnit ? 'per unit' : `all ${line.unit_count}`}`, `
      <div class="deriv-value">${fmt.money(value)}</div>
      <div class="muted">${perUnit ? 'net x rate' : 'net x rate x units'}</div>
      <div class="deriv-expr">${fmt.n(line.net, 3)} ${escapeHtml(line.unit)} ×
        ₹${fmt.n(line.rate, 2)}${perUnit ? '' : ` × ${line.unit_count}`} = ${
        fmt.money(value)}</div>
      <div class="deriv-note">The multiplication goes through the unit system, so
        a rate per Nos. meeting a square-metre quantity raises rather than
        producing a plausible number (C-35).</div>`);
  }
});
