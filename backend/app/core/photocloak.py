"""PhotoCloak: YCbCr mid-frequency DCT-PGD immunization.

Why the DCT domain: pixel-space adversarial noise lives in high frequencies that JPEG quantisation throws away.
We instead confine the perturbation δ to the 8x8 DCT *mid-frequency* coefficients of the luminance channel and
size every coefficient change to at least one quantisation step of the Q=50 JPEG luminance table, so the
perturbation is "trapped" inside what WhatsApp / Instagram recompression preserves.

Objective (maximised with projected ascent, SSIM-gated at >= 0.96):
    L(δ) = || f_id(I) - f_id(I+δ) ||²  -  λ (1 - SSIM(I, I+δ))

f_id is InsightFace ArcFace when installed; otherwise a HOG identity surrogate (see identity.py).  The ascent is
zeroth-order (sign-pattern search in DCT space) so it runs on CPU with no autograd dependency; with torch +
InsightFace present a gradient step can be dropped in at ``_candidate_patterns``.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import settings
from .identity import cosine_distance, identity_backend
from .imaging import FaceBox, primary_face, psnr, rgb_to_ycbcr, simulate_social_compression, ssim, ycbcr_to_rgb

# Standard JPEG luminance quantisation table (= quality 50 scaling factor 1.0)
_Q50 = np.array(
    [
        [16, 11, 10, 16, 24, 40, 51, 61],
        [12, 12, 14, 19, 26, 58, 60, 55],
        [14, 13, 16, 24, 40, 57, 69, 56],
        [14, 17, 22, 29, 51, 87, 80, 62],
        [18, 22, 37, 56, 68, 109, 103, 77],
        [24, 35, 55, 64, 81, 104, 113, 92],
        [49, 64, 78, 87, 103, 121, 120, 101],
        [72, 92, 95, 98, 112, 100, 103, 99],
    ],
    dtype=np.float32,
)

# Mid-frequency band: zig-zag positions 3..14 (skip DC + 2 lowest, skip the >=15 band JPEG crushes)
_ZIGZAG = [
    (0, 0), (0, 1), (1, 0), (2, 0), (1, 1), (0, 2), (0, 3), (1, 2), (2, 1), (3, 0),
    (4, 0), (3, 1), (2, 2), (1, 3), (0, 4), (0, 5), (1, 4), (2, 3), (3, 2), (4, 1), (5, 0),
]
MID_FREQ_MASK = np.zeros((8, 8), dtype=np.float32)
for _u, _v in _ZIGZAG[3:15]:
    MID_FREQ_MASK[_u, _v] = 1.0


@dataclass
class CloakProfile:
    name: str = "WHATSAPP_ROBUST"
    jpeg_quality: int = 50
    epsilon_steps: float = 1.6       # starting perturbation in units of quantisation steps
    pgd_steps: int = settings.PGD_STEPS
    candidates: int = 4              # zeroth-order sign patterns tried per step
    ssim_floor: float = settings.SSIM_FLOOR
    region_expand: float = 1.35


PROFILES = {
    "WHATSAPP_ROBUST": CloakProfile(),
    "INSTAGRAM_ROBUST": CloakProfile("INSTAGRAM_ROBUST", jpeg_quality=60, epsilon_steps=1.4),
    "MAX_STEALTH": CloakProfile("MAX_STEALTH", jpeg_quality=75, epsilon_steps=1.0, ssim_floor=0.975),
    "MAX_IMMUNITY": CloakProfile("MAX_IMMUNITY", jpeg_quality=40, epsilon_steps=2.2, ssim_floor=0.95),
}


@dataclass
class CloakResult:
    image: np.ndarray                     # RGB uint8 (cloaked, before watermark)
    face: FaceBox
    ssim: float
    psnr: float
    identity_shift: float
    identity_backend: str
    epsilon: float
    steps: int
    timings_ms: dict = field(default_factory=dict)


def jpeg_quant_table(quality: int) -> np.ndarray:
    """IJG scaling of the base table: the quantisation steps a JPEG at ``quality`` will apply."""
    quality = int(np.clip(quality, 1, 100))
    scale = 5000 / quality if quality < 50 else 200 - 2 * quality
    tab = np.floor((_Q50 * scale + 50) / 100)
    return np.clip(tab, 1, 255).astype(np.float32)


# ---------------------------------------------------------------------------
# block DCT helpers
# ---------------------------------------------------------------------------

def _block_dct(y: np.ndarray) -> np.ndarray:
    h, w = y.shape
    out = np.zeros_like(y, dtype=np.float32)
    for r in range(0, h, 8):
        for c in range(0, w, 8):
            out[r : r + 8, c : c + 8] = cv2.dct(y[r : r + 8, c : c + 8])
    return out


def _block_idct(d: np.ndarray) -> np.ndarray:
    h, w = d.shape
    out = np.zeros_like(d, dtype=np.float32)
    for r in range(0, h, 8):
        for c in range(0, w, 8):
            out[r : r + 8, c : c + 8] = cv2.idct(d[r : r + 8, c : c + 8])
    return out


def _tile(mat: np.ndarray, h: int, w: int) -> np.ndarray:
    return np.tile(mat, (h // 8, w // 8))


def _candidate_patterns(shape: tuple[int, int], n: int, seed: int) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    h, w = shape
    return [rng.choice([-1.0, 1.0], size=(h // 8, w // 8, 8, 8)).transpose(0, 2, 1, 3).reshape(h, w)
            .astype(np.float32) for _ in range(n)]


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def cloak(rgb: np.ndarray, profile: CloakProfile | str = "WHATSAPP_ROBUST", seed_material: str = "") -> CloakResult:
    t0 = time.perf_counter()
    prof = PROFILES[profile] if isinstance(profile, str) else profile
    H, W = rgb.shape[:2]

    face = primary_face(rgb)
    region = face.expanded(prof.region_expand, W, H)
    # align region to the 8x8 grid
    x0, y0 = region.x - region.x % 8, region.y - region.y % 8
    x1 = min(W - W % 8, x0 + ((region.w + 7) // 8 + 1) * 8)
    y1 = min(H - H % 8, y0 + ((region.h + 7) // 8 + 1) * 8)
    t_detect = time.perf_counter()

    ycc = rgb_to_ycbcr(rgb)
    y_roi = ycc[y0:y1, x0:x1, 0].copy()
    rh, rw = y_roi.shape
    if rh < 16 or rw < 16:
        raise ValueError("Face region too small to immunise")

    dct = _block_dct(y_roi)
    qtab = _tile(jpeg_quant_table(prof.jpeg_quality), rh, rw)
    mask = _tile(MID_FREQ_MASK, rh, rw)

    be = identity_backend()
    e_orig = be.embed(rgb, face)
    seed = int.from_bytes(hashlib.sha256(seed_material.encode()).digest()[:4], "big")

    def render(delta_dct: np.ndarray) -> np.ndarray:
        y_new = np.clip(_block_idct(dct + delta_dct), 0, 255)
        out = ycc.copy()
        out[y0:y1, x0:x1, 0] = y_new
        return ycbcr_to_rgb(out)

    def score(img: np.ndarray) -> float:
        # evaluate identity shift *after* the social-media compression the image will actually face
        compressed = simulate_social_compression(img, prof.jpeg_quality)
        return cosine_distance(e_orig, be.embed(compressed, face))

    # --- projected zeroth-order ascent in mid-frequency DCT space ---
    eps = prof.epsilon_steps
    delta = np.zeros_like(dct)
    best_score = -1.0
    best_img = rgb
    for step in range(prof.pgd_steps):
        pats = _candidate_patterns((rh, rw), prof.candidates, seed + step)
        trial_best = None
        for p in pats:
            cand = np.clip(delta + 0.6 * eps * qtab * p * mask, -eps * qtab * mask, eps * qtab * mask)
            img = render(cand)
            s = score(img)
            if trial_best is None or s > trial_best[0]:
                trial_best = (s, cand, img)
        s, cand, img = trial_best
        # SSIM gate: shrink the step if we overshoot perceptual budget
        q = ssim(rgb, img)
        if q < prof.ssim_floor:
            eps *= 0.8
            continue
        if s >= best_score:
            best_score, best_img, delta = s, img, cand
        else:
            eps *= 0.9  # no improvement -> anneal

    if best_score < 0:  # every step tripped the gate; fall back to a minimal single pass
        p = _candidate_patterns((rh, rw), 1, seed)[0]
        best_img = render(0.5 * eps * qtab * p * mask)
        best_score = score(best_img)

    t_pgd = time.perf_counter()
    q = ssim(rgb, best_img)
    return CloakResult(
        image=best_img,
        face=face,
        ssim=round(q, 4),
        psnr=round(psnr(rgb, best_img), 2),
        identity_shift=round(float(best_score), 4),
        identity_backend=be.backend,
        epsilon=round(float(eps), 3),
        steps=prof.pgd_steps,
        timings_ms={"detect": round((t_detect - t0) * 1000), "pgd": round((t_pgd - t_detect) * 1000)},
    )
