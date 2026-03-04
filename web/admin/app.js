const $ = (id) => document.getElementById(id);

function setActivePanel(panelId) {
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.panel === panelId);
  });
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('active', p.id === panelId);
  });
}

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => setActivePanel(btn.dataset.panel));
});

async function api(path, opts = {}) {
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`${resp.status} ${txt}`);
  }
  return await resp.json();
}

function fmtTs(ts) {
  if (!ts) return '-';
  const n = Number(ts);
  if (Number.isNaN(n)) return String(ts);
  const d = new Date(n * 1000);
  return d.toLocaleString();
}

async function loadOverview() {
  const data = await api('/v1/admin/overview');
  const cards = [
    ['Files', data.knowledge_db.files],
    ['Chunks', data.knowledge_db.chunks],
    ['Tags', data.knowledge_db.tags],
    ['FileTags', data.knowledge_db.file_tags],
    ['Diaries', data.knowledge_db.diaries],
    ['Events', data.observability.events],
    ['JSONL Files', data.observability.jsonl_files],
  ];
  $('overviewCards').innerHTML = cards.map(([k, v]) => `
    <div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>
  `).join('');
}

async function loadLogs() {
  const limit = Number($('logLimit').value || 100);
  const endpoint = $('logEndpoint').value;
  const status = $('logStatus').value;
  const params = new URLSearchParams({ limit: String(limit) });
  if (endpoint) params.set('endpoint', endpoint);
  if (status) params.set('status', status);

  const data = await api(`/v1/admin/logs/recent?${params.toString()}`);
  const tbody = $('logsBody');
  tbody.innerHTML = '';
  $('logDetailsPanel').classList.add('hidden');
  $('logDetailsHint').classList.remove('hidden');

  const showLogDetails = (item) => {
    $('logDetailsPanel').classList.remove('hidden');
    $('logDetailsHint').classList.add('hidden');
    $('logSummary').textContent = JSON.stringify({
      request_id: item.request_id,
      endpoint: item.endpoint,
      timestamp: item.timestamp_iso || item.ts,
      message: item.message,
      diary_name: item.diary_name,
      history_size: item.history_size,
      use_rerank: item.use_rerank,
      result_count: item.result_count,
      search_vector_count: item.search_vector_count,
      cache_hit: item.cache_hit,
      latency_ms: item.latency_ms,
      duration_ms: item.duration_ms,
      status: item.status,
      error: item.error,
    }, null, 2);
    $('logMetrics').textContent = JSON.stringify(item.metrics || {}, null, 2);
    $('logResults').textContent = JSON.stringify(item.results || [], null, 2);
    $('logMemoryContext').textContent = item.memory_context || '';
    $('logRaw').textContent = JSON.stringify(item, null, 2);
  };

  data.items.forEach(item => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.timestamp_iso || fmtTs(item.ts)}</td>
      <td>${item.endpoint}</td>
      <td>${(item.message || '').slice(0, 80)}</td>
      <td>${item.diary_name || ''}</td>
      <td>${item.result_count ?? ''}</td>
      <td>${item.duration_ms?.toFixed?.(2) ?? item.duration_ms ?? ''}</td>
      <td>${item.status}</td>
    `;
    tr.addEventListener('click', () => showLogDetails(item));
    tbody.appendChild(tr);
  });
}

async function loadTables() {
  const source = $('dbSource').value;
  const data = await api(`/v1/admin/db/tables?source=${source}`);
  const sel = $('dbTable');
  sel.innerHTML = data.tables.map(t => `<option value="${t}">${t}</option>`).join('');
}

async function loadTableData() {
  const source = $('dbSource').value;
  const table = $('dbTable').value;
  if (!table) return;

  const page = Number($('dbPage').value || 1);
  const pageSize = Number($('dbPageSize').value || 50);
  const search = $('dbSearch').value || '';

  const params = new URLSearchParams({
    source,
    page: String(page),
    page_size: String(pageSize),
    search,
  });

  const data = await api(`/v1/admin/db/table/${encodeURIComponent(table)}?${params.toString()}`);
  $('dbMeta').textContent = `total=${data.total}, page=${data.page}, pageSize=${data.page_size}`;

  const head = `<thead><tr>${data.columns.map(c => `<th>${c}</th>`).join('')}</tr></thead>`;
  const body = `<tbody>${data.rows.map(r => `<tr>${data.columns.map(c => `<td>${String(r[c] ?? '').slice(0, 500)}</td>`).join('')}</tr>`).join('')}</tbody>`;
  $('dbTableWrap').innerHTML = `<table>${head}${body}</table>`;
}

let latestDiaryList = [];

async function loadDiaries() {
  const data = await api('/v1/admin/diaries');
  latestDiaryList = data.items || [];
  const tbody = $('diaryBody');
  const fileSel = $('diaryFileSelect');
  tbody.innerHTML = '';
  fileSel.innerHTML = '';

  latestDiaryList.forEach(item => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${item.diary_name}</td><td>${item.file_count}</td><td>${fmtTs(item.last_seen)}</td>`;
    tr.addEventListener('click', () => loadDiaryFiles(item.diary_name));
    tbody.appendChild(tr);
  });
}

async function loadDiaryFiles(diaryName) {
  const data = await api(`/v1/admin/diaries/files?diary_name=${encodeURIComponent(diaryName)}`);
  $('diaryFileSelect').innerHTML = (data.items || []).map(f => `<option value="${f.path}">${f.path}</option>`).join('');
}

async function loadDiaryContent() {
  const path = $('diaryFileSelect').value;
  if (!path) return;
  const data = await api(`/v1/admin/diaries/content?path=${encodeURIComponent(path)}`);
  $('diaryContent').textContent = data.content || '';
}

async function runMemoryPreview() {
  const body = {
    message: $('memoryMessage').value,
    diaryName: $('memoryDiary').value || null,
    history: [],
  };
  const data = await api('/v1/admin/memory/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  $('memoryMetrics').textContent = JSON.stringify(data.metrics || {}, null, 2);
  $('memoryContext').textContent = data.memory_context || '';
  $('memoryResults').textContent = JSON.stringify(data.results || [], null, 2);
}

$('refreshLogs').addEventListener('click', () => loadLogs().catch(e => alert(e.message)));
$('logEndpoint').addEventListener('change', () => loadLogs().catch(e => alert(e.message)));
$('logStatus').addEventListener('change', () => loadLogs().catch(e => alert(e.message)));
$('logLimit').addEventListener('change', () => loadLogs().catch(e => alert(e.message)));
$('dbSource').addEventListener('change', () => loadTables().then(loadTableData).catch(e => alert(e.message)));
$('dbTable').addEventListener('change', () => loadTableData().catch(e => alert(e.message)));
$('dbPage').addEventListener('change', () => loadTableData().catch(e => alert(e.message)));
$('dbPageSize').addEventListener('change', () => loadTableData().catch(e => alert(e.message)));
$('dbSearch').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    $('dbPage').value = '1';
    loadTableData().catch(err => alert(err.message));
  }
});
$('loadTable').addEventListener('click', () => loadTableData().catch(e => alert(e.message)));
$('refreshDiaries').addEventListener('click', () => loadDiaries().catch(e => alert(e.message)));
$('loadDiaryFile').addEventListener('click', () => loadDiaryContent().catch(e => alert(e.message)));
$('runMemoryPreview').addEventListener('click', () => runMemoryPreview().catch(e => alert(e.message)));

(async function boot() {
  await loadOverview();
  await loadLogs();
  await loadTables();
  await loadTableData();
  await loadDiaries();
})().catch(e => {
  console.error(e);
  alert(e.message);
});
