"""Central configuration for NullFace. Everything is overridable via environment variables."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    return val if val not in (None, "") else default


class Settings:
    # --- app ---
    APP_NAME = "NullFace (Kavach-AI)"
    VERSION = "0.1.0"
    ENV = _env("NF_ENV", "dev")
    FRONTEND_DIR = Path(_env("NF_FRONTEND_DIR", str(BASE_DIR.parents[1] / "frontend" / "public")))

    # --- security ---
    SERVER_SECRET = _env("NF_SERVER_SECRET", "dev-only-change-me-32-bytes-minimum!!")
    JWT_ALG = "HS256"
    JWT_TTL_SECONDS = int(_env("NF_JWT_TTL", "900"))  # 15 min access tokens
    SUPABASE_JWT_SECRET = _env("SUPABASE_JWT_SECRET")  # when set, Supabase-issued tokens are accepted
    CORS_ORIGINS = [o.strip() for o in _env("NF_CORS_ORIGINS", "*").split(",")]

    # --- storage ---
    DATABASE_URL = _env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'nullface.db'}")
    REDIS_URL = _env("REDIS_URL")  # optional; in-memory limiter when absent
    EPHEMERAL_DIR = Path(_env("NF_EPHEMERAL_DIR", "/dev/shm" if Path("/dev/shm").exists() else "/tmp"))

    # --- rate limiting (token bucket) ---
    RATE_LIMIT_PER_MINUTE = int(_env("NF_RATE_LIMIT_PER_MINUTE", "60"))

    # --- PhotoCloak ---
    SSIM_FLOOR = float(_env("NF_SSIM_FLOOR", "0.96"))
    JPEG_TARGET_QUALITY = int(_env("NF_JPEG_TARGET_QUALITY", "50"))
    PGD_STEPS = int(_env("NF_PGD_STEPS", "10"))
    WATERMARK_DELTA = float(_env("NF_WATERMARK_DELTA", "28.0"))
    WATERMARK_REDUNDANCY = int(_env("NF_WATERMARK_REDUNDANCY", "24"))
    WATERMARK_KEY = _env("NF_WATERMARK_KEY", "nullface-canary-v1")
    MAX_IMAGE_SIDE = int(_env("NF_MAX_IMAGE_SIDE", "1600"))

    # --- DeepLens ---
    BER_MATCH_THRESHOLD = float(_env("NF_BER_MATCH_THRESHOLD", "0.12"))  # 12 % => <= 7 flipped bits of 64
    HF_DEEPFAKE_MODEL = _env("NF_HF_DEEPFAKE_MODEL", "dima806/deepfake_vs_real_image_detection")
    HF_AUDIO_MODEL = _env("NF_HF_AUDIO_MODEL", "MelodyMachine/Deepfake-audio-detection-V2")

    # --- ScamRadar ---
    GROQ_API_KEY = _env("GROQ_API_KEY")
    GROQ_WHISPER_MODEL = _env("NF_GROQ_WHISPER_MODEL", "whisper-large-v3")
    GROQ_LLM_MODEL = _env("NF_GROQ_LLM_MODEL", "llama-3.3-70b-versatile")
    SAFE_BROWSING_API_KEY = _env("GOOGLE_SAFE_BROWSING_API_KEY")
    EMBEDDING_MODEL = _env("NF_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    CHROMA_DIR = Path(_env("NF_CHROMA_DIR", str(BASE_DIR / "chroma")))


settings = Settings()
