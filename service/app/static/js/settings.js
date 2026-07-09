// Settings page behavior: pane navigation, search filter, per-pane save, and
// the live driver list. Mirrors the source project's sectioned settings shell.
(function () {
  // Activate a pane by its element id (used by the overview cards).
  window.openPane = function (paneId) {
    const pill = document.querySelector('[data-bs-target="#' + paneId + '"]');
    if (pill && window.bootstrap) {
      bootstrap.Tab.getOrCreateInstance(pill).show();
      pill.scrollIntoView({ block: 'nearest' });
    }
  };

  // Filter the side menu to pills whose label or pane title matches.
  window.settingsSearch = function (query) {
    const q = (query || '').trim().toLowerCase();
    document.querySelectorAll('.side-menu .nav-link').forEach((pill) => {
      const target = pill.getAttribute('data-bs-target');
      const pane = target && document.querySelector(target);
      const hay = (pill.textContent + ' ' + (pane ? (pane.getAttribute('data-title') || '') : '')).toLowerCase();
      pill.style.display = !q || hay.indexOf(q) !== -1 ? '' : 'none';
    });
  };

  // Collect [data-setting] fields inside a pane and POST them to /setup/save.
  async function savePane(pane, statusEl) {
    const body = {};
    pane.querySelectorAll('[data-setting]').forEach((el) => {
      const key = el.getAttribute('data-setting');
      const type = el.getAttribute('data-type') || 'str';
      let value;
      if (el.type === 'checkbox') value = el.checked;
      else value = el.value;
      if (type === 'int') value = parseInt(value, 10);
      else if (type === 'bool') value = Boolean(value);
      body[key] = value;
    });
    try {
      const r = await fetch('setup/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const ok = r.ok && (await r.json()).ok;
      if (statusEl) {
        statusEl.textContent = ok ? 'Saved' : 'Save failed';
        statusEl.className = 'save-status ms-2 small ' + (ok ? 'text-success' : 'text-danger');
        setTimeout(() => { statusEl.textContent = ''; }, 2000);
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = 'Save failed';
    }
  }

  document.querySelectorAll('.save-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const pane = btn.closest('.section-card') || btn.closest('.tab-pane');
      savePane(pane, btn.parentElement.querySelector('.save-status'));
    });
  });

  // Open the pane named in the URL hash (e.g. /setup#pane-security).
  if (location.hash && document.querySelector(location.hash)) {
    openPane(location.hash.slice(1));
  }

  // Populate the Actions pane with the drivers the app reports.
  const list = document.getElementById('drivers-list');
  if (list) {
    fetch('actions/drivers').then((r) => r.json()).then((d) => {
      list.innerHTML = '';
      (d.drivers || []).forEach((drv) => {
        const row = document.createElement('div');
        const badge = drv.available
          ? '<span class="badge text-bg-success">available</span>'
          : '<span class="badge text-bg-secondary">not on this host</span>';
        row.innerHTML = '<span class="text-body">' + drv.label + '</span> ' + badge;
        list.appendChild(row);
      });
    }).catch(() => { list.textContent = 'Could not load drivers.'; });
  }

  // AI Assist: report whether the saved key/model are usable. Save first, then
  // Test, since it reflects what is persisted, not the unsaved form fields.
  const aiTest = document.getElementById('ai-test-btn');
  if (aiTest) {
    aiTest.addEventListener('click', () => {
      const st = document.getElementById('ai-test-status');
      st.textContent = 'Checking…';
      st.className = 'ms-2 small text-secondary';
      fetch('reverse/llm/status').then((r) => r.json()).then((d) => {
        if (d.available) {
          st.textContent = 'Ready (' + (d.model || 'default model') + '). Save first if you just changed the key.';
          st.className = 'ms-2 small text-success';
        } else {
          st.textContent = d.reason || 'Not configured.';
          st.className = 'ms-2 small text-warning';
        }
      }).catch(() => { st.textContent = 'Check failed.'; st.className = 'ms-2 small text-danger'; });
    });
  }
})();
