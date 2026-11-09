/* NullFace MV3 service worker: talks to the API with the scoped nf_live_ key and serves the context-menu quick cloak. */
const DEFAULTS = { apiBase: 'http://localhost:8000', apiKey: '', profile: 'WHATSAPP_ROBUST', enabled: true };

async function cfg() { return { ...DEFAULTS, ...(await chrome.storage.sync.get(Object.keys(DEFAULTS))) }; }

async function immunize(blob, filename) {
  const c = await cfg();
  if (!c.apiKey) throw new Error('No API key — open NullFace options and paste your nf_live_ key');
  const fd = new FormData();
  fd.append('file', blob, filename || 'upload.jpg');
  fd.append('profile', c.profile);
  fd.append('output', 'jpeg');
  const r = await fetch(`${c.apiBase.replace(/\/$/, '')}/api/v1/cloak/immunize`, { method: 'POST', headers: { 'X-API-Key': c.apiKey }, body: fd });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'NF_IMMUNIZE') {
    (async () => {
      try {
        const bytes = Uint8Array.from(atob(msg.b64), (ch) => ch.charCodeAt(0));
        const res = await immunize(new Blob([bytes], { type: msg.mime || 'image/jpeg' }), msg.name);
        const { apiKey, ...stats } = await cfg();
        await chrome.storage.local.set({ lastCloak: { at: Date.now(), site: msg.site, ssim: res.metrics.ssim, ms: res.timings_ms.total, hex: res.watermark_hex } });
        chrome.notifications?.create({ type: 'basic', iconUrl: 'icons/icon-128.png', title: 'NullFace: photo immunized',
          message: `${msg.site}: SSIM ${res.metrics.ssim}, watermark ${res.watermark_hex}, ${res.timings_ms.total} ms` });
        sendResponse({ ok: true, b64: res.image_b64, mime: res.mime });
      } catch (e) { sendResponse({ ok: false, error: e.message }); }
    })();
    return true; // async
  }
  if (msg.type === 'NF_GET_CFG') { cfg().then((c) => sendResponse({ enabled: c.enabled })); return true; }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: 'nf-cloak', title: 'Cloak with NullFace (open in app)', contexts: ['image'] });
});
chrome.contextMenus.onClicked.addListener(async (info) => {
  if (info.menuItemId === 'nf-cloak') { const c = await cfg(); chrome.tabs.create({ url: `${c.apiBase}/?src=${encodeURIComponent(info.srcUrl)}` }); }
});
