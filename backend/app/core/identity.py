"""Identity embedding backends.

Primary: InsightFace ArcFace (``buffalo_l``) + ``inswapper_128.onnx`` when installed.
Fallback: a HOG-based face descriptor so the pipeline (and demo) runs on a plain CPU box with no model downloads.
Every result carries ``backend`` so the UI can say which one produced the number.
"""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np
from skimage.feature import hog

from .imaging import FaceBox, primary_face

_FACE_SIZE = 112


def _crop(rgb: np.ndarray, box: FaceBox) -> np.ndarray:
    b = box.expanded(1.15, rgb.shape[1], rgb.shape[0])
    crop = rgb[b.y : b.y + b.h, b.x : b.x + b.w]
    return cv2.resize(crop, (_FACE_SIZE, _FACE_SIZE), interpolation=cv2.INTER_AREA)


class HogIdentity:
    """Cheap, deterministic surrogate for an identity embedding (no downloads)."""

    backend = "hog-surrogate"

    def embed(self, rgb: np.ndarray, box: FaceBox | None = None) -> np.ndarray:
        box = box or primary_face(rgb)
        gray = cv2.cvtColor(_crop(rgb, box), cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        feat = hog(gray, orientations=9, pixels_per_cell=(8, 8), cells_per_block=(2, 2), feature_vector=True)
        feat = feat.astype(np.float32)
        n = np.linalg.norm(feat) + 1e-8
        return feat / n


class InsightFaceIdentity:
    backend = "insightface-arcface"

    def __init__(self) -> None:
        from insightface.app import FaceAnalysis  # type: ignore

        self.app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        self.app.prepare(ctx_id=0, det_size=(640, 640))

    def faces(self, rgb: np.ndarray):
        return self.app.get(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))

    def embed(self, rgb: np.ndarray, box: FaceBox | None = None) -> np.ndarray | None:
        faces = self.faces(rgb)
        if not faces:
            return None
        f = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        e = f.normed_embedding.astype(np.float32)
        return e / (np.linalg.norm(e) + 1e-8)


@lru_cache(maxsize=1)
def identity_backend():
    try:
        return InsightFaceIdentity()
    except Exception:  # insightface / onnxruntime not installed, or models not downloaded
        return HogIdentity()


def cosine_distance(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 1.0  # embedding vanished entirely: maximal shift
    return float(1.0 - np.dot(a, b))


def identity_shift(original: np.ndarray, cloaked: np.ndarray, box: FaceBox | None = None) -> dict:
    be = identity_backend()
    ea, eb = be.embed(original, box), be.embed(cloaked, box)
    return {"identity_shift_cosine": round(cosine_distance(ea, eb), 4), "backend": be.backend}
