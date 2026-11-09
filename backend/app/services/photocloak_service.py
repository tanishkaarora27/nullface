"""Service 1 — PhotoCloak: in-RAM immunise + Canary-Link watermark + hash-only ledger write."""
from __future__ import annotations

import base64
import time

import numpy as np

from ..core import watermark as wm
from ..core.config import settings
from ..core.db import get_db
from ..core.ephemeral import EphemeralBuffer
from ..core.identity import identity_backend, cosine_distance
from ..core.imaging import (decode_image, encode_jpeg, encode_png, luminance, phash, psnr, rgb_to_ycbcr, sha256,
                            simulate_social_compression, ssim, ycbcr_to_rgb, primary_face, detect_faces)
from ..core.photocloak import PROFILES, cloak


def immunize(data: bytes, user: dict, profile: str = "WHATSAPP_ROBUST", output: str = "png") -> dict:
    """Full pipeline. ``data`` lives only inside an EphemeralBuffer (RAM) and is zeroed in ``finally``."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    t0 = time.perf_counter()
    with EphemeralBuffer(data) as buf:
        try:
            rgb = decode_image(buf.read())
            res = cloak(rgb, profile, seed_material=user["user_crypto_salt"])
            t_cloak = time.perf_counter()

            # --- Canary-Link watermark on the immunised luminance channel ---
            ts = int(time.time())
            bits = wm.derive_payload(user["id"], ts)
            ycc = rgb_to_ycbcr(res.image)
            ycc[..., 0] = wm.embed(ycc[..., 0], bits)
            final = ycbcr_to_rgb(ycc)
            t_wm = time.perf_counter()

            # --- robustness self-check: survive social-media recompression? ---
            compressed = simulate_social_compression(final, PROFILES[profile].jpeg_quality)
            rec_bits, conf = wm.extract(luminance(compressed))
            survived_hamming = wm.hamming(rec_bits, bits)

            q_ssim, q_psnr = ssim(rgb, final), psnr(rgb, final)
            out_bytes = encode_png(final) if output == "png" else encode_jpeg(final, 92)
            sha = sha256(out_bytes)
            ph = phash(final)
            t_metrics = time.perf_counter()

            asset_id = get_db().insert_ledger(user["id"], bits, ph, sha, q_ssim, q_psnr, res.identity_shift, profile)
            return {
                "asset_id": asset_id,
                "profile": profile,
                "watermark_hex": wm.bits_to_hex(bits),
                "watermark_bits": bits,
                "perceptual_hash": ph,
                "sha256": sha,
                "metrics": {
                    "ssim": round(q_ssim, 4),
                    "psnr_db": round(q_psnr, 2),
                    "identity_shift_cosine": res.identity_shift,
                    "identity_backend": res.identity_backend,
                    "watermark_survives_jpeg_q": PROFILES[profile].jpeg_quality,
                    "watermark_hamming_after_compression": survived_hamming,
                    "watermark_confidence_after_compression": conf,
                },
                "face": res.face.as_dict(),
                "timings_ms": {
                    **res.timings_ms,
                    "watermark": round((t_wm - t_cloak) * 1000),
                    "metrics": round((t_metrics - t_wm) * 1000),
                    "total": round((time.perf_counter() - t0) * 1000),
                },
                "image_b64": base64.b64encode(out_bytes).decode(),
                "mime": "image/png" if output == "png" else "image/jpeg",
                "retention": "zero — raw image zeroed from RAM; only hashes persisted",
            }
        finally:
            # free large arrays eagerly; the buffer itself is wiped by EphemeralBuffer.__exit__
            for arr in (locals().get("rgb"), locals().get("final"), locals().get("ycc"), locals().get("compressed")):
                if isinstance(arr, np.ndarray) and arr.flags.writeable:
                    arr.fill(0)


def stress_test(data: bytes, user: dict, profile: str = "WHATSAPP_ROBUST") -> dict:
    """Side-by-side: run the face-swap / identity pipeline on ORIGINAL vs CLOAKED, after social compression.

    With InsightFace installed the real ``inswapper_128`` swap runs; otherwise the identity backend (HOG surrogate)
    reports how far the face-recognition descriptor moved and whether the Haar detector still locks on.
    """
    with EphemeralBuffer(data) as buf:
        rgb = decode_image(buf.read())
        res = cloak(rgb, profile, seed_material=user["user_crypto_salt"])
        q = PROFILES[profile].jpeg_quality
        orig_c = simulate_social_compression(rgb, q)
        cloak_c = simulate_social_compression(res.image, q)

        be = identity_backend()
        e_ref = be.embed(rgb, res.face)
        shift_orig = cosine_distance(e_ref, be.embed(orig_c, res.face))
        shift_cloak = cosine_distance(e_ref, be.embed(cloak_c, res.face))

        report = {
            "profile": profile,
            "compression_quality": q,
            "identity_backend": be.backend,
            "original": {"identity_shift_cosine": round(shift_orig, 4), "faces_detected": len(detect_faces(orig_c))},
            "cloaked": {"identity_shift_cosine": round(shift_cloak, 4), "faces_detected": len(detect_faces(cloak_c)),
                        "ssim": res.ssim, "psnr_db": res.psnr},
            "swap": None,
        }

        swapped_orig = swapped_cloak = None
        if be.backend == "insightface-arcface":
            try:
                swapped_orig, swapped_cloak, swap_report = _real_swap(be, orig_c, cloak_c)
                report["swap"] = swap_report
            except Exception as exc:  # model file missing etc.
                report["swap"] = {"available": False, "reason": str(exc)[:200]}
        else:
            report["swap"] = {"available": False,
                              "reason": "InsightFace/inswapper not installed — showing identity-descriptor shift instead"}

        return {
            "report": report,
            "images": {
                "original_compressed": base64.b64encode(encode_jpeg(orig_c, 90)).decode(),
                "cloaked_compressed": base64.b64encode(encode_jpeg(cloak_c, 90)).decode(),
                "swap_on_original": base64.b64encode(encode_jpeg(swapped_orig, 90)).decode() if swapped_orig is not None else None,
                "swap_on_cloaked": base64.b64encode(encode_jpeg(swapped_cloak, 90)).decode() if swapped_cloak is not None else None,
            },
        }


def _real_swap(be, orig: np.ndarray, cloaked: np.ndarray):
    """InsightFace inswapper_128: swap the *original* face into both images, measure success via ArcFace."""
    import cv2
    import insightface  # type: ignore

    swapper = insightface.model_zoo.get_model("inswapper_128.onnx", providers=["CPUExecutionProvider"])
    src_faces = be.faces(orig)
    if not src_faces:
        raise RuntimeError("no face in source")
    src = src_faces[0]
    out = []
    for img in (orig, cloaked):
        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        faces = be.faces(img)
        if faces:
            bgr = swapper.get(bgr, faces[0], src, paste_back=True)
        out.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    e_src = src.normed_embedding
    def sim(img):
        f = be.faces(img)
        return float(np.dot(e_src, f[0].normed_embedding)) if f else 0.0
    return out[0], out[1], {"available": True, "model": "inswapper_128",
                            "swap_similarity_original": round(sim(out[0]), 4),
                            "swap_similarity_cloaked": round(sim(out[1]), 4)}
