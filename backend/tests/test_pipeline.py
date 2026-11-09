"""End-to-end tests for the three services. Run: cd backend && pytest -q"""
import base64
import io
import os
import pathlib

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["NF_SERVER_SECRET"] = "test-secret-at-least-thirty-two-bytes-long!!"

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core import watermark as wm
from app.core.imaging import decode_image, luminance, simulate_social_compression
from app.main import app
from app.services.scamradar_service import audit_urls, score_text

ASSET = pathlib.Path(__file__).parent / "assets" / "sample_face.jpg"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/api/v1/auth/session", json={"email": "t@example.com", "full_name": "Test User"})
    assert r.status_code == 200
    return r.json()["access_token"]


# ---------------------------------------------------------------- watermark

def test_watermark_roundtrip_survives_jpeg_q50():
    rgb = decode_image(ASSET.read_bytes())
    bits = wm.derive_payload("user-1", 1700000000)
    assert len(bits) == 64
    from app.core.imaging import rgb_to_ycbcr, ycbcr_to_rgb
    ycc = rgb_to_ycbcr(rgb)
    ycc[..., 0] = wm.embed(ycc[..., 0], bits)
    marked = ycbcr_to_rgb(ycc)
    for q in (90, 70, 50):
        rec, _ = wm.extract(luminance(simulate_social_compression(marked, q)))
        assert wm.hamming(rec, bits) <= 7, f"Q={q}"
    rec_unmarked, _ = wm.extract(luminance(rgb))
    assert wm.hamming(rec_unmarked, bits) > 7  # no false attribution


def test_payload_is_keyed_and_deterministic():
    a = wm.derive_payload("u", 1, "k1")
    assert a == wm.derive_payload("u", 1, "k1")
    assert a != wm.derive_payload("u", 1, "k2")
    assert a != wm.derive_payload("v", 1, "k1")


# ---------------------------------------------------------------- PhotoCloak + DeepLens via API

def test_immunize_then_attribute_after_compression(client, token):
    h = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/v1/cloak/immunize", headers=h, files={"file": ("f.jpg", ASSET.read_bytes(), "image/jpeg")},
                    data={"profile": "WHATSAPP_ROBUST"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["metrics"]["ssim"] >= 0.95
    assert j["metrics"]["watermark_hamming_after_compression"] <= 7
    assert j["timings_ms"]["total"] < 5000
    assert "image_b64" in j

    # simulate WhatsApp: JPEG Q=50 with 4:2:0 subsampling
    im = Image.open(io.BytesIO(base64.b64decode(j["image_b64"])))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=50, subsampling=2)
    f = client.post("/api/v1/forensics/inspect", headers=h, files={"file": ("wa.jpg", buf.getvalue(), "image/jpeg")})
    assert f.status_code == 200, f.text
    rep = f.json()
    assert rep["verdict"] == "STOLEN_IDENTITY_MATCH"
    assert rep["stage1_canary_link"]["match"]["owner_name"] == "Test User"
    assert rep["stage1_canary_link"]["match"]["hamming_distance"] <= 7
    assert rep["stage1_canary_link"]["latency_ms"] < 200

    # an unprotected photo must not attribute to anyone
    f2 = client.post("/api/v1/forensics/inspect", files={"file": ("o.jpg", ASSET.read_bytes(), "image/jpeg")})
    assert f2.json()["stage1_canary_link"]["match"] is None


def test_stress_test_endpoint(client, token):
    r = client.post("/api/v1/cloak/stress-test", headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("f.jpg", ASSET.read_bytes(), "image/jpeg")})
    assert r.status_code == 200
    rep = r.json()["report"]
    assert rep["cloaked"]["identity_shift_cosine"] >= rep["original"]["identity_shift_cosine"]


def test_auth_required(client):
    r = client.post("/api/v1/cloak/immunize", files={"file": ("f.jpg", ASSET.read_bytes(), "image/jpeg")})
    assert r.status_code == 401


def test_audio_inspect(client):
    sr = 16000
    t = np.linspace(0, 2, sr * 2, endpoint=False)
    tone = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(tone.tobytes())
    r = client.post("/api/v1/forensics/inspect", files={"file": ("v.wav", buf.getvalue(), "audio/wav")})
    assert r.status_code == 200
    assert 0.0 <= r.json()["voice_clone_score"] <= 1.0


# ---------------------------------------------------------------- ScamRadar

def test_digital_arrest_script_is_critical():
    r = score_text("Main CBI se bol raha hoon. Kisi ko mat batana, call band mat karna. Abhi 2 lakh RBI ke safe account me transfer karo warna arrest.")
    assert r["risk_level"] == "CRITICAL"
    assert {"AUTHORITY_IMPERSONATION", "ISOLATION_COMMANDS", "URGENT_FINANCIAL_EXTRACTION"} <= set(r["tactics"])


def test_benign_message_is_low():
    r = score_text("Hey, dinner at 8 tonight? Mom is asking.")
    assert r["risk_level"] == "LOW"


def test_url_heuristics():
    u = audit_urls("update kyc at http://sbi-kyc-update.xyz/verify.apk")[0]
    assert u["risk"] >= 0.5 and any("sbi" in x for x in u["reasons"])


def test_audit_text_endpoint(client):
    r = client.post("/api/v1/scam/audit-text", json={"text": "Papa accident ho gaya, 50 hazar bhejo abhi, mummy ko mat batana"})
    assert r.status_code == 200 and r.json()["risk_level"] in ("HIGH", "CRITICAL")


def test_call_stream_websocket(client):
    with client.websocket_connect("/ws/v1/scam/call-stream") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "transcript", "text": "Main ED se officer bol raha hoon, aap digital arrest me hain"})
        u = ws.receive_json(); assert u["type"] == "update" and "AUTHORITY_IMPERSONATION" in u["tactics"]
        ws.send_json({"type": "transcript", "text": "kisi ko mat batana, abhi paisa transfer karo"})
        u = ws.receive_json(); assert u["alert"] and u["alert"]["level"] == "CRITICAL"
        pcm = (np.random.default_rng(0).normal(0, 0.1, 32000) * 32767).astype(np.int16).tobytes()
        ws.send_bytes(pcm)
        u = ws.receive_json(); assert u["voice_clone_chunk"] is not None
        ws.send_json({"type": "end"})
