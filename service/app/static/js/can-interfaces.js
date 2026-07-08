// CAN Interfaces pane: list, add, edit, and delete configured CAN channels,
// plus per-interface bring-up/down, live link state, and self-test.
// Mirrors the Network pane's pattern of small fetch calls against a router
// dedicated to this feature, since the config here is a list, not a set of
// flat settings that fit the generic [data-setting] save mechanism.
(function () {
  const listEl = document.getElementById('can-if-list');
  if (!listEl) return;

  const backendSel = document.getElementById('can-if-backend');
  const idInput = document.getElementById('can-if-id');
  const channelInput = document.getElementById('can-if-channel');
  const bitrateInput = document.getElementById('can-if-bitrate');
  const dataBitrateInput = document.getElementById('can-if-data-bitrate');
  const purposeSel = document.getElementById('can-if-purpose');
  const labelInput = document.getElementById('can-if-label');
  const labelWrap = document.getElementById('can-if-label-wrap');
  const fdInput = document.getElementById('can-if-fd');
  const saveBtn = document.getElementById('can-if-save-btn');
  const cancelBtn = document.getElementById('can-if-cancel-btn');
  const statusEl = document.getElementById('can-if-save-status');
  const formTitle = document.getElementById('can-if-form-title');

  const LINK_BACKENDS = new Set(['socketcan']);
  let editingId = null;

  function updateLabelVisibility() {
    // A named purpose has a fixed display name; the free-text label is only
    // meaningful (and only shown) when "Custom label below" is selected.
    labelWrap.classList.toggle('d-none', !!purposeSel.value);
  }
  purposeSel.addEventListener('change', updateLabelVisibility);

  function resetForm() {
    editingId = null;
    idInput.value = '';
    idInput.disabled = false;
    channelInput.value = '';
    bitrateInput.value = 500000;
    dataBitrateInput.value = '';
    purposeSel.value = '';
    labelInput.value = '';
    fdInput.checked = false;
    formTitle.textContent = 'Add an interface';
    cancelBtn.classList.add('d-none');
    updateLabelVisibility();
  }

  function loadBackends() {
    fetch('can/interfaces/backends').then((r) => r.json()).then((d) => {
      backendSel.innerHTML = '';
      (d.backends || []).forEach((b) => {
        const opt = document.createElement('option');
        opt.value = b.backend;
        opt.textContent = b.label;
        backendSel.appendChild(opt);
      });
    }).catch(() => {});
  }

  function stateBadge(state) {
    const map = { ok: 'success', warning: 'warning', error: 'danger', down: 'secondary', unknown: 'secondary' };
    const label = { ok: 'error-active', warning: 'errors', error: 'bus-off', down: 'down', unknown: 'unknown' };
    return '<span class="badge text-bg-' + (map[state] || 'secondary') + '">' + (label[state] || state) + '</span>';
  }

  function renderHealth(el, iface, data) {
    if (!data.ok) {
      el.innerHTML = '<span class="small text-secondary">' + (data.error || 'Not available.') + '</span>';
      return;
    }
    const h = data.health || {};
    const s = data.state || {};
    let text = stateBadge(h.status) + ' <span class="small text-secondary ms-1">' + (h.message || '') + '</span>';
    if (s.bitrate) {
      text += '<span class="small text-secondary ms-2">' + s.bitrate + ' bit/s' +
        (s.data_bitrate ? ' / ' + s.data_bitrate + ' fd' : '') + '</span>';
    }
    el.innerHTML = text;
  }

  function refreshLinkState(iface, row) {
    const stateEl = row.querySelector('[data-linkstate="' + iface.id + '"]');
    if (!stateEl) return;
    fetch('can/interfaces/config/' + encodeURIComponent(iface.id) + '/health')
      .then((r) => r.json())
      .then((d) => renderHealth(stateEl, iface, d))
      .catch(() => { stateEl.innerHTML = '<span class="small text-secondary">Could not read link state.</span>'; });
  }

  function bringUpDown(iface, row, up) {
    const resultEl = row.querySelector('[data-op-result="' + iface.id + '"]');
    resultEl.textContent = up ? 'Bringing up…' : 'Bringing down…';
    fetch('can/interfaces/config/' + encodeURIComponent(iface.id) + '/' + (up ? 'up' : 'down'), { method: 'POST' })
      .then((r) => r.json())
      .then((d) => {
        resultEl.textContent = d.ok ? (d.message || 'Done') : (d.error || 'Failed');
        resultEl.className = 'small mt-1 ' + (d.ok ? 'text-success' : 'text-danger');
        refreshLinkState(iface, row);
      })
      .catch(() => {
        resultEl.textContent = 'Request failed';
        resultEl.className = 'small mt-1 text-danger';
      });
  }

  function runSniff(iface, row) {
    const resultEl = row.querySelector('[data-op-result="' + iface.id + '"]');
    resultEl.textContent = 'Listening on ' + iface.channel + ' for 3s…';
    resultEl.className = 'small mt-1 text-secondary';
    fetch('can/interfaces/config/' + encodeURIComponent(iface.id) + '/sniff', { method: 'POST' })
      .then((r) => r.json())
      .then((d) => {
        if (d.ok === false) {
          resultEl.textContent = d.error || 'Listen failed';
          resultEl.className = 'small mt-1 text-danger';
          return;
        }
        if (!d.frames) {
          resultEl.innerHTML = '<span class="text-warning">No frames arrived in ' + d.seconds + 's.</span> '
            + 'The interface is up but nothing is reaching it: check the wiring to this bus, that the bus is '
            + 'awake, and that the bitrate/FD settings match it.';
          resultEl.className = 'small mt-1';
          return;
        }
        resultEl.innerHTML = '<span class="text-success">' + d.frames + ' frames, ' + d.unique_ids
          + ' unique IDs</span> in ' + d.seconds + 's. IDs: ' + (d.ids || []).join(', ');
        resultEl.className = 'small mt-1';
      })
      .catch(() => {
        resultEl.textContent = 'Request failed';
        resultEl.className = 'small mt-1 text-danger';
      });
  }

  function runSelfTest(iface, row) {
    const resultEl = row.querySelector('[data-op-result="' + iface.id + '"]');
    resultEl.textContent = 'Running loopback test…';
    resultEl.className = 'small mt-1 text-secondary';
    fetch('can/interfaces/config/' + encodeURIComponent(iface.id) + '/self-test', { method: 'POST' })
      .then((r) => r.json())
      .then((d) => {
        resultEl.textContent = d.passed ? (d.message || 'Passed') : (d.error || 'Failed');
        resultEl.className = 'small mt-1 ' + (d.passed ? 'text-success' : 'text-danger');
      })
      .catch(() => {
        resultEl.textContent = 'Request failed';
        resultEl.className = 'small mt-1 text-danger';
      });
  }

  function sendTestFrame(iface, row) {
    const resultEl = row.querySelector('[data-op-result="' + iface.id + '"]');
    resultEl.textContent = 'Sending test frame…';
    resultEl.className = 'small mt-1 text-secondary';
    fetch('can/interfaces/config/' + encodeURIComponent(iface.id) + '/send-test-frame', { method: 'POST' })
      .then((r) => r.json())
      .then((d) => {
        resultEl.textContent = d.ok ? (d.message || 'Sent') : (d.error || 'Failed');
        resultEl.className = 'small mt-1 ' + (d.ok ? 'text-success' : 'text-danger');
      })
      .catch(() => {
        resultEl.textContent = 'Request failed';
        resultEl.className = 'small mt-1 text-danger';
      });
  }

  function statusBadge(available) {
    return available
      ? '<span class="badge text-bg-success">available</span>'
      : '<span class="badge text-bg-secondary">not detected</span>';
  }

  function renderList(interfaces) {
    listEl.innerHTML = '';
    if (!interfaces.length) {
      listEl.innerHTML = '<span class="small text-secondary">No CAN interfaces configured yet.</span>';
      return;
    }
    interfaces.forEach((iface) => {
      const fd = iface.fd ? ', FD' + (iface.data_bitrate ? ' @ ' + iface.data_bitrate : '') : '';
      const isLinkBacked = LINK_BACKENDS.has(iface.backend);
      const row = document.createElement('div');
      row.className = 'border rounded p-2';
      row.innerHTML =
        '<div class="d-flex align-items-center justify-content-between">' +
        '<div>' +
        '<div class="fw-semibold">' + (iface.purpose_label || iface.label || iface.id) + '</div>' +
        '<div class="small text-secondary">' + iface.id + ' &middot; ' + iface.backend +
        ' &middot; ' + iface.channel + ' &middot; ' + iface.bitrate + ' bit/s' + fd + '</div>' +
        '<div class="small mt-1" data-status="' + iface.id + '">Checking&hellip;</div>' +
        '</div>' +
        '<div class="d-flex gap-1">' +
        '<button type="button" class="btn btn-outline-secondary btn-sm" data-edit="' + iface.id + '">Edit</button>' +
        '<button type="button" class="btn btn-outline-danger btn-sm" data-delete="' + iface.id + '">Delete</button>' +
        '</div>' +
        '</div>' +
        (isLinkBacked
          ? '<div class="d-flex align-items-center gap-2 mt-2 flex-wrap">' +
            '<button type="button" class="btn btn-outline-success btn-sm" data-up="' + iface.id + '">Bring up</button>' +
            '<button type="button" class="btn btn-outline-secondary btn-sm" data-down="' + iface.id + '">Bring down</button>' +
            '<button type="button" class="btn btn-outline-primary btn-sm" data-selftest="' + iface.id + '">Run self-test</button>' +
            '<button type="button" class="btn btn-outline-primary btn-sm" data-testframe="' + iface.id + '">Send test frame</button>' +
            '<button type="button" class="btn btn-outline-info btn-sm" data-sniff="' + iface.id + '">Listen 3s</button>' +
            '<span data-linkstate="' + iface.id + '"></span>' +
            '</div>' +
            '<div class="small mt-1" data-op-result="' + iface.id + '"></div>'
          : '');
      listEl.appendChild(row);

      fetch('can/interfaces/config/' + encodeURIComponent(iface.id) + '/status')
        .then((r) => r.json())
        .then((d) => {
          const el = row.querySelector('[data-status="' + iface.id + '"]');
          if (el) {
            const reason = (!d.available && d.error)
              ? '<span class="small text-secondary d-block mt-1">' + d.error + '</span>' : '';
            el.innerHTML = statusBadge(!!d.available) + reason;
          }
        })
        .catch(() => {
          const el = row.querySelector('[data-status="' + iface.id + '"]');
          if (el) el.innerHTML = statusBadge(false);
        });

      row.querySelector('[data-edit]').addEventListener('click', () => startEdit(iface));
      row.querySelector('[data-delete]').addEventListener('click', () => deleteInterface(iface.id));

      if (isLinkBacked) {
        row.querySelector('[data-up]').addEventListener('click', () => bringUpDown(iface, row, true));
        row.querySelector('[data-down]').addEventListener('click', () => bringUpDown(iface, row, false));
        row.querySelector('[data-selftest]').addEventListener('click', () => runSelfTest(iface, row));
        row.querySelector('[data-testframe]').addEventListener('click', () => sendTestFrame(iface, row));
        row.querySelector('[data-sniff]').addEventListener('click', () => runSniff(iface, row));
        refreshLinkState(iface, row);
      }
    });
  }

  function loadList() {
    fetch('can/interfaces/config').then((r) => r.json()).then((d) => renderList(d.interfaces || []))
      .catch(() => { listEl.textContent = 'Could not load CAN interfaces.'; });
  }

  function startEdit(iface) {
    editingId = iface.id;
    idInput.value = iface.id;
    idInput.disabled = true;
    backendSel.value = iface.backend;
    channelInput.value = iface.channel;
    bitrateInput.value = iface.bitrate;
    dataBitrateInput.value = iface.data_bitrate || '';
    purposeSel.value = iface.purpose || '';
    labelInput.value = iface.label || '';
    fdInput.checked = !!iface.fd;
    formTitle.textContent = 'Edit ' + iface.id;
    cancelBtn.classList.remove('d-none');
    updateLabelVisibility();
    formTitle.scrollIntoView({ block: 'nearest' });
  }

  function deleteInterface(id) {
    fetch('can/interfaces/config/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(() => { if (editingId === id) resetForm(); loadList(); });
  }

  function saveInterface() {
    const id = (editingId || idInput.value).trim();
    if (!id) {
      statusEl.textContent = 'A channel name is required';
      statusEl.className = 'ms-2 small text-danger';
      return;
    }
    const body = {
      id: id,
      backend: backendSel.value,
      channel: channelInput.value.trim() || id,
      bitrate: parseInt(bitrateInput.value, 10) || 500000,
      fd: fdInput.checked,
      data_bitrate: dataBitrateInput.value ? parseInt(dataBitrateInput.value, 10) : null,
      purpose: purposeSel.value,
      label: labelInput.value.trim(),
    };
    fetch('can/interfaces/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then((r) => r.json()).then((d) => {
      statusEl.textContent = d.ok ? 'Saved' : 'Save failed';
      statusEl.className = 'ms-2 small ' + (d.ok ? 'text-success' : 'text-danger');
      setTimeout(() => { statusEl.textContent = ''; }, 2000);
      if (d.ok) { resetForm(); loadList(); }
    }).catch(() => {
      statusEl.textContent = 'Save failed';
      statusEl.className = 'ms-2 small text-danger';
    });
  }

  const detectedEl = document.getElementById('can-if-detected');
  function loadDetected() {
    if (!detectedEl) return;
    fetch('can/interfaces/detected').then((r) => r.json()).then((d) => {
      const items = d.interfaces || [];
      if (!items.length) {
        detectedEl.innerHTML = '<span class="text-secondary">No CAN interfaces detected on this device yet. '
          + 'On a Pi, enable the CAN HAT and reboot; a USB adapter should appear once it is plugged in.</span>';
        return;
      }
      detectedEl.innerHTML = '';
      items.forEach((it) => {
        const row = document.createElement('div');
        row.className = 'd-flex align-items-center justify-content-between border-bottom py-1 gap-2';
        const state = it.up
          ? '<span class="badge text-bg-success">up</span>'
          : '<span class="badge text-bg-secondary">down</span>';
        const port = it.port_label ? ' <span class="badge text-bg-info">HAT ' + it.port_label + '</span>' : '';
        const st = it.stats || {};
        const rx = (st.rx_packets != null)
          ? ' <span class="text-secondary">rx ' + st.rx_packets + ' / tx ' + (st.tx_packets != null ? st.tx_packets : '?') + '</span>'
          : '';
        row.innerHTML = '<div><code>' + it.name + '</code> ' + state + port
          + '<div class="text-secondary">' + (it.description || '')
          + (it.spi_device ? ' (' + it.spi_device + ')' : '') + rx + '</div></div>';
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-outline-primary btn-sm flex-shrink-0';
        btn.textContent = 'Use';
        btn.title = 'Fill the form below with this channel';
        btn.addEventListener('click', () => {
          if (idInput) idInput.value = it.name;
          if (channelInput) channelInput.value = it.name;
          if (backendSel) backendSel.value = 'socketcan';
          if (channelInput) channelInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
        row.appendChild(btn);
        detectedEl.appendChild(row);
      });
    }).catch(() => { detectedEl.textContent = 'Could not read the detected interfaces.'; });
  }

  saveBtn.addEventListener('click', saveInterface);
  cancelBtn.addEventListener('click', resetForm);

  updateLabelVisibility();
  loadBackends();
  loadDetected();
  loadList();
})();
