chrome.storage.sync.get({ enabled: true }, (c) => { document.getElementById('enabled').checked = c.enabled; });
document.getElementById('enabled').addEventListener('change', (e) => chrome.storage.sync.set({ enabled: e.target.checked }));
chrome.storage.local.get('lastCloak', ({ lastCloak }) => { if (lastCloak) document.querySelector('#last b').textContent = `${lastCloak.site} · SSIM ${lastCloak.ssim} · ${lastCloak.ms} ms`; });
