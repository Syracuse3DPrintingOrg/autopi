// Operator screen: the touch-first bench view. Runs a key from the start
// layout exactly like the builder's start page, plus a full-screen "Run
// test" launcher over the /tests API and a status strip (log tail, CAN
// interface state).
(function () {
  const toast = document.getElementById('toast');

  function flash(msg, ok) {
    if (!toast) return;
    toast.textContent = msg;
    toast.style.borderColor = ok === false ? '#dc3545' : 'var(--bs-border-color)';
    toast.style.display = 'block';
    clearTimeout(toast._h);
    toast._h = setTimeout(() => { toast.style.display = 'none'; }, 2000);
  }

  // -- key grid: identical behavior to the builder's start page ------------

  async function runAction(id) {
    try {
      const r = await fetch('actions/' + encodeURIComponent(id) + '/run', { method: 'POST' });
      const data = await r.json();
      if (data.data && data.data.builtin) {
        flash('That key works on a connected Stream Deck.', true);
        return;
      }
      flash(data.message || (data.ok ? 'Done' : 'Failed'), data.ok);
    } catch (e) {
      flash('Could not reach the server.', false);
    }
  }

  document.querySelectorAll('.op-key[role="button"]').forEach((el) => {
    function activate() {
      if (el.dataset.kind === 'deckonly') {
        flash('"' + (el.dataset.label || 'This') + '" runs on a connected Stream Deck.', true);
        return;
      }
      const id = el.dataset.action;
      if (id) runAction(id);
    }
    el.addEventListener('click', activate);
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
    });
  });

  // -- status strip: log tail + CAN interface state -------------------------

  async function pollStatus() {
    try {
      const r = await fetch('logs/recent?limit=1');
      const data = await r.json();
      const el = document.getElementById('log-tail');
      if (el) {
        const ev = data.events && data.events[0];
        el.textContent = ev ? ev.message : 'No recent activity';
      }
    } catch (e) { /* best-effort */ }
    try {
      const r = await fetch('can/interfaces');
      const data = await r.json();
      (data.interfaces || []).forEach((i) => {
        const dot = document.getElementById(i.channel + '-dot');
        if (dot) dot.className = 'op-can-dot ' + (i.available ? 'up' : 'down');
      });
    } catch (e) { /* best-effort */ }
  }
  pollStatus();
  setInterval(pollStatus, 5000);

  // -- run test: pick a sequence, then a big live pass/fail/confirm view ---

  const overlay = document.getElementById('run-overlay');
  const pickEl = document.getElementById('run-pick');
  const liveEl = document.getElementById('run-live');
  const titleEl = document.getElementById('run-title');
  const stepsEl = document.getElementById('run-steps');
  const iconEl = document.getElementById('run-icon');
  const labelEl = document.getElementById('run-label');
  const confirmBox = document.getElementById('confirm-box');
  const confirmText = document.getElementById('confirm-text');

  const STEP_ICONS = {
    pending: 'bi-circle', running: 'bi-arrow-repeat', pass: 'bi-check-circle-fill',
    fail: 'bi-x-circle-fill', skip: 'bi-slash-circle', pending_confirm: 'bi-question-circle-fill',
  };

  let pollTimer = null;

  function showPick() {
    stopPolling();
    liveEl.classList.add('d-none');
    pickEl.classList.remove('d-none');
    titleEl.textContent = 'Run test';
    const sequences = window.OPERATOR_SEQUENCES || [];
    pickEl.innerHTML = '';
    if (!sequences.length) {
      pickEl.innerHTML = '<div class="op-seq-empty">No test sequences yet. Build one in the builder\'s Tests page.</div>';
      return;
    }
    sequences.forEach((seq) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'op-seq-btn';
      btn.innerHTML = '<i class="bi bi-play-fill"></i><span>' +
        (seq.name || seq.id) + ' <span class="text-secondary">(' + (seq.steps || []).length + ' steps)</span></span>';
      btn.addEventListener('click', () => startRun(seq));
      pickEl.appendChild(btn);
    });
  }

  async function startRun(seq) {
    try {
      const r = await fetch('tests/' + encodeURIComponent(seq.id) + '/run', { method: 'POST' });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        flash(err.detail || 'Could not start the run.', false);
        return;
      }
      pickEl.classList.add('d-none');
      liveEl.classList.remove('d-none');
      titleEl.textContent = seq.name || seq.id;
      pollTimer = setInterval(pollRun, 500);
      pollRun();
    } catch (e) {
      flash('Could not reach the server.', false);
    }
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function renderState(state, steps) {
    iconEl.className = 'bi op-run-icon';
    confirmBox.classList.add('d-none');
    if (state === 'done') {
      const failed = steps.some((s) => s.status === 'fail');
      iconEl.classList.add(failed ? 'bi-x-circle-fill' : 'bi-check-circle-fill', failed ? 'fail' : 'pass');
      labelEl.textContent = failed ? 'Failed' : 'Passed';
      stopPolling();
    } else if (state === 'waiting_confirm') {
      iconEl.classList.add('bi-question-circle-fill', 'running');
      labelEl.textContent = 'Needs confirmation';
      const pending = steps.find((s) => s.status === 'pending_confirm');
      confirmText.textContent = (pending && pending.message) || 'Confirm the result of this step';
      confirmBox.classList.remove('d-none');
    } else {
      iconEl.classList.add('bi-arrow-repeat', 'running');
      labelEl.textContent = 'Running';
    }
  }

  function renderSteps(steps) {
    stepsEl.innerHTML = '';
    steps.forEach((s) => {
      const row = document.createElement('div');
      row.className = 'op-run-step ' + s.status;
      row.innerHTML = '<i class="bi ' + (STEP_ICONS[s.status] || 'bi-circle') + '"></i>' +
        '<span class="lbl">' + (s.label || s.type) + (s.message ? ' &mdash; ' + s.message : '') + '</span>';
      stepsEl.appendChild(row);
    });
  }

  async function pollRun() {
    try {
      const r = await fetch('tests/run/status');
      if (!r.ok) { stopPolling(); return; }
      const status = await r.json();
      renderSteps(status.steps || []);
      renderState(status.state, status.steps || []);
    } catch (e) { /* best-effort; keep polling */ }
  }

  document.getElementById('run-test-btn').addEventListener('click', () => {
    overlay.classList.add('open');
    showPick();
  });
  document.getElementById('run-close-btn').addEventListener('click', () => {
    overlay.classList.remove('open');
    stopPolling();
  });
  document.getElementById('run-again-btn').addEventListener('click', showPick);

  document.getElementById('confirm-pass').addEventListener('click', () => confirmRun(true));
  document.getElementById('confirm-fail').addEventListener('click', () => confirmRun(false));

  async function confirmRun(passed) {
    try {
      await fetch('tests/run/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ passed: passed }),
      });
      pollRun();
    } catch (e) {
      flash('Could not reach the server.', false);
    }
  }
})();
