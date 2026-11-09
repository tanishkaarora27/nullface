"""Service 2 — DeepLens multimodal forensics & traceability lab.

Stage 1  Blind DWT watermark extraction (<50 ms) + Hamming attribution against the ledger (BER < 12 %).
Stage 2  2D-FFT azimuthal power spectrum (GAN/diffusion upsampling grid exposure) + ViT deepfake classifier
         (HF ``dima806/deepfake_vs_real_image_detection``) with Grad-CAM heat-map when torch is available.
Stage 3  C2PA / provenance metadata audit.
Audio    Mel-spectrogram vocoder artefact scoring (librosa + Wav2Vec2 ``MelodyMachine/Deepfake-audio-detection-V2``).

Every heavy model is optional; when absent the stage reports ``backend: "heuristic"`` instead of lying.
"""
from __future__ import annotations

import base64
import io
import time
from functools import lru_cache

import cv2
import numpy as np

from ..core import watermark as wm
from ..core.config import settings
from ..core.db import get_db
from ..core.ephemeral import EphemeralBuffer
from ..core.imaging import decode_image, encode_png, luminance, phash, sha256

# ---------------------------------------------------------------------------
# Stage 1 — Canary-Link extraction + attribution
# ---------------------------------------------------------------------------

def extract_and_attribute(rgb: np.ndarray) -> dict:
    t0 = time.perf_counter()
    bits, conf = wm.extract(luminance(rgb))
    max_flips = int(settings.BER_MATCH_THRESHOLD * wm.PAYLOAD_BITS)  # 0.12 * 64 = 7
    match = get_db().match_watermark(bits, max_hamming=max_flips)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    out = {
        "extracted_hex": wm.bits_to_hex(bits),
        "extracted_bits": bits,
        "confidence": conf,
        "ber_threshold": settings.BER_MATCH_THRESHOLD,
        "latency_ms": ms,
        "match": None,
    }
    if match:
        out["match"] = {
            "asset_id": match["asset_id"],
            "owner_name": match["full_name"],
            "owner_email": _mask_email(match["email"]),
            "immunized_at": str(match["created_at"]),
            "profile": match.get("protection_profile"),
            "hamming_distance": int(match["hamming_distance"]),
            "ber": round(int(match["hamming_distance"]) / wm.PAYLOAD_BITS, 4),
        }
    return out


def _mask_email(email: str) -> str:
    name, _, dom = email.partition("@")
    return (name[:2] + "***@" + dom) if dom else "***"


# ---------------------------------------------------------------------------
# Stage 2a — 2D-FFT azimuthal power spectrum
# ---------------------------------------------------------------------------

def fft_spectrum_analysis(rgb: np.ndarray) -> dict:
    """Azimuthally-averaged power spectrum. Natural photos decay ~1/f²; GAN/diffusion upsamplers leave periodic
    peaks and an inflated high-frequency tail. Returns an anomaly score in [0,1] and the 1-D profile."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gray = cv2.resize(gray, (512, 512), interpolation=cv2.INTER_AREA)
    f = np.fft.fftshift(np.fft.fft2(gray - gray.mean()))
    psd = np.log1p(np.abs(f) ** 2)
    h, w = psd.shape
    cy, cx = h // 2, w // 2
    yy, xx = np.indices(psd.shape)
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2).astype(np.int32)
    nbins = min(cy, cx)
    prof = np.bincount(r.ravel(), psd.ravel(), minlength=nbins)[:nbins] / np.maximum(np.bincount(r.ravel(), minlength=nbins)[:nbins], 1)
    prof = (prof - prof.min()) / (prof.max() - prof.min() + 1e-8)

    # (a) high-frequency energy ratio (upsampling artefacts raise the tail)
    tail = float(prof[int(nbins * 0.7):].mean())
    # (b) periodic peaks: residual after smoothing, counted on the upper half of the spectrum
    smooth = np.convolve(prof, np.ones(9) / 9, mode="same")
    resid = prof - smooth
    upper = np.abs(resid[int(nbins * 0.15):])
    thr = max(0.05, 3.0 * float(np.median(upper)) + 0.03)
    spikes = (upper[1:-1] > upper[:-2]) & (upper[1:-1] > upper[2:]) & (upper[1:-1] > thr)
    peaks = int(np.sum(spikes))   # sharp spectral spikes/nulls = regular resampling / upsampling grid
    peak_score = min(1.0, peaks / 4.0)
    tail_score = float(np.clip((tail - 0.35) / 0.40, 0, 1))
    score = round(float(0.55 * tail_score + 0.45 * peak_score), 4)

    # grid-artefact heat-map (log-PSD, for the UI)
    heat = cv2.normalize(psd, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    heat = cv2.applyColorMap(cv2.resize(heat, (256, 256)), cv2.COLORMAP_INFERNO)
    heat = cv2.cvtColor(heat, cv2.COLOR_BGR2RGB)
    return {
        "fft_anomaly_score": score,
        "high_freq_tail": round(tail, 4),
        "periodic_peaks": peaks,
        "profile": [round(float(v), 4) for v in prof[:: max(1, nbins // 32)]],
        "spectrum_png_b64": base64.b64encode(encode_png(heat)).decode(),
    }


# ---------------------------------------------------------------------------
# Stage 2b — ViT deepfake classifier (+ Grad-CAM) with heuristic fallback
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _vit():
    try:
        import torch  # type: ignore
        from transformers import AutoImageProcessor, AutoModelForImageClassification  # type: ignore

        proc = AutoImageProcessor.from_pretrained(settings.HF_DEEPFAKE_MODEL)
        model = AutoModelForImageClassification.from_pretrained(settings.HF_DEEPFAKE_MODEL, output_attentions=True)
        model.eval()
        return torch, proc, model
    except Exception:
        return None


def vit_deepfake(rgb: np.ndarray, fft_score: float, face_box: dict | None = None) -> dict:
    loaded = _vit()
    if loaded is None:
        # Heuristic: combine FFT score with noise-residual uniformity (synthetic images have unusually smooth
        # sensor-noise residuals) and chroma-edge inconsistency.
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        resid = gray - cv2.GaussianBlur(gray, (0, 0), 1.2)
        local_std = cv2.blur(resid ** 2, (16, 16)) ** 0.5
        uniformity = float(1.0 - np.clip(local_std.std() / (local_std.mean() + 1e-6), 0, 1))
        prob = float(np.clip(0.6 * fft_score + 0.4 * uniformity, 0, 1))
        heat = cv2.normalize(cv2.resize(local_std, (256, 256)), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        heat = cv2.cvtColor(cv2.applyColorMap(255 - heat, cv2.COLORMAP_JET), cv2.COLOR_BGR2RGB)
        return {"deepfake_probability": round(prob, 4), "backend": "heuristic (noise-residual + FFT)",
                "label": "SYNTHETIC" if prob > 0.5 else "REAL",
                "gradcam_png_b64": base64.b64encode(encode_png(heat)).decode()}

    torch, proc, model = loaded
    from PIL import Image

    inputs = proc(images=Image.fromarray(rgb), return_tensors="pt")
    with torch.no_grad():
        out = model(**inputs)
    probs = out.logits.softmax(-1)[0]
    labels = {i: l.lower() for i, l in model.config.id2label.items()}
    fake_idx = next((i for i, l in labels.items() if "fake" in l), 0)
    prob = float(probs[fake_idx])
    # attention-rollout CAM from the last layer (cheap stand-in for Grad-CAM on ViT)
    att = out.attentions[-1][0].mean(0)[0, 1:]
    side = int(att.numel() ** 0.5)
    cam = att.reshape(side, side).numpy()
    cam = cv2.normalize(cv2.resize(cam, (256, 256)), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    heat = cv2.cvtColor(cv2.applyColorMap(cam, cv2.COLORMAP_JET), cv2.COLOR_BGR2RGB)
    return {"deepfake_probability": round(prob, 4), "backend": settings.HF_DEEPFAKE_MODEL,
            "label": labels[int(probs.argmax())].upper(),
            "gradcam_png_b64": base64.b64encode(encode_png(heat)).decode()}


# ---------------------------------------------------------------------------
# Stage 3 — C2PA / provenance audit
# ---------------------------------------------------------------------------

def c2pa_audit(data: bytes) -> dict:
    head = data[:4_000_000]
    has_jumbf = b"jumb" in head or b"c2pa" in head.lower()
    has_exif = b"Exif\x00\x00" in head[:65536]
    has_xmp = b"http://ns.adobe.com/xap/1.0/" in head[:65536]
    software = None
    if has_xmp:
        i = head.find(b"CreatorTool")
        if i != -1:
            software = head[i : i + 80].decode("latin-1", "ignore").split(">")[1].split("<")[0] if b">" in head[i:i+80] else None
    return {"c2pa_manifest_present": has_jumbf, "exif_present": has_exif, "xmp_present": has_xmp,
            "creator_tool": software, "note": "C2PA manifest found — signed provenance chain available" if has_jumbf
            else "No C2PA manifest — no cryptographic provenance (typical of screenshots, re-encodes and generators)"}


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------

def inspect_image(data: bytes, user: dict | None) -> dict:
    t0 = time.perf_counter()
    with EphemeralBuffer(data) as buf:
        raw = buf.read()
        rgb = decode_image(raw)
        s1 = extract_and_attribute(rgb)
        s2a = fft_spectrum_analysis(rgb)
        s2b = vit_deepfake(rgb, s2a["fft_anomaly_score"])
        s3 = c2pa_audit(raw)

        prob = s2b["deepfake_probability"]
        if s1["match"]:
            verdict = "STOLEN_IDENTITY_MATCH"
        elif prob >= 0.7:
            verdict = "SYNTHETIC_DEEPFAKE"
        elif prob >= 0.4 or s2a["fft_anomaly_score"] >= 0.5:
            verdict = "SUSPICIOUS"
        else:
            verdict = "AUTHENTIC"

        report = {
            "verdict": verdict,
            "stage1_canary_link": s1,
            "stage2_fft": {k: v for k, v in s2a.items() if k != "spectrum_png_b64"},
            "stage2_vit": {k: v for k, v in s2b.items() if k != "gradcam_png_b64"},
            "stage3_c2pa": s3,
            "perceptual_hash": phash(rgb),
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
        scan_id = get_db().insert_scan(
            user["id"] if user else None, "IMAGE", sha256(raw), prob, s2a["fft_anomaly_score"],
            s1["match"]["asset_id"] if s1["match"] else None,
            s1["match"]["hamming_distance"] if s1["match"] else None, verdict, report,
        )
        report["scan_id"] = scan_id
        report["visuals"] = {"spectrum_png_b64": s2a["spectrum_png_b64"], "gradcam_png_b64": s2b["gradcam_png_b64"]}
        return report


# ---------------------------------------------------------------------------
# audio clone forensics
# ---------------------------------------------------------------------------

def _load_audio(data: bytes) -> tuple[np.ndarray, int]:
    try:
        import librosa  # type: ignore

        y, sr = librosa.load(io.BytesIO(data), sr=16000, mono=True)
        return y.astype(np.float32), sr
    except Exception:
        import wave

        with wave.open(io.BytesIO(data)) as w:
            sr = w.getframerate()
            frames = w.readframes(w.getnframes())
            dtype = {1: np.int8, 2: np.int16, 4: np.int32}[w.getsampwidth()]
            y = np.frombuffer(frames, dtype=dtype).astype(np.float32) / np.iinfo(dtype).max
            if w.getnchannels() > 1:
                y = y.reshape(-1, w.getnchannels()).mean(1)
        return y, sr


def pcm16_to_float(chunk: bytes) -> np.ndarray:
    return np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0


@lru_cache(maxsize=1)
def _wav2vec():
    try:
        import torch  # type: ignore
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification  # type: ignore

        fe = AutoFeatureExtractor.from_pretrained(settings.HF_AUDIO_MODEL)
        model = AutoModelForAudioClassification.from_pretrained(settings.HF_AUDIO_MODEL)
        model.eval()
        return torch, fe, model
    except Exception:
        return None


def voice_clone_score(y: np.ndarray, sr: int = 16000) -> dict:
    """Returns P(synthetic voice) in [0,1]. Wav2Vec2 classifier when available, else vocoder-artefact heuristics:
    neural vocoders produce unnaturally stable pitch/energy and phase discontinuities at frame boundaries."""
    if y.size < sr // 4:
        return {"voice_clone_score": 0.0, "backend": "n/a (chunk too short)"}
    loaded = _wav2vec()
    if loaded is not None:
        torch, fe, model = loaded
        inputs = fe(y, sampling_rate=sr, return_tensors="pt", padding=True)
        with torch.no_grad():
            probs = model(**inputs).logits.softmax(-1)[0]
        labels = {i: l.lower() for i, l in model.config.id2label.items()}
        fake_idx = next((i for i, l in labels.items() if "fake" in l or "spoof" in l), 1)
        return {"voice_clone_score": round(float(probs[fake_idx]), 4), "backend": settings.HF_AUDIO_MODEL}

    # --- heuristic path ---
    frame, hop = 512, 256
    n = (len(y) - frame) // hop
    if n < 4:
        return {"voice_clone_score": 0.0, "backend": "heuristic"}
    frames = np.stack([y[i * hop : i * hop + frame] * np.hanning(frame) for i in range(n)])
    spec = np.abs(np.fft.rfft(frames, axis=1)) + 1e-9
    # spectral flatness (vocoders flatten mid-band noise floors)
    flat = np.exp(np.mean(np.log(spec), axis=1)) / np.mean(spec, axis=1)
    # frame-to-frame phase discontinuity
    ph = np.angle(np.fft.rfft(frames, axis=1))
    dphi = np.abs(np.diff(np.unwrap(ph, axis=0), axis=0))
    disc = float(np.mean(dphi > np.pi * 0.9))
    # energy-envelope regularity (synthetic speech is suspiciously steady)
    env = np.log(frames.std(1) + 1e-6)
    steadiness = float(1.0 - np.clip(env.std() / 2.0, 0, 1))
    score = float(np.clip(0.4 * np.clip(flat.mean() * 4, 0, 1) + 0.3 * np.clip(disc * 3, 0, 1) + 0.3 * steadiness, 0, 1))
    return {"voice_clone_score": round(score, 4), "backend": "heuristic (flatness/phase/envelope)",
            "features": {"spectral_flatness": round(float(flat.mean()), 4), "phase_discontinuity": round(disc, 4),
                         "envelope_steadiness": round(steadiness, 4)}}


def inspect_audio(data: bytes, user: dict | None) -> dict:
    t0 = time.perf_counter()
    with EphemeralBuffer(data) as buf:
        raw = buf.read()
        y, sr = _load_audio(raw)
        res = voice_clone_score(y, sr)
        prob = res["voice_clone_score"]
        verdict = "SYNTHETIC_DEEPFAKE" if prob >= 0.7 else "SUSPICIOUS" if prob >= 0.4 else "AUTHENTIC"
        report = {"verdict": verdict, "duration_s": round(len(y) / sr, 2), "sample_rate": sr, **res,
                  "latency_ms": round((time.perf_counter() - t0) * 1000)}
        report["scan_id"] = get_db().insert_scan(user["id"] if user else None, "AUDIO", sha256(raw), prob, None,
                                                 None, None, verdict, report)
        return report
