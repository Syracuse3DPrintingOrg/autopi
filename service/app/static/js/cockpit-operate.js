// Cockpit kiosk (operate) view: render the placed keys and gauges over the
// background image and keep gauge/indicator readouts live by polling
// /cockpit/{id}/values. Tapping a key fires its action through
// /cockpit/{id}/elements/{id}/fire, same as any other surface.
(() => {
  const cockpitId = window.COCKPIT_ID;
  const elements = window.COCKPIT_ELEMENTS || [];
  const stage = document.getElementById('cp-stage');
  const toast = document.getElementById('toast');
  let toastTimer = null;

  function showToast(text) {
    if (!toast) return;
    toast.textContent = text;
    toast.style.display = 'block';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.style.display = 'none'; }, 2200);
  }

  if (!stage) return;

  const nodesById = {};

  function buildNode(el) {
    const node = document.createElement('div');
    node.className = `cp-el ${el.type}`;
    node.style.left = `${el.x * 100}%`;
    node.style.top = `${el.y * 100}%`;
    node.style.width = `${el.w * 100}%`;
    node.style.height = `${el.h * 100}%`;

    if (el.type === 'key') {
      node.style.background = el.color || '#334155';
      const label = document.createElement('span');
      label.textContent = el.label || '';
      node.appendChild(label);
      node.addEventListener('click', () => fireKey(el));
    } else if (el.type === 'gauge') {
      node.innerHTML = `
        <div class="cp-gauge-label">${escapeHtml(el.label || '')}</div>
        <div class="cp-gauge-value" data-role="value">--</div>
        ${el.style === 'bar' ? '<div class="cp-gauge-bar-track"><div class="cp-gauge-bar-fill" data-role="fill"></div></div>' : ''}
      `;
    } else if (el.type === 'indicator') {
      node.innerHTML = `
        <div class="cp-gauge-label">${escapeHtml(el.label || '')}</div>
        <div class="cp-indicator-dot" data-role="dot"></div>
      `;
    }
    stage.appendChild(node);
    nodesById[el.id] = node;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  async function fireKey(el) {
    try {
      const res = await fetch(`cockpit/${cockpitId}/elements/${el.id}/fire`, { method: 'POST' });
      const data = await res.json();
      if (data.message) showToast(data.message);
    } catch (e) {
      showToast('Could not run that key');
    }
  }

  async function pollValues() {
    try {
      const res = await fetch(`cockpit/${cockpitId}/values`);
      if (!res.ok) return;
      const data = await res.json();
      for (const [id, v] of Object.entries(data.values || {})) {
        const node = nodesById[id];
        if (!node) continue;
        const valueEl = node.querySelector('[data-role="value"]');
        if (valueEl) valueEl.textContent = v.display;
        const fillEl = node.querySelector('[data-role="fill"]');
        if (fillEl) fillEl.style.width = `${v.percent != null ? v.percent : 0}%`;
        const dotEl = node.querySelector('[data-role="dot"]');
        if (dotEl) dotEl.classList.toggle('on', !!v.on);
      }
    } catch (e) {
      // A poll miss (network blip, server restart) just leaves the last
      // known readouts on screen; the next tick will catch up.
    }
  }

  for (const el of elements) buildNode(el);
  const hasLiveElements = elements.some((el) => el.type === 'gauge' || el.type === 'indicator');
  if (hasLiveElements) {
    pollValues();
    setInterval(pollValues, 1000);
  }
})();
