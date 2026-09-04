// The editable grid.
//
// QS staff live in a spreadsheet. If this feels like a web form with Save
// buttons they will quietly keep using Excel, so the grid has to behave like the
// thing it replaces: arrow keys, Tab, type-to-replace, Escape, undo, and paste a
// block straight out of Excel.
//
// One behaviour is deliberately *not* spreadsheet-like. A derived cell cannot be
// edited. Clicking it opens the derivation panel instead. That is the difference
// between this and the workbook, where `Flat Sizes!E57` accepted a perimeter
// typed into an area column and understated 27 flats (C-3).

import { fmt, openPanel, toast } from './app.js';
import { escapeHtml } from './panel.js';

// The undo stack lives outside any one grid instance. Committing an edit
// reloads the screen -- that is how the recalculation cascade becomes visible --
// which rebuilds the grid from scratch. A stack held inside the instance would
// be thrown away by the very action it needs to record. Entries hold ids, not
// live objects, so they survive the rebuild.
let undoStack = [];
export function clearUndo() { undoStack = []; }

//: Where the cursor was when a write triggered a redraw.
//
// Committing reloads the screen, which rebuilds the table -- and focus died
// with the old DOM, so the next keystroke went nowhere. Ctrl+Z after a fill
// did nothing at all, which is exactly the kind of silence this app exists to
// remove. The first grid that can honour it takes it, and clears it.
let pendingFocus = null;

export function createGrid(host, config) {
  const {
    columns, rows, rowKey = r => r.id,
    onCommit,                 // async (row, column, value) => void
    onDerivedClick,           // (row, column) => void
    stickyFirst = true,
    footer,                   // optional array of cells for a totals row
    emptyMessage = 'Nothing here yet.',
  } = config;

  const wrap = document.createElement('div');
  wrap.className = 'grid-wrap';

  if (!rows.length) {
    wrap.innerHTML = `<div class="card-body muted">${escapeHtml(emptyMessage)}</div>`;
    host.appendChild(wrap);
    if (config.onAdd) {
      const bar = document.createElement('div');
      bar.className = 'grid-actions';
      bar.innerHTML = `<button class="btn" id="addRowEmpty">+ ${
        escapeHtml(config.addLabel || 'Add row')}</button>`;
      bar.querySelector('#addRowEmpty').onclick = async () => {
        try {
          await config.onAdd();
          if (config.reload) await config.reload();
        } catch (err) { toast(err.message, true); }
      };
      host.appendChild(bar);
    }
    return { element: wrap };
  }

  const table = document.createElement('table');
  table.className = 'grid';
  table.innerHTML = `
    <thead><tr>${columns.map((c, ci) => `
      <th class="${c.kind === 'label' || c.kind === 'select' || c.align === 'left'
                    ? 'left' : ''} ${c.total ? 'total' : ''}"
          ${c.width ? `style="min-width:${c.width}"` : ''}
          ${stickyFirst && ci === 0 ? 'style="position:sticky;left:0;z-index:4"' : ''}
          title="${escapeHtml(c.title || '')}">${escapeHtml(c.label)}${
            c.unit ? `<div class="muted" style="font-weight:400">${escapeHtml(c.unit)}</div>` : ''
          }</th>`).join('')}</tr></thead>
    <tbody></tbody>
    ${footer ? '<tfoot></tfoot>' : ''}`;

  const tbody = table.querySelector('tbody');

  function valueOf(row, col) {
    return col.get ? col.get(row) : row[col.key];
  }

  function display(row, col) {
    const v = valueOf(row, col);
    if (col.kind === 'delete') {
      return `<button class="row-del" title="Delete this row" tabindex="-1">&times;</button>`;
    }
    if (col.render) return col.render(v, row);
    if (col.kind === 'select') {
      // Show the label, not the id. A dropdown is how a typo stops being
      // possible -- the workbook's joins broke on 'Vitrfied Skirting',
      // 'Skriting', 'Arcylic' and 'Membrame' (C-34).
      const opt = (col.options || []).find(o => String(o.value) === String(v));
      return opt ? escapeHtml(opt.label)
                 : `<span class="muted">${escapeHtml(v ?? '—')}</span>`;
    }
    if (col.kind === 'label' || col.kind === 'note') return escapeHtml(v ?? '');
    // A matrix of counts reads far better with blanks than with a wall of
    // zeros -- the same reason the workbook leaves those cells empty.
    if (col.blankZero && !v) return '';
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v === 'number') {
      if (col.dp === 0) return fmt.int(v);
      return fmt.n(v, col.dp ?? 2);
    }
    return escapeHtml(String(v));
  }

  function cellClass(row, col) {
    const classes = [];
    if (col.kind === 'label') classes.push('label', 'left');
    // A calculated figure, and a grey cell that is merely not typeable, used to
    // be the same thing here. `Unit` = SQM and `In the workbook` =
    // Summary!D20 rendered in the same grey as a Rs 9 crore total and invited
    // the same click. `note` is the second kind: it reads as information, not
    // as a figure with a working behind it.
    else if (col.kind === 'derived') classes.push('derived', 'clickable');
    else if (col.kind === 'note') classes.push('derived', 'note');
    else if (col.kind === 'delete') classes.push('act');
    else classes.push('cell');
    if (col.kind === 'select') classes.push('sel-cell', 'left');
    if (col.total) classes.push('total');
    if (col.align === 'left') classes.push('left');
    const v = valueOf(row, col);
    if (col.kind !== 'label' && col.kind !== 'note'
        && (v === 0 || v === null || v === undefined)) {
      // Never a silent zero -- but "empty" and "missing" are different things.
      // A blank laying rate on plaster is normal; a blank *overall* rate on a
      // measured quantity is the false-ceiling case, ₹65.5 lakh shown as
      // nothing, and only that gets flagged.
      classes.push(col.flagMissing && v !== 0 ? 'missing' : 'zero');
    }
    return classes.join(' ');
  }

  function draw() {
    tbody.innerHTML = rows.map((row, ri) => `
      <tr data-r="${ri}">${columns.map((col, ci) => `
        <td class="${cellClass(row, col)}"
            data-r="${ri}" data-c="${ci}"
            tabindex="${col.kind === 'label' || col.kind === 'note'
              || col.kind === 'delete' ? -1 : 0}"
            ${stickyFirst && ci === 0
              ? 'style="position:sticky;left:0;z-index:2;background:var(--surface)"' : ''}
            >${display(row, col)}</td>`).join('')}</tr>`).join('');

    if (footer) {
      table.querySelector('tfoot').innerHTML = `<tr class="total-row">${
        footer(rows).map((c, ci) => `<td class="${ci === 0 ? 'left' : ''}"
          ${stickyFirst && ci === 0
            ? 'style="position:sticky;left:0;z-index:2;background:#eef1f7"' : ''}
          >${c}</td>`).join('')}</tr>`;
    }
  }

  // -- navigation ---------------------------------------------------------

  function cellAt(r, c) {
    return tbody.querySelector(`td[data-r="${r}"][data-c="${c}"]`);
  }

  function move(from, dr, dc) {
    let r = Number(from.dataset.r) + dr;
    let c = Number(from.dataset.c) + dc;
    while (columns[c] && columns[c].kind === 'label' && dc !== 0) c += dc;
    const next = cellAt(r, c);
    if (next) { next.focus(); return true; }
    return false;
  }

  function nextEditable(from, step) {
    let r = Number(from.dataset.r);
    let c = Number(from.dataset.c) + step;
    for (let guard = 0; guard < columns.length * rows.length + 5; guard++) {
      if (c >= columns.length) { c = 0; r += 1; }
      if (c < 0) { c = columns.length - 1; r -= 1; }
      if (r < 0 || r >= rows.length) return null;
      if (columns[c].kind === 'input') return cellAt(r, c);
      c += step;
    }
    return null;
  }

  // -- editing ------------------------------------------------------------

  let editing = null;

  function beginEdit(td, seed) {
    const col = columns[td.dataset.c];
    if (col.kind === 'select') return beginSelect(td, col);
    if (col.kind !== 'input') return;
    const row = rows[td.dataset.r];
    const current = valueOf(row, col);
    const original = td.innerHTML;
    editing = { td, col, row, original };

    td.classList.add('editing');
    td.innerHTML = `<input value="${seed ?? (current ?? '')}">`;
    const input = td.querySelector('input');
    input.focus();
    if (seed === undefined) input.select();
    else input.setSelectionRange(input.value.length, input.value.length);

    input.addEventListener('keydown', e => {
      e.stopPropagation();
      if (e.key === 'Enter')  { e.preventDefault(); commit(input.value, 1, 0); }
      else if (e.key === 'Tab') { e.preventDefault(); commit(input.value, 0, e.shiftKey ? -1 : 1); }
      else if (e.key === 'Escape') { e.preventDefault(); cancel(); }
    });
    input.addEventListener('blur', () => { if (editing) commit(input.value, 0, 0); });
  }

  function beginSelect(td, col) {
    const row = rows[td.dataset.r];
    const current = valueOf(row, col);
    const original = td.innerHTML;
    editing = { td, col, row, original };
    td.classList.add('editing');
    td.innerHTML = `<select>${(col.options || []).map(o =>
      `<option value="${escapeHtml(o.value)}" ${
        String(o.value) === String(current) ? 'selected' : ''
      }>${escapeHtml(o.label)}</option>`).join('')}</select>`;

    const select = td.querySelector('select');
    select.focus();
    const finish = async (commitIt) => {
      if (!editing) return;
      const chosen = select.value;
      editing = null;
      td.classList.remove('editing');
      if (!commitIt || chosen === String(current)) {
        td.innerHTML = original;
      } else {
        undoStack.push({ row, col, value: current });
        td.innerHTML = display(row, col);
        await apply(row, col, chosen, td);
      }
      td.focus();
    };
    select.addEventListener('change', () => finish(true));
    select.addEventListener('blur', () => finish(true));
    select.addEventListener('keydown', e => {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); finish(false); }
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    });
  }

  function cancel() {
    if (!editing) return;
    const { td, original } = editing;
    editing = null;
    td.classList.remove('editing');
    td.innerHTML = original;
    td.focus();
  }

  async function commit(raw, dr, dc) {
    if (!editing) return;
    const { td, col, row } = editing;
    editing = null;
    td.classList.remove('editing');

    const before = valueOf(row, col);
    const value = parse(raw, col);
    td.innerHTML = display(row, col);
    td.focus();

    if (value === before) { if (dr || dc) move(td, dr, dc); return; }
    undoStack.push({ row, col, value: before });
    await apply(row, col, value, td);
    if (dr || dc) move(td, dr, dc);
  }

  function parse(raw, col) {
    const text = String(raw).trim().replace(/,/g, '');
    if (text === '') return col.nullable ? null : 0;
    if (col.text) return text;
    const n = Number(text);
    return Number.isFinite(n) ? n : 0;
  }

  async function apply(row, col, value, td) {
    try {
      await onCommit(row, col, value);
      if (config.reload) await config.reload();
    } catch (err) {
      toast(err.message, true);
      if (td) td.innerHTML = display(row, col);
    }
  }

  // -- selection ----------------------------------------------------------
  //
  // A QS works in blocks: a column of areas, a row of counts. Without a range
  // there is no copy, no fill and no paste-into-a-selection, and the grid stops
  // being a place you can do the work.

  let selection = null;          // {ar, ac, fr, fc} anchor and focus

  function bounds(sel) {
    return {
      r0: Math.min(sel.ar, sel.fr), r1: Math.max(sel.ar, sel.fr),
      c0: Math.min(sel.ac, sel.fc), c1: Math.max(sel.ac, sel.fc),
    };
  }

  function paint() {
    tbody.querySelectorAll('td.in-range').forEach(td => td.classList.remove('in-range'));
    if (!selection) { announce(''); return; }
    const b = bounds(selection);
    let n = 0;
    for (let r = b.r0; r <= b.r1; r++) {
      for (let c = b.c0; c <= b.c1; c++) {
        const td = cellAt(r, c);
        if (td) { td.classList.add('in-range'); n++; }
      }
    }
    announce(n > 1 ? `${n} cells selected` : '');
  }

  function announce(text) {
    let el = wrap.querySelector('.grid-status');
    if (!el) {
      el = document.createElement('div');
      el.className = 'grid-status';
      el.setAttribute('aria-live', 'polite');
      wrap.appendChild(el);
    }
    el.textContent = text;
    el.hidden = !text;
  }

  function cellAt(r, c) {
    return tbody.querySelector(`td[data-r="${r}"][data-c="${c}"]`);
  }

  function setAnchor(td) {
    selection = { ar: Number(td.dataset.r), ac: Number(td.dataset.c),
                  fr: Number(td.dataset.r), fc: Number(td.dataset.c) };
    paint();
  }

  function extendTo(r, c) {
    if (!selection) return;
    selection.fr = Math.max(0, Math.min(rows.length - 1, r));
    selection.fc = Math.max(0, Math.min(columns.length - 1, c));
    const td = cellAt(selection.fr, selection.fc);
    if (td) td.focus({ preventScroll: false });
    paint();
  }

  /** What a cell copies as: the raw number for inputs, what you see for the rest. */
  function copyText(row, col) {
    const v = valueOf(row, col);
    if (col.kind === 'input') return v === null || v === undefined ? '' : String(v);
    if (col.kind === 'select') {
      const opt = (col.options || []).find(o => String(o.value) === String(v));
      return opt ? opt.label : (v ?? '');
    }
    const td = document.createElement('div');
    td.innerHTML = display(row, col);
    return td.textContent.replace(/\u2014/g, '').trim();
  }

  async function copySelection() {
    if (!selection) return;
    const b = bounds(selection);
    const lines = [];
    for (let r = b.r0; r <= b.r1; r++) {
      const line = [];
      for (let c = b.c0; c <= b.c1; c++) line.push(copyText(rows[r], columns[c]));
      lines.push(line.join('\t'));
    }
    const text = lines.join('\n');
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard permission refused -- fall back to a hidden textarea.
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } finally { ta.remove(); }
    }
    const n = (b.r1 - b.r0 + 1) * (b.c1 - b.c0 + 1);
    toast(`Copied ${n} cell${n === 1 ? '' : 's'} — paste straight into Excel`);
  }

  /** Ctrl+D / Ctrl+R: repeat the first row (or column) across the selection. */
  async function fill(direction) {
    if (!selection) return;
    const b = bounds(selection);
    const edits = [];
    for (let r = b.r0; r <= b.r1; r++) {
      for (let c = b.c0; c <= b.c1; c++) {
        if (direction === 'down' && r === b.r0) continue;
        if (direction === 'right' && c === b.c0) continue;
        const col = columns[c];
        if (col.kind !== 'input') continue;
        const source = direction === 'down' ? valueOf(rows[b.r0], col)
                                            : valueOf(rows[r], columns[b.c0]);
        const before = valueOf(rows[r], col);
        if (source === before) continue;
        edits.push({ row: rows[r], col, value: source, before });
      }
    }
    await commitMany(edits, `Filled ${direction}`);
  }

  /** One undo entry for the whole block, so a fill or paste reverses in one go. */
  async function commitMany(edits, what) {
    if (!edits.length) { toast('Nothing editable in that selection', true); return; }
    rememberFocus();
    undoStack.push(...edits.map(e => ({ row: e.row, col: e.col, value: e.before })).reverse());
    for (const edit of edits) {
      try { await onCommit(edit.row, edit.col, edit.value); }
      catch (err) { toast(err.message, true); break; }
    }
    if (config.reload) await config.reload();
    toast(`${what}: ${edits.length} cell${edits.length === 1 ? '' : 's'}`);
  }

  // -- events -------------------------------------------------------------

  tbody.addEventListener('mousedown', e => {
    const td = e.target.closest('td');
    if (!td || editing || e.target.closest('.row-del')) return;
    if (e.shiftKey && selection) {
      e.preventDefault();
      extendTo(Number(td.dataset.r), Number(td.dataset.c));
      return;
    }
    setAnchor(td);
    dragging = true;
  });

  // Click-drag to select, the way a spreadsheet does.
  let dragging = false;
  tbody.addEventListener('mouseover', e => {
    if (!dragging || editing) return;
    const td = e.target.closest('td');
    if (td) extendTo(Number(td.dataset.r), Number(td.dataset.c));
  });
  document.addEventListener('mouseup', () => { dragging = false; });

  tbody.addEventListener('click', async e => {
    const td = e.target.closest('td');
    if (!td || editing) return;
    const col = columns[td.dataset.c];
    const row = rows[td.dataset.r];
    if (e.target.closest('.row-del')) { await removeRow(row); return; }
    if (col.kind === 'select') { beginSelect(td, col); return; }
    if (col.kind === 'derived') {
      // A cell may render a link to *look* like one -- "where is this used?" --
      // but it is a figure, not navigation, and letting the href through sets
      // the hash and re-routes the whole screen underneath the panel.
      if (e.target.closest('a')) e.preventDefault();
      explain(row, col, td);
    }
  });

  // Open the working behind a calculated cell.
  //
  // The screen's handler gets first refusal and says whether it took the
  // click. If it did not -- a column nobody wrote a case for, a figure with no
  // derivation behind it yet -- the fallback opens anyway, with the column's
  // own explanation and the value in front of it. A grey cell that does
  // nothing when you click it is the silence this whole platform exists to
  // remove, so the grid refuses to produce one.
  function explain(row, col, td) {
    if (!onDerivedClick) { fallback(row, col); return; }
    // A handler may be async -- the take-off fetches one line's working on
    // demand rather than shipping 2 MB of panels nobody opens -- so a promise
    // is waited on before deciding whether the fallback is needed. Without
    // this every async handler would read as "handled" simply by returning a
    // promise, and an unmatched column would go quiet again.
    const handled = onDerivedClick(row, col, td);
    if (handled && typeof handled.then === 'function') {
      handled.then(result => { if (!result) fallback(row, col); },
                   () => fallback(row, col));
      return;
    }
    // A handler has to *say* it handled the click. Returning nothing is what
    // a handler does when it has no case for a column, and that is exactly
    // when the fallback is needed -- so silence must not be the default.
    if (!handled) fallback(row, col);
  }

  function fallback(row, col) {
    const value = valueOf(row, col);
    const label = [col.label, col.unit].filter(Boolean).join(' ');
    const shown = value === null || value === undefined || value === ''
      ? '<span class="muted">nothing here</span>'
      : escapeHtml(typeof value === 'number'
        ? fmt.n(value, col.dp ?? 2) : String(value));
    const name = config.rowName ? config.rowName(row)
      : (row.label || row.name || row.description || row.code || '');

    openPanel(`${name ? `${name} — ` : ''}${label || 'this figure'}`, `
      <div class="deriv-value">${shown}${col.unit
        ? ` <span class="muted" style="font-size:13px">${escapeHtml(col.unit)}</span>` : ''}</div>
      ${col.title ? `<div class="deriv-note">${escapeHtml(col.title)}</div>` : ''}
      <div class="deriv-note">The platform computes this on request rather than
        storing it, so it moves when what it is built from moves. The step-by-step
        working for this particular column has not been wired up yet — if you need
        it, say so and it will be.</div>`);
  }

  tbody.addEventListener('dblclick', e => {
    const td = e.target.closest('td.cell');
    if (td) beginEdit(td);
  });

  tbody.addEventListener('keydown', e => {
    const td = e.target.closest('td');
    if (!td || editing) return;
    const col = columns[td.dataset.c];
    const row = rows[td.dataset.r];

    const r = Number(td.dataset.r), c = Number(td.dataset.c);
    const mod = e.ctrlKey || e.metaKey;

    // Shift+arrows grow the selection; a bare arrow moves and resets it.
    if (e.shiftKey && e.key.startsWith('Arrow')) {
      e.preventDefault();
      if (!selection) setAnchor(td);
      const d = { ArrowUp: [-1, 0], ArrowDown: [1, 0],
                  ArrowLeft: [0, -1], ArrowRight: [0, 1] }[e.key];
      extendTo(selection.fr + d[0], selection.fc + d[1]);
      return;
    }
    if (mod) {
      switch (e.key.toLowerCase()) {
        case 'c': e.preventDefault(); copySelection(); return;
        case 'd': e.preventDefault(); fill('down'); return;
        case 'r': e.preventDefault(); fill('right'); return;
        case 'a':
          e.preventDefault();
          selection = { ar: 0, ac: 0, fr: rows.length - 1, fc: columns.length - 1 };
          paint();
          return;
        case 'home': {
          e.preventDefault();
          const first = cellAt(0, 0); if (first) { first.focus(); setAnchor(first); }
          return;
        }
        case 'end': {
          e.preventDefault();
          const last = cellAt(rows.length - 1, columns.length - 1);
          if (last) { last.focus(); setAnchor(last); }
          return;
        }
      }
    }

    switch (e.key) {
      case 'Escape':     selection = null; paint(); return;
      case 'ArrowUp':    e.preventDefault(); setAnchor(td); move(td, -1, 0); return;
      case 'ArrowDown':  e.preventDefault(); setAnchor(td); move(td, 1, 0);  return;
      case 'ArrowLeft':  e.preventDefault(); setAnchor(td); move(td, 0, -1); return;
      case 'ArrowRight': e.preventDefault(); setAnchor(td); move(td, 0, 1);  return;
      case 'Tab': {
        const next = nextEditable(td, e.shiftKey ? -1 : 1);
        if (next) { e.preventDefault(); next.focus(); }
        return;
      }
      case 'Enter':
        e.preventDefault();
        if (col.kind === 'input' || col.kind === 'select') beginEdit(td);
        else if (col.kind === 'derived') explain(row, col, td);
        return;
      case 'Delete':
      case 'Backspace': {
        e.preventDefault();
        const b = selection ? bounds(selection) : { r0: r, r1: r, c0: c, c1: c };
        const edits = [];
        for (let rr = b.r0; rr <= b.r1; rr++) {
          for (let cc = b.c0; cc <= b.c1; cc++) {
            const cl = columns[cc];
            if (cl.kind !== 'input') continue;
            const before = valueOf(rows[rr], cl);
            const blank = cl.nullable ? null : 0;
            if (before === blank) continue;
            edits.push({ row: rows[rr], col: cl, value: blank, before });
          }
        }
        if (edits.length) commitMany(edits, 'Cleared');
        return;
      }
    }

    if (e.key === 'z' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); undo(); return; }
    // Type over a cell to replace it, as a spreadsheet does.
    if (col.kind === 'input' && e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      beginEdit(td, e.key);
    }
  });

  // Paste a block straight out of Excel. Without this the grid is a toy: a QS
  // pastes a column of areas, not thirty individual numbers.
  tbody.addEventListener('paste', async e => {
    const td = e.target.closest('td.cell');
    if (!td || editing) return;
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text');
    const block = text.replace(/\r/g, '').replace(/\n$/, '')
      .split('\n').map(line => line.split('\t'));

    const r0 = Number(td.dataset.r), c0 = Number(td.dataset.c);
    const edits = [];
    const single = block.length === 1 && block[0].length === 1;

    if (single && selection && (selection.ar !== selection.fr || selection.ac !== selection.fc)) {
      // One value pasted over a range fills it, as Excel does.
      const b = bounds(selection);
      for (let r = b.r0; r <= b.r1; r++) {
        for (let c = b.c0; c <= b.c1; c++) {
          const col = columns[c];
          if (col.kind !== 'input') continue;
          edits.push({ row: rows[r], col, value: parse(block[0][0], col),
                       before: valueOf(rows[r], col) });
        }
      }
    } else {
      block.forEach((line, dr) => line.forEach((cellText, dc) => {
        const row = rows[r0 + dr], col = columns[c0 + dc];
        if (!row || !col || col.kind !== 'input') return;
        edits.push({ row, col, value: parse(cellText, col), before: valueOf(row, col) });
      }));
    }

    if (!edits.length) {
      toast('Nothing in the clipboard landed on an editable cell', true);
      return;
    }
    await commitMany(edits, 'Pasted');
  });

  async function undo() {
    const last = undoStack.pop();
    if (!last) { toast('Nothing to undo'); return; }
    rememberFocus();
    try {
      await onCommit(last.row, last.col, last.value);
      if (config.reload) await config.reload();
      toast('Undone');
    } catch (err) { toast(err.message, true); }
  }

  function rememberFocus() {
    const td = tbody.querySelector('td:focus') ||
      (selection ? cellAt(selection.fr, selection.fc) : null);
    if (td) pendingFocus = { r: Number(td.dataset.r), c: Number(td.dataset.c) };
  }

  function restoreFocus() {
    if (!pendingFocus) return;
    const td = cellAt(pendingFocus.r, pendingFocus.c);
    if (!td) return;                      // a different grid on the same screen
    pendingFocus = null;
    td.focus({ preventScroll: true });
    setAnchor(td);
  }

  // Repainting after a redraw, so a selection survives a reload.
  const drawAndPaint = () => { draw(); paint(); };

  async function removeRow(row) {
    if (!config.onDelete) return;
    const name = config.rowName ? config.rowName(row) : 'this row';
    // Ask first, and let the caller's endpoint be the one that refuses when
    // something still points at the record.
    if (!window.confirm(`Delete ${name}?`)) return;
    try {
      const result = await config.onDelete(row);
      if (config.reload) await config.reload();
      const removed = result && result.removed
        ? Object.entries(result.removed).map(([k, n]) => `${n} ${k}`).join(', ')
        : 'deleted';
      toast(`Removed: ${removed}`);
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function addRow() {
    if (!config.onAdd) return;
    try {
      await config.onAdd();
      if (config.reload) await config.reload();
      toast(config.addedMessage || 'Row added');
    } catch (err) {
      toast(err.message, true);
    }
  }

  draw();
  wrap.appendChild(table);
  host.appendChild(wrap);
  restoreFocus();

  // The shortcuts live under the grid they belong to. A spreadsheet's
  // keyboard is muscle memory; this says which of it works here.
  if (columns.some(c => c.kind === 'input') && config.shortcuts !== false) {
    const help = document.createElement('div');
    help.className = 'grid-help';
    help.innerHTML = [
      ['Select a block', 'drag, or <kbd>Shift</kbd>+arrows'],
      ['Copy to Excel', '<kbd>Ctrl</kbd>+<kbd>C</kbd>'],
      ['Paste from Excel', '<kbd>Ctrl</kbd>+<kbd>V</kbd>'],
      ['Fill down / right', '<kbd>Ctrl</kbd>+<kbd>D</kbd> / <kbd>Ctrl</kbd>+<kbd>R</kbd>'],
      ['Clear', '<kbd>Delete</kbd>'],
      ['Undo', '<kbd>Ctrl</kbd>+<kbd>Z</kbd>'],
    ].map(([what, keys]) => `<span>${what} ${keys}</span>`).join('');
    host.appendChild(help);
  }

  if (config.onAdd) {
    const bar = document.createElement('div');
    bar.className = 'grid-actions';
    bar.innerHTML = `<button class="btn" id="addRow">+ ${
      escapeHtml(config.addLabel || 'Add row')}</button>`;
    bar.querySelector('#addRow').onclick = addRow;
    host.appendChild(bar);
  }

  return { element: wrap, redraw: drawAndPaint, undo, addRow, copySelection };
}
