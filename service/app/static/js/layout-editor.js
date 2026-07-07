// Drag-and-drop layout editor. Actions in the palette are dragged onto surface
// slots; each surface saves its ordered list of action ids back to the API.
(function () {
  const actions = window.__ACTIONS__ || [];
  const surfaces = window.__SURFACES__ || {};
  const byId = {};
  actions.forEach((a) => { byId[a.id] = a; });

  // Number of slots each surface grid shows in the editor. Extra empty slots
  // give room to drop new keys; trailing blanks are trimmed on save.
  const SLOTS = 32;

  function chip(action) {
    const el = document.createElement('div');
    el.className = 'chip';
    el.style.background = (action && action.color) || '#475569';
    el.textContent = action ? (action.label || action.id) : 'Blank';
    el.draggable = true;
    el.dataset.action = action ? action.id : 'blank';
    el.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', el.dataset.action);
    });
    return el;
  }

  // Build the palette (skip builtins that are placed automatically like paging).
  const palette = document.getElementById('palette');
  actions.filter((a) => a.id !== 'blank' && a.id !== 'page_next' && a.id !== 'page_prev')
    .forEach((a) => palette.appendChild(chip(a)));

  function makeSlot(surface, index, actionId) {
    const slot = document.createElement('div');
    slot.dataset.index = index;
    function paint(id) {
      slot.dataset.action = id || '';
      const a = id ? byId[id] : null;
      if (a) {
        slot.className = 'slot';
        slot.style.background = a.color || '#1e293b';
        slot.textContent = a.label || a.id;
      } else {
        slot.className = 'slot blank';
        slot.style.background = '';
        slot.textContent = 'empty';
      }
    }
    paint(actionId);
    slot.addEventListener('dragover', (e) => { e.preventDefault(); slot.classList.add('drag-over'); });
    slot.addEventListener('dragleave', () => slot.classList.remove('drag-over'));
    slot.addEventListener('drop', (e) => {
      e.preventDefault();
      slot.classList.remove('drag-over');
      const id = e.dataTransfer.getData('text/plain');
      paint(id === 'blank' ? '' : id);
    });
    return slot;
  }

  function buildGrid(surface) {
    const grid = document.getElementById('grid-' + surface);
    const current = surfaces[surface] || [];
    grid.innerHTML = '';
    for (let i = 0; i < SLOTS; i++) {
      grid.appendChild(makeSlot(surface, i, current[i] || ''));
    }
  }

  Object.keys(surfaces).forEach(buildGrid);

  function collect(surface) {
    const grid = document.getElementById('grid-' + surface);
    const slots = Array.from(grid.children).map((s) => s.dataset.action || null);
    // Trim trailing empties so the surface only stores what was actually placed.
    while (slots.length && slots[slots.length - 1] === null) slots.pop();
    return slots;
  }

  document.querySelectorAll('[data-save]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const surface = btn.dataset.save;
      const slots = collect(surface);
      const r = await fetch('/layout/' + surface, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slots }),
      });
      btn.textContent = r.ok ? 'Saved' : 'Failed';
      setTimeout(() => { btn.textContent = 'Save'; }, 1500);
    });
  });
})();
