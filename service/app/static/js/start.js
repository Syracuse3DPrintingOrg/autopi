// Start menu: run the bound action when a key is pressed. Keys that only do
// something on a physical Stream Deck (page navigation, brightness) show a hint
// instead, matching the source project's start page behavior.
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
  document.querySelectorAll('.start-key[role="button"]').forEach((el) => {
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
})();
