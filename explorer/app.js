/* Kagaj explorer — browse and query datasets/kagaj.sqlite in the browser.
   No backend: sql.js runs SQLite as WebAssembly against one fetched file. */

'use strict';

const CDN = 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.15.2/';
const DB_GZ = '../output/explorer/kagaj.sqlite.gz';
const DB_PLAIN = '../output/explorer/kagaj.sqlite';
const MAX_CUSTOM_ROWS = 1000;

const state = {
  db: null,
  catalog: [],
  tables: [],
  dataset: null,
  openDataset: null,
  table: null,
  columns: [],
  filters: [],
  sort: null,
  page: 0,
  pageSize: 100,
  sql: '',
  last: null,
};

const $ = (id) => document.getElementById(id);

/* ── boot ──────────────────────────────────────────────────── */

async function boot() {
  try {
    setOverlay('loading sql.js…');
    if (typeof initSqlJs !== 'function') throw { code: 'cdn' };
    const SQL = await initSqlJs({ locateFile: (file) => CDN + file });

    setOverlay('fetching kagaj.sqlite…');
    const loaded = await loadBytes();

    setOverlay('opening database…');
    state.db = new SQL.Database(loaded.bytes);

    state.catalog = rows('SELECT * FROM catalog ORDER BY dataset');
    state.tables = rows('SELECT dataset, tbl, role, rows, description FROM catalog_tables ORDER BY dataset, tbl');

    renderSidebar();
    renderSideFoot(loaded);
    const primary = state.tables.find((entry) => entry.role === 'primary') || state.tables[0];
    if (primary) selectTable(primary.dataset, primary.tbl);
    else throw { code: 'empty' };

    hideOverlay();
  } catch (error) {
    showBootError(error);
  }
}

async function loadBytes() {
  if (typeof DecompressionStream === 'function') {
    try {
      const response = await fetch(DB_GZ);
      if (response.ok) {
        const blob = await response.blob();
        const stream = blob.stream().pipeThrough(new DecompressionStream('gzip'));
        const buffer = await new Response(stream).arrayBuffer();
        return { bytes: new Uint8Array(buffer), size: blob.size, gz: true };
      }
      if (response.status !== 404) throw new Error('gzip fetch failed');
    } catch (error) {
      /* fall through to the uncompressed file */
    }
  }
  const response = await fetch(DB_PLAIN);
  if (!response.ok) throw { code: 'missing' };
  const buffer = await response.arrayBuffer();
  return { bytes: new Uint8Array(buffer), size: buffer.byteLength, gz: false };
}

function showBootError(error) {
  const text = $('overlay-text');
  text.classList.add('is-error');
  const messages = {
    cdn: 'sql.js could not be loaded from the CDN — check your connection, then reload.',
    missing: 'Database not found. Build it first:\npython datasets/build_sqlite.py\nthen serve the repo root:\npython -m http.server  →  /explorer/',
    empty: 'The database has no tables. Rebuild it: python datasets/build_sqlite.py',
  };
  if (error && error.code && messages[error.code]) {
    text.textContent = messages[error.code];
  } else if (location.protocol === 'file:') {
    text.textContent = 'Open this page over HTTP, not file://\npython -m http.server  →  http://localhost:8000/explorer/';
  } else {
    text.textContent = 'Could not open the database: ' + (error && error.message ? error.message : error);
  }
  document.querySelector('.overlay-bar').style.display = 'none';
}

/* ── sql helpers ───────────────────────────────────────────── */

function query(sql, params = []) {
  const stmt = state.db.prepare(sql);
  try {
    stmt.bind(params);
    const columns = stmt.getColumnNames();
    const values = [];
    while (stmt.step()) values.push(stmt.get());
    return { columns, values };
  } finally {
    stmt.free();
  }
}

function rows(sql, params = []) {
  const result = query(sql, params);
  return result.values.map((row) =>
    Object.fromEntries(result.columns.map((column, i) => [column, row[i]]))
  );
}

function quote(identifier) {
  return '"' + String(identifier).replace(/"/g, '""') + '"';
}

function tableInfo(table) {
  return query(`PRAGMA table_info(${quote(table)})`).values.map((row) => ({
    name: row[1],
    type: String(row[2] || 'TEXT').toUpperCase(),
  }));
}

/* ── query building ────────────────────────────────────────── */

function filterClause() {
  const clauses = [];
  const params = [];
  for (const filter of state.filters) {
    const column = quote(filter.col);
    switch (filter.op) {
      case 'is null':
        clauses.push(`${column} IS NULL`);
        break;
      case 'is not null':
        clauses.push(`${column} IS NOT NULL`);
        break;
      case 'contains':
        clauses.push(`${column} LIKE ?`);
        params.push(`%${filter.value}%`);
        break;
      case 'starts':
        clauses.push(`${column} LIKE ?`);
        params.push(`${filter.value}%`);
        break;
      default:
        clauses.push(`${column} ${filter.op} ?`);
        params.push(filter.value);
    }
  }
  return { where: clauses.length ? ' WHERE ' + clauses.join(' AND ') : '', params };
}

function browseSql() {
  const { where, params } = filterClause();
  let sql = `SELECT * FROM ${quote(state.table)}${where}`;
  if (state.sort) sql += ` ORDER BY ${quote(state.sort.col)} ${state.sort.dir}`;
  return { sql, params };
}

function assertReadOnly(sql) {
  const stripped = sql.trim().replace(/--[^\n]*/g, '').trim();
  if (!stripped) return;
  if (!/^(select|with|explain)\b/i.test(stripped)) {
    throw new Error('Read-only: only SELECT / WITH / EXPLAIN statements are allowed.');
  }
  if (stripped.replace(/;\s*$/, '').includes(';')) {
    throw new Error('One statement at a time.');
  }
}

/* ── running queries ───────────────────────────────────────── */

function run() {
  if (!state.table && !state.sql) return;
  const status = $('status-line');
  status.classList.remove('error');
  const started = performance.now();
  try {
    if (state.sql) {
      assertReadOnly(state.sql);
      const result = query(state.sql);
      const elapsed = Math.round(performance.now() - started);
      state.last = {
        columns: result.columns,
        values: result.values,
        types: inferTypes(result),
        elapsed,
        truncated: result.values.length > MAX_CUSTOM_ROWS,
      };
      state.page = 0;
      renderGrid();
      const note = state.last.truncated ? ` · first ${MAX_CUSTOM_ROWS} of ${result.values.length} shown` : '';
      status.innerHTML = `<b>${fmt(result.values.length)}</b> rows${note} · <b>${elapsed}</b> ms · custom query`;
      $('pager').hidden = true;
      return;
    }

    const { sql, params } = browseSql();
    const count = query(`SELECT COUNT(*) FROM (${sql})`, params).values[0][0];
    const pageSql = `${sql} LIMIT ? OFFSET ?`;
    const result = query(pageSql, [...params, state.pageSize, state.page * state.pageSize]);
    const elapsed = Math.round(performance.now() - started);

    state.last = {
      columns: result.columns,
      values: result.values,
      types: state.columns.map((column) => column.type),
      elapsed,
      count,
    };
    renderGrid();

    const pages = Math.max(1, Math.ceil(count / state.pageSize));
    const bits = [`<b>${fmt(count)}</b> rows`];
    if (state.filters.length) bits.push(`${state.filters.length} filter${state.filters.length > 1 ? 's' : ''}`);
    if (state.sort) bits.push(`sorted by ${state.sort.col} ${state.sort.dir === 'ASC' ? '↑' : '↓'}`);
    bits.push(`<b>${elapsed}</b> ms`);
    bits.push(`page <b>${state.page + 1}</b>/${fmt(pages)}`);
    status.innerHTML = bits.join(' · ');

    $('pager').hidden = count <= state.pageSize;
    $('page-label').textContent = `page ${state.page + 1} of ${fmt(pages)}`;
    $('page-prev').disabled = state.page === 0;
    $('page-next').disabled = state.page >= pages - 1;
  } catch (error) {
    status.classList.add('error');
    status.textContent = 'error: ' + (error && error.message ? error.message : error);
    state.last = null;
  }
}

function inferTypes(result) {
  return result.columns.map((_, index) => {
    let numeric = 0;
    let seen = 0;
    for (const row of result.values.slice(0, 200)) {
      const value = row[index];
      if (value === null || value === undefined || value === '') continue;
      seen += 1;
      if (typeof value === 'number') numeric += 1;
    }
    return seen > 0 && numeric === seen ? 'REAL' : 'TEXT';
  });
}

function fmt(value) {
  return Number(value).toLocaleString('en-US');
}

/* ── rendering ─────────────────────────────────────────────── */

function renderGrid() {
  const table = $('grid');
  const head = table.querySelector('thead');
  const body = table.querySelector('tbody');
  head.innerHTML = '';
  body.innerHTML = '';
  if (!state.last) return;

  const { columns, values, types } = state.last;

  const headerRow = document.createElement('tr');
  const gutter = document.createElement('th');
  gutter.className = 'gutter';
  gutter.textContent = '#';
  headerRow.appendChild(gutter);

  columns.forEach((column, index) => {
    const th = document.createElement('th');
    th.textContent = column;
    th.title = 'sort by ' + column;
    if (!state.sql) {
      if (state.sort && state.sort.col === column) {
        const arrow = document.createElement('span');
        arrow.className = 'arrow';
        arrow.textContent = state.sort.dir === 'ASC' ? ' ▲' : ' ▼';
        th.appendChild(arrow);
      }
      th.addEventListener('click', () => toggleSort(column));
    } else {
      th.style.cursor = 'default';
    }
    headerRow.appendChild(th);
  });
  head.appendChild(headerRow);

  const offset = state.sql ? 0 : state.page * state.pageSize;
  const fragment = document.createDocumentFragment();
  values.forEach((row, rowIndex) => {
    const tr = document.createElement('tr');

    const gutterCell = document.createElement('td');
    gutterCell.className = 'gutter';
    gutterCell.textContent = fmt(offset + rowIndex + 1);
    tr.appendChild(gutterCell);

    row.forEach((value, columnIndex) => {
      const td = document.createElement('td');
      if (value === null || value === undefined) {
        td.className = 'null';
        td.textContent = '—';
        td.title = 'NULL';
      } else {
        const type = types[columnIndex] || 'TEXT';
        if (type === 'INTEGER' || type === 'REAL') td.className = 'num';
        const text = typeof value === 'number' ? String(value) : String(value);
        td.textContent = text;
        if (text.length > 60) td.title = text;
      }
      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
  body.appendChild(fragment);
}

function toggleSort(column) {
  if (state.sort && state.sort.col === column) {
    state.sort = state.sort.dir === 'ASC' ? { col: column, dir: 'DESC' } : null;
  } else {
    state.sort = { col: column, dir: 'ASC' };
  }
  state.page = 0;
  run();
}

function renderSidebar() {
  const nav = $('dataset-list');
  nav.innerHTML = '';

  for (const dataset of state.catalog) {
    const item = document.createElement('div');
    item.className = 'dataset';
    item.dataset.status = dataset.status;
    if (dataset.dataset === state.dataset) item.classList.add('is-active');
    if (dataset.dataset === state.openDataset) item.classList.add('is-open');

    const title = document.createElement('div');
    title.className = 'dataset-title';
    const dot = document.createElement('span');
    dot.className = 'status-dot';
    title.appendChild(dot);
    title.appendChild(document.createTextNode(dataset.title));
    item.appendChild(title);

    const coverage = document.createElement('div');
    coverage.className = 'dataset-coverage';
    coverage.textContent = `${dataset.coverage_start} → ${dataset.coverage_end}`;
    item.appendChild(coverage);

    const list = document.createElement('div');
    list.className = 'tables';
    const tables = state.tables.filter((entry) => entry.dataset === dataset.dataset);
    if (!tables.length) {
      const hint = document.createElement('div');
      hint.className = 'table-item';
      hint.style.cursor = 'default';
      hint.textContent = 'no tabular tables';
      list.appendChild(hint);
    }
    for (const entry of tables) {
      const row = document.createElement('div');
      row.className = 'table-item';
      if (entry.tbl === state.table) row.classList.add('is-active');
      const name = document.createElement('span');
      name.textContent = entry.tbl;
      const count = document.createElement('span');
      count.className = 'rows';
      count.textContent = fmt(entry.rows);
      row.appendChild(name);
      row.appendChild(count);
      row.addEventListener('click', (event) => {
        event.stopPropagation();
        selectTable(dataset.dataset, entry.tbl);
      });
      list.appendChild(row);
    }
    item.appendChild(list);

    title.addEventListener('click', () => {
      const alreadyOpen = state.openDataset === dataset.dataset;
      state.openDataset = alreadyOpen ? null : dataset.dataset;
      if (alreadyOpen) {
        renderSidebar();
      } else if (tables.length) {
        const preferred = tables.find((entry) => entry.role === 'primary') || tables[0];
        selectTable(dataset.dataset, preferred.tbl);
      } else {
        selectDatasetOnly(dataset.dataset);
      }
    });

    nav.appendChild(item);
  }
}

function renderSideFoot(loaded) {
  const totalTables = state.tables.length;
  const size = (loaded.size / 1e6).toFixed(1) + ' MB';
  const suffix = loaded.gz ? ' gz' : '';
  $('side-foot').innerHTML =
    `<code>kagaj.sqlite</code> · ${size}${suffix} · ${totalTables} tables<br>` +
    'built by <code>python datasets/build_sqlite.py</code>';
  $('db-status').innerHTML = `<b>${state.catalog.length}</b> datasets · <b>${totalTables}</b> tables · ${size}${suffix}`;
}

function renderCard() {
  const dataset = state.catalog.find((entry) => entry.dataset === state.dataset);
  if (!dataset) return;
  $('dataset-card').hidden = false;

  const pill = $('card-status');
  pill.textContent = dataset.status;
  pill.dataset.status = dataset.status;

  $('card-title').textContent = dataset.title;
  $('card-desc').textContent = dataset.description;

  const meta = $('card-meta');
  meta.innerHTML = '';
  const fields = [
    ['grain', dataset.grain],
    ['coverage', `${dataset.coverage_start} → ${dataset.coverage_end}`],
    ['verification', verificationLabel(dataset)],
    ['rebuild', cliLabel(dataset)],
    ['sources', sourceLinks(dataset)],
    ['licence', licenceLabel(dataset)],
  ];
  for (const [label, value] of fields) {
    if (!value) continue;
    const item = document.createElement('div');
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    if (value instanceof Node) dd.appendChild(value);
    else dd.textContent = value;
    item.appendChild(dt);
    item.appendChild(dd);
    meta.appendChild(item);
  }

  const notes = $('card-notes');
  notes.innerHTML = '';
  const list = parseJson(dataset.notes);
  if (list.length) {
    const ul = document.createElement('ul');
    for (const note of list) {
      const li = document.createElement('li');
      li.textContent = note;
      ul.appendChild(li);
    }
    notes.appendChild(ul);
    notes.hidden = false;
  } else {
    notes.hidden = true;
  }
}

function verificationLabel(dataset) {
  const verification = parseJson(dataset.verification);
  if (!verification.status) return null;
  return `${verification.status} — ${verification.method || ''}`.trim();
}

function cliLabel(dataset) {
  const pipeline = parseJson(dataset.pipeline);
  const cli = pipeline.cli;
  if (!cli) return null;
  return Array.isArray(cli) ? cli.join('\n') : cli;
}

function sourceLinks(dataset) {
  const sources = parseJson(dataset.sources);
  if (!sources.length) return null;
  const wrap = document.createDocumentFragment();
  sources.forEach((source, index) => {
    if (index) wrap.appendChild(document.createTextNode(' · '));
    const anchor = document.createElement('a');
    anchor.href = source.url;
    anchor.target = '_blank';
    anchor.rel = 'noopener';
    anchor.textContent = source.name;
    wrap.appendChild(anchor);
  });
  return wrap;
}

function licenceLabel(dataset) {
  const licence = parseJson(dataset.license);
  const code = licence.code || '';
  let data = licence.data || '';
  if (code && data.startsWith(code)) {
    data = data.slice(code.length).replace(/^[;\s—\-–]+/, '');
    if (data) data = data[0].toUpperCase() + data.slice(1);
  }
  return [code, data].filter(Boolean).join(' — ');
}

function parseJson(value) {
  if (!value) return {};
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch (error) {
    return {};
  }
}

/* ── selection ─────────────────────────────────────────────── */

function selectTable(datasetId, table) {
  const changedDataset = state.dataset !== datasetId;
  state.dataset = datasetId;
  state.openDataset = datasetId;
  state.table = table;
  state.columns = tableInfo(table);
  state.filters = [];
  state.sort = null;
  state.page = 0;
  state.sql = '';
  $('sql').value = '';

  if (changedDataset) renderCard();
  renderFilterColumns();
  renderChips();
  renderSidebar();
  run();
}

function selectDatasetOnly(datasetId) {
  state.dataset = datasetId;
  state.table = null;
  state.columns = [];
  state.filters = [];
  state.sort = null;
  state.page = 0;
  state.sql = '';
  state.last = null;
  $('sql').value = '';
  $('filter-column').innerHTML = '';
  renderChips();
  renderCard();
  renderSidebar();
  $('grid').querySelector('thead').innerHTML = '';
  $('grid').querySelector('tbody').innerHTML = '';
  $('pager').hidden = true;
  const status = $('status-line');
  status.classList.remove('error');
  status.innerHTML = 'no tabular tables in this dataset — its files are listed in the catalogue card below';
}

function renderFilterColumns() {
  const select = $('filter-column');
  select.innerHTML = '';
  for (const column of state.columns) {
    const option = document.createElement('option');
    option.value = column.name;
    option.textContent = column.name;
    select.appendChild(option);
  }
}

function renderChips() {
  const wrap = $('filter-chips');
  wrap.innerHTML = '';
  state.filters.forEach((filter, index) => {
    const chip = document.createElement('span');
    chip.className = 'chip';
    const label = filter.op === 'is null' || filter.op === 'is not null'
      ? `${filter.col} ${filter.op}`
      : `${filter.col} ${filter.op} ${filter.value}`;
    chip.appendChild(document.createTextNode(label));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '×';
    remove.title = 'remove filter';
    remove.addEventListener('click', () => {
      state.filters.splice(index, 1);
      state.page = 0;
      renderChips();
      run();
    });
    chip.appendChild(remove);
    wrap.appendChild(chip);
  });
}

/* ── csv export ────────────────────────────────────────────── */

function exportCsv() {
  if (!state.last) return;
  const { columns, values } = state.last;
  if (values.length > 20000 && !window.confirm(`Export ${fmt(values.length)} rows to CSV?`)) return;

  const escape = (value) => {
    if (value === null || value === undefined) return '';
    const text = String(value);
    return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  };

  const lines = [columns.map(escape).join(',')];
  for (const row of values) lines.push(row.map(escape).join(','));
  const blob = new Blob([String.fromCharCode(0xfeff) + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${state.table || 'kagaj'}${state.sql ? '-query' : ''}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

/* ── overlay ───────────────────────────────────────────────── */

function setOverlay(text) {
  $('overlay-text').textContent = text;
}

function hideOverlay() {
  const overlay = $('overlay');
  overlay.classList.add('is-gone');
  setTimeout(() => overlay.remove(), 400);
}

/* ── wiring ────────────────────────────────────────────────── */

function wire() {
  $('filter-add').addEventListener('click', () => {
    const col = $('filter-column').value;
    const op = $('filter-op').value;
    const needsValue = op !== 'is null' && op !== 'is not null';
    const value = $('filter-value').value;
    if (!col) return;
    if (needsValue && value === '') {
      $('filter-value').focus();
      return;
    }
    state.filters.push({ col, op, value });
    $('filter-value').value = '';
    state.page = 0;
    renderChips();
    run();
  });

  $('filter-value').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') $('filter-add').click();
  });

  $('sql-run').addEventListener('click', () => {
    state.sql = $('sql').value.trim();
    state.page = 0;
    run();
  });

  $('sql-clear').addEventListener('click', () => {
    state.sql = '';
    $('sql').value = '';
    state.page = 0;
    run();
  });

  $('sql').addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      $('sql-run').click();
    }
  });

  $('page-size').addEventListener('change', (event) => {
    state.pageSize = Number(event.target.value);
    state.page = 0;
    run();
  });

  $('page-prev').addEventListener('click', () => {
    if (state.page > 0) {
      state.page -= 1;
      run();
    }
  });

  $('page-next').addEventListener('click', () => {
    state.page += 1;
    run();
  });

  $('export-csv').addEventListener('click', exportCsv);
}

wire();
boot();
