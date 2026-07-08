// Network pane: Wi-Fi status, scan, and connect for a Raspberry Pi appliance.
// Every call degrades quietly on a server, where the routes report they are
// not available and this script just leaves the status line as-is.
(function () {
  const statusEl = document.getElementById('wifi-status');
  if (!statusEl) return;

  const scanBtn = document.getElementById('wifi-scan-btn');
  const networksEl = document.getElementById('wifi-networks');
  const formEl = document.getElementById('wifi-connect-form');
  const ssidInput = document.getElementById('wifi-ssid');
  const pskInput = document.getElementById('wifi-psk');
  const connectBtn = document.getElementById('wifi-connect-btn');
  const connectStatus = document.getElementById('wifi-connect-status');

  function renderStatus(d) {
    if (!d || d.ok === false) {
      statusEl.textContent = (d && d.error) || 'Not available on this device.';
      return;
    }
    const parts = [d.ssid ? ('Connected to ' + d.ssid) : 'Not connected to a Wi-Fi network'];
    if (d.ip) parts.push(d.ip);
    statusEl.textContent = parts.join(' · ');
  }

  function loadStatus() {
    fetch('network/status').then((r) => r.json()).then(renderStatus)
      .catch(() => { statusEl.textContent = 'Could not read network status.'; });
  }
  loadStatus();

  function selectNetwork(ssid) {
    ssidInput.value = ssid;
    formEl.classList.remove('d-none');
    pskInput.focus();
  }

  function renderNetworks(networks) {
    networksEl.innerHTML = '';
    if (!networks.length) {
      networksEl.innerHTML = '<div class="small text-secondary">No networks found.</div>';
      return;
    }
    networks.forEach((n) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'btn btn-outline-secondary btn-sm text-start d-flex justify-content-between align-items-center';
      const lock = n.secured === false ? '' : '<i class="bi bi-lock-fill ms-2"></i>';
      row.innerHTML = '<span></span>' + lock;
      row.querySelector('span').textContent = n.ssid;
      row.addEventListener('click', () => selectNetwork(n.ssid));
      networksEl.appendChild(row);
    });
  }

  if (scanBtn) {
    scanBtn.addEventListener('click', () => {
      scanBtn.disabled = true;
      networksEl.innerHTML = '<div class="small text-secondary">Scanning…</div>';
      fetch('network/wifi/scan', { method: 'POST' }).then((r) => r.json()).then((d) => {
        scanBtn.disabled = false;
        if (d.ok === false) {
          networksEl.innerHTML = '<div class="small text-danger"></div>';
          networksEl.firstChild.textContent = d.error || 'Scan failed.';
          return;
        }
        renderNetworks(d.networks || []);
      }).catch(() => {
        scanBtn.disabled = false;
        networksEl.innerHTML = '<div class="small text-danger">Scan failed.</div>';
      });
    });
  }

  if (connectBtn) {
    connectBtn.addEventListener('click', () => {
      const ssid = ssidInput.value.trim();
      if (!ssid) return;
      connectBtn.disabled = true;
      connectStatus.textContent = 'Connecting…';
      connectStatus.className = 'ms-2 small text-secondary';
      fetch('network/wifi/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid: ssid, psk: pskInput.value }),
      }).then((r) => r.json()).then((d) => {
        connectBtn.disabled = false;
        connectStatus.textContent = d.ok ? (d.message || 'Connected') : (d.error || 'Connect failed.');
        connectStatus.className = 'ms-2 small ' + (d.ok ? 'text-success' : 'text-danger');
        if (d.ok) setTimeout(loadStatus, 2000);
      }).catch(() => {
        connectBtn.disabled = false;
        connectStatus.textContent = 'Connect failed.';
        connectStatus.className = 'ms-2 small text-danger';
      });
    });
  }
})();
