const ids = ['apiBase', 'apiKey', 'profile'];
chrome.storage.sync.get({ apiBase: 'http://localhost:8000', apiKey: '', profile: 'WHATSAPP_ROBUST' }, (c) => ids.forEach((k) => (document.getElementById(k).value = c[k])));
document.getElementById('save').addEventListener('click', () => {
  const v = Object.fromEntries(ids.map((k) => [k, document.getElementById(k).value.trim()]));
  chrome.storage.sync.set(v, () => { document.getElementById('msg').textContent = 'Saved ✓'; });
});
