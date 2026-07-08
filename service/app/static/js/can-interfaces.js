// CAN Interfaces pane: list, add, edit, and delete configured CAN channels.
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
  const labelInput = document.getElementById('can-if-label');
  const fdInput = document.getElementById('can-if-fd');
  const saveBtn = document.getElementById('can-if-save-btn');
  const cancelBtn = document.getElementById('can-if-cancel-btn');
  const statusEl = document.getElementById('can-if-save-status');
  const formTitle = document.getElementById('can-if-form-title');

  let editingId = null;

  function resetForm() {
    editingId = null;
    idInput.value = '';
    idInput.disabled = false;
    channelInput.value = '';
    bitrateInput.value = 500000;
    dataBitrateInput.value = '';
    labelInput.value = '';
    fdInput.checked = false;
    formTitle.textContent = 'Add an interface';
    cancelBtn.classList.add('d-none');
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
      const row = document.createElement('div');
      row.className = 'd-flex align-items-center justify-content-between border rounded p-2';
      const fd = iface.fd ? ', FD' + (iface.data_bitrate ? ' @ ' + iface.data_bitrate : '') : '';
      row.innerHTML =
        '<div>' +
        '<div class="fw-semibold">' + (iface.label || iface.id) + '</div>' +
        '<div class="small text-secondary">' + iface.id + ' &middot; ' + iface.backend +
        ' &middot; ' + iface.channel + ' &middot; ' + iface.bitrate + ' bit/s' + fd + '</div>' +
        '<div class="small mt-1" data-status="' + iface.id + '">Checking&hellip;</div>' +
        '</div>' +
        '<div class="d-flex gap-1">' +
        '<button type="button" class="btn btn-outline-secondary btn-sm" data-edit="' + iface.id + '">Edit</button>' +
        '<button type="button" class="btn btn-outline-danger btn-sm" data-delete="' + iface.id + '">Delete</button>' +
        '</div>';
      listEl.appendChild(row);

      fetch('can/interfaces/config/' + encodeURIComponent(iface.id) + '/status')
        .then((r) => r.json())
        .then((d) => {
          const el = row.querySelector('[data-status="' + iface.id + '"]');
          if (el) el.innerHTML = statusBadge(!!d.available);
        })
        .catch(() => {
          const el = row.querySelector('[data-status="' + iface.id + '"]');
          if (el) el.innerHTML = statusBadge(false);
        });

      row.querySelector('[data-edit]').addEventListener('click', () => startEdit(iface));
      row.querySelector('[data-delete]').addEventListener('click', () => deleteInterface(iface.id));
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
    labelInput.value = iface.label || '';
    fdInput.checked = !!iface.fd;
    formTitle.textContent = 'Edit ' + iface.id;
    cancelBtn.classList.remove('d-none');
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

  saveBtn.addEventListener('click', saveInterface);
  cancelBtn.addEventListener('click', resetForm);

  loadBackends();
  loadList();
})();
