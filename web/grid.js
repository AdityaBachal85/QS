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

import { fmt, toast } from './app.js';
import { escapeHtml } from './panel.js';

// The undo stack lives outside any one grid instance. Committing an edit
// reloads the screen -- that is how the recalculation cascade becomes visible --
// which rebuilds the grid from scratch. A stack held inside the instance would
// be thrown away by the very action it needs to record. Entries hold ids, not
// live objects, so they survive the rebuild.
let undoStack = [];
export function clearUndo() { undoStack = []; }

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
    if (col.kind === 'label') return escapeHtml(v ?? '');
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
    else if (col.kind === 'derived') classes.push('derived');
    else if (col.kind === 'delete') classes.push('act');
    else classes.push('cell');
    if (col.kind === 'select') classes.push('sel-cell', 'left');
    if (col.total) classes.push('total');
    if (col.align === 'left') classes.push('left');
    const v = valueOf(row, col);
    if (col.kind !== 'label' && (v === 0 || v === null || v === undefined)) {
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
            tabindex="${col.kind === 'label' || col.kind === 'delete' ? -1 : 0}"
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

  // -- events -------------------------------------------------------------

  tbody.addEventListener('click', async e => {
    const td = e.target.closest('td');
    if (!td || editing) return;
    const col = columns[td.dataset.c];
    const row = rows[td.dataset.r];
    if (e.target.closest('.row-del')) { await removeRow(row); return; }
    if (col.kind === 'select') { beginSelect(td, col); return; }
    if (col.kind === 'derived' && onDerivedClick) onDerivedClick(row, col, td);
  });

  tbody.addEventListener('dblclick', e => {
    const td = e.target.closest('td.cell');
    if (td) beginEdit(td);
  });

  tbody.addEventListener('keydown', e => {
    const td = e.target.closest('td');
    if (!td || editing) return;
    const col = columns[td.dataset.c];
    const row = rows[td.dataset.r];

    switch (e.key) {
      case 'ArrowUp':    e.preventDefault(); move(td, -1, 0); return;
      case 'ArrowDown':  e.preventDefault(); move(td, 1, 0);  return;
      case 'ArrowLeft':  e.preventDefault(); move(td, 0, -1); return;
      case 'ArrowRight': e.preventDefault(); move(td, 0, 1);  return;
      case 'Tab': {
        const next = nextEditable(td, e.shiftKey ? -1 : 1);
        if (next) { e.preventDefault(); next.focus(); }
        return;
      }
      case 'Enter':
        e.preventDefault();
        if (col.kind === 'input' || col.kind === 'select') beginEdit(td);
        else if (col.kind === 'derived' && onDerivedClick) onDerivedClick(row, col, td);
        return;
      case 'Delete':
      case 'Backspace':
        if (col.kind === 'input') {
          e.preventDefault();
          undoStack.push({ row, col, value: valueOf(row, col) });
          apply(row, col, col.nullable ? null : 0, td);
        }
        return;
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
    block.forEach((line, dr) => line.forEach((cellText, dc) => {
      const row = rows[r0 + dr], col = columns[c0 + dc];
      if (!row || !col || col.kind !== 'input') return;
      edits.push({ row, col, value: parse(cellText, col), before: valueOf(row, col) });
    }));

    if (!edits.length) { toast('Nothing in the clipboard landed on an editable cell', true); return; }
    undoStack.push(...edits.map(x => ({ row: x.row, col: x.col, value: x.before })).reverse());

    for (const edit of edits) {
      try { await onCommit(edit.row, edit.col, edit.value); }
      catch (err) { toast(err.message, true); break; }
    }
    if (config.reload) await config.reload();
    toast(`Pasted ${edits.length} cell${edits.length === 1 ? '' : 's'}`);
  });

  async function undo() {
    const last = undoStack.pop();
    if (!last) { toast('Nothing to undo'); return; }
    try {
      await onCommit(last.row, last.col, last.value);
      if (config.reload) await config.reload();
      toast('Undone');
    } catch (err) { toast(err.message, true); }
  }

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

  if (config.onAdd) {
    const bar = document.createElement('div');
    bar.className = 'grid-actions';
    bar.innerHTML = `<button class="btn" id="addRow">+ ${
      escapeHtml(config.addLabel || 'Add row')}</button>`;
    bar.querySelector('#addRow').onclick = addRow;
    host.appendChild(bar);
  }

  return { element: wrap, redraw: draw, undo, addRow };
}
