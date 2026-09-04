import { api, fmt, route } from '../app.js';
import { escapeHtml, wireTiles } from '../panel.js';

route('/overview', async (main) => {
  // Reconciliation reads the workbook, which is slow the first time in a
  // session. Awaiting it here used to hold the whole screen for 5.4 seconds
  // before anything appeared. It now fills in on its own.
  const reconciling = api.get('/reconciliation').catch(() => null);
  const h = await api.get('/headline');
  const recon = null;

  const bhk = Object.entries(h.classification)
    .filter(([k]) => k !== 'Office')
    .map(([k, v]) => `<span class="tag">${escapeHtml(k)} ${v}</span>`).join(' ');

  main.innerHTML = `
    <div class="screen-head">
      <h1>${escapeHtml(h.project.name)}</h1>
      <p>You enter room configuration, unit sizes, doors and windows, and rates.
         Everything else on every screen is computed from those — there are no
         links to maintain and no ranges to extend.</p>
    </div>

    <div class="tile-row">
      <div class="tile" data-tile="flats"><div class="k">Flats</div><div class="v">${fmt.int(h.flats)}</div>
        <div class="s">${bhk}</div></div>
      <div class="tile" data-tile="offices"><div class="k">Offices</div><div class="v">${fmt.int(h.offices)}</div>
        <div class="s">across ${h.floors} floors</div></div>
      <div class="tile" data-tile="carpet"><div class="k">Carpet area</div>
        <div class="v">${fmt.int(h.carpet_area_sqft)}</div><div class="s">sq.ft</div></div>
      <div class="tile" data-tile="doors"><div class="k">Doors</div><div class="v">${fmt.int(h.doors)}</div>
        <div class="s">from the room schedule</div></div>
      <div class="tile" data-tile="rooms"><div class="k">Rooms defined</div><div class="v">${fmt.int(h.rooms)}</div>
        <div class="s">${h.rate_items} rate items</div></div>
      <div class="tile" data-tile="height"><div class="k">Building height</div>
        <div class="v">${h.building_height_m}</div><div class="s">metres</div></div>
    </div>

    <div class="card" style="margin-top:16px">
      <h2>Try the automation <span class="sub">the point of the whole thing</span></h2>
      <div class="card-body">
        <p style="margin-top:0">Open <a href="#/room-config">Room Config</a> and change how many
        Flat 1B sit on one floor. The flat count, the carpet area, the room quantities, the door
        count and every type total move together, in the bar at the top of this window. Nothing
        needs re-linking, and no formula has to be dragged down.</p>
        <p class="muted" style="margin-bottom:0">Then open
        <a href="#/rates">Rate Library</a> and change a wastage percentage — every rate built on
        it recalculates at once, and the working is shown.</p>
      </div>
    </div>

    <div class="card" id="reconCard">
      <h2>Reconciliation against the workbook</h2>
      <div class="card-body" id="reconBody">
        <div class="skeleton-row"></div>
        <p class="muted" style="margin-bottom:0">Reading the workbook…</p>
      </div>
    </div>

    <div class="card">
      <h2>Health <span class="sub">${h.health.blocking} blocking · ${h.health.warnings} warnings</span></h2>
      <div class="card-body">
        <p style="margin-top:0" class="muted">An estimate cannot be issued while anything is
        blocking. <a href="#/validation">Open the issue list</a>.</p>
      </div>
    </div>`;

  // The headline figures are the first ones anybody reads and were the last
  // that could not be questioned.
  wireTiles(main, {
    flats: {
      title: 'Flats in the building',
      value: fmt.int(h.flats),
      subtitle: 'counted from the floor matrix, never typed',
      rows: Object.entries(h.classification || {})
        .filter(([k]) => k !== 'Office')
        .map(([k, v]) => [escapeHtml(k), fmt.int(v)]),
      note: `A group-by over Room Config, so the split cannot go stale. The
        workbook computes its own from hand-typed column lists —
        <span class="mono">Room Conf!L44 = M40+O40+R40+U40+V40+Y40+Z40+P40</span>,
        with <span class="mono">P40</span> appended out of sequence, which is
        what a later patch looks like (C-21). Add a unit type here and it
        appears by itself.`,
    },
    offices: {
      title: 'Offices in the building',
      value: fmt.int(h.offices),
      subtitle: `across ${h.floors} floors`,
      note: `The same fold as the flats, filtered on classification. An office
        is not a special case in the code — it is a unit type with a different
        word against it.`,
    },
    carpet: {
      title: 'Carpet area',
      value: `${fmt.int(h.carpet_area_sqft)} <span class="muted"
        style="font-size:13px">sq.ft</span>`,
      expression: 'sum over every unit type of (rooms added × units of that type)',
      note: `Common areas excluded. Square feet come from square metres through
        the project's own factor of 10.764 — a named parameter on the
        <a href="#/parameters">Parameters</a> screen, not a number typed into a
        formula. Change it there and this moves.`,
    },
    doors: {
      title: 'Doors in the building',
      value: fmt.int(h.doors),
      note: `Every door placed in a room, folded up through the unit types that
        contain it. The workbook has two answers to this —
        <span class="mono">Doors!E141</span> says 58 where
        <span class="mono">Doors!L141</span> says 2,180, because they were two
        sums over two ranges (C-12). Here the count and the money come from one
        fold. <a href="#/openings">See the schedule</a>.`,
    },
    rooms: {
      title: 'Rooms defined',
      value: fmt.int(h.rooms),
      subtitle: `${h.rate_items} rate items price them`,
      note: `Rows across every unit type. A flat with four bathrooms and a flat
        with one are just different numbers of rows — nothing in the engine
        assumes a shape.`,
    },
    height: {
      title: 'Building height',
      value: `${h.building_height_m} <span class="muted"
        style="font-size:13px">m</span>`,
      expression: `every floor's floor-to-floor height, added`,
      note: `From <a href="#/room-config">Room Config</a>. Each floor carries
        its own height, and wall quantities are measured against the floor the
        unit actually sits on rather than one figure for the whole tower.`,
    },
  });

  // Fill the reconciliation card when the workbook comes back.
  reconciling.then(recon => {
    const card = document.getElementById('reconCard');
    const body = document.getElementById('reconBody');
    if (!card || !body) return;              // navigated away already
    if (!recon) { card.remove(); return; }
    card.querySelector('h2').innerHTML =
      `Reconciliation against the workbook
       <span class="sub">${escapeHtml(recon.workbook)}</span>`;
    body.innerHTML = `
      <span class="chip ok">${recon.pass} PASS</span>
      <span class="chip warn" style="margin-left:6px">${recon.explained} EXPLAINED</span>
      <span class="chip ${recon.fail ? 'bad' : 'mute'}" style="margin-left:6px">${recon.fail} FAIL</span>
      <p class="muted" style="margin-bottom:0">Every figure the platform computes, beside the
      workbook's own cached value. <a href="#/reconciliation">See all ${recon.lines.length} lines</a>.</p>`;
  });
});
