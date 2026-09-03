// The project dashboard.
//
// The store has held more than one project since it was written; nothing ever
// showed them. A new estimate almost always starts from the last one, so
// copying is the important action here — and a copy rewrites every id, so the
// two can never share a row and editing one cannot reach into the other.

import { api, fmt, refresh, route, toast } from '../app.js';
import { createGrid } from '../grid.js';
import { escapeHtml } from '../panel.js';

route('/projects', async (main) => {
  main.innerHTML = '<div class="loading">Reading the projects…</div>';
  const [data, me] = await Promise.all([api.get('/dashboard'), api.get('/me')]);
  const live = data.projects.filter(p => !p.archived);
  const archived = data.projects.filter(p => p.archived);
  const mayWrite = me.open_access || (me.user && me.user.may_write);

  main.innerHTML = `
    <div class="screen-head">
      <h1>Projects</h1>
      <p>Every estimate this installation holds. Open one to work in it, or copy
         one to start the next — a copy shares no rows with its original.</p>
    </div>
    <div class="card"><h2>Live <span class="sub">${live.length}</span></h2>
      <div id="live"></div></div>
    ${archived.length ? `<div class="card"><h2>Archived
      <span class="sub">${archived.length} — kept, not deleted</span></h2>
      <div id="archived"></div></div>` : ''}`;

  function grid(host, rows, isArchived) {
    createGrid(document.getElementById(host), {
      columns: [
        { key: 'name', label: 'Project', kind: 'label', width: '230px',
          render: (v, r) => `${escapeHtml(v)}${r.open
            ? ' <span class="tag ok">open</span>' : ''}` },
        { key: 'city', label: 'City', kind: 'derived', width: '110px', align: 'left',
          render: v => escapeHtml(v || '—') },
        { key: 'units', label: 'Units', kind: 'derived', dp: 0, width: '76px' },
        { key: 'rooms', label: 'Rooms', kind: 'derived', dp: 0, width: '76px' },
        { key: 'cost_total', label: 'Cost lines', kind: 'derived', width: '130px',
          render: v => (v ? fmt.money(v) : '<span class="muted">—</span>') },
        { key: 'health', label: 'Health', kind: 'derived', width: '92px',
          render: (v, r) => `<span class="tag ${r.blocking ? 'bad' : v >= 70 ? 'ok' : 'warn'}">${
            v ?? '—'}/100</span>` },
        { key: 'updated_at', label: 'Last changed', kind: 'derived', width: '160px',
          align: 'left',
          render: v => `<span class="muted">${v ? escapeHtml(v.replace('T', ' ').slice(0, 16)) : '—'}</span>` },
        { key: '_open', label: '', kind: 'derived', width: '210px', align: 'left',
          get: () => null,
          render: (v, r) => mayWrite ? `
            ${r.open ? '' : `<a class="link-quiet" data-act="open" data-id="${r.id}" href="#">open</a> · `}
            <a class="link-quiet" data-act="copy" data-id="${r.id}" href="#">copy</a> ·
            <a class="link-quiet" data-act="${isArchived ? 'restore' : 'archive'}"
               data-id="${r.id}" href="#">${isArchived ? 'restore' : 'archive'}</a>`
            : '<span class="muted">read only</span>' },
      ],
      rows,
      rowKey: r => r.id,
      shortcuts: false,
      emptyMessage: isArchived ? 'Nothing archived.' : 'No projects yet.',
    });
  }

  grid('live', live, false);
  if (archived.length) grid('archived', archived, true);

  main.addEventListener('click', async (e) => {
    const link = e.target.closest('[data-act]');
    if (!link) return;
    e.preventDefault();
    const id = link.dataset.id;
    const project = data.projects.find(p => p.id === id);
    try {
      if (link.dataset.act === 'open') {
        await api.post('/projects/open', { project_id: id });
        toast(`Opened ${project.name}`);
        location.hash = '#/overview';
        location.reload();
      } else if (link.dataset.act === 'copy') {
        const name = window.prompt('Name for the copy', `${project.name} R1`);
        if (!name) return;
        await api.post('/projects/duplicate', { project_id: id, name });
        toast(`Copied to “${name}” and opened it`);
        location.reload();
      } else {
        const archiving = link.dataset.act === 'archive';
        await api.post('/projects/archive', { project_id: id, archived: archiving });
        toast(archiving ? 'Archived — kept, not deleted' : 'Restored');
        await refresh();
      }
    } catch (err) { toast(err.message, true); }
  });
});
