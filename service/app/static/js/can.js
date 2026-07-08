// CAN console: databases (DBC), message browser, decode, encode, and send.
(function () {
  const $ = (id) => document.getElementById(id);
  const j = (r) => r.json();
  let databases = [];
  let selectedDbId = null;
  let encMessages = {};   // message name -> {arbitration_id, signals:[{name,definition}]}

  function hexToInt(s) {
    s = (s || '').trim();
    if (!s) return NaN;
    return s.toLowerCase().startsWith('0x') ? parseInt(s, 16) : parseInt(s, s.match(/[a-f]/i) ? 16 : 10);
  }

  async function loadInterfaces() {
    try {
      const d = await fetch('can/interfaces').then(j);
      $('interfaces').innerHTML = (d.interfaces || []).map((i) =>
        `<span class="badge iface-pill ${i.available ? 'text-bg-success' : 'text-bg-secondary'}">${i.channel}: ${i.available ? 'live' : 'no bus'}</span>`).join('');
    } catch (e) { /* ignore */ }
    try {
      const a = await fetch('can/dbc/available').then(j);
      if (!a.available) $('cantools-warn').classList.remove('d-none');
    } catch (e) { /* ignore */ }
  }

  function vehicle(d) {
    return [d.year, d.make, d.model].filter(Boolean).join(' ') || '—';
  }

  async function loadDatabases() {
    databases = (await fetch('can/databases').then(j)).databases || [];
    const body = $('db-list');
    if (!databases.length) {
      body.innerHTML = '<tr><td colspan="5" class="text-secondary">No databases yet. Upload a DBC or import opendbc.</td></tr>';
    } else {
      body.innerHTML = databases.map((d) => `
        <tr class="db-row" data-id="${d.id}">
          <td>${esc(d.name)}</td><td class="small">${esc(vehicle(d))}</td>
          <td><span class="badge text-bg-secondary">${esc(d.license || '?')}</span></td>
          <td>${d.message_count}</td>
          <td><button class="btn btn-sm btn-outline-danger py-0 del" data-id="${d.id}">&times;</button></td>
        </tr>`).join('');
    }
    // Populate decode/encode database selects.
    const opts = databases.map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('');
    $('dec-db').innerHTML = opts;
    $('enc-db').innerHTML = opts;
    document.querySelectorAll('.db-row').forEach((r) =>
      r.addEventListener('click', (e) => { if (!e.target.classList.contains('del')) selectDb(+r.dataset.id); }));
    document.querySelectorAll('.del').forEach((b) =>
      b.addEventListener('click', async (e) => {
        e.stopPropagation();
        await fetch('can/databases/' + b.dataset.id, { method: 'DELETE' });
        loadDatabases();
      }));
    if (databases.length && $('enc-db').value) loadEncMessages($('enc-db').value);
  }

  async function selectDb(id) {
    selectedDbId = id;
    document.querySelectorAll('.db-row').forEach((r) => r.classList.toggle('active', +r.dataset.id === id));
    const d = await fetch('can/databases/' + id).then(j);
    $('msg-db-name').textContent = d.name;
    $('msg-list').innerHTML = (d.messages || []).map((m) => `
      <details class="mb-1"><summary class="small">
        <span class="mono">0x${m.arbitration_id.toString(16).toUpperCase()}</span> ${esc(m.name)}
        <span class="text-secondary">(${m.signals.length} sig)</span></summary>
        <table class="table table-sm sig-table mb-1"><tbody>
        ${m.signals.map((s) => `<tr><td>${esc(s.name)}</td><td class="text-secondary">${s.definition.length}b @${s.definition.start}, x${s.definition.scale}${s.definition.unit ? ' ' + esc(s.definition.unit) : ''}</td></tr>`).join('')}
        </tbody></table></details>`).join('') || '<div class="text-secondary small">No messages.</div>';
  }

  async function loadEncMessages(dbId) {
    const d = await fetch('can/databases/' + dbId).then(j);
    encMessages = {};
    (d.messages || []).forEach((m) => { encMessages[m.name] = m; });
    $('enc-msg').innerHTML = (d.messages || []).map((m) => `<option value="${esc(m.name)}">${esc(m.name)}</option>`).join('');
    renderEncSignals();
  }

  function renderEncSignals() {
    const m = encMessages[$('enc-msg').value];
    if (!m) { $('enc-signals').innerHTML = ''; return; }
    $('enc-signals').innerHTML = m.signals.map((s) => `
      <div class="col-6"><label class="form-label small mb-0">${esc(s.name)}${s.definition.unit ? ' (' + esc(s.definition.unit) + ')' : ''}</label>
      <input class="form-control form-control-sm sig-in" data-name="${esc(s.name)}" value="0"></div>`).join('');
  }

  function collectEncSignals() {
    const out = {};
    document.querySelectorAll('#enc-signals .sig-in').forEach((el) => {
      const v = parseFloat(el.value);
      out[el.dataset.name] = isNaN(v) ? el.value : v;
    });
    return out;
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

  // --- actions ---
  $('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = $('dbc-file').files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    fd.append('name', file.name.replace(/\.dbc$/i, ''));
    fd.append('source', 'upload');
    const r = await fetch('can/dbc/import', { method: 'POST', body: fd });
    const d = await r.json();
    $('db-status').innerHTML = r.ok ? '<span class="result-ok">Imported ' + esc(d.database.name) + '</span>'
      : '<span class="result-err">' + esc(d.detail || 'Import failed') + '</span>';
    loadDatabases();
  });

  $('import-opendbc').addEventListener('click', async () => {
    $('db-status').textContent = 'Importing opendbc (this can take a minute)…';
    const r = await fetch('can/dbc/import-directory', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: '/app/data/opendbc-src/opendbc/dbc', source: 'opendbc', license: 'MIT' }),
    });
    const d = await r.json();
    if (d.ok) $('db-status').innerHTML = `<span class="result-ok">Imported ${d.imported} databases (${d.failed} failed).</span>`;
    else $('db-status').innerHTML = `<span class="result-err">${esc(d.error || 'Import failed')}. Run scripts/import-opendbc.sh on the device first.</span>`;
    loadDatabases();
  });

  $('dec-go').addEventListener('click', async () => {
    const id = hexToInt($('dec-id').value);
    if (isNaN(id) || !$('dec-db').value) return;
    const r = await fetch('can/decode', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ database_id: +$('dec-db').value, arbitration_id: id, data: $('dec-data').value }),
    });
    const d = await r.json();
    if (d.ok) {
      $('dec-result').innerHTML = '<table class="table table-sm sig-table"><tbody>' +
        Object.entries(d.signals).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="mono">${esc(v)}</td></tr>`).join('') + '</tbody></table>';
    } else $('dec-result').innerHTML = '<span class="result-err">' + esc(d.detail || 'Decode failed') + '</span>';
  });

  $('enc-db').addEventListener('change', () => loadEncMessages($('enc-db').value));
  $('enc-msg').addEventListener('change', renderEncSignals);

  async function encode() {
    const r = await fetch('can/encode', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ database_id: +$('enc-db').value, message: $('enc-msg').value, signals: collectEncSignals() }),
    });
    return r.json();
  }
  $('enc-go').addEventListener('click', async () => {
    const d = await encode();
    $('enc-result').innerHTML = d.ok ? '<span class="result-ok mono">' + esc(d.hex) + '</span>'
      : '<span class="result-err">' + esc(d.detail || 'Encode failed') + '</span>';
  });
  $('enc-send').addEventListener('click', async () => {
    const e = await encode();
    if (!e.ok) { $('enc-result').innerHTML = '<span class="result-err">' + esc(e.detail || 'Encode failed') + '</span>'; return; }
    const m = encMessages[$('enc-msg').value];
    const r = await fetch('can/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel: $('enc-ch').value, arbitration_id: '0x' + m.arbitration_id.toString(16), data: e.hex, is_fd: m.is_fd }),
    });
    const d = await r.json();
    $('enc-result').innerHTML = '<span class="' + (d.ok ? 'result-ok' : 'result-err') + '">' + esc(d.message) + '</span>';
  });

  $('raw-go').addEventListener('click', async () => {
    const r = await fetch('can/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel: $('raw-ch').value, arbitration_id: $('raw-id').value, data: $('raw-data').value, is_fd: $('raw-fd').checked }),
    });
    const d = await r.json();
    $('raw-result').innerHTML = '<span class="' + (d.ok ? 'result-ok' : 'result-err') + '">' + esc(d.message || (d.ok ? 'Sent' : 'Failed')) + '</span>';
  });

  loadInterfaces();
  loadDatabases();
})();
