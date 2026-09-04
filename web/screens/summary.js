// The number at the bottom.
//
// The workbook reaches it through SUBTOTAL(9, D6:D14) over ranges that each
// name a block of the cost sheet by row. That works until a band grows: the
// MEP EXTERNAL heading covers rows 118 to 126, `Summary!D11` sums 118 to 125,
// and the Substation at ₹24,00,000 is computed, formatted and totalled into
// the cost sheet's own I129 while reaching the budget through nothing.
//
// Here a section total is a filter over the lines that name it, so a band
// cannot outgrow the range that sums it. Nothing on this screen is added up
// in the browser.

import { api, fmt, route } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml, showDerivation } from '../panel.js';

route('/summary', async (main) => {
  main.innerHTML = '<div class="loading">Adding the project up…</div>';
  const s = await api.get('/summary');
  const carried = s.sections.filter(x => x.is_carried);

  main.innerHTML = `
    <div class="screen-head">
      <h1>Cost summary</h1>
      <p>Every section, then escalation, contingency and tax. Section totals are
         filters over the lines that belong to them, so a band cannot grow past
         the total that is supposed to contain it.</p>
    </div>

    <div class="tile-row">
      <div class="tile"><div class="k">Project total</div>
        <div class="v">${fmt.money(s.total)}</div>
        <div class="s">including GST</div></div>
      <div class="tile"><div class="k">Before tax</div>
        <div class="v">${fmt.money(s.before_tax)}</div>
        <div class="s">subtotal + escalation + contingency</div></div>
      <div class="tile"><div class="k">Section subtotal</div>
        <div class="v">${fmt.money(s.subtotal)}</div>
        <div class="s">${s.sections.length} sections</div></div>
      <div class="tile"><div class="k">Per sq ft</div>
        <div class="v">${s.rate_per_sqft ? '₹' + fmt.n(s.rate_per_sqft, 0) : '—'}</div>
        <div class="s">${fmt.int(s.construction_area_sqft)} sq ft</div></div>
    </div>

    <div class="card" style="margin-top:16px">
      <h2>By section <span class="sub">click a total to see what it is made of</span></h2>
      <div id="sections"></div>
    </div>

    ${carried.length ? `
    <div class="card explainer">
      <div class="card-body">
        <p style="margin-top:0"><strong>What is carried, and what is derived.</strong>
        ${carried.length} section${carried.length === 1 ? '' : 's'} —
        ${carried.map(c => escapeHtml(c.name)).join(', ')} — take their quantities
        from sheets this platform has not modelled yet (Excavation, Shore Pile,
        Concrete &amp; Steel, Electrical, Plumbing). Those figures are carried
        across with their source cell attached and marked, rather than
        recalculated from something the platform does not yet hold.</p>
        <p style="margin-bottom:0">Preliminaries, Amenities and External Development
        are fully derived here — each line is quantity × rate, and each reconciles
        to its sheet to the paisa.</p>
      </div>
    </div>` : ''}`;

  createGrid(document.getElementById('sections'), {
    columns: [
      { key: 'name', label: 'Section', kind: 'label', width: '220px' },
      { key: 'lines', label: 'Lines', kind: 'derived', dp: 0, width: '76px' },
      { key: '_source', label: 'Quantities', kind: 'note', width: '150px',
        align: 'left',
        title: 'Derived means the platform computes the quantity. Carried means '
             + 'it came across from a sheet not modelled here yet.',
        get: row => row.is_carried ? 'carried' : 'derived',
        render: v => v === 'carried'
          ? '<span class="tag warn">carried across</span>'
          : '<span class="tag ok">derived here</span>' },
      { key: 'excel_ref', label: 'In the workbook', kind: 'note', width: '250px',
        align: 'left',
        render: v => `<span class="muted mono">${escapeHtml(v || '—')}</span>` },
      { key: 'amount', label: 'Amount', kind: 'derived', width: '150px', total: true,
        render: v => fmt.money(v) },
    ],
    rows: s.sections,
    rowKey: r => r.id,
    shortcuts: false,
    onDerivedClick: (row, col) => {
      if (col.key === 'amount') {
        showDerivation(`${row.name} — section total`, row.amount, row.derivation, {
          format: v => fmt.money(v),
          extra: `<div class="deriv-note">${row.is_carried
            ? `Every quantity in this section is carried across from a sheet
               this platform has not modelled yet, with its source cell
               attached. The rate and the arithmetic are real; the quantity
               was not recomputed here.`
            : `Each line here is quantity × rate, computed by the engine, and
               reconciles to its sheet to the paisa.`}</div>
            <h4 class="deriv-h">Where this goes</h4>
            <div class="deriv-note">Into the section subtotal, then escalation
              and contingency on top of that, then GST on the result. Click the
              project total below to see those three steps.</div>`,
        });
        return true;
      }
      if (col.key === 'lines') {
        showDerivation(`${row.name} — lines`, row.lines, row.derivation, {
          format: v => `${v} line${v === 1 ? '' : 's'}`,
          extra: `<div class="deriv-note">${row.carried} of them carry a
            quantity from a sheet not modelled here. A section is a filter over
            the lines that name it, so a line added at the foot of the band is
            counted because it names the band — never because somebody widened
            a SUM.</div>`,
        });
        return true;
      }
      return false;
    },
    footer: rows => [
      '<strong>Subtotal</strong>', '', '', '',
      `<strong>${fmt.money(rows.reduce((a, r) => a + r.amount, 0))}</strong>`,
    ],
  });

  // The uplifts, and the total, as a short ledger rather than a grid.
  const rows = [
    ...s.uplifts.map(u => [`${u.label} @ ${(u.rate * 100).toFixed(0)}%`,
                           `<span class="muted">${escapeHtml(u.basis)}</span>`,
                           fmt.money(u.amount)]),
    ['<strong>Before tax</strong>', '', `<strong>${fmt.money(s.before_tax)}</strong>`],
    [`GST @ ${(s.tax / s.before_tax * 100).toFixed(0)}%`, '', fmt.money(s.tax)],
  ];

  document.getElementById('sections').insertAdjacentHTML('afterend', `
    <div class="card-body" style="border-top:1px solid var(--line)">
      <table class="kv" style="width:100%"><tbody>
        ${rows.map(([a, b, c]) => `<tr><td>${a}</td><td>${b}</td>
          <td class="right mono">${c}</td></tr>`).join('')}
        <tr class="total-row"><td><strong>Project total</strong></td><td></td>
          <td class="right mono"><strong><a href="#" id="totalWorking"
            class="link-quiet">${fmt.money(s.total)}</a></strong></td></tr>
      </tbody></table>
    </div>`);

  const link = document.getElementById('totalWorking');
  if (link) {
    link.onclick = e => {
      e.preventDefault();
      showDerivation('Project total', s.total, s.derivation,
                     { format: v => fmt.money(v) });
    };
  }
});
