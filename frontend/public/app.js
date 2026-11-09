/* NullFace PWA — vanilla JS, no build step. Talks to the FastAPI gateway at API_BASE. */
const API_BASE = (window.NULLFACE_API || localStorage.getItem('nf_api') || location.origin).replace(/\/$/, '');
const API = API_BASE + '/api/v1';
const WS_BASE = API_BASE.replace(/^http/, 'ws');

const $ = (s) => document.querySelector(s);
const state = { token: localStorage.getItem('nf_token'), user: JSON.parse(localStorage.getItem('nf_user') || 'null') };

// ---------------------------------------------------------------- helpers
function toast(msg, ms = 2600) { const t = $('#toast'); t.textContent = msg; t.classList.remove('hidden'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.add('hidden'), ms); }
function headers(extra = {}) { return state.token ? { Authorization: 'Bearer ' + state.token, ...extra } : extra; }
async function api(path, opts = {}) {
  const r = await fetch(API + path, { ...opts, headers: headers(opts.headers || {}) });
  if (r.status === 401) { logout(); throw new Error('Session expired — sign in again'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}
function pct(x) { return Math.round((x || 0) * 100) + '%'; }
function b64img(b64, mime = 'image/png') { return `data:${mime};base64,${b64}`; }
function show(view) {
  document.querySelectorAll('.view').forEach((v) => v.classList.add('hidden'));
  $('#view-' + view).classList.remove('hidden');
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  $('#tabs').classList.toggle('hidden', view === 'auth');
  if (view === 'account') loadAccount();
}
function setBusy(id, on) { $(id).classList.toggle('hidden', !on); }

// ---------------------------------------------------------------- health
async function health() {
  try {
    const h = await fetch(API + '/health').then((r) => r.json());
    $('#status').className = 'status ok';
    $('#statusText').textContent = `${h.db} · ${h.identity_backend}${h.groq ? ' · groq' : ''}`;
    state.health = h;
  } catch { $('#status').className = 'status bad'; $('#statusText').textContent = 'API offline'; }
}

// ---------------------------------------------------------------- auth
$('#authForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const j = await api('/auth/session', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: $('#authEmail').value.trim(), full_name: $('#authName').value.trim() }) });
    state.token = j.access_token; state.user = j.user;
    localStorage.setItem('nf_token', j.access_token); localStorage.setItem('nf_user', JSON.stringify(j.user));
    toast(`Welcome, ${j.user.full_name.split(' ')[0]}`); show('cloak');
  } catch (err) { toast(err.message); }
});
function logout() { state.token = null; state.user = null; localStorage.removeItem('nf_token'); localStorage.removeItem('nf_user'); show('auth'); }
$('#logoutBtn').addEventListener('click', logout);
document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => show(b.dataset.view)));

// ---------------------------------------------------------------- cloak
let cloakFileObj = null;
$('#cloakFile').addEventListener('change', (e) => { cloakFileObj = e.target.files[0]; $('#cloakBtn').disabled = !cloakFileObj; if (cloakFileObj) $('#cloakFile').nextElementSibling.textContent = '📷 ' + cloakFileObj.name; });
$('#cloakBtn').addEventListener('click', async () => {
  if (!cloakFileObj) return;
  setBusy('#cloakProgress', true); $('#cloakBtn').disabled = true; $('#cloakResult').classList.add('hidden');
  const t0 = performance.now();
  try {
    const fd = new FormData(); fd.append('file', cloakFileObj); fd.append('profile', $('#cloakProfile').value); fd.append('output', 'png');
    const r = await api('/cloak/immunize', { method: 'POST', body: fd });
    const wall = Math.round(performance.now() - t0);
    $('#cmpBefore').src = URL.createObjectURL(cloakFileObj);
    $('#cmpAfter').src = b64img(r.image_b64, r.mime);
    $('#cloakDownload').href = b64img(r.image_b64, r.mime);
    const m = r.metrics;
    $('#cloakMetrics').innerHTML = [
      ['SSIM', m.ssim.toFixed(4), m.ssim >= 0.96 ? 'good' : 'warn', 'perceptual quality (≥ 0.96 gate)'],
      ['PSNR', m.psnr_db + ' dB', 'good', 'signal fidelity'],
      ['Identity shift', m.identity_shift_cosine.toFixed(4), '', m.identity_backend],
      ['Watermark after Q=' + m.watermark_survives_jpeg_q, m.watermark_hamming_after_compression + ' / 64 bits flipped', m.watermark_hamming_after_compression <= 7 ? 'good' : 'warn', 'blind re-extraction after JPEG'],
      ['Latency', r.timings_ms.total + ' ms', r.timings_ms.total <= 1800 ? 'good' : 'warn', `server · ${wall} ms round-trip`],
      ['Signature', r.watermark_hex, '', '64-bit HMAC-derived canary'],
    ].map(([k, v, c, s]) => `<div class="metric ${c}"><b>${v}</b><span>${k}</span><br><span>${s}</span></div>`).join('');
    const { image_b64, ...rest } = r; $('#cloakJson').textContent = JSON.stringify(rest, null, 2);
    $('#cloakResult').classList.remove('hidden');
    state.lastCloak = r;
    toast(`Immunized in ${r.timings_ms.total} ms · SSIM ${m.ssim}`);
  } catch (err) { toast('Cloak failed: ' + err.message, 5000); }
  finally { setBusy('#cloakProgress', false); $('#cloakBtn').disabled = false; }
});
$('#cmpRange').addEventListener('input', (e) => { $('#cmpAfterWrap').style.width = e.target.value + '%'; });
$('#cloakShare').addEventListener('click', async () => {
  if (!state.lastCloak) return;
  try {
    const blob = await (await fetch(b64img(state.lastCloak.image_b64, state.lastCloak.mime))).blob();
    const file = new File([blob], 'nullface-immunized.png', { type: 'image/png' });
    if (navigator.canShare && navigator.canShare({ files: [file] })) await navigator.share({ files: [file], title: 'NullFace protected photo' });
    else toast('Sharing not supported here — use Download.');
  } catch (e) { if (e.name !== 'AbortError') toast(e.message); }
});

// ---------------------------------------------------------------- stress test
let stressFileObj = null;
$('#stressFile').addEventListener('change', (e) => { stressFileObj = e.target.files[0]; $('#stressBtn').disabled = !stressFileObj; });
$('#stressBtn').addEventListener('click', async () => {
  setBusy('#stressProgress', true); $('#stressBtn').disabled = true; $('#stressResult').classList.add('hidden');
  try {
    const fd = new FormData(); fd.append('file', stressFileObj); fd.append('profile', $('#stressProfile').value);
    const r = await api('/cloak/stress-test', { method: 'POST', body: fd });
    const rep = r.report, im = r.images;
    $('#stOrig').src = b64img(im.original_compressed, 'image/jpeg'); $('#stCloak').src = b64img(im.cloaked_compressed, 'image/jpeg');
    const swapOk = rep.swap && rep.swap.available;
    $('#stSwapOrig').classList.toggle('hidden', !swapOk); $('#stSwapCloak').classList.toggle('hidden', !swapOk);
    if (swapOk) { $('#stSwapOrig').src = b64img(im.swap_on_original, 'image/jpeg'); $('#stSwapCloak').src = b64img(im.swap_on_cloaked, 'image/jpeg'); }
    const kv = (o, extra = []) => [['Faces detected', o.faces_detected], ['Identity shift (cos)', o.identity_shift_cosine], ...extra].map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('');
    $('#stOrigM').innerHTML = kv(rep.original, swapOk ? [['Swap similarity', rep.swap.swap_similarity_original]] : []);
    $('#stCloakM').innerHTML = kv(rep.cloaked, [['SSIM', rep.cloaked.ssim], ['PSNR', rep.cloaked.psnr_db + ' dB'], ...(swapOk ? [['Swap similarity', rep.swap.swap_similarity_cloaked]] : [])]);
    $('#stNote').textContent = swapOk
      ? `InsightFace inswapper_128 ran on both images after JPEG Q=${rep.compression_quality}. Lower swap similarity on the immunized photo = the swap failed to carry the identity.`
      : `Identity backend: ${rep.identity_backend}. ${rep.swap.reason}. Install insightface + onnxruntime and drop inswapper_128.onnx in the model cache to run the live face-swap.`;
    $('#stressResult').classList.remove('hidden');
  } catch (err) { toast('Stress test failed: ' + err.message, 5000); }
  finally { setBusy('#stressProgress', false); $('#stressBtn').disabled = false; }
});

// ---------------------------------------------------------------- deeplens
let forFileObj = null;
$('#forFile').addEventListener('change', (e) => { forFileObj = e.target.files[0]; $('#forBtn').disabled = !forFileObj; });
$('#forBtn').addEventListener('click', async () => {
  setBusy('#forProgress', true); $('#forBtn').disabled = true; $('#forResult').classList.add('hidden');
  try {
    const fd = new FormData(); fd.append('file', forFileObj);
    const r = await api('/forensics/inspect', { method: 'POST', body: fd });
    const v = $('#forVerdict'); v.className = 'verdict ' + r.verdict;
    const icons = { AUTHENTIC: '✅', SUSPICIOUS: '⚠️', SYNTHETIC_DEEPFAKE: '🚨', STOLEN_IDENTITY_MATCH: '🔗' };
    if (r.stage1_canary_link) {
      const s1 = r.stage1_canary_link, m = s1.match;
      v.innerHTML = `${icons[r.verdict]} ${r.verdict.replace(/_/g, ' ')} <small>${r.latency_ms} ms</small>`;
      $('#forStage1').innerHTML = `<h3>Stage 1 · Canary-Link extraction <small class="muted">${s1.latency_ms} ms</small></h3>
        <div class="kv"><div><span>Extracted signature</span><b>${s1.extracted_hex}</b></div><div><span>Confidence</span><b>${pct(s1.confidence)}</b></div>
        ${m ? `<div><span>Owner</span><b>${m.owner_name}</b></div><div><span>Email</span><b>${m.owner_email}</b></div><div><span>Immunized at</span><b>${m.immunized_at.slice(0, 19).replace('T', ' ')}</b></div><div><span>Hamming / BER</span><b>${m.hamming_distance} bits · ${pct(m.ber)}</b></div>`
             : `<div><span>Ledger match</span><b>none (BER &gt; ${pct(s1.ber_threshold)} or unprotected photo)</b></div>`}</div>`;
      const f = r.stage2_fft, vit = r.stage2_vit;
      $('#forStage2').innerHTML = `<h3>Stage 2 · 2D-FFT + ViT</h3><div class="kv">
        <div><span>Deepfake probability</span><b>${pct(vit.deepfake_probability)}</b></div><div><span>Classifier</span><b>${vit.backend}</b></div>
        <div><span>FFT anomaly score</span><b>${f.fft_anomaly_score}</b></div><div><span>High-freq tail</span><b>${f.high_freq_tail}</b></div><div><span>Spectral spikes</span><b>${f.periodic_peaks}</b></div></div>`;
      const c = r.stage3_c2pa;
      $('#forStage3').innerHTML = `<h3>Stage 3 · C2PA provenance</h3><div class="kv">
        <div><span>C2PA manifest</span><b>${c.c2pa_manifest_present ? 'present' : 'absent'}</b></div><div><span>EXIF / XMP</span><b>${c.exif_present ? 'yes' : 'no'} / ${c.xmp_present ? 'yes' : 'no'}</b></div>
        <div><span>Creator tool</span><b>${c.creator_tool || '—'}</b></div></div><p class="muted">${c.note}</p>`;
      $('#forSpectrum').src = b64img(r.visuals.spectrum_png_b64); $('#forCam').src = b64img(r.visuals.gradcam_png_b64);
      $('#forSpectrum').parentElement.parentElement.parentElement.classList.remove('hidden');
    } else {
      v.innerHTML = `${icons[r.verdict]} ${r.verdict.replace(/_/g, ' ')} <small>audio · ${r.duration_s}s · ${r.latency_ms} ms</small>`;
      $('#forStage1').innerHTML = `<h3>Audio clone forensics</h3><div class="kv"><div><span>Voice-clone score</span><b>${pct(r.voice_clone_score)}</b></div><div><span>Backend</span><b>${r.backend}</b></div>
        ${r.features ? Object.entries(r.features).map(([k, x]) => `<div><span>${k}</span><b>${x}</b></div>`).join('') : ''}</div>`;
      $('#forStage2').innerHTML = ''; $('#forStage3').innerHTML = '';
      $('#forSpectrum').parentElement.parentElement.parentElement.classList.add('hidden');
    }
    const { visuals, ...rest } = r; $('#forJson').textContent = JSON.stringify(rest, null, 2);
    $('#forResult').classList.remove('hidden');
  } catch (err) { toast('Inspect failed: ' + err.message, 5000); }
  finally { setBusy('#forProgress', false); $('#forBtn').disabled = false; }
});

// ---------------------------------------------------------------- scamradar: text audit
const SAMPLE = 'Main CBI Mumbai se Inspector bol raha hoon. Aapke naam par ek parcel pakda gaya hai jisme drugs hai, money laundering ka case darj hua hai. Aap digital arrest me hain — video call band mat karna, ghar wale ko bhi mat batana. Verification ke liye abhi 2 lakh RBI ke safe account me transfer karo: http://rbi-verify-secure.xyz/kyc.apk';
$('#auditSample').addEventListener('click', () => { $('#auditText').value = SAMPLE; });
$('#auditBtn').addEventListener('click', async () => {
  const text = $('#auditText').value.trim(); if (!text) return;
  try {
    const r = await api('/scam/audit-text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, channel: 'WHATSAPP_MSG' }) });
    const out = $('#auditResult'); out.classList.remove('hidden');
    out.innerHTML = `<div class="verdict ${r.risk_level === 'LOW' ? 'AUTHENTIC' : r.risk_level === 'MEDIUM' ? 'SUSPICIOUS' : 'SYNTHETIC_DEEPFAKE'}">${r.risk_level} · ${pct(r.coercion_risk_score)} <small>${r.latency_ms} ms</small></div>
      <div class="chips">${r.tactics.map((t) => `<span class="chip">${t.replace(/_/g, ' ')}</span>`).join('') || '<span class="chip soft">no coercion tactics</span>'}</div>
      <p class="note">${r.recommendation}</p>
      ${r.urls.length ? `<h3>Links</h3><div class="kv">${r.urls.map((u) => `<div><span>${u.url}</span><b>${pct(u.risk)} ${u.reasons.length ? '· ' + u.reasons.join(', ') : ''}</b></div>`).join('')}</div>` : ''}
      <details><summary>Retrieved I4C scripts (RAG evidence)</summary><div class="kv">${r.evidence.map((e) => `<div><span>${e.id} · ${e.category} · ${e.i4c_ref || ''}</span><b>sim ${e.similarity}</b></div>`).join('')}</div><pre>${JSON.stringify({ tactic_scores: r.tactic_scores, lexicon: r.lexicon, backend: r.backend }, null, 2)}</pre></details>`;
  } catch (err) { toast('Audit failed: ' + err.message, 5000); }
});

// ---------------------------------------------------------------- scamradar: live call shield
let callWS = null, audioCtx = null, mediaStream = null, procNode = null, recog = null, pcmQueue = [];
const CHUNK_SECONDS = 2;

function downsampleTo16k(float32, fromRate) {
  if (fromRate === 16000) return float32;
  const ratio = fromRate / 16000, n = Math.floor(float32.length / ratio), out = new Float32Array(n);
  for (let i = 0; i < n; i++) { const s = Math.floor(i * ratio), e = Math.floor((i + 1) * ratio); let sum = 0, c = 0; for (let j = s; j < e && j < float32.length; j++) { sum += float32[j]; c++; } out[i] = c ? sum / c : 0; }
  return out;
}
function toPCM16(f32) { const b = new Int16Array(f32.length); for (let i = 0; i < f32.length; i++) { const s = Math.max(-1, Math.min(1, f32[i])); b[i] = s < 0 ? s * 0x8000 : s * 0x7fff; } return b; }

async function startCall() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: false } });
  } catch { toast('Microphone permission denied'); return; }
  const url = `${WS_BASE}/ws/v1/scam/call-stream${state.token ? '?token=' + encodeURIComponent(state.token) : ''}`;
  callWS = new WebSocket(url); callWS.binaryType = 'arraybuffer';
  callWS.onopen = () => { $('#callState').textContent = 'listening…'; callWS.send(JSON.stringify({ type: 'config', sample_rate: 16000, language: $('#callLang').value.startsWith('hi') ? 'hi' : 'en' })); };
  callWS.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.type === 'ready') { state.asr = m.asr; if (m.asr !== 'groq') startRecognition(); toast(`Shield ready · ASR: ${m.asr} · voice: ${m.voice_backend}`); } else if (m.type === 'update') renderUpdate(m); };
  callWS.onclose = () => { $('#callState').textContent = 'stopped'; };
  callWS.onerror = () => toast('WebSocket error');

  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = audioCtx.createMediaStreamSource(mediaStream);
  procNode = audioCtx.createScriptProcessor(4096, 1, 1);
  let buf = [], len = 0; const target = 16000 * CHUNK_SECONDS;
  procNode.onaudioprocess = (e) => {
    const ds = downsampleTo16k(e.inputBuffer.getChannelData(0), audioCtx.sampleRate);
    buf.push(ds); len += ds.length;
    if (len >= target) {
      const all = new Float32Array(len); let o = 0; for (const b of buf) { all.set(b, o); o += b.length; }
      buf = []; len = 0;
      if (callWS && callWS.readyState === 1) callWS.send(toPCM16(all).buffer);
    }
  };
  src.connect(procNode); procNode.connect(audioCtx.destination);
  $('#callStart').classList.add('hidden'); $('#callStop').classList.remove('hidden');
  $('#callTranscript').innerHTML = ''; $('#callTactics').innerHTML = ''; $('#callAlert').classList.add('hidden');
}
function startRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('No on-device speech recognition — set GROQ_API_KEY on the server for Whisper ASR'); return; }
  recog = new SR(); recog.lang = $('#callLang').value; recog.continuous = true; recog.interimResults = false;
  recog.onresult = (ev) => { for (let i = ev.resultIndex; i < ev.results.length; i++) if (ev.results[i].isFinal) { const text = ev.results[i][0].transcript; if (callWS && callWS.readyState === 1) callWS.send(JSON.stringify({ type: 'transcript', text })); } };
  recog.onend = () => { if (callWS && callWS.readyState === 1) try { recog.start(); } catch {} };
  try { recog.start(); } catch {}
}
function stopCall() {
  if (recog) { recog.onend = null; try { recog.stop(); } catch {} recog = null; }
  if (procNode) { procNode.disconnect(); procNode = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  if (mediaStream) { mediaStream.getTracks().forEach((t) => t.stop()); mediaStream = null; }
  if (callWS) { try { callWS.send(JSON.stringify({ type: 'end' })); } catch {} callWS.close(); callWS = null; }
  $('#callStart').classList.remove('hidden'); $('#callStop').classList.add('hidden'); $('#callState').textContent = 'idle';
}
function renderUpdate(m) {
  $('#riskRing').style.setProperty('--v', Math.round(m.coercion_risk_score * 100)); $('#riskVal').textContent = pct(m.coercion_risk_score);
  $('#cloneRing').style.setProperty('--v', Math.round(m.voice_clone_score * 100)); $('#cloneVal').textContent = pct(m.voice_clone_score);
  $('#callTactics').innerHTML = m.tactics.map((t) => `<span class="chip">${t.replace(/_/g, ' ')}</span>`).join('');
  if (m.transcript_chunk) {
    let html = m.transcript_chunk;
    Object.values(m.lexicon || {}).flat().forEach((w) => { html = html.replace(new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'), (x) => `<mark>${x}</mark>`); });
    const tr = $('#callTranscript'); if (tr.querySelector('em')) tr.innerHTML = '';
    const p = document.createElement('p'); p.innerHTML = html; tr.appendChild(p); $('#callTranscript').scrollTop = 1e9;
  }
  const a = $('#callAlert');
  if (m.alert) { a.className = 'alert ' + m.alert.level; a.textContent = `${m.alert.level}: ${m.alert.message}`; if (m.alert.level === 'CRITICAL' && navigator.vibrate) navigator.vibrate([200, 100, 200]); }
  else a.classList.add('hidden');
  $('#callJson').textContent = JSON.stringify({ session: m.session, latency_ms: m.latency_ms, voice_clone_chunk: m.voice_clone_chunk, evidence: m.evidence }, null, 2);
  $('#callState').textContent = `chunk ${m.session.chunks} · ${m.latency_ms} ms`;
}
$('#callStart').addEventListener('click', startCall);
$('#callStop').addEventListener('click', stopCall);

// ---------------------------------------------------------------- account
async function loadAccount() {
  try {
    const me = await api('/auth/me');
    $('#accountCard').innerHTML = `<h3>${me.full_name} <span class="tag">${me.tier}</span></h3><p class="muted">${me.email} · ${me.id}</p>
      <h3>Immunization ledger (${me.ledger.length})</h3>
      ${me.ledger.length ? `<div class="kv">${me.ledger.map((l) => `<div><span>${l.created_at.slice(0, 16).replace('T', ' ')} · ${l.protection_profile}</span><b>SSIM ${l.ssim_score} · pHash ${l.perceptual_hash}</b></div>`).join('')}</div>` : '<p class="muted">No protected photos yet.</p>'}`;
  } catch (err) { $('#accountCard').textContent = err.message; }
}
$('#keyBtn').addEventListener('click', async () => {
  try { const r = await api('/auth/api-key', { method: 'POST' }); $('#keyOut').textContent = r.api_key + '\n' + r.note; $('#keyOut').classList.remove('hidden'); }
  catch (err) { toast(err.message); }
});

// ---------------------------------------------------------------- boot
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
health(); setInterval(health, 30000);
show(state.token ? 'cloak' : 'auth');
