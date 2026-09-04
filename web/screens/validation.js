// The issue list. Every finding names the defect it exists to prevent.

import { api, route } from '../app.js';
import { escapeHtml, wireTiles } from '../panel.js';

const SEV = { blocking: 'bad', warning: 'warn', info: 'mute' };

route('/validation', async (main) => {
  const v = await api.get('/validation');
  const groups = { blocking: [], warning: [], info: [] };
  v.findings.forEach(f => groups[f.severity].push(f));

  main.innerHTML = `
    <div class="screen-head">
      <h1>Validation</h1>
      <p>Rules are data, not code, so a new check ships without a release. An estimate cannot be
         issued while anything is blocking.</p>
    </div>
    <div class="tile-row">
      <div class="tile" data-tile="score"><div class="k">Health</div><div class="v">${v.score}</div>
        <div class="s">out of 100</div></div>
      <div class="tile"><div class="k">Blocking</div>
        <div class="v" style="color:var(--bad)">${groups.blocking.length}</div>
        <div class="s">must be resolved</div></div>
      <div class="tile"><div class="k">Warnings</div>
        <div class="v" style="color:var(--warn)">${groups.warning.length}</div>
        <div class="s">acknowledge with a note</div></div>
      <div class="tile" data-tile="issue"><div class="k">Can issue</div>
        <div class="v">${v.can_issue ? 'Yes' : 'No'}</div>
        <div class="s">${v.summary}</div></div>
    </div>

    ${['blocking', 'warning', 'info'].filter(s => groups[s].length).map(s => `
      <div class="card" style="margin-top:16px">
        <h2>${s[0].toUpperCase() + s.slice(1)}
          <span class="sub">${groups[s].length} finding${groups[s].length === 1 ? '' : 's'}</span></h2>
        ${groups[s].map(f => `
          <div class="finding">
            <div><span class="chip ${SEV[f.severity]}">${escapeHtml(f.severity)}</span></div>
            <div class="rule">${escapeHtml(f.rule)}</div>
            <div class="msg">${escapeHtml(f.message)}</div>
          </div>`).join('')}
      </div>`).join('')}`;

  wireTiles(main, {
    score: {
      title: 'Health score',
      value: `${v.score}<span class="muted" style="font-size:13px">/100</span>`,
      expression: '100 less what the findings take, capped per severity',
      rows: [
        ['Blocking', `${groups.blocking.length} · up to 60`],
        ['Warnings', `${groups.warning.length} · up to 30`],
        ['Information', `${groups.info.length} · up to 10`],
      ],
      note: `Capped per band so a hundred spelling notes cannot look like a
        broken estimate, and one blocking finding cannot be lost in the noise.
        The findings themselves are listed below — the score is a summary of
        them, never a substitute for reading them.`,
    },
    issue: {
      title: 'Can this estimate be issued?',
      value: v.can_issue ? 'Yes' : 'No',
      subtitle: v.summary,
      note: v.can_issue
        ? `Nothing is blocking. Warnings remain — they are things somebody
           should acknowledge, not things that stop the estimate going out.`
        : `${groups.blocking.length} blocking finding${
            groups.blocking.length === 1 ? '' : 's'} below. A blocking finding
           is one where a number on the estimate would be wrong, not merely
           unexplained.`,
    },
  });
});
