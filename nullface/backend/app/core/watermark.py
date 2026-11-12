"""Canary-Link: 64-bit blind watermark in the 2-level Haar DWT domain using Quantization Index Modulation.

Payload:   W = Trunc64( HMAC-SHA256(user_id || timestamp, server_secret) )
Embedding: 2-level Haar DWT of the luminance channel -> sub-bands {LL2, HL2, LH2, HH2}.
           Each of the 64 bits is written into R redundant mid-frequency coefficients C_k in {HL2, LH2}:
               C'_k = round(C_k / Δ) · Δ + (-1)^{W_k} · Δ/4
Extraction: blind (no original needed) — re-run the DWT, read the same keyed positions, majority-vote per bit.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import numpy as np
import pywt

from .config import settings

PAYLOAD_BITS = 64


# ---------------------------------------------------------------------------
# payload
# ---------------------------------------------------------------------------

def derive_payload(user_id: str, timestamp: float | None = None, secret: str | None = None) -> str:
    ts = int(timestamp if timestamp is not None else time.time())
    msg = f"{user_id}|{ts}".encode()
    digest = hmac.new((secret or settings.SERVER_SECRET).encode(), msg, hashlib.sha256).digest()
    return "".join(f"{b:08b}" for b in digest[:8])  # 64 chars of '0'/'1'


def bits_to_hex(bits: str) -> str:
    return f"{int(bits, 2):016x}"


# ---------------------------------------------------------------------------
# keyed coefficient positions
# ---------------------------------------------------------------------------

def _positions(shape: tuple[int, int], n: int, key: str, band: str) -> np.ndarray:
    """Deterministic, key-dependent sample of coefficient indices avoiding the band border."""
    h, w = shape
    seed = int.from_bytes(hashlib.sha256(f"{key}:{band}:{h}x{w}".encode()).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    margin = 2
    ys = np.arange(margin, h - margin)
    xs = np.arange(margin, w - margin)
    grid = np.array(np.meshgrid(ys, xs, indexing="ij")).reshape(2, -1).T
    if len(grid) < n:
        raise ValueError("Image too small to carry the watermark")
    idx = rng.choice(len(grid), size=n, replace=False)
    return grid[idx]


def _pad_to_multiple(y: np.ndarray, m: int = 4) -> tuple[np.ndarray, tuple[int, int]]:
    h, w = y.shape
    ph, pw = (-h) % m, (-w) % m
    if ph or pw:
        y = np.pad(y, ((0, ph), (0, pw)), mode="reflect")
    return y, (h, w)


# ---------------------------------------------------------------------------
# embed / extract
# ---------------------------------------------------------------------------

def embed(y: np.ndarray, bits: str, delta: float | None = None, redundancy: int | None = None,
          key: str | None = None) -> np.ndarray:
    """y: float32 luminance (H, W) -> watermarked luminance (same shape)."""
    assert len(bits) == PAYLOAD_BITS
    delta = delta or settings.WATERMARK_DELTA
    red = redundancy or settings.WATERMARK_REDUNDANCY
    key = key or settings.WATERMARK_KEY

    yp, (h, w) = _pad_to_multiple(y.astype(np.float64), 4)
    coeffs = pywt.wavedec2(yp, "haar", level=2)
    ll2, (lh2, hl2, hh2), lvl1 = coeffs

    per_band = (PAYLOAD_BITS * red) // 2
    half = per_band // PAYLOAD_BITS  # redundancy per band
    for band_name, band in (("HL2", hl2), ("LH2", lh2)):
        pos = _positions(band.shape, PAYLOAD_BITS * half, key, band_name)
        for k in range(PAYLOAD_BITS * half):
            bit = int(bits[k % PAYLOAD_BITS])
            r, c = pos[k]
            q = np.round(band[r, c] / delta) * delta
            band[r, c] = q + (delta / 4.0 if bit == 0 else -delta / 4.0)

    rec = pywt.waverec2([ll2, (lh2, hl2, hh2), lvl1], "haar")
    return np.clip(rec[:h, :w], 0, 255).astype(np.float32)


def extract(y: np.ndarray, delta: float | None = None, redundancy: int | None = None,
            key: str | None = None) -> tuple[str, float]:
    """Blind extraction. Returns (bits, confidence in [0,1] = mean majority margin)."""
    delta = delta or settings.WATERMARK_DELTA
    red = redundancy or settings.WATERMARK_REDUNDANCY
    key = key or settings.WATERMARK_KEY

    yp, _ = _pad_to_multiple(y.astype(np.float64), 4)
    ll2, (lh2, hl2, hh2), _ = pywt.wavedec2(yp, "haar", level=2)

    half = ((PAYLOAD_BITS * red) // 2) // PAYLOAD_BITS
    votes = np.zeros(PAYLOAD_BITS, dtype=np.float64)
    total = np.zeros(PAYLOAD_BITS, dtype=np.float64)
    for band_name, band in (("HL2", hl2), ("LH2", lh2)):
        pos = _positions(band.shape, PAYLOAD_BITS * half, key, band_name)
        for k in range(PAYLOAD_BITS * half):
            r, c = pos[k]
            residual = np.mod(band[r, c], delta)  # in [0, delta)
            # bit 0 sits at delta/4, bit 1 at 3*delta/4 — soft vote by distance
            d0 = min(abs(residual - delta / 4), delta - abs(residual - delta / 4))
            d1 = min(abs(residual - 3 * delta / 4), delta - abs(residual - 3 * delta / 4))
            votes[k % PAYLOAD_BITS] += 1.0 if d1 < d0 else 0.0
            total[k % PAYLOAD_BITS] += 1.0
    frac = votes / np.maximum(total, 1)
    bits = "".join("1" if f > 0.5 else "0" for f in frac)
    confidence = float(np.mean(np.abs(frac - 0.5) * 2))
    return bits, round(confidence, 4)


def hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b))


def ber(a: str, b: str) -> float:
    return hamming(a, b) / PAYLOAD_BITS
