// Populates <datalist id="can-channel-list"> with every configured CAN
// interface (channel name plus its purpose or label), so any channel text
// input on the page (monitor, simulate, raw send) can suggest them and a
// user always knows which physical bus "can0" (or whatever it was named)
// actually is. Safe to include on any page; it no-ops if the datalist is
// not present.
(function () {
  const datalist = document.getElementById('can-channel-list');
  if (!datalist) return;

  fetch('can/interfaces/config').then((r) => r.json()).then((d) => {
    datalist.innerHTML = '';
    (d.interfaces || []).forEach((iface) => {
      const opt = document.createElement('option');
      opt.value = iface.id;
      const purposeLabel = iface.purpose_label || iface.label || '';
      opt.label = purposeLabel && purposeLabel !== iface.id
        ? iface.id + ' — ' + purposeLabel
        : iface.id;
      datalist.appendChild(opt);
    });
  }).catch(() => {});
})();
