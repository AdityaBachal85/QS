import { api, fmt, route } from '../app.js';
import { escapeHtml } from '../panel.js';

route('/overview', async (main) => {
  const [h, recon] = await Promise.all([
    api.get('/headline'),
    api.get('/reconciliation').catch(() => null),
  ]);

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
      <div class="tile"><div class="k">Flats</div><div class="v">${fmt.int(h.flats)}</div>
        <div class="s">${bhk}</div></div>
      <div class="tile"><div class="k">Offices</div><div class="v">${fmt.int(h.offices)}</div>
        <div class="s">across ${h.floors} floors</div></div>
      <div class="tile"><div class="k">Carpet area</div>
        <div class="v">${fmt.int(h.carpet_area_sqft)}</div><div class="s">sq.ft</div></div>
      <div class="tile"><div class="k">Doors</div><div class="v">${fmt.int(h.doors)}</div>
        <div class="s">from the room schedule</div></div>
      <div class="tile"><div class="k">Rooms defined</div><div class="v">${fmt.int(h.rooms)}</div>
        <div class="s">${h.rate_items} rate items</div></div>
      <div class="tile"><div class="k">Building height</div>
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

    ${recon ? `
    <div class="card">
      <h2>Reconciliation against the workbook
        <span class="sub">${escapeHtml(recon.workbook)}</span></h2>
      <div class="card-body">
        <span class="chip ok">${recon.pass} PASS</span>
        <span class="chip warn" style="margin-left:6px">${recon.explained} EXPLAINED</span>
        <span class="chip ${recon.fail ? 'bad' : 'mute'}" style="margin-left:6px">${recon.fail} FAIL</span>
        <p class="muted" style="margin-bottom:0">Every figure the platform computes, beside the
        workbook's own cached value. <a href="#/reconciliation">See all ${recon.lines.length} lines</a>.</p>
      </div>
    </div>` : ''}

    <div class="card">
      <h2>Health <span class="sub">${h.health.blocking} blocking · ${h.health.warnings} warnings</span></h2>
      <div class="card-body">
        <p style="margin-top:0" class="muted">An estimate cannot be issued while anything is
        blocking. <a href="#/validation">Open the issue list</a>.</p>
      </div>
    </div>`;
});
