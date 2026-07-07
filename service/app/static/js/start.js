// Start menu: run the bound action when a key is pressed.
(function () {
  const toast = document.getElementById('toast');
  function flash(msg, ok) {
    if (!toast) return;
    toast.textContent = msg;
    toast.style.background = ok ? '#166534' : '#7f1d1d';
    toast.style.display = 'block';
    setTimeout(() => { toast.style.display = 'none'; }, 1800);
  }
  async function runAction(id) {
    try {
      const r = await fetch('/actions/' + encodeURIComponent(id) + '/run', { method: 'POST' });
      const data = await r.json();
      flash(data.message || (data.ok ? 'Done' : 'Failed'), data.ok);
    } catch (e) {
      flash('Request failed', false);
    }
  }
  document.querySelectorAll('.start-key[data-action]').forEach((el) => {
    const id = el.getAttribute('data-action');
    el.addEventListener('click', () => runAction(id));
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); runAction(id); }
    });
  });
})();
