const $ = (sel) => document.querySelector(sel);

const PROVIDERS = {
  'gmail.com': ['imap.gmail.com', 993],
  'googlemail.com': ['imap.gmail.com', 993],
  'outlook.com': ['outlook.office365.com', 993],
  'hotmail.com': ['outlook.office365.com', 993],
  'live.com': ['outlook.office365.com', 993],
  'live.fr': ['outlook.office365.com', 993],
  'yahoo.com': ['imap.mail.yahoo.com', 993],
  'yahoo.fr': ['imap.mail.yahoo.com', 993],
  'aol.com': ['imap.aol.com', 993],
  'icloud.com': ['imap.mail.me.com', 993],
  'me.com': ['imap.mail.me.com', 993],
};

const FIELDS = [
  ['fromName', 'From Name'],
  ['fromEmail', 'From Email'],
  ['to', 'To'],
  ['cc', 'CC'],
  ['bcc', 'BCC'],
  ['subject', 'Subject'],
  ['date', 'Date'],
  ['messageId', 'Message ID'],
  ['replyTo', 'Reply-To'],
  ['body', 'Body'],
  ['htmlBody', 'HTML'],
  ['textBody', 'Text body'],
  ['attachments', 'Attachments'],
];

let allResults = []; // {row, folder, selected}
let currentFields = [];
let foldersLoaded = false;
let connectedOk = false;
let autoTimer = null;
let busy = false;

function credentials() {
  const email = $('#email').value.trim();
  const password = $('#password').value;
  const host = $('#host').value.trim();
  let port = $('#port').value.trim();
  if (port && !host) port = '';
  return {
    email,
    password,
    host: host || undefined,
    port: port ? parseInt(port, 10) : undefined,
  };
}

function providerFor(email) {
  const domain = (email.split('@')[1] || '').toLowerCase();
  const p = PROVIDERS[domain];
  return p ? { name: domain.split('.')[0], host: p[0], port: p[1] } : null;
}

function detectProvider() {
  const p = providerFor($('#email').value);
  if (p && !$('#host').value) {
    $('#providerTag').textContent = p.name + ' detected';
  } else if ($('#host').value) {
    $('#providerTag').textContent = 'Custom IMAP';
  } else {
    $('#providerTag').textContent = 'Provider auto-detected';
  }
}

function showErr(el, msg) { el.textContent = msg; el.classList.remove('hidden'); }
function hidel(el) { el.classList.add('hidden'); }
function toast(msg, type = 'ok') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast ' + type;
  clearTimeout(t._tm);
  t._tm = setTimeout(() => t.classList.add('hidden'), 3500);
}

async function jpost(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok && data.error) throw new Error(data.error);
  return data;
}

// ---------- Section 1: connection ----------
let providerTouched = false;
$('#email').addEventListener('input', detectProvider);
$('#email').addEventListener('change', () => {
  const p = providerFor($('#email').value);
  if (p && !$('#host').value && !providerTouched) {
    $('#host').value = p.host;
    $('#port').value = p.port;
    $('#providerTag').textContent = p.name + ' filled in';
  }
});
$('#host').addEventListener('input', () => { providerTouched = $('#host').value !== ''; });

$('#testBtn').addEventListener('click', async () => {
  const c = credentials();
  if (!c.email || !c.password) { showErr($('#mailboxError'), 'Enter email and password first.'); return; }
  $('#testBtn').disabled = true;
  $('#testBtn').textContent = 'Testing…';
  hidel($('#mailboxSuccess'));
  try {
    const r = await jpost('/api/test-connection', c);
    if (r.success) {
      connectedOk = true;
      hidel($('#mailboxError'));
      $('#mailboxSuccess').textContent = `✓ Connected (${r.provider}). Click "Load folders".`;
      $('#mailboxSuccess').classList.remove('hidden');
      $('#loadFoldersBtn').disabled = false;
    } else {
      connectedOk = false;
      showErr($('#mailboxError'), r.error || 'Connection failed.');
      hidel($('#mailboxSuccess'));
      $('#loadFoldersBtn').disabled = true;
    }
  } catch (e) {
    connectedOk = false;
    showErr($('#mailboxError'), e.message);
    hidel($('#mailboxSuccess'));
  } finally {
    $('#testBtn').disabled = false;
    $('#testBtn').textContent = 'Test connection';
  }
});

// ---------- Section 2: folders ----------
$('#loadFoldersBtn').addEventListener('click', async () => {
  const c = credentials();
  if (!c.email || !c.password) { showErr($('#mailboxError'), 'Enter email and password first.'); return; }
  $('#loadFoldersBtn').disabled = true;
  $('#loadFoldersBtn').textContent = 'Loading…';
  hidel($('#mailboxError'));
  try {
    const r = await jpost('/api/folders', c);
    renderFolders(r.folders || []);
    foldersLoaded = true;
    $('#mailboxSuccess').textContent = `✓ Loaded ${(r.folders || []).length} folders.`;
    $('#mailboxSuccess').classList.remove('hidden');
    updateExtractState();
  } catch (e) {
    showErr($('#mailboxError'), e.message);
  } finally {
    $('#loadFoldersBtn').disabled = false;
    $('#loadFoldersBtn').textContent = 'Load folders';
  }
});

function renderFolders(folders) {
  const list = $('#folderList');
  list.innerHTML = '';
  folders.forEach((f) => {
    const label = document.createElement('label');
    label.className = 'folder-item';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = f.path;
    cb.className = 'folder-cb';
    cb.addEventListener('change', updateExtractState);
    const name = document.createElement('span');
    name.textContent = f.name;
    const cnt = document.createElement('span');
    cnt.className = 'count';
    cnt.textContent = f.count || '';
    label.append(cb, name, cnt);
    list.appendChild(label);
  });
  $('#folderSearch').addEventListener('input', (e) => {
    const q = (e.target.value || '').toLowerCase();
    list.querySelectorAll('.folder-item').forEach((li) => {
      const show = li.textContent.toLowerCase().includes(q);
      li.style.display = show ? 'flex' : 'none';
    });
  });
}

function selectedFolders() {
  return Array.from(document.querySelectorAll('.folder-cb:checked')).map((cb) => cb.value);
}

// ---------- Section 3: fields ----------
$('#toggleFields').addEventListener('click', () => {
  const all = document.querySelectorAll('.field-item input');
  const checked = all.length && all[0].checked;
  all.forEach((cb) => { cb.checked = !checked; });
  updateFields();
});
function renderFields() {
  const list = $('#fieldList');
  list.innerHTML = '';
  FIELDS.forEach(([key, label]) => {
    const item = document.createElement('label');
    item.className = 'field-item';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = key;
    cb.checked = ['fromEmail', 'subject', 'fromName', 'date'].includes(key);
    cb.addEventListener('change', updateFields);
    const span = document.createElement('span');
    span.textContent = label;
    item.append(cb, span);
    list.appendChild(item);
  });
}
function updateFields() {
  currentFields = Array.from(document.querySelectorAll('.field-item input:checked')).map((cb) => cb.value);
}
renderFields();
updateFields();

// ---------- Section 4: range + extract ----------
function updateExtractState() {
  const ready = connectedOk && selectedFolders().length > 0;
  $('#extractBtn').disabled = !ready;
}

async function runExtraction() {
  if (busy) return;
  const c = credentials();
  if (!c.email || !c.password) return;
  const folders = selectedFolders();
  if (!folders.length) return;
  busy = true;
  $('#extractBtn').disabled = true;
  $('#progressError').classList.add('hidden');
  setProgress(0, 'Connecting to mailbox…');
  const body = {
    email: c.email, password: c.password, host: c.host, port: c.port,
    folders,
    startFrom: parseInt($('#startFrom').value || '1', 10),
    count: parseInt($('#count').value || '100', 10),
    fields: currentFields.length ? currentFields : ['fromEmail', 'subject', 'fromName', 'date'],
  };
  const t0 = Date.now();
  try {
    setProgress(20, 'Extracting emails…');
    const r = await jpost('/api/extract', body);
    if (r.error) throw new Error(r.error);
    addResults(r.results || [], body.folders);
    const s = r.stats || {};
    setProgress(100, `Done in ${((Date.now() - t0) / 1000).toFixed(1)}s — ${s.found} found, ${s.errors} errors.`);
    if (s.errors > 0) showErr($('#progressError'), `${s.errors} message(s) could not be parsed and were skipped.`);
  } catch (e) {
    showErr($('#progressError'), e.message);
    setProgress(0, 'Extraction failed.');
  } finally {
    busy = false;
    $('#extractBtn').disabled = !(connectedOk && selectedFolders().length > 0);
  }
}

function setProgress(pct, text) {
  $('#progressFill').style.width = pct + '%';
  $('#progressText').textContent = text;
}

$('#extractBtn').addEventListener('click', runExtraction);

// ---------- Results table ----------
function addResults(rows, folderLabel) {
  let added = 0;
  rows.forEach((row) => {
    if (row.messageId && allResults.some((x) => x.row.messageId === row.messageId)) return; // dedupe on add
    allResults.push({ row, folder: folderLabel, selected: false, addedAt: Date.now() });
    added++;
  });
  if (added) {
    toast(`+${added} new email${added === 1 ? '' : 's'} added`);
    renderStats();
    renderTable();
  } else {
    toast('No new emails found.');
  }
}

let sortKey = 'uid';
let sortDir = 1;
function renderTable() {
  const rows = filteredRows();
  const head = $('#tableHead');
  const body = $('#tableBody');
  head.innerHTML = '';
  body.innerHTML = '';
  $('#emptyState').style.display = rows.length ? 'none' : 'block';

  const cols = [
    ['_sel', '☑'], ['_row', '#'], ['folder', 'Category'], ...currentFields.map((f) => [f, fieldLabel(f)]),
  ];
  const htr = document.createElement('tr');
  cols.forEach(([key, label]) => {
    const th = document.createElement('th');
    th.textContent = label;
    if (key !== '_sel') {
      th.addEventListener('click', () => {
        if (sortKey === key) sortDir *= -1; else { sortKey = key; sortDir = 1; }
        renderTable();
      });
      th.style.cursor = 'pointer';
      if (sortKey === key) th.textContent = label + (sortDir === 1 ? ' ↑' : ' ↓');
    }
    htr.appendChild(th);
  });
  head.appendChild(htr);

  rows.forEach((item, idx) => {
    const r = item.row;
    const tr = document.createElement('tr');
    if (item.selected) tr.classList.add('selected');
    const cbTd = document.createElement('td');
    cbTd.className = 'narrow';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = item.selected;
    cb.addEventListener('change', () => { item.selected = cb.checked; tr.classList.toggle('selected'); renderStats(); });
    cbTd.appendChild(cb);
    tr.appendChild(cbTd);

    const numTd = document.createElement('td');
    numTd.className = 'narrow';
    numTd.textContent = (idx + 1).toString();
    tr.appendChild(numTd);

    const folderTd = document.createElement('td');
    const chip = document.createElement('span');
    chip.className = 'chip folder-chip';
    chip.textContent = item.folder;
    folderTd.appendChild(chip);
    tr.appendChild(folderTd);

    currentFields.forEach((f) => {
      const td = document.createElement('td');
      const v = r[f];
      if (f === 'attachments' && Array.isArray(v)) {
        td.textContent = (v || []).join(', ');
      } else if (f === 'htmlBody' && typeof v === 'string') {
        td.textContent = truncate(stripTags(v), 200);
        td.title = stripTags(v);
      } else if (typeof v === 'string') {
        td.textContent = truncate(v, 200);
        if (v.length > 200) td.title = v;
      } else {
        td.textContent = v ?? '';
      }
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
  renderStats();
}

function fieldLabel(key) {
  const f = FIELDS.find(([k]) => k === key);
  return f ? f[1] : key;
}
function truncate(s, n) { return s.length > n ? s.slice(0, n) + '…' : s; }
function stripTags(h) { const d = document.createElement('div'); d.innerHTML = h; return (d.textContent || '').replace(/\s+/g, ' ').trim(); }

let tableQ = '';
$('#tableSearch').addEventListener('input', (e) => { tableQ = (e.target.value || '').toLowerCase(); renderTable(); });
function filteredRows() {
  let rows = [...allResults];
  if (tableQ) {
    rows = rows.filter((it) => currentFields.some((f) => {
      const v = it.row[f];
      return typeof v === 'string' && v.toLowerCase().includes(tableQ);
    }));
  }
  if (sortKey && sortKey !== '_sel') {
    rows.sort((a, b) => {
      let va = a.row[sortKey]; let vb = b.row[sortKey];
      if (va == null) va = ''; if (vb == null) vb = '';
      if (Array.isArray(vb)) vb = vb.join(', '); if (Array.isArray(va)) va = va.join(', ');
      const cmp = String(va).localeCompare(String(vb));
      return cmp * sortDir;
    });
  }
  return rows;
}

function renderStats() {
  const selected = allResults.filter((x) => x.selected).length;
  const sizes = new Set(allResults.map((x) => x.row.fromEmail || '').filter(Boolean));
  const dupes = allResults.length - sizes.size;
  $('#statFound').textContent = allResults.length;
  $('#statSelected').textContent = selected;
  $('#statDupes').textContent = dupes;
  $('#folderCount').textContent = allResults.length + ' total';
}

// ---------- Toolbar actions ----------
$('#copyEmailsBtn').addEventListener('click', async () => {
  const sel = allResults.filter((x) => x.selected && x.row.fromEmail);
  const list = sel.length ? sel : allResults.filter((x) => x.row.fromEmail);
  const text = [...new Set(list.map((x) => x.row.fromEmail).filter(Boolean))].join('\n');
  await copyText(text || 'No emails found.');
});
$('#copyAllBtn').addEventListener('click', async () => {
  const rows = filteredRows();
  const text = rows.map((x) => JSON.stringify(x.row)).join('\n');
  await copyText(text || 'No results.');
});
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('Copied to clipboard.'); }
  catch { toast('Copy failed.', 'err'); }
}

$('#removeDupesBtn').addEventListener('click', () => {
  const seen = new Set();
  allResults = allResults.filter((x) => {
    const k = x.row.messageId || x.row.fromEmail || JSON.stringify(x.row);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  toast('Duplicates removed.');
  renderTable();
});

$('#exportCsvBtn').addEventListener('click', () => exportData('csv'));
$('#exportJsonBtn').addEventListener('click', () => exportData('json'));
async function exportData(fmt) {
  const rows = filteredRows().map((x) => x.row);
  if (!rows.length) { toast('Nothing to export.', 'err'); return; }
  try {
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: rows, format: fmt }),
    });
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'extraction.' + (fmt === 'csv' ? 'csv' : 'json');
    a.click();
    URL.revokeObjectURL(a.href);
    toast('Export downloaded.');
  } catch (e) {
    toast('Export failed: ' + e.message, 'err');
  }
}

// ---------- Auto refresh ----------
$('#refreshBtn').addEventListener('click', () => { if (!busy) runExtraction(); });
$('#autoRefresh').addEventListener('change', (e) => {
  clearInterval(autoTimer);
  if (e.target.checked && selectedFolders().length) {
    autoTimer = setInterval(() => { if (!busy && connectedOk && selectedFolders().length) runExtraction(); }, 30000);
    toast('Auto-check on (every 30s).');
  } else {
    if (e.target.checked) toast('Load folders to enable auto-check.', 'err');
  }
});

detectProvider();
updateExtractState();
renderStats();
