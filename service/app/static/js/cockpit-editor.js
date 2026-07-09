// Cockpit editor: pick or create a cockpit, upload its background image,
// place key/gauge/indicator elements on it by dragging, and bind each one to
// an action or a CAN signal. Talks to the /cockpit REST API in service/app/
// routers/cockpit.py.
(() => {
  const state = {
    cockpits: [],
    cockpit: null,      // the currently loaded cockpit record
    actions: [],
    databases: [],
    selectedId: null,
    dragging: null,      // {elementId, startX, startY, origX, origY}
  };

  const $ = (sel) => document.querySelector(sel);
  const fCockpit = $('#f-cockpit');
  const canvasWrap = $('#canvas-wrap');
  const canvasEmpty = $('#canvas-empty');
  const panel = $('#element-panel');
  const btnOpenOperate = $('#btn-open-operate');

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`${res.status}: ${text}`);
    }
    return res.status === 204 ? null : res.json();
  }

  async function loadLookups() {
    try {
      const [a, d] = await Promise.all([
        api('actions'),
        api('can/databases'),
      ]);
      state.actions = a.actions || [];
      state.databases = d.databases || [];
    } catch (e) {
      state.actions = [];
      state.databases = [];
    }
  }

  async function loadCockpits(selectId) {
    const data = await api('cockpit');
    state.cockpits = data.cockpits || [];
    fCockpit.innerHTML = '';
    for (const c of state.cockpits) {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = c.name || `Cockpit ${c.id}`;
      fCockpit.appendChild(opt);
    }
    const target = selectId != null ? selectId : (state.cockpits[0] && state.cockpits[0].id);
    if (target != null) {
      fCockpit.value = target;
      await selectCockpit(target);
    } else {
      state.cockpit = null;
      renderCanvas();
      renderPanel();
    }
  }

  async function selectCockpit(id) {
    state.cockpit = await api(`cockpit/${id}`);
    state.selectedId = null;
    btnOpenOperate.href = `ui/cockpit/${id}`;
    renderCanvas();
    renderPanel();
  }

  function renderCanvas() {
    canvasWrap.querySelectorAll('.cp-el, .cp-canvas-img').forEach((el) => el.remove());
    const cockpit = state.cockpit;
    if (!cockpit) {
      canvasEmpty.style.display = 'flex';
      return;
    }
    if (cockpit.image_filename) {
      canvasEmpty.style.display = 'none';
      const img = document.createElement('img');
      img.className = 'cp-canvas-img';
      img.src = `cockpit/${cockpit.id}/image?t=${Date.now()}`;
      canvasWrap.appendChild(img);
    } else {
      canvasEmpty.style.display = 'flex';
    }
    for (const el of cockpit.elements || []) {
      canvasWrap.appendChild(buildElementNode(el));
    }
  }

  function buildElementNode(el) {
    const node = document.createElement('div');
    node.className = `cp-el type-${el.type}` + (el.id === state.selectedId ? ' selected' : '');
    node.style.left = `${el.x * 100}%`;
    node.style.top = `${el.y * 100}%`;
    node.style.width = `${el.w * 100}%`;
    node.style.height = `${el.h * 100}%`;
    node.style.background = el.color || '#334155';
    node.dataset.id = el.id;
    const label = document.createElement('span');
    label.className = 'cp-el-label';
    label.textContent = el.label || el.type;
    node.appendChild(label);
    node.addEventListener('mousedown', (ev) => startDrag(ev, el));
    node.addEventListener('click', (ev) => {
      ev.stopPropagation();
      state.selectedId = el.id;
      renderCanvas();
      renderPanel();
    });
    return node;
  }

  function startDrag(ev, el) {
    ev.preventDefault();
    ev.stopPropagation();
    const rect = canvasWrap.getBoundingClientRect();
    state.dragging = {
      elementId: el.id,
      rect,
      startClientX: ev.clientX,
      startClientY: ev.clientY,
      origX: el.x,
      origY: el.y,
      w: el.w,
      h: el.h,
    };
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup', onDragEnd);
  }

  function onDragMove(ev) {
    const d = state.dragging;
    if (!d) return;
    const dx = (ev.clientX - d.startClientX) / d.rect.width;
    const dy = (ev.clientY - d.startClientY) / d.rect.height;
    let x = Math.min(Math.max(d.origX + dx, 0), Math.max(0, 1 - d.w));
    let y = Math.min(Math.max(d.origY + dy, 0), Math.max(0, 1 - d.h));
    const node = canvasWrap.querySelector(`.cp-el[data-id="${d.elementId}"]`);
    if (node) {
      node.style.left = `${x * 100}%`;
      node.style.top = `${y * 100}%`;
      d.lastX = x;
      d.lastY = y;
    }
  }

  async function onDragEnd() {
    document.removeEventListener('mousemove', onDragMove);
    document.removeEventListener('mouseup', onDragEnd);
    const d = state.dragging;
    state.dragging = null;
    if (!d || d.lastX === undefined) return;
    const el = (state.cockpit.elements || []).find((e) => e.id === d.elementId);
    if (el) {
      el.x = d.lastX;
      el.y = d.lastY;
    }
    await api(`cockpit/${state.cockpit.id}/elements/${d.elementId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x: d.lastX, y: d.lastY }),
    });
  }

  function actionOptions(selected) {
    let html = '<option value="">(none)</option>';
    for (const a of state.actions) {
      if (a.id === 'blank') continue;
      html += `<option value="${a.id}" ${a.id === selected ? 'selected' : ''}>${a.label || a.id}</option>`;
    }
    return html;
  }

  function databaseOptions(selected) {
    let html = '<option value="">(none)</option>';
    for (const d of state.databases) {
      html += `<option value="${d.id}" ${d.id === selected ? 'selected' : ''}>${d.name || `Database ${d.id}`}</option>`;
    }
    return html;
  }

  function renderPanel() {
    const cockpit = state.cockpit;
    const el = cockpit ? (cockpit.elements || []).find((e) => e.id === state.selectedId) : null;
    if (!el) {
      panel.innerHTML = '<p class="text-body-secondary small mb-0">Select an element on the canvas to edit it.</p>';
      return;
    }
    const common = `
      <div class="mb-2">
        <label class="form-label small">Label</label>
        <input type="text" class="form-control form-control-sm" id="p-label" value="${escapeAttr(el.label)}">
      </div>
      <div class="mb-2">
        <label class="form-label small">Color</label>
        <input type="color" class="form-control form-control-sm form-control-color" id="p-color" value="${el.color || '#334155'}">
      </div>
      <div class="row g-2 mb-2">
        <div class="col-6"><label class="form-label small">Width</label>
          <input type="number" step="0.01" min="0.01" max="1" class="form-control form-control-sm" id="p-w" value="${el.w}"></div>
        <div class="col-6"><label class="form-label small">Height</label>
          <input type="number" step="0.01" min="0.01" max="1" class="form-control form-control-sm" id="p-h" value="${el.h}"></div>
      </div>`;

    let bindingHtml = '';
    if (el.type === 'key') {
      bindingHtml = `
        <div class="mb-2">
          <label class="form-label small">Action</label>
          <select class="form-select form-select-sm" id="p-action">${actionOptions(el.action_id)}</select>
        </div>
        <div class="mb-2">
          <label class="form-label small">Try it here</label>
          <div class="d-flex align-items-center gap-2">
            <button class="btn btn-sm btn-outline-success" id="p-test" disabled>
              <i class="bi bi-play-fill me-1"></i>Test key</button>
            <span class="small text-body-secondary" id="p-test-status"></span>
          </div>
        </div>`;
    } else {
      bindingHtml = `
        <div class="mb-2">
          <label class="form-label small">CAN database</label>
          <select class="form-select form-select-sm" id="p-database">${databaseOptions(el.database_id)}</select>
        </div>
        <div class="row g-2 mb-2">
          <div class="col-6"><label class="form-label small">Channel</label>
            <input type="text" class="form-control form-control-sm" id="p-channel" value="${escapeAttr(el.channel)}"></div>
          <div class="col-6"><label class="form-label small">Arbitration id</label>
            <input type="text" class="form-control form-control-sm" id="p-arb" value="${el.arbitration_id != null ? el.arbitration_id : ''}" placeholder="0x201"></div>
        </div>
        <div class="mb-2">
          <label class="form-label small">Signal name</label>
          <input type="text" class="form-control form-control-sm" id="p-signal" list="p-signal-list"
                 autocomplete="off" placeholder="Type to search this database's signals"
                 value="${escapeAttr(el.signal)}">
          <datalist id="p-signal-list"></datalist>
          <div class="form-text" id="p-signal-hint"></div>
        </div>
        <div class="row g-2 mb-2">
          <div class="col-6"><label class="form-label small">Min</label>
            <input type="number" step="any" class="form-control form-control-sm" id="p-min" value="${el.min}"></div>
          <div class="col-6"><label class="form-label small">Max</label>
            <input type="number" step="any" class="form-control form-control-sm" id="p-max" value="${el.max}"></div>
        </div>
        <div class="mb-2">
          <label class="form-label small">Unit</label>
          <input type="text" class="form-control form-control-sm" id="p-unit" value="${escapeAttr(el.unit)}">
        </div>`;
      if (el.type === 'gauge') {
        bindingHtml += `
        <div class="mb-2">
          <label class="form-label small">Style</label>
          <select class="form-select form-select-sm" id="p-style">
            <option value="bar" ${el.style === 'bar' ? 'selected' : ''}>Bar</option>
            <option value="numeric" ${el.style === 'numeric' ? 'selected' : ''}>Numeric</option>
          </select>
        </div>`;
      } else {
        bindingHtml += `
        <div class="mb-2">
          <label class="form-label small">On threshold</label>
          <input type="number" step="any" class="form-control form-control-sm" id="p-threshold" value="${el.threshold != null ? el.threshold : ''}">
        </div>`;
      }
    }

    panel.innerHTML = `
      <div class="d-flex align-items-center justify-content-between mb-2">
        <h6 class="mb-0 text-capitalize">${el.type}</h6>
        <button class="btn btn-sm btn-outline-danger" id="p-delete"><i class="bi bi-trash"></i></button>
      </div>
      ${common}
      ${bindingHtml}
      <button class="btn btn-sm btn-primary w-100" id="p-save"><i class="bi bi-check-lg me-1"></i>Save</button>
    `;

    $('#p-save').addEventListener('click', () => savePanel(el));
    $('#p-delete').addEventListener('click', () => deleteElement(el));

    if (el.type === 'key') setupKeyTest(el);

    // For gauges/indicators, turn the signal field into a searchable dropdown of
    // the selected database's signals, and fill in the arbitration id from the
    // signal's message when one is picked.
    if (el.type !== 'key') {
      let signalMap = {};
      const dbSel = $('#p-database');
      const sigInput = $('#p-signal');
      const list = $('#p-signal-list');
      const hint = $('#p-signal-hint');
      const toHex = (n) => '0x' + Number(n).toString(16).toUpperCase();

      async function loadSignals() {
        signalMap = {};
        if (list) list.innerHTML = '';
        const dbId = dbSel && dbSel.value ? parseInt(dbSel.value, 10) : null;
        if (!dbId) { if (hint) hint.textContent = 'Pick a database to list its signals.'; return; }
        try {
          const d = await api('can/databases/' + dbId);
          (d.messages || []).forEach((m) => (m.signals || []).forEach((s) => {
            signalMap[s.name] = { arb: m.arbitration_id, message: m.name };
            if (list) {
              const opt = document.createElement('option');
              opt.value = s.name;
              opt.label = (m.name ? m.name + ' · ' : '') + toHex(m.arbitration_id);
              list.appendChild(opt);
            }
          }));
          const count = Object.keys(signalMap).length;
          if (hint) hint.textContent = count + ' signal' + (count === 1 ? '' : 's') + ' in this database.';
          applySignalInfo();
        } catch (e) { if (hint) hint.textContent = 'Could not load this database\'s signals.'; }
      }

      function applySignalInfo() {
        const info = signalMap[sigInput.value];
        if (info) {
          const arb = $('#p-arb');
          if (arb) arb.value = toHex(info.arb);  // a signal lives in one message
          if (hint) hint.textContent = 'In ' + (info.message || 'message') + ' (' + toHex(info.arb) + ')';
        }
      }

      if (dbSel) dbSel.addEventListener('change', loadSignals);
      if (sigInput) sigInput.addEventListener('change', applySignalInfo);
      loadSignals();
    }
  }

  // Live test control for a key: fire the element's saved action without
  // leaving the editor, through the same /fire endpoint the operate view uses.
  // A periodic (toggle) CAN action renders as an on/off button that reflects
  // the current sending state; anything else fires once per press.
  function setupKeyTest(el) {
    const btn = $('#p-test');
    const status = $('#p-test-status');
    if (!btn || !status) return;
    let isToggle = false;
    let running = false;

    function render() {
      btn.disabled = false;
      if (isToggle && running) {
        btn.className = 'btn btn-sm btn-danger';
        btn.innerHTML = '<i class="bi bi-stop-fill me-1"></i>Turn off';
      } else if (isToggle) {
        btn.className = 'btn btn-sm btn-outline-success';
        btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Turn on';
      } else {
        btn.className = 'btn btn-sm btn-outline-success';
        btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Test key';
      }
    }

    async function load() {
      try {
        const s = await api(`cockpit/${state.cockpit.id}/elements/${el.id}/state`);
        if (!s.bound) {
          btn.disabled = true;
          status.textContent = 'Pick an action and save to test it.';
          return;
        }
        isToggle = !!s.toggle;
        running = !!s.running;
        status.textContent = isToggle ? (running ? 'Sending now.' : 'Not sending.') : '';
        render();
      } catch (e) {
        btn.disabled = true;
        status.textContent = 'Could not read this key\'s state.';
      }
    }

    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const res = await fetch(`cockpit/${state.cockpit.id}/elements/${el.id}/fire`, { method: 'POST' });
        const data = await res.json();
        if (data.data && typeof data.data.periodic === 'boolean') {
          isToggle = true;
          running = data.data.periodic;
        }
        status.textContent = data.message || (data.ok ? 'Done.' : 'That did not work.');
        status.classList.toggle('text-danger', data.ok === false);
      } catch (e) {
        status.textContent = 'Could not run that key.';
        status.classList.add('text-danger');
      }
      render();
    });

    // Changing the dropdown does not retarget the test until saved; make that
    // visible instead of quietly firing the old binding.
    const actionSel = $('#p-action');
    if (actionSel) {
      actionSel.addEventListener('change', () => {
        if ((actionSel.value || null) !== (el.action_id || null)) {
          btn.disabled = true;
          status.classList.remove('text-danger');
          status.textContent = 'Save to test the new action.';
        } else {
          load();
        }
      });
    }

    load();
  }

  function escapeAttr(v) {
    return (v == null ? '' : String(v)).replace(/"/g, '&quot;');
  }

  async function savePanel(el) {
    const patch = {
      label: $('#p-label').value,
      color: $('#p-color').value,
      w: parseFloat($('#p-w').value) || el.w,
      h: parseFloat($('#p-h').value) || el.h,
    };
    if (el.type === 'key') {
      patch.action_id = $('#p-action').value || null;
    } else {
      const dbVal = $('#p-database').value;
      patch.database_id = dbVal ? parseInt(dbVal, 10) : null;
      patch.channel = $('#p-channel').value;
      patch.arbitration_id = $('#p-arb').value || null;
      patch.signal = $('#p-signal').value || null;
      patch.min = parseFloat($('#p-min').value);
      patch.max = parseFloat($('#p-max').value);
      patch.unit = $('#p-unit').value;
      if (el.type === 'gauge') {
        patch.style = $('#p-style').value;
      } else {
        const thr = $('#p-threshold').value;
        patch.threshold = thr === '' ? null : parseFloat(thr);
      }
    }
    await api(`cockpit/${state.cockpit.id}/elements/${el.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    await selectCockpit(state.cockpit.id);
    state.selectedId = el.id;
    renderCanvas();
    renderPanel();
  }

  async function deleteElement(el) {
    if (!confirm('Delete this element?')) return;
    await api(`cockpit/${state.cockpit.id}/elements/${el.id}`, { method: 'DELETE' });
    state.selectedId = null;
    await selectCockpit(state.cockpit.id);
  }

  async function addElement(type) {
    if (!state.cockpit) {
      alert('Create or select a cockpit first.');
      return;
    }
    const body = { type, x: 0.4, y: 0.4, w: 0.14, h: 0.14, label: type };
    if (type !== 'key') {
      body.style = type === 'gauge' ? 'bar' : 'numeric';
      body.min = 0;
      body.max = 100;
    }
    const cockpit = await api(`cockpit/${state.cockpit.id}/elements`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    state.cockpit = cockpit;
    const last = cockpit.elements[cockpit.elements.length - 1];
    state.selectedId = last ? last.id : null;
    renderCanvas();
    renderPanel();
  }

  fCockpit.addEventListener('change', () => selectCockpit(fCockpit.value));

  $('#btn-new-cockpit').addEventListener('click', async () => {
    const name = prompt('Cockpit name', 'New Cockpit');
    if (name === null) return;
    const cockpit = await api('cockpit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    await loadCockpits(cockpit.id);
  });

  $('#btn-delete-cockpit').addEventListener('click', async () => {
    if (!state.cockpit) return;
    if (!confirm(`Delete cockpit "${state.cockpit.name}"? This cannot be undone.`)) return;
    await api(`cockpit/${state.cockpit.id}`, { method: 'DELETE' });
    await loadCockpits();
  });

  $('#btn-upload-image').addEventListener('click', async () => {
    if (!state.cockpit) {
      alert('Create or select a cockpit first.');
      return;
    }
    const input = $('#f-image');
    if (!input.files.length) {
      alert('Choose an image file first.');
      return;
    }
    const form = new FormData();
    form.append('file', input.files[0]);
    try {
      await api(`cockpit/${state.cockpit.id}/image`, { method: 'POST', body: form });
      await selectCockpit(state.cockpit.id);
    } catch (e) {
      alert(`Upload failed: ${e.message}`);
    }
  });

  $('#btn-add-key').addEventListener('click', () => addElement('key'));
  $('#btn-add-gauge').addEventListener('click', () => addElement('gauge'));
  $('#btn-add-indicator').addEventListener('click', () => addElement('indicator'));

  canvasWrap.addEventListener('click', () => {
    state.selectedId = null;
    renderCanvas();
    renderPanel();
  });

  (async () => {
    await loadLookups();
    await loadCockpits();
  })();
})();
