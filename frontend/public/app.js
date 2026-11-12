/**
 * NullFace (KavachAI) - Client Orchestration & Interactive Terminal
 */

let selectedFile = null;
let forensicsFile = null;
let currentSampleBase64 = null;
let currentImmunizedBase64 = null;
let demoScenarios = [];
let activeWs = null;
let streamInterval = null;

// Hero section playback state
let isPlaying = true;
let heroProgress = 48;
let heroTimelineInterval = null;

// Initialize Dashboard
document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    lucide.createIcons();
  }
  setupComparisonSlider();
  fetchSystemStatus();
  fetchDemoScenarios();
  refreshLedger();
  loadSamplePortrait();
  startHeroTimeline();
  initHeroVideo();

  // Forwarded citizen identity from hero registration input
  try {
    const params = new URLSearchParams(window.location.search);
    const identity = params.get("identity") || params.get("citizen") || params.get("store");
    if (identity) {
      const presetBtnSpan = document.querySelector("button[onclick*='loadSamplePortrait'] span");
      if (presetBtnSpan) {
        presetBtnSpan.textContent = `Load Preset Demo Citizen: ${identity}`;
      }
    }
  } catch (e) {}
});

// ==========================================
// HERO SECTION INTERACTIVE CONTROLS
// ==========================================
function initHeroVideo() {
  const video = document.getElementById("hero-video");
  if (!video) return;

  video.addEventListener("timeupdate", () => {
    if (video.duration && !isNaN(video.duration)) {
      const pct = (video.currentTime / video.duration) * 100;
      const bar = document.getElementById("hero-timeline-progress");
      if (bar) bar.style.width = `${pct}%`;
    }
  });

  video.addEventListener("play", () => {
    isPlaying = true;
    updateHeroPlayPauseButton();
  });

  video.addEventListener("pause", () => {
    isPlaying = false;
    updateHeroPlayPauseButton();
  });

  // Ensure muted autoplay succeeds in modern browsers
  video.muted = true;
  const playPromise = video.play();
  if (playPromise !== undefined) {
    playPromise.catch(() => {});
  }
}

function startHeroTimeline() {
  if (heroTimelineInterval) {
    clearInterval(heroTimelineInterval);
    heroTimelineInterval = null;
  }
  // If video is present, video timeupdate events handle the progress bar
  const video = document.getElementById("hero-video");
  if (video) return;

  const bar = document.getElementById("hero-timeline-progress");
  if (!bar) return;
  heroTimelineInterval = setInterval(() => {
    if (isPlaying) {
      heroProgress = (heroProgress + 0.3) % 100;
      const b = document.getElementById("hero-timeline-progress");
      if (b) b.style.width = `${heroProgress}%`;
    }
  }, 100);
}

function toggleHeroPlayback() {
  const video = document.getElementById("hero-video");
  if (video) {
    if (video.paused) {
      video.play().catch(() => {});
      isPlaying = true;
    } else {
      video.pause();
      isPlaying = false;
    }
  } else {
    isPlaying = !isPlaying;
  }
  updateHeroPlayPauseButton();
}

function updateHeroPlayPauseButton() {
  const btn = document.getElementById("btn-hero-pause");
  const video = document.getElementById("hero-video");
  const playing = video ? !video.paused : isPlaying;
  if (btn) {
    if (playing) {
      btn.innerHTML = `<svg id="hero-pause-svg" class="w-4 h-4 fill-current text-[#e8eefc]" viewBox="0 0 24 24"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>`;
    } else {
      btn.innerHTML = `<svg id="hero-pause-svg" class="w-4 h-4 fill-current text-[#e8eefc] ml-0.5" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
    }
  }
}

function seekHeroTimeline(event) {
  const rect = event.currentTarget.getBoundingClientRect();
  const clickX = event.clientX - rect.left;
  const ratio = Math.min(Math.max(clickX / rect.width, 0), 1);
  const video = document.getElementById("hero-video");
  if (video && video.duration && !isNaN(video.duration)) {
    video.currentTime = ratio * video.duration;
    heroProgress = ratio * 100;
  } else {
    heroProgress = ratio * 100;
  }
  const bar = document.getElementById("hero-timeline-progress");
  if (bar) bar.style.width = `${heroProgress}%`;
}

function handleHeroSubmit() {
  const identityInput = document.getElementById("hero-identity-name") || document.getElementById("hero-store-name");
  const identityName = identityInput ? identityInput.value.trim() : "";
  const nameToUse = identityName || "Rahul Sharma";
  
  const btn = document.getElementById("btn-hero-submit");
  if (btn) {
    btn.innerHTML = `<svg class="w-4 h-4 text-white animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
    setTimeout(() => {
      btn.innerHTML = `<svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
      scrollToSuite(nameToUse);
      switchTab('tab-cloak');
      setTimeout(() => {
        btn.innerHTML = `<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>`;
      }, 2000);
    }, 350);
  } else {
    scrollToSuite(nameToUse);
    switchTab('tab-cloak');
  }
}

function scrollToSuite(identityName) {
  const target = document.getElementById("defense-suite");
  if (target) {
    target.scrollIntoView({ behavior: "smooth" });
  } else {
    const query = identityName ? `?identity=${encodeURIComponent(identityName)}&store=${encodeURIComponent(identityName)}` : "";
    window.location.href = `photocloak.html${query}`;
  }
}

// ==========================================
// TAB NAVIGATION
// ==========================================
function switchTab(tabId) {
  document.querySelectorAll(".tab-content").forEach((el) => el.classList.add("hidden"));
  document.querySelectorAll(".tab-btn").forEach((el) => el.classList.remove("active"));
  
  const targetTab = document.getElementById(tabId);
  if (targetTab) {
    targetTab.classList.remove("hidden");
  }

  const activeBtn = document.getElementById(`btn-${tabId}`);
  if (activeBtn) {
    activeBtn.classList.add("active");
  }

  if (window.lucide) {
    lucide.createIcons();
  }
}

// ==========================================
// SYSTEM STATUS & DEMO FIXTURES
// ==========================================
async function fetchSystemStatus() {
  try {
    const res = await fetch("/api/v1/system/status");
    const data = await res.json();
    const ind = document.getElementById("system-status-indicator");
    if (ind && data.status === "OPERATIONAL") {
      ind.textContent = `GATEWAY: ONLINE (${data.protected_assets_count} ASSETS)`;
    }
  } catch (err) {
    console.error("Status fetch failed:", err);
  }
}

async function fetchDemoScenarios() {
  try {
    let res = await fetch("/api/v1/demo/scenarios").catch(() => null);
    if (!res || !res.ok) {
      res = await fetch("/api/v1/system/demo-scenarios").catch(() => null);
    }
    if (!res || !res.ok) return;
    const data = await res.json();
    demoScenarios = data.scenarios || [];
    const scamInput = document.getElementById("scam-text-input");
    if (scamInput && !scamInput.value && demoScenarios.length > 0) {
      scamInput.value = demoScenarios[0].transcript;
      executeScamAudit();
    }
  } catch (err) {
    console.error("Scenarios fetch failed:", err);
  }
}

async function loadSamplePortrait() {
  try {
    let res = await fetch("/api/v1/demo/sample-portrait").catch(() => null);
    if (!res || !res.ok) {
      res = await fetch("/api/v1/system/sample-portrait").catch(() => null);
    }
    if (!res || !res.ok) return;
    const data = await res.json();
    currentSampleBase64 = data.sample_image_data_url || data.image_data_url;

    const preview = document.getElementById("preview-image");
    const prompt = document.getElementById("upload-prompt");
    if (preview && currentSampleBase64) {
      preview.src = currentSampleBase64;
      preview.classList.remove("hidden");
    }
    if (prompt && currentSampleBase64) {
      prompt.classList.add("hidden");
    }

    // Populate comparison preview box initially
    const compOrig = document.getElementById("comp-original");
    const compImm = document.getElementById("comp-immunized");
    if (compOrig && currentSampleBase64) compOrig.src = currentSampleBase64;
    if (compImm && currentSampleBase64) compImm.src = currentSampleBase64;
    selectedFile = null;
  } catch (err) {
    console.error("Sample portrait fetch failed:", err);
  }
}

// File Upload Handler for Ingestion
function handleFileSelect(e) {
  const file = e.target.files[0];
  if (!file) return;
  selectedFile = file;

  const reader = new FileReader();
  reader.onload = (event) => {
    const preview = document.getElementById("preview-image");
    const prompt = document.getElementById("upload-prompt");
    if (preview) {
      preview.src = event.target.result;
      preview.classList.remove("hidden");
    }
    if (prompt) {
      prompt.classList.add("hidden");
    }

    const compOrig = document.getElementById("comp-original");
    const compImm = document.getElementById("comp-immunized");
    if (compOrig) compOrig.src = event.target.result;
    if (compImm) compImm.src = event.target.result;
  };
  reader.readAsDataURL(file);
}

// ==========================================
// INTERACTIVE COMPARISON SLIDER SETUP
// ==========================================
function setupComparisonSlider() {
  const box = document.getElementById("comparison-box");
  const wrapper = document.getElementById("comp-wrapper-immunized");
  const handle = document.getElementById("slider-handle");
  if (!box || !wrapper || !handle) return;

  let isDragging = false;

  const updateSlider = (clientX) => {
    const rect = box.getBoundingClientRect();
    let pos = (clientX - rect.left) / rect.width;
    pos = Math.max(0.02, Math.min(0.98, pos));
    const pct = pos * 100;
    wrapper.style.width = `${pct}%`;
    handle.style.left = `${pct}%`;
  };

  handle.addEventListener("mousedown", () => (isDragging = true));
  window.addEventListener("mouseup", () => (isDragging = false));
  window.addEventListener("mousemove", (e) => {
    if (isDragging) updateSlider(e.clientX);
  });

  handle.addEventListener("touchstart", () => (isDragging = true), { passive: true });
  window.addEventListener("touchend", () => (isDragging = false));
  window.addEventListener("touchmove", (e) => {
    if (isDragging && e.touches[0]) updateSlider(e.touches[0].clientX);
  }, { passive: true });
}

// ==========================================
// ACT 1: EXECUTE PHOTOCLOAK IMMUNIZATION
// ==========================================
async function executeImmunization() {
  const btn = document.getElementById("btn-immunize");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin mr-2">⏳</span> Perturbing YCbCr Mid-Freqs & Embedding DWT...`;
  }

  try {
    const profileSelect = document.getElementById("profile-select");
    const profile = profileSelect ? profileSelect.value : "WHATSAPP_ROBUST";
    const formData = new FormData();
    formData.append("profile", profile);
    formData.append("user_id", "u-94a1-rahul-sharma");

    if (selectedFile) {
      formData.append("file", selectedFile);
      formData.append("use_sample", "false");
    } else {
      formData.append("use_sample", "true");
    }

    const res = await fetch("/api/v1/cloak/immunize", {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();

    if (data.status === "IMMUNIZATION_SUCCESS") {
      currentImmunizedBase64 = data.images.immunized_data_url;

      // Update comparison slider images
      const compOrig = document.getElementById("comp-original");
      const compImm = document.getElementById("comp-immunized");
      if (compOrig) compOrig.src = data.images.original_data_url;
      if (compImm) compImm.src = currentImmunizedBase64;

      // Update Telemetry Badges
      const ssimEl = document.getElementById("metric-ssim");
      const psnrEl = document.getElementById("metric-psnr");
      const shiftEl = document.getElementById("metric-shift");
      const latEl = document.getElementById("metric-latency");
      if (ssimEl) ssimEl.textContent = data.metrics.ssim;
      if (psnrEl) psnrEl.textContent = `${data.metrics.psnr_db} dB`;
      if (shiftEl) shiftEl.textContent = `+${data.metrics.identity_shift_cosine}`;
      if (latEl) latEl.textContent = `${data.latency_ms} ms`;

      // Show Quality Gate & Bitstring
      const qg = document.getElementById("badge-quality-gate");
      if (qg) {
        qg.textContent = `SSIM ${data.metrics.ssim} (PASSED)`;
        qg.classList.remove("hidden");
      }

      const canaryBox = document.getElementById("canary-signature-box");
      const bitstringEl = document.getElementById("bitstring-display");
      if (bitstringEl) bitstringEl.textContent = data.metrics.watermark_bitstring;
      if (canaryBox) canaryBox.classList.remove("hidden");

      refreshLedger();
      fetchSystemStatus();
    }
  } catch (err) {
    alert("Immunization failed: " + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="lock" class="w-4 h-4 mr-2"></i><span>Immunize & Embed 64-Bit Canary</span>`;
    }
    if (window.lucide) lucide.createIcons();
  }
}

// ==========================================
// ACT 1: EXECUTE FACE-SWAP STRESS TEST
// ==========================================
async function executeStressTest() {
  const btn = document.getElementById("btn-stress-test");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin mr-2">⏳</span> Simulating InsightFace Inswapper...`;
  }

  try {
    const profileSelect = document.getElementById("profile-select");
    const profile = profileSelect ? profileSelect.value : "WHATSAPP_ROBUST";
    const formData = new FormData();
    formData.append("profile", profile);

    if (selectedFile) {
      formData.append("file", selectedFile);
      formData.append("use_sample", "false");
    } else {
      formData.append("use_sample", "true");
    }

    const res = await fetch("/api/v1/cloak/stress-test", {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();

    if (data.status === "STRESS_TEST_COMPLETED") {
      const unprotImg = document.getElementById("img-unprotected-swap");
      const cloakedImg = document.getElementById("img-cloaked-swap");
      const results = document.getElementById("stress-test-results");
      if (unprotImg) unprotImg.src = data.unprotected_swap_data_url;
      if (cloakedImg) cloakedImg.src = data.cloaked_swap_data_url;
      if (results) results.classList.remove("hidden");
    }
  } catch (err) {
    alert("Stress test failed: " + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="play" class="w-3.5 h-3.5 text-rose-500 mr-1.5"></i><span>Run Face-Swap Stress Test</span>`;
    }
    if (window.lucide) lucide.createIcons();
  }
}

// ==========================================
// ACT 2: DEEPLENS FORENSICS
// ==========================================
function handleForensicsFileSelect(e) {
  const file = e.target.files[0];
  if (!file) return;
  forensicsFile = file;

  const reader = new FileReader();
  reader.onload = (event) => {
    const preview = document.getElementById("forensics-preview");
    const prompt = document.getElementById("forensics-upload-prompt");
    if (preview) {
      preview.src = event.target.result;
      preview.classList.remove("hidden");
    }
    if (prompt) prompt.classList.add("hidden");
  };
  reader.readAsDataURL(file);
}

async function loadSeededDeepfakeFrame() {
  forensicsFile = null;
  const preview = document.getElementById("forensics-preview");
  const prompt = document.getElementById("forensics-upload-prompt");
  if (!currentImmunizedBase64 && !currentSampleBase64) {
    await loadSamplePortrait();
  }
  if (preview) {
    preview.src = currentImmunizedBase64 || currentSampleBase64 || "";
    if (preview.src) {
      preview.classList.remove("hidden");
    }
  }
  if (prompt) prompt.classList.add("hidden");
}

async function executeForensicsInspection() {
  const btn = document.getElementById("btn-inspect");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin mr-2">⏳</span> Extracting 64-Bit DWT Canary & Computing 2D-FFT...`;
  }

  try {
    const formData = new FormData();
    if (forensicsFile) {
      formData.append("file", forensicsFile);
      formData.append("simulate_deepfake", "false");
    } else {
      formData.append("simulate_deepfake", "true");
    }

    const res = await fetch("/api/v1/forensics/inspect", {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();

    // Update Verdict Badge
    const badge = document.getElementById("forensics-verdict-badge");
    if (badge) {
      badge.textContent = `${data.verdict} (${data.latency_ms}ms)`;
      badge.className = "text-xs font-bold px-3 py-1 rounded-full " + 
        (data.verdict === "STOLEN_IDENTITY_MATCH" 
          ? "bg-purple-100 text-purple-800 border border-purple-200" 
          : data.verdict === "SYNTHETIC_DEEPFAKE" 
          ? "bg-rose-100 text-rose-800 border border-rose-200" 
          : "bg-emerald-100 text-emerald-800 border border-emerald-200");
    }

    // STAGE 1: Attribution
    const stage1 = data.stage_1_watermark_attribution;
    const attr = stage1 ? stage1.attribution : null;
    const popcountEl = document.getElementById("popcount-latency");
    if (popcountEl && attr) {
      popcountEl.textContent = `Hardware Popcount: ${attr.search_latency_ms || 0.4}ms`;
    }

    const attrDetails = document.getElementById("attribution-details");
    if (attrDetails && attr) {
      if (attr.matched) {
        attrDetails.innerHTML = `
          <div class="p-3.5 rounded-2xl bg-purple-50/80 border border-purple-200 space-y-1.5">
            <div class="flex items-center space-x-2 text-purple-900 font-bold">
              <i data-lucide="shield-check" class="w-4 h-4 text-emerald-600"></i>
              <span>STOLEN IDENTITY CONFIRMED CRYPTOGRAPHICALLY</span>
            </div>
            <div class="text-[#0c1024]">Registered Citizen: <strong>${attr.owner_name}</strong> (${attr.owner_email})</div>
            <div class="text-slate-600 text-xs">Immunization Date: ${attr.original_immunization_date} | Profile: ${attr.protection_profile}</div>
            <div class="text-rose-600 font-mono text-[11px] font-semibold">Bit Error Rate (BER): ${attr.bit_error_rate_pct}% | Hamming Distance: ${attr.hamming_distance} / 64 bits</div>
          </div>
        `;
      } else {
        attrDetails.innerHTML = `<div class="p-2 text-slate-500">No matching citizen watermark found within BER &lt; 12%.</div>`;
      }
    }

    // STAGE 2: 2D-FFT Spectrum
    const fft = data.stage_2_frequency_spectrum;
    if (fft) {
      const fftBadge = document.getElementById("fft-anomaly-badge");
      if (fftBadge) fftBadge.textContent = `Anomaly: ${(fft.fft_anomaly_score * 100).toFixed(1)}%`;
      const fftImg = document.getElementById("img-fft-spectrum");
      if (fftImg) {
        fftImg.src = fft.spectrum_image_data_url;
        fftImg.classList.remove("hidden");
      }
      const fftPh = document.getElementById("fft-placeholder");
      if (fftPh) fftPh.classList.add("hidden");
    }

    // STAGE 3: Grad-CAM
    const vit = data.stage_3_vit_heatmap;
    if (vit) {
      const vitBadge = document.getElementById("deepfake-prob-badge");
      if (vitBadge) vitBadge.textContent = `Probability: ${(vit.deepfake_probability * 100).toFixed(1)}%`;
      const gradImg = document.getElementById("img-gradcam-heatmap");
      if (gradImg) {
        gradImg.src = vit.gradcam_heatmap_data_url;
        gradImg.classList.remove("hidden");
      }
      const gradPh = document.getElementById("gradcam-placeholder");
      if (gradPh) gradPh.classList.add("hidden");
    }

    // STAGE 4: C2PA
    const c2pa = data.stage_4_c2pa_audit;
    if (c2pa) {
      const c2paStatus = document.getElementById("c2pa-status");
      const c2paBadge = document.getElementById("c2pa-badge");
      if (c2paStatus) c2paStatus.textContent = c2pa.status;
      if (c2paBadge) c2paBadge.textContent = c2pa.details;
    }

  } catch (err) {
    alert("Forensics inspection failed: " + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="microscope" class="w-4 h-4 mr-2"></i><span>Execute DeepLens Forensics</span>`;
    }
    if (window.lucide) lucide.createIcons();
  }
}

// ==========================================
// ACT 3: SCAMRADAR LIVE SHIELD
// ==========================================
function loadScamScenario(idx) {
  if (!demoScenarios || !demoScenarios[idx]) return;
  const input = document.getElementById("scam-text-input");
  if (input) input.value = demoScenarios[idx].transcript;
  executeScamAudit();
}

async function executeScamAudit() {
  const inputEl = document.getElementById("scam-text-input");
  if (!inputEl) return;
  const text = inputEl.value.trim();
  if (!text) {
    alert("Please enter or select a call transcript first.");
    return;
  }

  try {
    const isScamScenario = text.toLowerCase().includes("cbi") || text.toLowerCase().includes("mdma") || text.toLowerCase().includes("trai");
    const simulatedAudioScore = isScamScenario ? 0.88 : 0.12;

    const payload = JSON.stringify({
      text: text,
      transcript: text,
      channel: "CALL_TRANSCRIPT",
      caller_id: "+91-98765-43210",
      audio_clone_score: simulatedAudioScore,
    });

    let res = await fetch("/api/v1/scam/audit-text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
    }).catch(() => null);

    if (!res || !res.ok) {
      res = await fetch("/api/v1/scam/analyze-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
      }).catch(() => null);
    }

    if (!res || !res.ok) throw new Error(res ? `HTTP ${res.status}` : "Network error");
    const data = await res.json();
    updateScamDashboard(data);
  } catch (err) {
    alert("Scam audit failed: " + err.message);
  }
}

function updateScamDashboard(data) {
  const levelEl = document.getElementById("radar-threat-level");
  const pctEl = document.getElementById("radar-risk-percentage");
  const barEl = document.getElementById("radar-progress-bar");
  const cloneBadge = document.getElementById("voice-clone-badge");

  const risk = typeof data.risk_score === "number" ? data.risk_score : 0;
  if (levelEl) levelEl.textContent = data.headline || data.threat_level || "MONITORING CALL";
  if (pctEl) pctEl.textContent = `${risk}%`;
  if (barEl) barEl.style.width = `${risk}%`;

  if (levelEl && barEl && pctEl) {
    if (risk >= 70) {
      levelEl.className = "text-lg font-black text-rose-400";
      pctEl.className = "text-3xl font-black font-mono text-rose-400";
      barEl.className = "h-full rounded-full bg-rose-500 transition-all duration-500";
    } else if (risk >= 35) {
      levelEl.className = "text-lg font-black text-amber-400";
      pctEl.className = "text-3xl font-black font-mono text-amber-400";
      barEl.className = "h-full rounded-full bg-amber-500 transition-all duration-500";
    } else {
      levelEl.className = "text-lg font-black text-emerald-400";
      pctEl.className = "text-3xl font-black font-mono text-emerald-400";
      barEl.className = "h-full rounded-full bg-emerald-500 transition-all duration-500";
    }
  }

  // Voice Clone Badge
  if (cloneBadge) {
    if (data.audio_clone_score !== undefined && data.audio_clone_score !== null) {
      const isClone = data.audio_clone_score >= 0.5;
      cloneBadge.textContent = isClone
        ? `SYNTHETIC CLONE (${Math.round(data.audio_clone_score * 100)}%)`
        : `NATURAL HUMAN (${Math.round((1 - data.audio_clone_score) * 100)}%)`;
      cloneBadge.className = isClone
        ? "text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-rose-100 text-rose-800 border border-rose-200"
        : "text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200";
    } else {
      cloneBadge.textContent = "TEXT ONLY";
      cloneBadge.className = "text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200";
    }
  }

  // 3-Axis Updates
  const tactics = data.tactics_breakdown || {};
  
  // Axis 1: Authority
  const a1 = tactics["AUTHORITY_IMPERSONATION"];
  const a1Status = document.getElementById("axis-1-status");
  const a1Kw = document.getElementById("axis-1-keywords");
  if (a1Status && a1Kw) {
    if (a1) {
      a1Status.textContent = `ALERT (+${a1.contribution}%)`;
      a1Status.className = "text-amber-600 font-bold";
      a1Kw.textContent = `Matched: ${a1.matched_keywords.join(", ")}`;
    } else {
      a1Status.textContent = "CLEAR (0%)";
      a1Status.className = "text-[#64748b] font-semibold";
      a1Kw.textContent = "No authority impersonation detected.";
    }
  }

  // Axis 2: Isolation
  const a2 = tactics["ISOLATION_COMMANDS"];
  const a2Status = document.getElementById("axis-2-status");
  const a2Kw = document.getElementById("axis-2-keywords");
  if (a2Status && a2Kw) {
    if (a2) {
      a2Status.textContent = `CRITICAL (+${a2.contribution}%)`;
      a2Status.className = "text-rose-600 font-bold";
      a2Kw.textContent = `Matched: ${a2.matched_keywords.join(", ")}`;
    } else {
      a2Status.textContent = "CLEAR (0%)";
      a2Status.className = "text-[#64748b] font-semibold";
      a2Kw.textContent = "No isolation commands detected.";
    }
  }

  // Axis 3: Financial Coercion
  const a3 = tactics["FINANCIAL_COERCION"];
  const a3Status = document.getElementById("axis-3-status");
  const a3Kw = document.getElementById("axis-3-keywords");
  if (a3Status && a3Kw) {
    if (a3) {
      a3Status.textContent = `URGENT (+${a3.contribution}%)`;
      a3Status.className = "text-purple-600 font-bold";
      a3Kw.textContent = `Matched: ${a3.matched_keywords.join(", ")}`;
    } else {
      a3Status.textContent = "CLEAR (0%)";
      a3Status.className = "text-[#64748b] font-semibold";
      a3Kw.textContent = "No financial coercion detected.";
    }
  }

  // I4C Complaint Box
  const complaintBox = document.getElementById("i4c-complaint-box");
  const draftPre = document.getElementById("i4c-draft-text");
  if (complaintBox && draftPre) {
    if (data.emergency_complaint_draft && risk >= 60) {
      draftPre.textContent = data.emergency_complaint_draft;
      complaintBox.classList.remove("hidden");
    } else {
      complaintBox.classList.add("hidden");
    }
  }
}

function toggleWebSocketStream() {
  const btn = document.getElementById("btn-ws-stream");
  const btnText = document.getElementById("ws-btn-text");

  if (activeWs) {
    if (streamInterval) clearInterval(streamInterval);
    streamInterval = null;
    activeWs.close();
    activeWs = null;
    btnText.textContent = "Stream Live (WS)";
    btn.className = "w-full py-3 px-4 rounded-full bg-[#0c1024] hover:bg-[#1a233d] border border-[#0c1024] text-white font-bold text-xs uppercase tracking-wider flex items-center justify-center space-x-1.5 shadow-md transition cursor-pointer";
    return;
  }

  // Start stream
  let rawText = document.getElementById("scam-text-input").value.trim();
  if (!rawText) {
    if (demoScenarios && demoScenarios.length > 0) {
      rawText = demoScenarios[0].transcript;
      document.getElementById("scam-text-input").value = rawText;
    } else {
      rawText = "This is Officer Vikram from CBI Cyber Crime Cell Mumbai. A FedEx parcel with MDMA narcotics has your Aadhaar. Digital arrest warrant issued. Deposit funds to RBI escrow immediately.";
      document.getElementById("scam-text-input").value = rawText;
    }
  }

  const sentences = rawText.match(/[^.!?]+[.!?]+/g) || [rawText];
  let chunkIndex = 0;
  let accumulated = "";

  const isScamScenario = rawText.toLowerCase().includes("cbi") || rawText.toLowerCase().includes("mdma") || rawText.toLowerCase().includes("trai");

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/v1/scam/call-stream`;

  try {
    activeWs = new WebSocket(wsUrl);
  } catch (e) {
    alert("Failed to initialize WebSocket: " + e.message);
    return;
  }

  btnText.textContent = "Streaming Live...";
  btn.className = "w-full py-3 px-4 rounded-full bg-rose-600 text-white font-bold text-xs uppercase tracking-wider flex items-center justify-center space-x-1.5 animate-pulse transition";

  activeWs.onopen = () => {
    accumulated = sentences[0] || rawText;
    activeWs.send(JSON.stringify({
      text_chunk: accumulated,
      simulate_clone: isScamScenario
    }));
    chunkIndex = 1;

    streamInterval = setInterval(() => {
      if (chunkIndex < sentences.length) {
        accumulated += " " + sentences[chunkIndex];
        if (activeWs && activeWs.readyState === WebSocket.OPEN) {
          activeWs.send(JSON.stringify({
            text_chunk: accumulated,
            simulate_clone: isScamScenario
          }));
        }
        chunkIndex++;
      } else {
        if (streamInterval) clearInterval(streamInterval);
        streamInterval = null;
        if (activeWs) {
          activeWs.close();
          activeWs = null;
        }
        btnText.textContent = "Stream Live (WS)";
        btn.className = "w-full py-3 px-4 rounded-full bg-[#0c1024] hover:bg-[#1a233d] border border-[#0c1024] text-white font-bold text-xs uppercase tracking-wider flex items-center justify-center space-x-1.5 shadow-md transition cursor-pointer";
      }
    }, 1200);
  };

  activeWs.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      updateScamDashboard(data);
    } catch (err) {
      console.error("WS message parse failed:", err);
    }
  };

  activeWs.onerror = (err) => {
    console.error("WebSocket error:", err);
    if (streamInterval) clearInterval(streamInterval);
    streamInterval = null;
    activeWs = null;
    btnText.textContent = "Stream Live (WS)";
    btn.className = "w-full py-3 px-4 rounded-full bg-[#0c1024] hover:bg-[#1a233d] border border-[#0c1024] text-white font-bold text-xs uppercase tracking-wider flex items-center justify-center space-x-1.5 shadow-md transition cursor-pointer";
  };

  activeWs.onclose = () => {
    if (streamInterval) clearInterval(streamInterval);
    streamInterval = null;
    activeWs = null;
    btnText.textContent = "Stream Live (WS)";
    btn.className = "w-full py-3 px-4 rounded-full bg-[#0c1024] hover:bg-[#1a233d] border border-[#0c1024] text-white font-bold text-xs uppercase tracking-wider flex items-center justify-center space-x-1.5 shadow-md transition cursor-pointer";
  };
}

function copyComplaintDraft() {
  const text = document.getElementById("i4c-draft-text").textContent;
  navigator.clipboard.writeText(text);
  alert("1930 Cybercrime complaint draft copied to clipboard!");
}

// ==========================================
// ACT 4: REFRESH PROOF LEDGER
// ==========================================
async function refreshLedger() {
  try {
    const res = await fetch("/api/v1/ledger/recent");
    const data = await res.json();
    const tbody = document.getElementById("ledger-table-body");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!data.ledger || data.ledger.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="p-6 text-center text-[#64748b]">No records found.</td></tr>`;
      return;
    }

    data.ledger.forEach((row) => {
      const tr = document.createElement("tr");
      tr.className = "hover:bg-slate-50 transition border-b border-slate-100";
      tr.innerHTML = `
        <td class="p-3 font-bold text-[#0c1024]">${row.asset_id || "—"}</td>
        <td class="p-3 text-[#0c1024] font-semibold">${row.user_id || "—"}</td>
        <td class="p-3 text-slate-500 font-mono text-[11px] truncate max-w-xs" title="${row.watermark_bitstring || ''}">${row.watermark_bitstring ? row.watermark_bitstring.substring(0, 24) + '...' : '—'}</td>
        <td class="p-3 text-slate-500 font-mono text-[11px]">${row.perceptual_hash || '—'}</td>
        <td class="p-3 text-emerald-600 font-black">${row.ssim_score || '—'}</td>
        <td class="p-3 text-slate-700 font-semibold">${row.psnr_db} dB</td>
        <td class="p-3"><span class="px-2.5 py-0.5 rounded-full bg-pink-50 text-[#f43f8e] border border-pink-200 text-[10px] font-bold">${row.protection_profile}</span></td>
        <td class="p-3 text-slate-400 text-[11px]">${row.created_at}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Ledger refresh failed:", err);
  }
}
