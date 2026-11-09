/* NullFace content script — DOM upload interceptor.
   Hooks <input type="file"> (change) and drag/drop so that every image chosen on Instagram / WhatsApp Web / LinkedIn is swapped
   for its immunized, watermarked twin *before* the site reads it. Pure JS, no page-API patching required. */
(() => {
  let enabled = true;
  chrome.runtime.sendMessage({ type: 'NF_GET_CFG' }, (c) => { if (c) enabled = c.enabled; });

  const busy = new WeakSet();
  const toB64 = (file) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result.split(',')[1]); r.onerror = rej; r.readAsDataURL(file); });
  const fromB64 = (b64, mime, name) => { const bin = atob(b64); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return new File([u], name.replace(/\.[^.]+$/, '') + '-nullface.jpg', { type: mime }); };

  function badge(text, ok = true) {
    const el = document.createElement('div');
    el.textContent = text;
    Object.assign(el.style, { position: 'fixed', zIndex: 2147483647, right: '16px', bottom: '16px', padding: '10px 14px', borderRadius: '10px', background: ok ? '#0b2a1a' : '#5b0f1c', color: '#fff', font: '600 13px system-ui', border: `1px solid ${ok ? '#22c55e' : '#ff3b5c'}`, boxShadow: '0 10px 30px rgba(0,0,0,.4)' });
    document.documentElement.appendChild(el); setTimeout(() => el.remove(), 3500);
  }

  async function swapFiles(input) {
    if (!enabled || busy.has(input)) return;
    const files = [...(input.files || [])].filter((f) => f.type.startsWith('image/'));
    if (!files.length || [...input.files].some((f) => f.name.includes('-nullface'))) return;
    busy.add(input);
    badge('NullFace: immunizing ' + files.length + ' photo(s)…');
    try {
      const dt = new DataTransfer();
      for (const f of input.files) {
        if (!f.type.startsWith('image/')) { dt.items.add(f); continue; }
        const res = await new Promise((r) => chrome.runtime.sendMessage({ type: 'NF_IMMUNIZE', b64: await toB64(f), mime: f.type, name: f.name, site: location.hostname }, r));
        if (!res || !res.ok) throw new Error(res ? res.error : 'no response');
        dt.items.add(fromB64(res.b64, res.mime, f.name));
      }
      input.files = dt.files;
      badge('NullFace: upload replaced with immunized copy ✓');
      input.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (e) {
      badge('NullFace failed: ' + e.message + ' — original upload kept', false);
    } finally { setTimeout(() => busy.delete(input), 500); }
  }

  // capture phase so we run before the site's own change handlers
  document.addEventListener('change', (e) => {
    const t = e.target;
    if (t && t.tagName === 'INPUT' && t.type === 'file' && !busy.has(t) && [...t.files].some((f) => f.type.startsWith('image/') && !f.name.includes('-nullface'))) {
      e.stopImmediatePropagation(); e.preventDefault();
      swapFiles(t);
    }
  }, true);
})();
