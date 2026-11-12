"""Shared image helpers: decoding, colour-space, SSIM/PSNR, pHash, face localisation, JPEG simulation."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from functools import lru_cache

import cv2
import imagehash
import numpy as np
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

from .config import DATA_DIR, settings

# ---------------------------------------------------------------------------
# decode / encode
# ---------------------------------------------------------------------------

def decode_image(data: bytes) -> np.ndarray:
    """bytes -> RGB uint8 array (downscaled so the longest side <= MAX_IMAGE_SIDE)."""
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    w, h = img.size
    m = max(w, h)
    if m > settings.MAX_IMAGE_SIDE:
        s = settings.MAX_IMAGE_SIDE / m
        img = img.resize((max(8, int(w * s)), max(8, int(h * s))), Image.LANCZOS)
    return np.array(img, dtype=np.uint8)


def encode_jpeg(rgb: np.ndarray, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG", quality=quality, subsampling=0)
    return buf.getvalue()


def encode_png(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def simulate_social_compression(rgb: np.ndarray, quality: int | None = None) -> np.ndarray:
    """Round-trip through JPEG at WhatsApp/Instagram-like quality (default Q=50, 4:2:0 subsampling)."""
    q = quality or settings.JPEG_TARGET_QUALITY
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG", quality=q, subsampling=2)
    return np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"), dtype=np.uint8)


# ---------------------------------------------------------------------------
# colour space
# ---------------------------------------------------------------------------

def rgb_to_ycbcr(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb).astype(np.float32)[..., [0, 2, 1]]  # Y, Cb, Cr


def ycbcr_to_rgb(ycbcr: np.ndarray) -> np.ndarray:
    ycrcb = np.clip(ycbcr[..., [0, 2, 1]], 0, 255).astype(np.uint8)
    return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2RGB)


def luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb_to_ycbcr(rgb)[..., 0]


# ---------------------------------------------------------------------------
# quality metrics & hashes
# ---------------------------------------------------------------------------

def ssim(a: np.ndarray, b: np.ndarray) -> float:
    ga = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    gb = cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)
    return float(structural_similarity(ga, gb, data_range=255))


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    if np.array_equal(a, b):
        return 99.0
    return float(peak_signal_noise_ratio(a, b, data_range=255))


def phash(rgb: np.ndarray) -> str:
    return str(imagehash.phash(Image.fromarray(rgb)))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# face localisation (OpenCV Haar cascade; InsightFace used instead when installed)
# ---------------------------------------------------------------------------

@dataclass
class FaceBox:
    x: int
    y: int
    w: int
    h: int
    detector: str

    def expanded(self, factor: float, width: int, height: int) -> "FaceBox":
        cx, cy = self.x + self.w / 2, self.y + self.h / 2
        nw, nh = self.w * factor, self.h * factor
        x0 = int(max(0, cx - nw / 2))
        y0 = int(max(0, cy - nh / 2))
        x1 = int(min(width, cx + nw / 2))
        y1 = int(min(height, cy + nh / 2))
        return FaceBox(x0, y0, x1 - x0, y1 - y0, self.detector)

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h, "detector": self.detector}


@lru_cache(maxsize=1)
def _cascade() -> cv2.CascadeClassifier:
    return cv2.CascadeClassifier(str(DATA_DIR / "haarcascade_frontalface_default.xml"))


def detect_faces(rgb: np.ndarray) -> list[FaceBox]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.equalizeHist(gray)
    min_side = max(24, int(min(gray.shape) * 0.08))
    boxes = _cascade().detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(min_side, min_side))
    out = [FaceBox(int(x), int(y), int(w), int(h), "opencv-haar") for (x, y, w, h) in boxes]
    out.sort(key=lambda b: b.w * b.h, reverse=True)
    return out


def primary_face(rgb: np.ndarray) -> FaceBox:
    faces = detect_faces(rgb)
    if faces:
        return faces[0]
    # No face found: protect the central region so the pipeline still runs end-to-end.
    h, w = rgb.shape[:2]
    s = int(min(w, h) * 0.6)
    return FaceBox((w - s) // 2, (h - s) // 2, s, s, "center-fallback")
