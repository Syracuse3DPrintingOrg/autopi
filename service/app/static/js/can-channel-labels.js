// Fills CAN channel pickers with the interfaces that actually exist on this
// device (from /can/interfaces/detected), merged with each configured
// interface's purpose/label (from /can/interfaces/config), so a user picks a
// real channel and always knows which physical bus it is instead of typing a
// name blind. It populates:
//   - any <select data-channel-select> as a dropdown of channels, and
//   - any <datalist id="can-channel-list"> for plain text inputs.
// Safe to include on any page; it no-ops if neither is present.
(function () {
  const selects = document.querySelectorAll('select[data-channel-select]');
  const datalist = document.getElementById('can-channel-list');
  if (!selects.length && !datalist) return;

  function labelFor(name, detected, configured) {
    const parts = [];
    const d = detected[name];
    const c = configured[name];
    if (c && c.purpose_label && c.purpose_label !== name) parts.push(c.purpose_label);
    if (d && d.description) parts.push(d.description);
    if (d && d.up === false) parts.push('down');
    return parts.length ? name + ', ' + parts.join(', ') : name;
  }

  Promise.all([
    fetch('can/interfaces/detected').then((r) => r.json()).catch(() => ({ interfaces: [] })),
    fetch('can/interfaces/config').then((r) => r.json()).catch(() => ({ interfaces: [] })),
  ]).then(([det, cfg]) => {
    const detected = {};
    (det.interfaces || []).forEach((i) => { detected[i.name] = i; });
    const configured = {};
    (cfg.interfaces || []).forEach((i) => { configured[i.id] = i; });

    // Channel order: detected first (they are real), then any configured
    // channel that is not currently detected.
    const names = (det.interfaces || []).map((i) => i.name);
    (cfg.interfaces || []).forEach((i) => { if (!names.includes(i.id)) names.push(i.id); });

    selects.forEach((sel) => {
      const current = sel.value || sel.getAttribute('data-default') || '';
      sel.innerHTML = '';
      if (!names.length) {
        // Nothing detected or configured (e.g. off a Pi): keep it usable.
        ['can0', 'can1', 'can2'].forEach((n) => names.push(n));
      }
      names.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = labelFor(name, detected, configured);
        sel.appendChild(opt);
      });
      if (current && names.includes(current)) sel.value = current;
    });

    if (datalist) {
      datalist.innerHTML = '';
      names.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.label = labelFor(name, detected, configured);
        datalist.appendChild(opt);
      });
    }
  });
})();
