"""REST + WebSocket API contract (FastAPI gateway)."""
from __future__ import annotations

import base64
import json
import secrets
import time
import uuid

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, EmailStr, Field

from ..core.auth import current_user, issue_token, new_api_key, optional_user, ws_user
from ..core.config import settings
from ..core.db import get_db
from ..core.ephemeral import EphemeralBuffer
from ..core.identity import identity_backend
from ..core.photocloak import PROFILES
from ..core.ratelimit import rate_limit
from ..services import deeplens_service as deeplens
from ..services import photocloak_service as photocloak
from ..services import scamradar_service as scamradar

router = APIRouter(prefix="/api/v1", dependencies=[Depends(rate_limit)])

MAX_UPLOAD = 15 * 1024 * 1024


async def _read_upload(f: UploadFile) -> bytes:
    data = await f.read()
    if not data:
        raise HTTPException(400, "empty upload")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file larger than 15 MB")
    return data


# --------------------------------------------------------------------------- auth

class SessionIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    provider_token: str | None = Field(default=None, description="Supabase OAuth/Passkey token (optional in demo mode)")


@router.post("/auth/session", summary="Exchange a Supabase OAuth/Passkey token (or demo email) for an access token")
def auth_session(body: SessionIn):
    db = get_db()
    user = db.upsert_user(body.email.lower(), body.full_name, secrets.token_hex(32))
    return {"access_token": issue_token(user), "token_type": "bearer", "expires_in": settings.JWT_TTL_SECONDS,
            "user": {"id": user["id"], "email": user["email"], "full_name": user["full_name"], "tier": user["protection_tier"]}}


@router.post("/auth/api-key", summary="Mint a scoped extension API key (only its SHA-256 hash is stored)")
def mint_api_key(user: dict = Depends(current_user)):
    raw, h = new_api_key()
    get_db().set_api_key_hash(user["id"], h)
    return {"api_key": raw, "note": "Shown once. Store it in the Chrome extension options page."}


@router.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return {"id": user["id"], "email": user["email"], "full_name": user["full_name"], "tier": user["protection_tier"],
            "ledger": get_db().ledger_for_user(user["id"])}


# --------------------------------------------------------------------------- PhotoCloak

@router.post("/cloak/immunize", summary="In-RAM YCbCr DCT-PGD + 64-bit DWT watermark; hash-only ledger; streams protected image")
async def immunize(file: UploadFile = File(...), profile: str = Form("WHATSAPP_ROBUST"), output: str = Form("png"),
                   user: dict = Depends(current_user)):
    data = await _read_upload(file)
    try:
        return photocloak.immunize(data, user, profile, output)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/cloak/stress-test", summary="Original vs cloaked through social compression + face-swap / identity pipeline")
async def stress(file: UploadFile = File(...), profile: str = Form("WHATSAPP_ROBUST"), user: dict = Depends(current_user)):
    data = await _read_upload(file)
    try:
        return photocloak.stress_test(data, user, profile)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/cloak/profiles")
def profiles():
    return {k: {"jpeg_quality": v.jpeg_quality, "ssim_floor": v.ssim_floor, "pgd_steps": v.pgd_steps} for k, v in PROFILES.items()}


# --------------------------------------------------------------------------- DeepLens

@router.post("/forensics/inspect", summary="3-stage check: blind DWT extraction → 2D-FFT + ViT + Grad-CAM → C2PA audit")
async def inspect(file: UploadFile = File(...), user: dict | None = Depends(optional_user)):
    data = await _read_upload(file)
    ctype = (file.content_type or "").lower()
    name = (file.filename or "").lower()
    if ctype.startswith("audio/") or name.endswith((".wav", ".mp3", ".ogg", ".m4a", ".opus", ".webm", ".flac")):
        return deeplens.inspect_audio(data, user)
    try:
        return deeplens.inspect_image(data, user)
    except Exception as exc:
        raise HTTPException(400, f"could not analyse media: {exc}")


# --------------------------------------------------------------------------- ScamRadar

class AuditIn(BaseModel):
    text: str | None = None
    transcript: str | None = None
    channel: str = Field(default="WHATSAPP_MSG")


@router.post("/scam/audit-text", summary="Audit SMS/WhatsApp text + URLs via Coercion RAG & Safe Browsing")
@router.post("/scam/analyze-text", summary="Alias for scam audit")
def audit_text(body: AuditIn, user: dict | None = Depends(optional_user)):
    content = body.text or body.transcript or ""
    if not content:
        raise HTTPException(400, "empty text")
    return scamradar.audit_text(content, user, body.channel)


@router.get("/scam/kb")
def kb():
    k = scamradar.load_kb()
    return {"tactics": k["tactics"], "scripts": len(k["scripts"]), "source": k["source"]}


# --------------------------------------------------------------------------- system & demo fixtures

@router.get("/system/status")
def system_status():
    stats = get_db().stats()
    return {
        "status": "OPERATIONAL",
        "protected_assets_count": stats.get("immunization_ledger", 0),
        "active_users": stats.get("users", 0),
        "scans_completed": stats.get("forensic_scans", 0),
    }


@router.get("/demo/sample-portrait")
@router.get("/system/sample-portrait")
def demo_sample_portrait():
    import pathlib
    asset_path = pathlib.Path(__file__).parent.parent.parent / "tests" / "assets" / "sample_face.jpg"
    if asset_path.exists():
        raw = asset_path.read_bytes()
        b64 = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
        return {"sample_image_data_url": b64, "image_data_url": b64}
    return {"sample_image_data_url": "", "image_data_url": ""}


@router.get("/demo/scenarios")
@router.get("/system/demo-scenarios")
def demo_scenarios():
    return {
        "scenarios": [
            {
                "id": "cbi_digital_arrest",
                "title": "CBI Digital Arrest (Extortion)",
                "transcript": "Main CBI Cyber Crime Cell Mumbai se Inspector bol raha hoon. Aapke Aadhaar par ek parcel pakda gaya hai jisme MDMA drugs paye gaye hain. Aap digital arrest me hain, video call band mat karna. Verification ke liye abhi 2 lakh transfer karo.",
            },
            {
                "id": "trai_disconnection",
                "title": "TRAI Immediate Mobile Disconnection",
                "transcript": "This is Department of Telecommunications. All your mobile numbers will be blocked within 2 hours due to illegal advertising. Press 9 immediately to speak with our compliance executive.",
            },
            {
                "id": "family_emergency",
                "title": "Family Emergency / Bail Scam",
                "transcript": "Papa mera accident ho gaya hai police station me hoon, 50 hazar turant transfer karo mamla settle karne ke liye, mummy ko mat batana.",
            },
        ]
    }


@router.get("/ledger/recent")
def ledger_recent():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            db._q(
                "SELECT asset_id, user_id, watermark_bitstring, perceptual_hash, ssim_score, psnr_db, protection_profile, created_at "
                "FROM immunization_ledger ORDER BY created_at DESC LIMIT 50"
            )
        )
        rows = [db._row(cur, r) for r in cur.fetchall()]
    return {"ledger": rows, "total_records": len(rows)}


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.VERSION, "env": settings.ENV,
            "identity_backend": identity_backend().backend, "db": get_db().dialect,
            "ephemeral_store": EphemeralBuffer.backing_store(), "groq": bool(settings.GROQ_API_KEY),
            "safe_browsing": bool(settings.SAFE_BROWSING_API_KEY), "stats": get_db().stats()}


# --------------------------------------------------------------------------- WebSocket: live call shield

ws_router = APIRouter()


@ws_router.websocket("/ws/v1/scam/call-stream")
async def call_stream(ws: WebSocket):
    """Protocol
    client → server:  binary frames = 16 kHz mono PCM16 chunks (~2 s)   |  text frames = JSON
                       {"type":"transcript","text":"..."}  (browser SpeechRecognition fallback)
                       {"type":"config","sample_rate":16000,"language":"hi"} | {"type":"end"}
    server → client:  {"type":"update", transcript_chunk, transcript_window, voice_clone_score, coercion_risk_score,
                       risk_level, tactics, alert, evidence, session}
    """
    await ws.accept()
    user = ws_user(ws)
    sid = str(uuid.uuid4())
    sess = scamradar.sessions.get(sid, user["id"] if user else None)
    sample_rate, language = 16000, None
    await ws.send_json({"type": "ready", "session_id": sid, "asr": "groq" if settings.GROQ_API_KEY else "browser-fallback",
                        "voice_backend": "wav2vec2" if deeplens._wav2vec() else "heuristic"})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            t0 = time.perf_counter()
            text_chunk, clone = "", None
            if msg.get("bytes"):
                pcm = msg["bytes"]
                y = deeplens.pcm16_to_float(pcm)
                clone = deeplens.voice_clone_score(y, sample_rate)
                asr = scamradar.transcribe_pcm16(pcm, sample_rate, language)
                text_chunk = asr.get("text", "")
            elif msg.get("text"):
                try:
                    payload = json.loads(msg["text"])
                except json.JSONDecodeError:
                    payload = {"type": "transcript", "text": msg["text"]}
                if payload.get("type") == "config":
                    sample_rate = int(payload.get("sample_rate", 16000))
                    language = payload.get("language")
                    continue
                if payload.get("type") == "end":
                    break
                text_chunk = payload.get("text", "")
                if payload.get("pcm_b64"):
                    y = deeplens.pcm16_to_float(base64.b64decode(payload["pcm_b64"]))
                    clone = deeplens.voice_clone_score(y, sample_rate)

            sess.chunks += 1
            if text_chunk.strip():
                sess.transcript.append((time.time(), text_chunk.strip()))
            if clone is not None:
                sess.clone_scores.append(clone["voice_clone_score"])
            window = sess.window_text(30)
            score = scamradar.score_text(window) if window else {"coercion_risk_score": 0.0, "risk_level": "LOW", "tactics": [],
                                                                   "tactic_scores": {}, "evidence": [], "lexicon": {}}
            risk = score["coercion_risk_score"]
            mean_clone = float(np.mean(sess.clone_scores)) if sess.clone_scores else 0.0
            sess.peak_risk = max(sess.peak_risk, risk)
            sess.tactics_seen.update(score["tactics"])
            alert = None
            if risk >= 0.75 or (risk >= 0.55 and mean_clone >= 0.6):
                alert = {"level": "CRITICAL", "message": "Likely 'Digital Arrest' / coercion script" + (" + cloned voice" if mean_clone >= 0.6 else "")
                         + ". Hang up. Do not transfer money. Call 1930."}
            elif risk >= 0.55 or mean_clone >= 0.75:
                alert = {"level": "HIGH", "message": "Coercion tactics detected — verify the caller through an official number."}
            elif risk >= 0.35:
                alert = {"level": "MEDIUM", "message": "Suspicious pressure language — stay cautious."}
            if alert and alert["level"] in ("CRITICAL", "HIGH") and sess.chunks % 5 == 1:
                get_db().insert_incident(user["id"] if user else None, "LIVE_CALL", window[-500:], mean_clone, risk,
                                         score["tactics"], [])
            scamradar.sessions.persist(sess)
            await ws.send_json({
                "type": "update", "transcript_chunk": text_chunk, "transcript_window": window,
                "voice_clone_score": round(mean_clone, 4), "voice_clone_chunk": clone,
                "coercion_risk_score": risk, "risk_level": score.get("risk_level", "LOW"), "tactics": score["tactics"],
                "tactic_scores": score.get("tactic_scores", {}), "lexicon": score.get("lexicon", {}),
                "evidence": score.get("evidence", [])[:2], "alert": alert, "session": sess.snapshot(),
                "latency_ms": round((time.perf_counter() - t0) * 1000),
            })
    except WebSocketDisconnect:
        pass
    finally:
        final = scamradar.sessions.drop(sid)
        try:
            await ws.send_json({"type": "closed", "session": final.snapshot() if final else None})
        except Exception:
            pass
