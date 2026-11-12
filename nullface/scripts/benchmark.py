#!/usr/bin/env python3
"""Reproduce the headline numbers on any folder of face photos (LFW / CelebA / your own selfies).

    python scripts/benchmark.py path/to/images --limit 50

Reports mean SSIM, PSNR, identity shift, cloak latency, and watermark bit-error rate after JPEG Q=90/70/50/40.
"""
import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

import numpy as np

from app.core import watermark as wm
from app.core.imaging import decode_image, luminance, rgb_to_ycbcr, simulate_social_compression, ssim, psnr, ycbcr_to_rgb
from app.core.photocloak import cloak

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("--limit", type=int, default=25)
ap.add_argument("--profile", default="WHATSAPP_ROBUST")
args = ap.parse_args()

files = sorted(p for p in pathlib.Path(args.folder).rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))[: args.limit]
if not files:
    sys.exit("no images found")
rows = []
for i, f in enumerate(files, 1):
    rgb = decode_image(f.read_bytes())
    t0 = time.perf_counter()
    res = cloak(rgb, args.profile, seed_material=str(i))
    bits = wm.derive_payload("bench", i)
    ycc = rgb_to_ycbcr(res.image); ycc[..., 0] = wm.embed(ycc[..., 0], bits); final = ycbcr_to_rgb(ycc)
    ms = (time.perf_counter() - t0) * 1000
    ber = {q: wm.ber(wm.extract(luminance(simulate_social_compression(final, q)))[0], bits) for q in (90, 70, 50, 40)}
    rows.append((ssim(rgb, final), psnr(rgb, final), res.identity_shift, ms, ber, res.face.detector))
    print(f"[{i}/{len(files)}] {f.name[:28]:28s} SSIM {rows[-1][0]:.4f} PSNR {rows[-1][1]:5.2f} shift {res.identity_shift:.4f} "
          f"{ms:6.0f} ms  BER@50 {ber[50]*100:4.1f}%  ({res.identity_backend}, {res.face.detector})")

a = np.array([(r[0], r[1], r[2], r[3]) for r in rows])
print("\n=== summary ===")
print(f"images                 {len(rows)}   (faces found: {sum(r[5] != 'center-fallback' for r in rows)})")
print(f"mean SSIM              {a[:,0].mean():.4f}   (min {a[:,0].min():.4f})")
print(f"mean PSNR              {a[:,1].mean():.2f} dB")
print(f"mean identity shift    {a[:,2].mean():.4f}   backend: {res.identity_backend}")
print(f"mean cloak+wm latency  {a[:,3].mean():.0f} ms  (p95 {np.percentile(a[:,3],95):.0f} ms)")
for q in (90, 70, 50, 40):
    b = np.array([r[4][q] for r in rows])
    print(f"watermark BER @Q={q:<3} {b.mean()*100:5.2f}%   attributable (<12%): {np.mean(b < 0.12)*100:5.1f}%")
