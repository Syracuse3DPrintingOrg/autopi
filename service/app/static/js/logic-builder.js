// Visual builder for logic rules (AutoPi-49q): point-and-click WHEN/THEN
// automation on top of the pure engine in app/logic. Two headline flows:
// "when this CAN signal crosses a value, drive this output" and "when this
// input pin goes high, send this CAN command." No-ops if the page has none
// of the builder's containers, so it is safe to include anywhere.
(function () {
  const inputsList = document.getElementById('lb-inputs-list');
  const rulesList = document.getElementById('lb-rules-list');
  if (!inputsList || !rulesList) return;

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]
  ));

  let inputsCfg = [];      // [{name, type, ...}]
  let rules = [];          // [{id, name, condition, actions, trigger, enabled}]
  let actionsCache = [];   // [{id, label, driver, ...}]
  let canDatabases = [];   // [{id, name, ...}]
  const canDbDetailCache = {}; // database_id -> {messages: [...]}

  function autoId(prefix) {
    return prefix + '_' + Math.random().toString(36).slice(2, 8);
  }

  function parseVal(raw) {
    const s = String(raw == null ? '' : raw).trim();
    if (s === '') return '';
    try { return JSON.parse(s); } catch (err) { return s; }
  }

  // --- loading ---------------------------------------------------------

  function loadAll() {
    Promise.all([
      fetch('logic/runtime').then((r) => r.json()),
      fetch('logic/rules').then((r) => r.json()),
      fetch('actions').then((r) => r.json()),
      fetch('can/databases').then((r) => r.json()).catch(() => ({ databases: [] })),
    ]).then(([rt, rl, ac, db]) => {
      inputsCfg = (rt.config && rt.config.inputs) || [];
      rules = rl.rules || [];
      actionsCache = ac.actions || [];
      canDatabases = db.databases || [];
      renderInputsList();
      renderRulesList();
      refreshKnownInputsDatalist();
    }).catch(() => {
      inputsList.innerHTML = '<div class="text-secondary small">Logic API unavailable.</div>';
      rulesList.innerHTML = '<div class="text-secondary small">Logic API unavailable.</div>';
    });
  }

  function refreshKnownInputsDatalist() {
    const dl = document.getElementById('lb-known-inputs');
    if (!dl) return;
    dl.innerHTML = inputsCfg.map((i) => `<option value="${esc(i.name)}">`).join('');
  }

  function canDbDetail(databaseId) {
    if (canDbDetailCache[databaseId]) return Promise.resolve(canDbDetailCache[databaseId]);
    return fetch(`can/databases/${databaseId}`).then((r) => r.json()).then((d) => {
      canDbDetailCache[databaseId] = d;
      return d;
    });
  }

  // --- inputs (WHAT a condition can look at) ----------------------------

  function describeInput(i) {
    if (i.type === 'constant') return `constant = ${JSON.stringify(i.value)}`;
    if (i.type === 'gpio') return `GPIO pin ${i.pin}`;
    if (i.type === 'can_signal') return `CAN ${i.message || '?'}.${i.signal || '?'} on ${i.channel || 'can0'}`;
    return i.type;
  }

  function renderInputsList() {
    if (!inputsCfg.length) {
      inputsList.innerHTML = '<div class="text-secondary small">No inputs defined yet. Add one to give a rule something to read.</div>';
      return;
    }
    inputsList.innerHTML = inputsCfg.map((i, idx) => `
      <div class="lb-row d-flex justify-content-between align-items-center">
        <div>
          <strong class="small">${esc(i.name)}</strong>
          <span class="text-secondary small mono ms-2">${esc(describeInput(i))}</span>
        </div>
        <div class="btn-group btn-group-sm">
          <button type="button" class="btn btn-outline-secondary" data-lb-edit-input="${idx}"><i class="bi bi-pencil"></i></button>
          <button type="button" class="btn btn-outline-danger" data-lb-del-input="${idx}"><i class="bi bi-trash"></i></button>
        </div>
      </div>`).join('');
    inputsList.querySelectorAll('[data-lb-edit-input]').forEach((btn) => {
      btn.addEventListener('click', () => openInputForm(Number(btn.dataset.lbEditInput)));
    });
    inputsList.querySelectorAll('[data-lb-del-input]').forEach((btn) => {
      btn.addEventListener('click', () => {
        inputsCfg.splice(Number(btn.dataset.lbDelInput), 1);
        saveInputs();
      });
    });
  }

  function saveInputs() {
    return fetch('logic/runtime', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs: inputsCfg }),
    }).then(() => { renderInputsList(); refreshKnownInputsDatalist(); });
  }

  const inputForm = document.getElementById('lb-input-form');
  const inputAddBtn = document.getElementById('lb-input-add-btn');

  function inputFieldsHtml(type, seed) {
    seed = seed || {};
    if (type === 'constant') {
      return `<div class="mb-2"><label class="form-label small mb-0">Value</label>
        <input class="form-control form-control-sm" id="lb-in-value" value="${esc(seed.value)}"
          placeholder="e.g. 1, true, or a number">
        <div class="form-text">Fixed value, handy for testing a rule before real hardware is wired up.</div></div>`;
    }
    if (type === 'gpio') {
      return `<div class="mb-2"><label class="form-label small mb-0">BCM pin</label>
        <input type="number" class="form-control form-control-sm" id="lb-in-pin" value="${esc(seed.pin != null ? seed.pin : '')}"></div>`;
    }
    // can_signal
    const dbOptions = canDatabases.map((d) => `<option value="${d.id}" ${seed.database_id === d.id ? 'selected' : ''}>${esc(d.name)}</option>`).join('');
    return `
      <div class="mb-2"><label class="form-label small mb-0">CAN database</label>
        <select class="form-select form-select-sm" id="lb-in-db"><option value="">Select a database…</option>${dbOptions}</select></div>
      <div class="mb-2"><label class="form-label small mb-0">Message</label>
        <select class="form-select form-select-sm" id="lb-in-msg"><option value="">Select the database first…</option></select></div>
      <div class="mb-2"><label class="form-label small mb-0">Signal</label>
        <select class="form-select form-select-sm" id="lb-in-sig"><option value="">Select the message first…</option></select></div>
      <div class="row g-2 mb-2">
        <div class="col"><label class="form-label small mb-0">Interface</label>
          <input class="form-control form-control-sm" id="lb-in-chan" value="${esc(seed.channel || 'can0')}"></div>
        <div class="col"><label class="form-label small mb-0">Backend</label>
          <input class="form-control form-control-sm" id="lb-in-backend" value="${esc(seed.backend || 'socketcan')}"></div>
      </div>`;
  }

  function wireCanSignalFields(seed) {
    seed = seed || {};
    const dbSel = document.getElementById('lb-in-db');
    const msgSel = document.getElementById('lb-in-msg');
    const sigSel = document.getElementById('lb-in-sig');
    if (!dbSel) return;

    function loadMessages(databaseId, preselectMessage, preselectSignal) {
      if (!databaseId) {
        msgSel.innerHTML = '<option value="">Select the database first…</option>';
        sigSel.innerHTML = '<option value="">Select the message first…</option>';
        return;
      }
      canDbDetail(databaseId).then((d) => {
        const messages = d.messages || [];
        msgSel.innerHTML = '<option value="">Select a message…</option>' + messages.map((m) =>
          `<option value="${esc(m.name)}" ${m.name === preselectMessage ? 'selected' : ''}>${esc(m.name)}</option>`).join('');
        const msg = messages.find((m) => m.name === (msgSel.value || preselectMessage));
        loadSignals(msg, preselectSignal);
      });
    }
    function loadSignals(msg, preselectSignal) {
      const signals = (msg && msg.signals) || [];
      sigSel.innerHTML = signals.length
        ? '<option value="">Select a signal…</option>' + signals.map((s) =>
            `<option value="${esc(s.name)}" ${s.name === preselectSignal ? 'selected' : ''}>${esc(s.name)}</option>`).join('')
        : '<option value="">No signals in this message</option>';
    }
    dbSel.addEventListener('change', () => loadMessages(dbSel.value ? Number(dbSel.value) : null, null, null));
    msgSel.addEventListener('change', () => {
      canDbDetail(Number(dbSel.value)).then((d) => {
        const msg = (d.messages || []).find((m) => m.name === msgSel.value);
        loadSignals(msg, null);
      });
    });
    if (seed.database_id) loadMessages(seed.database_id, seed.message, seed.signal);
  }

  function openInputForm(editIdx) {
    const seed = editIdx != null ? inputsCfg[editIdx] : {};
    const type = seed.type || 'constant';
    inputForm.classList.remove('d-none');
    inputForm.innerHTML = `
      <div class="row g-2 mb-2">
        <div class="col"><label class="form-label small mb-0">Name</label>
          <input class="form-control form-control-sm" id="lb-in-name" value="${esc(seed.name || '')}" placeholder="e.g. vehicle_speed"></div>
        <div class="col"><label class="form-label small mb-0">Source</label>
          <select class="form-select form-select-sm" id="lb-in-type">
            <option value="constant" ${type === 'constant' ? 'selected' : ''}>Constant</option>
            <option value="gpio" ${type === 'gpio' ? 'selected' : ''}>GPIO pin</option>
            <option value="can_signal" ${type === 'can_signal' ? 'selected' : ''}>CAN signal</option>
          </select></div>
      </div>
      <div id="lb-in-fields">${inputFieldsHtml(type, seed)}</div>
      <div class="d-flex gap-2 mt-2">
        <button type="button" class="btn btn-sm btn-primary" id="lb-in-save">Save input</button>
        <button type="button" class="btn btn-sm btn-outline-secondary" id="lb-in-cancel">Cancel</button>
      </div>`;
    if (type === 'can_signal') wireCanSignalFields(seed);

    document.getElementById('lb-in-type').addEventListener('change', (e) => {
      document.getElementById('lb-in-fields').innerHTML = inputFieldsHtml(e.target.value, {});
      if (e.target.value === 'can_signal') wireCanSignalFields({});
    });
    document.getElementById('lb-in-cancel').addEventListener('click', () => inputForm.classList.add('d-none'));
    document.getElementById('lb-in-save').addEventListener('click', () => {
      const name = document.getElementById('lb-in-name').value.trim();
      if (!name) { alert('Give the input a name.'); return; }
      const chosenType = document.getElementById('lb-in-type').value;
      let spec = { name, type: chosenType };
      if (chosenType === 'constant') {
        spec.value = parseVal(document.getElementById('lb-in-value').value);
      } else if (chosenType === 'gpio') {
        spec.pin = Number(document.getElementById('lb-in-pin').value || 0);
      } else {
        const dbSel = document.getElementById('lb-in-db');
        spec.database_id = dbSel.value ? Number(dbSel.value) : null;
        spec.message = document.getElementById('lb-in-msg').value;
        spec.signal = document.getElementById('lb-in-sig').value;
        spec.channel = document.getElementById('lb-in-chan').value || 'can0';
        spec.backend = document.getElementById('lb-in-backend').value || 'socketcan';
      }
      if (editIdx != null) inputsCfg[editIdx] = spec;
      else inputsCfg.push(spec);
      inputForm.classList.add('d-none');
      saveInputs();
    });
  }
  inputAddBtn.addEventListener('click', () => openInputForm(null));

  // --- condition builder -------------------------------------------------

  const CONDITION_LABELS = {
    compare: 'Compare to a value', bool: 'On / off', edge: 'Edge (rising/falling)',
    timer: 'On/off-delay timer', latch: 'Set-reset latch',
  };

  function signalPicker(id, value) {
    return `<input class="form-control form-control-sm" id="${id}" list="lb-known-inputs"
      value="${esc(value || '')}" placeholder="input name">`;
  }

  function mountCompare(div, seed) {
    seed = seed || {};
    div.innerHTML = `
      <div class="row g-2">
        <div class="col-5"><label class="form-label small mb-0">Input</label>${signalPicker('c-signal-' + div.dataset.cid, seed.signal)}</div>
        <div class="col-3"><label class="form-label small mb-0">Op</label>
          <select class="form-select form-select-sm" id="c-op-${div.dataset.cid}">
            ${['==', '!=', '<', '<=', '>', '>='].map((op) => `<option ${op === (seed.op || '==') ? 'selected' : ''}>${op}</option>`).join('')}
          </select></div>
        <div class="col-4"><label class="form-label small mb-0">Value</label>
          <input class="form-control form-control-sm" id="c-val-${div.dataset.cid}" value="${esc(seed.value != null ? seed.value : '')}"></div>
      </div>`;
    return () => ({
      type: 'compare',
      signal: document.getElementById('c-signal-' + div.dataset.cid).value.trim(),
      op: document.getElementById('c-op-' + div.dataset.cid).value,
      value: parseVal(document.getElementById('c-val-' + div.dataset.cid).value),
    });
  }

  function mountBool(div, seed) {
    seed = seed || {};
    div.innerHTML = `
      <div class="row g-2 align-items-end">
        <div class="col-8"><label class="form-label small mb-0">Input</label>${signalPicker('c-signal-' + div.dataset.cid, seed.signal)}</div>
        <div class="col-4 form-check ms-2">
          <input class="form-check-input" type="checkbox" id="c-neg-${div.dataset.cid}" ${seed.negate ? 'checked' : ''}>
          <label class="form-check-label small" for="c-neg-${div.dataset.cid}">Invert (fire when off)</label>
        </div>
      </div>`;
    return () => ({
      type: 'bool',
      signal: document.getElementById('c-signal-' + div.dataset.cid).value.trim(),
      negate: document.getElementById('c-neg-' + div.dataset.cid).checked,
    });
  }

  function mountEdge(div, seed) {
    seed = seed || {};
    div.innerHTML = `
      <div class="row g-2">
        <div class="col-6"><label class="form-label small mb-0">Input</label>${signalPicker('c-signal-' + div.dataset.cid, seed.signal)}</div>
        <div class="col-6"><label class="form-label small mb-0">Direction</label>
          <select class="form-select form-select-sm" id="c-edge-${div.dataset.cid}">
            <option value="rising" ${(seed.edge || 'rising') === 'rising' ? 'selected' : ''}>Rising (off to on)</option>
            <option value="falling" ${seed.edge === 'falling' ? 'selected' : ''}>Falling (on to off)</option>
          </select></div>
      </div>`;
    const id = seed.id || autoId('edge');
    return () => ({
      type: 'edge', id,
      signal: document.getElementById('c-signal-' + div.dataset.cid).value.trim(),
      edge: document.getElementById('c-edge-' + div.dataset.cid).value,
    });
  }

  function mountTimer(div, seed) {
    seed = seed || {};
    div.innerHTML = `
      <div class="row g-2 mb-2">
        <div class="col-6"><label class="form-label small mb-0">Mode</label>
          <select class="form-select form-select-sm" id="c-mode-${div.dataset.cid}">
            <option value="TON" ${(seed.mode || 'TON') === 'TON' ? 'selected' : ''}>On-delay (TON): true this long after the input goes true</option>
            <option value="TOF" ${seed.mode === 'TOF' ? 'selected' : ''}>Off-delay (TOF): stays true this long after the input goes false</option>
          </select></div>
        <div class="col-6"><label class="form-label small mb-0">Duration (seconds)</label>
          <input type="number" step="0.1" class="form-control form-control-sm" id="c-dur-${div.dataset.cid}" value="${seed.duration != null ? seed.duration : 5}"></div>
      </div>
      <label class="form-label small mb-0">When</label>
      <div id="c-inner-${div.dataset.cid}"></div>`;
    const id = seed.id || autoId('timer');
    const inner = mountCondition(document.getElementById('c-inner-' + div.dataset.cid), seed.input, ['compare', 'bool']);
    return () => ({
      type: 'timer', id,
      mode: document.getElementById('c-mode-' + div.dataset.cid).value,
      duration: parseFloat(document.getElementById('c-dur-' + div.dataset.cid).value || '0'),
      input: inner.getValue(),
    });
  }

  function mountLatch(div, seed) {
    seed = seed || {};
    div.innerHTML = `
      <div class="mb-2"><label class="form-label small mb-0">Tie</label>
        <select class="form-select form-select-sm" id="c-kind-${div.dataset.cid}">
          <option value="set_dominant" ${(seed.kind || 'set_dominant') === 'set_dominant' ? 'selected' : ''}>Set wins (SR)</option>
          <option value="reset_dominant" ${seed.kind === 'reset_dominant' ? 'selected' : ''}>Reset wins (RS)</option>
        </select></div>
      <label class="form-label small mb-0">Set when</label>
      <div id="c-set-${div.dataset.cid}"></div>
      <label class="form-label small mb-0 mt-2">Reset when</label>
      <div id="c-reset-${div.dataset.cid}"></div>`;
    const id = seed.id || autoId('latch');
    const setMount = mountCondition(document.getElementById('c-set-' + div.dataset.cid), seed.set, ['compare', 'bool']);
    const resetMount = mountCondition(document.getElementById('c-reset-' + div.dataset.cid), seed.reset, ['compare', 'bool']);
    return () => ({
      type: 'latch', id,
      kind: document.getElementById('c-kind-' + div.dataset.cid).value,
      set: setMount.getValue(),
      reset: resetMount.getValue(),
    });
  }

  let cidCounter = 0;

  function mountCondition(container, initialCond, allowedTypes) {
    initialCond = initialCond && initialCond.type ? initialCond : { type: allowedTypes[0] };
    const wrap = document.createElement('div');
    wrap.className = 'lb-cond-box';
    const typeSel = document.createElement('select');
    typeSel.className = 'form-select form-select-sm mb-2';
    allowedTypes.forEach((t) => {
      const o = document.createElement('option');
      o.value = t; o.textContent = CONDITION_LABELS[t] || t;
      typeSel.appendChild(o);
    });
    typeSel.value = allowedTypes.includes(initialCond.type) ? initialCond.type : allowedTypes[0];
    const fieldsDiv = document.createElement('div');
    fieldsDiv.dataset.cid = String(cidCounter++);
    wrap.appendChild(typeSel);
    wrap.appendChild(fieldsDiv);
    container.innerHTML = '';
    container.appendChild(wrap);

    let currentGetter = () => ({ type: typeSel.value });

    function mount(type, seed) {
      fieldsDiv.dataset.cid = fieldsDiv.dataset.cid || String(cidCounter++);
      if (type === 'compare') currentGetter = mountCompare(fieldsDiv, seed);
      else if (type === 'bool') currentGetter = mountBool(fieldsDiv, seed);
      else if (type === 'edge') currentGetter = mountEdge(fieldsDiv, seed);
      else if (type === 'timer') currentGetter = mountTimer(fieldsDiv, seed);
      else if (type === 'latch') currentGetter = mountLatch(fieldsDiv, seed);
    }
    mount(typeSel.value, typeSel.value === initialCond.type ? initialCond : {});
    typeSel.addEventListener('change', () => mount(typeSel.value, {}));

    return { getValue: () => currentGetter() };
  }

  function describeCondition(cond) {
    if (!cond) return '';
    if (cond.type === 'compare') return `${cond.signal} ${cond.op} ${JSON.stringify(cond.value)}`;
    if (cond.type === 'bool') return `${cond.negate ? 'not ' : ''}${cond.signal}`;
    if (cond.type === 'edge') return `${cond.signal} ${cond.edge} edge`;
    if (cond.type === 'timer') return `${cond.mode} ${cond.duration}s (${describeCondition(cond.input)})`;
    if (cond.type === 'latch') return `latch set(${describeCondition(cond.set)}) reset(${describeCondition(cond.reset)})`;
    return cond.type || '';
  }

  // --- rules -------------------------------------------------------------

  function actionLabel(id) {
    const a = actionsCache.find((x) => x.id === id);
    return a ? `${a.label || a.id} (${a.driver})` : id;
  }

  function renderRulesList() {
    if (!rules.length) {
      rulesList.innerHTML = '<div class="text-secondary small">No rules defined yet.</div>';
      return;
    }
    rulesList.innerHTML = rules.map((r, idx) => `
      <div class="lb-row">
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <strong class="small">${esc(r.name || r.id)}</strong>
            <span class="badge ${r.enabled ? 'text-bg-success' : 'text-bg-secondary'} ms-1">${r.enabled ? 'enabled' : 'disabled'}</span>
            <span class="badge text-bg-dark ms-1">${esc(r.trigger || 'level')}</span>
            <div class="text-secondary small mono">WHEN ${esc(describeCondition(r.condition))}</div>
            <div class="text-secondary small">THEN ${(r.actions || []).map(actionLabel).map(esc).join(', ') || '(no actions)'}</div>
          </div>
          <div class="btn-group btn-group-sm">
            <button type="button" class="btn btn-outline-secondary" data-lb-up="${idx}" ${idx === 0 ? 'disabled' : ''}><i class="bi bi-arrow-up"></i></button>
            <button type="button" class="btn btn-outline-secondary" data-lb-down="${idx}" ${idx === rules.length - 1 ? 'disabled' : ''}><i class="bi bi-arrow-down"></i></button>
            <button type="button" class="btn btn-outline-secondary" data-lb-toggle="${idx}"><i class="bi bi-power"></i></button>
            <button type="button" class="btn btn-outline-secondary" data-lb-edit="${idx}"><i class="bi bi-pencil"></i></button>
            <button type="button" class="btn btn-outline-danger" data-lb-del="${idx}"><i class="bi bi-trash"></i></button>
          </div>
        </div>
      </div>`).join('');

    rulesList.querySelectorAll('[data-lb-up]').forEach((btn) => btn.addEventListener('click', () => {
      const i = Number(btn.dataset.lbUp);
      [rules[i - 1], rules[i]] = [rules[i], rules[i - 1]];
      saveRules();
    }));
    rulesList.querySelectorAll('[data-lb-down]').forEach((btn) => btn.addEventListener('click', () => {
      const i = Number(btn.dataset.lbDown);
      [rules[i + 1], rules[i]] = [rules[i], rules[i + 1]];
      saveRules();
    }));
    rulesList.querySelectorAll('[data-lb-toggle]').forEach((btn) => btn.addEventListener('click', () => {
      const i = Number(btn.dataset.lbToggle);
      rules[i].enabled = !rules[i].enabled;
      saveRules();
    }));
    rulesList.querySelectorAll('[data-lb-edit]').forEach((btn) => btn.addEventListener('click', () => openRuleForm(Number(btn.dataset.lbEdit))));
    rulesList.querySelectorAll('[data-lb-del]').forEach((btn) => btn.addEventListener('click', () => {
      rules.splice(Number(btn.dataset.lbDel), 1);
      saveRules();
    }));
  }

  function saveRules() {
    return fetch('logic/rules', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rules }),
    }).then(() => renderRulesList());
  }

  const ruleForm = document.getElementById('lb-rule-form');
  const ruleAddBtn = document.getElementById('lb-rule-add-btn');

  function openRuleForm(editIdx) {
    const seed = editIdx != null ? rules[editIdx] : { id: autoId('rule'), name: '', condition: {}, actions: [], trigger: 'level', enabled: true };
    ruleForm.classList.remove('d-none');
    const actionRows = actionsCache.map((a) => `
      <div class="form-check">
        <input class="form-check-input" type="checkbox" value="${esc(a.id)}" id="lb-act-${esc(a.id)}"
          ${(seed.actions || []).includes(a.id) ? 'checked' : ''}>
        <label class="form-check-label small" for="lb-act-${esc(a.id)}">${esc(a.label || a.id)} <span class="text-secondary">(${esc(a.driver)})</span></label>
      </div>`).join('');
    ruleForm.innerHTML = `
      <div class="row g-2 mb-2">
        <div class="col"><label class="form-label small mb-0">Name</label>
          <input class="form-control form-control-sm" id="lb-rule-name" value="${esc(seed.name || '')}" placeholder="e.g. Drive fan relay above 90C"></div>
        <div class="col-3"><label class="form-label small mb-0">Fires</label>
          <select class="form-select form-select-sm" id="lb-rule-trigger">
            <option value="level" ${(seed.trigger || 'level') === 'level' ? 'selected' : ''}>Every scan it is true</option>
            <option value="rising" ${seed.trigger === 'rising' ? 'selected' : ''}>Once, when it becomes true</option>
            <option value="falling" ${seed.trigger === 'falling' ? 'selected' : ''}>Once, when it becomes false</option>
          </select></div>
        <div class="col-auto d-flex align-items-end">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="lb-rule-enabled" ${seed.enabled !== false ? 'checked' : ''}>
            <label class="form-check-label small" for="lb-rule-enabled">Enabled</label>
          </div>
        </div>
      </div>
      <div class="mb-2">
        <label class="form-label small mb-0">Condition</label>
        <div class="form-check form-switch mb-1">
          <input class="form-check-input" type="checkbox" id="lb-rule-json-toggle">
          <label class="form-check-label small" for="lb-rule-json-toggle">Edit as raw JSON</label>
        </div>
        <div id="lb-rule-cond"></div>
        <textarea id="lb-rule-json" class="form-control form-control-sm mono d-none" rows="6"></textarea>
      </div>
      <div class="mb-2">
        <label class="form-label small mb-0">Then, run these actions</label>
        <div class="border rounded p-2" style="max-height:10rem;overflow:auto">${actionRows || '<span class="text-secondary small">No actions defined yet. Create one under Actions first.</span>'}</div>
      </div>
      <div class="d-flex gap-2">
        <button type="button" class="btn btn-sm btn-primary" id="lb-rule-save">Save rule</button>
        <button type="button" class="btn btn-sm btn-outline-secondary" id="lb-rule-cancel">Cancel</button>
      </div>`;

    const condMount = mountCondition(document.getElementById('lb-rule-cond'), seed.condition, ['compare', 'bool', 'edge', 'timer', 'latch']);
    const jsonToggle = document.getElementById('lb-rule-json-toggle');
    const jsonArea = document.getElementById('lb-rule-json');
    const condDiv = document.getElementById('lb-rule-cond');
    jsonToggle.addEventListener('change', () => {
      if (jsonToggle.checked) {
        jsonArea.value = JSON.stringify(condMount.getValue(), null, 2);
        condDiv.classList.add('d-none');
        jsonArea.classList.remove('d-none');
      } else {
        condDiv.classList.remove('d-none');
        jsonArea.classList.add('d-none');
      }
    });

    document.getElementById('lb-rule-cancel').addEventListener('click', () => ruleForm.classList.add('d-none'));
    document.getElementById('lb-rule-save').addEventListener('click', () => {
      let condition;
      if (jsonToggle.checked) {
        try { condition = JSON.parse(jsonArea.value); } catch (err) { alert('That condition is not valid JSON.'); return; }
      } else {
        condition = condMount.getValue();
      }
      const checkedActions = Array.from(ruleForm.querySelectorAll('.form-check-input[id^="lb-act-"]:checked')).map((el) => el.value);
      const rule = {
        id: seed.id,
        name: document.getElementById('lb-rule-name').value.trim(),
        condition,
        actions: checkedActions,
        trigger: document.getElementById('lb-rule-trigger').value,
        enabled: document.getElementById('lb-rule-enabled').checked,
      };
      if (editIdx != null) rules[editIdx] = rule;
      else rules.push(rule);
      ruleForm.classList.add('d-none');
      saveRules();
    });
  }
  ruleAddBtn.addEventListener('click', () => openRuleForm(null));

  loadAll();
})();
