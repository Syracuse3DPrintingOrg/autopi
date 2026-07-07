// Visual layout editor for the Stream Deck and the Start Page.
//
// The grid scales to the selected deck model (6/15/32) or, when a controller
// reports one attached, to the live deck. Rotation reshapes the grid (columns
// and rows swap for 90/270). A layout longer than the deck paginates, with the
// last key of every page reserved as a wrapping "More" key, mirroring the
// server-side deck_layout math. The two surfaces share one key library.
(function () {
  var GRID = { 6: [3, 2], 15: [5, 3], 32: [8, 4] };

  var state = {
    surface: 'streamdeck',
    slots: { streamdeck: [], start: [] },
    catalog: {},          // id -> action
    actions: [],          // ordered list from /actions
    status: { key_count: 15, model: 15, rotation: 0, brightness: 60, enabled: false, connected: false },
    page: 0,
  };

  var $ = function (id) { return document.getElementById(id); };

  function displayDims(kc, rot) {
    var g = GRID[kc] || [kc, 1];
    return (rot === 90 || rot === 270) ? [g[1], g[0]] : [g[0], g[1]];
  }
  function keyCount() {
    if (state.status.connected) return state.status.key_count;
    return parseInt($('sd-model').value, 10) || 15;
  }
  function rotationForGrid() {
    return state.surface === 'streamdeck' ? (parseInt($('sd-rotation').value, 10) || 0) : 0;
  }
  function curSlots() { return state.slots[state.surface]; }

  function pageInfo() {
    var kc = keyCount(), total = curSlots().length;
    if (total <= kc) return { count: 1, usable: kc, multi: false };
    var usable = kc - 1;
    return { count: Math.ceil(total / usable), usable: usable, multi: true };
  }

  // ---- rendering -----------------------------------------------------------
  function keyEl(id, slotIdx, num, fixed) {
    var el = document.createElement('div');
    var a = id ? state.catalog[id] : null;
    if (fixed === 'more') {
      el.className = 'deck-key more';
      el.innerHTML = '<i class="bi bi-chevron-right"></i><span class="k-lbl">More</span>';
    } else if (!a) {
      el.className = 'deck-key blank';
      el.innerHTML = '<span class="k-lbl">Empty</span>';
    } else {
      el.className = 'deck-key';
      el.style.background = a.color || '#334155';
      el.innerHTML = '<i class="bi ' + (a.icon || 'bi-lightning-charge') + '"></i>' +
        '<span class="k-lbl">' + (a.label || a.id) + '</span>';
      el.draggable = true;
      el.addEventListener('dragstart', function (e) { e.dataTransfer.setData('text/plain', id); });
    }
    if (num != null) {
      var n = document.createElement('span'); n.className = 'k-num'; n.textContent = num; el.appendChild(n);
    }
    if (fixed !== 'more') {
      el.addEventListener('dragover', function (e) { e.preventDefault(); el.classList.add('drag-over'); });
      el.addEventListener('dragleave', function () { el.classList.remove('drag-over'); });
      el.addEventListener('drop', function (e) {
        e.preventDefault(); el.classList.remove('drag-over');
        var dropped = e.dataTransfer.getData('text/plain');
        setSlot(slotIdx, dropped === 'blank' ? null : dropped);
        render();
      });
    }
    return el;
  }

  function setSlot(idx, id) {
    var s = curSlots();
    while (s.length <= idx) s.push(null);
    s[idx] = id;
  }

  function render() {
    var kc = keyCount(), rot = rotationForGrid();
    var dims = displayDims(kc, rot), cols = dims[0], rows = dims[1];
    var info = pageInfo();
    if (state.page >= info.count) state.page = info.count - 1;
    if (state.page < 0) state.page = 0;

    var grid = $('deck-grid');
    grid.style.gridTemplateColumns = 'repeat(' + cols + ', 1fr)';
    grid.style.gridTemplateRows = 'repeat(' + rows + ', 1fr)';
    grid.innerHTML = '';
    for (var i = 0; i < kc; i++) {
      if (info.multi && i === kc - 1) {
        grid.appendChild(keyEl('page_next', -1, i + 1, 'more'));
      } else {
        var idx = state.page * info.usable + i;
        grid.appendChild(keyEl(curSlots()[idx] || null, idx, i + 1, null));
      }
    }
    $('page-label').textContent = 'Page ' + (state.page + 1) + ' of ' + info.count;
  }

  function renderPalette() {
    var groups = {};
    var order = [];
    state.actions.forEach(function (a) {
      if (a.id === 'blank') return;  // blank gets its own chip below
      var cat = a.category || 'Actions';
      if (!groups[cat]) { groups[cat] = []; order.push(cat); }
      groups[cat].push(a);
    });
    var pal = $('palette');
    pal.innerHTML = '';
    order.forEach(function (cat) {
      var g = document.createElement('div'); g.className = 'pal-group';
      g.innerHTML = '<div class="pal-head">' + cat + '</div>';
      var row = document.createElement('div'); row.className = 'pal-row';
      groups[cat].forEach(function (a) { row.appendChild(chip(a.id, a.label || a.id, a.icon, a.color)); });
      g.appendChild(row); pal.appendChild(g);
    });
    // Always offer a Blank chip to clear a slot.
    var other = document.createElement('div'); other.className = 'pal-group';
    other.innerHTML = '<div class="pal-head">Other</div>';
    var orow = document.createElement('div'); orow.className = 'pal-row';
    orow.appendChild(chip('blank', 'Blank', 'bi-eraser', '#475569'));
    other.appendChild(orow); pal.appendChild(other);
  }
  function chip(id, label, icon, color) {
    var el = document.createElement('div');
    el.className = 'pal-chip'; el.style.background = color || '#475569'; el.draggable = true;
    el.innerHTML = '<i class="bi ' + (icon || 'bi-lightning-charge') + '"></i>' + label;
    el.addEventListener('dragstart', function (e) { e.dataTransfer.setData('text/plain', id); });
    return el;
  }

  function applyControls() {
    $('sd-enabled').checked = !!state.status.enabled;
    $('sd-model').value = String(state.status.model);
    $('sd-rotation').value = String(state.status.rotation);
    $('sd-brightness').value = state.status.brightness;
    $('sd-model').disabled = state.status.connected;
    var badge = $('conn-badge');
    if (state.status.connected) {
      badge.className = 'conn-badge on ms-2 small';
      badge.innerHTML = '<i class="bi bi-plug-fill me-1"></i>' +
        (state.status.deck_type || 'Deck') + ' connected (' + state.status.key_count + ' keys)';
    } else {
      badge.className = 'conn-badge off ms-2 small';
      badge.innerHTML = '<i class="bi bi-plug me-1"></i>No deck reported (using selected model)';
    }
    // The deck-only controls fade for the Start Page surface.
    var deckOnly = state.surface !== 'streamdeck';
    $('deck-controls').style.opacity = deckOnly ? 0.5 : 1;
    $('sd-rotation').disabled = deckOnly;
    $('editor-title').textContent = deckOnly ? 'Start Page' : 'Stream Deck Device';
    $('enabled-wrap').style.display = deckOnly ? 'none' : '';
  }

  // ---- persistence ---------------------------------------------------------
  function trimTrailing(arr) {
    var a = arr.slice();
    while (a.length && (a[a.length - 1] === null || a[a.length - 1] === undefined)) a.pop();
    return a;
  }
  function save() {
    var status = $('save-status');
    var body = {
      streamdeck_enabled: $('sd-enabled').checked,
      deck_model: parseInt($('sd-model').value, 10),
      deck_rotation: parseInt($('sd-rotation').value, 10),
      deck_brightness: parseInt($('sd-brightness').value, 10),
    };
    var settingsSave = fetch('setup/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    var layoutSaves = ['streamdeck', 'start'].map(function (surf) {
      return fetch('layout/' + surf, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slots: trimTrailing(state.slots[surf]) }),
      });
    });
    Promise.all([settingsSave].concat(layoutSaves)).then(function (rs) {
      var ok = rs.every(function (r) { return r.ok; });
      status.textContent = ok ? 'Saved' : 'Save failed';
      status.className = 'small align-self-center ' + (ok ? 'text-success' : 'text-danger');
      setTimeout(function () { status.textContent = ''; }, 2000);
    });
  }

  function restart() {
    fetch('streamdeck/restart', { method: 'POST' }).then(function (r) { return r.json(); })
      .then(function (d) {
        var status = $('save-status');
        status.textContent = d.message || (d.ok ? 'Restarted' : 'No service');
        status.className = 'small align-self-center ' + (d.ok ? 'text-success' : 'text-secondary');
        setTimeout(function () { status.textContent = ''; }, 2500);
      });
  }

  function addPage() {
    var kc = keyCount(), usable = kc - 1, s = curSlots();
    var pages = s.length <= kc ? 1 : Math.ceil(s.length / usable);
    var target = (pages + 1) * usable;
    while (s.length < target) s.push(null);
    state.page = pageInfo().count - 1;
    render();
  }

  function switchSurface(surf) {
    state.surface = surf; state.page = 0;
    document.querySelectorAll('[data-surface-btn]').forEach(function (b) {
      var on = b.getAttribute('data-surface-btn') === surf;
      b.className = 'btn ' + (on ? 'btn-primary' : 'btn-outline-primary');
    });
    applyControls(); render();
  }

  // ---- init ----------------------------------------------------------------
  function init() {
    Promise.all([
      fetch('streamdeck/status').then(function (r) { return r.json(); }),
      fetch('actions').then(function (r) { return r.json(); }),
      fetch('layout/streamdeck').then(function (r) { return r.json(); }),
      fetch('layout/start').then(function (r) { return r.json(); }),
    ]).then(function (res) {
      state.status = res[0];
      state.actions = res[1].actions || [];
      state.actions.forEach(function (a) { state.catalog[a.id] = a; });
      state.slots.streamdeck = (res[2].slots || []).slice();
      state.slots.start = (res[3].slots || []).slice();
      applyControls(); renderPalette(); render();
    });

    $('sd-model').addEventListener('change', function () { state.page = 0; render(); });
    $('sd-rotation').addEventListener('change', render);
    $('save-btn').addEventListener('click', save);
    $('restart-btn').addEventListener('click', restart);
    $('add-page').addEventListener('click', addPage);
    $('page-prev').addEventListener('click', function () { if (state.page > 0) { state.page--; render(); } });
    $('page-next').addEventListener('click', function () {
      if (state.page < pageInfo().count - 1) { state.page++; render(); }
    });
    document.querySelectorAll('[data-surface-btn]').forEach(function (b) {
      b.addEventListener('click', function () { switchSurface(b.getAttribute('data-surface-btn')); });
    });
  }

  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
