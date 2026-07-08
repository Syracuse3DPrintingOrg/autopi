// Profile Sync pane: check a configured server for profiles and pull one in.
// This is a future feature with no real server yet, so every call degrades
// quietly to a status message until a server URL and device token are set.
(function () {
  const statusEl = document.getElementById('sync-status');
  if (!statusEl) return;

  const checkBtn = document.getElementById('sync-check-btn');
  const listEl = document.getElementById('sync-profiles-list');

  function loadStatus() {
    fetch('sync/status').then((r) => r.json()).then((d) => {
      if (d && d.configured) {
        statusEl.textContent = 'Configured for ' + d.server;
      } else {
        statusEl.textContent = 'Not configured yet. Add a server URL and device token above.';
      }
    }).catch(() => { statusEl.textContent = 'Could not read sync status.'; });
  }

  function renderProfiles(profiles) {
    listEl.innerHTML = '';
    if (!profiles.length) {
      listEl.innerHTML = '<div class="small text-secondary">No profiles on the server.</div>';
      return;
    }
    profiles.forEach((p) => {
      const row = document.createElement('div');
      row.className = 'd-flex justify-content-between align-items-center border rounded px-2 py-1';

      const label = document.createElement('span');
      const details = [p.year, p.make, p.model].filter(Boolean).join(' ');
      label.textContent = p.name + (details ? ' (' + details + ')' : '');

      const pullBtn = document.createElement('button');
      pullBtn.type = 'button';
      pullBtn.className = 'btn btn-outline-primary btn-sm';
      pullBtn.textContent = 'Pull';
      pullBtn.addEventListener('click', () => pullProfile(p.key, pullBtn));

      row.appendChild(label);
      row.appendChild(pullBtn);
      listEl.appendChild(row);
    });
  }

  function pullProfile(key, btn) {
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = 'Pulling…';
    fetch('sync/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key }),
    }).then((r) => r.json()).then((d) => {
      btn.disabled = false;
      btn.textContent = d.ok ? 'Pulled' : original;
      if (!d.ok) {
        listEl.insertAdjacentHTML('afterbegin',
          '<div class="small text-danger">' + (d.error || 'Pull failed.') + '</div>');
      }
    }).catch(() => {
      btn.disabled = false;
      btn.textContent = original;
      listEl.insertAdjacentHTML('afterbegin', '<div class="small text-danger">Pull failed.</div>');
    });
  }

  if (checkBtn) {
    checkBtn.addEventListener('click', () => {
      checkBtn.disabled = true;
      listEl.innerHTML = '<div class="small text-secondary">Checking…</div>';
      fetch('sync/list', { method: 'POST' }).then((r) => r.json()).then((d) => {
        checkBtn.disabled = false;
        if (d.ok === false) {
          listEl.innerHTML = '<div class="small text-danger"></div>';
          listEl.firstChild.textContent = d.error || 'Could not list profiles.';
          return;
        }
        renderProfiles(d.profiles || []);
      }).catch(() => {
        checkBtn.disabled = false;
        listEl.innerHTML = '<div class="small text-danger">Could not list profiles.</div>';
      });
    });
  }

  loadStatus();
})();
