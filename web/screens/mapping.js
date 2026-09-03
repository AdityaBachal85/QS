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

import { api, fmt, refresh, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml } from '../panel.js';

route('/mapping', async (main) => {
  const { mappings, targets } = await api.get('/room-type-mapping');
  const unconfirmed = mappings.filter(m => !m.confirmed && m.prices_as_id);
  const unmapped = mappings.filter(m => !m.prices_as_id && !m.own_schedule);

  main.innerHTML = `
    <div class="screen-head">
      <h1>Room type pricing</h1>
      <p>Your sizes sheets and your rate list call the same room by different names.
         This is where the two are joined up.</p>
    </div>

    <div class="card explainer">
      <div class="card-body">
        <p style="margin-top:0"><strong>Why you are being asked.</strong>
        <span class="mono">Flat Sizes</span> calls a room <span class="mono">M. Bedroom</span>;
        the rate-list block that prices it is called <span class="mono">M. Bed</span>.
        Only <strong>${mappings.filter(m => m.own_schedule).length} of ${mappings.length}</strong>
        room types match by name. For the rest the importer picked the closest match —
        <span class="mono">M. Toilet → Toilet With M. Bed</span>,
        <span class="mono">Balcony → Balcony / Utility</span> — and left each one flagged,
        because a guess that nobody checked is how a bedroom ends up priced as a toilet.</p>
        <p style="margin-bottom:0"><strong>Confirming means:</strong> “yes, this block of the
        rate library is what prices this room.” It changes no money on its own — the rooms are
        already costed on these links, and the amount beside each one is what it is currently
        worth. Confirming records that a person agreed, and clears the flag. Disagree with one?
        Change it in the dropdown instead.</p>
      </div>
    </div>

    <div class="toolbar">
      <span class="chip ${unconfirmed.length ? 'warn' : 'ok'}">
        ${unconfirmed.length} still flagged as a guess</span>
      <span class="chip ${unmapped.length ? 'bad' : 'mute'}">${unmapped.length} that cannot be priced</span>
      ${unconfirmed.length
        ? '<button class="btn primary" id="confirmAll">Agree with all ' + unconfirmed.length + ' proposals</button>' : ''}
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
      { key: 'amount', label: 'Currently worth', kind: 'derived', width: '128px',
        title: 'What this room type costs on the link as it stands. Agreeing does '
             + 'not change it — the rooms are already priced this way.',
        render: v => (v ? fmt.money(v) : '<span class="muted">—</span>') },
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
