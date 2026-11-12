-- NullFace production schema — PostgreSQL 16 (Supabase / Neon)
-- Zero-retention: no raw media is stored anywhere in this schema.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    password_hash TEXT,
    user_crypto_salt VARCHAR(64) NOT NULL DEFAULT encode(gen_random_bytes(32), 'hex'),
    api_key_hash VARCHAR(64) UNIQUE,
    protection_tier VARCHAR(20) DEFAULT 'FREE' CHECK (protection_tier IN ('FREE', 'PRO', 'ENTERPRISE')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS immunization_ledger (
    asset_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    watermark_bitstring BIT(64) NOT NULL,
    perceptual_hash VARCHAR(64) NOT NULL,
    sha256_checksum VARCHAR(64) UNIQUE NOT NULL,
    ssim_score NUMERIC(5, 4) NOT NULL,
    psnr_db NUMERIC(5, 2) NOT NULL,
    identity_shift_cosine NUMERIC(5, 4) NOT NULL,
    protection_profile VARCHAR(30) DEFAULT 'WHATSAPP_ROBUST',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ledger_user_id ON immunization_ledger(user_id);
CREATE INDEX IF NOT EXISTS idx_ledger_phash ON immunization_ledger(perceptual_hash);

CREATE TABLE IF NOT EXISTS forensic_scans (
    scan_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scanned_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    media_type VARCHAR(15) NOT NULL CHECK (media_type IN ('IMAGE', 'VIDEO', 'AUDIO')),
    file_sha256 VARCHAR(64) NOT NULL,
    deepfake_probability NUMERIC(5, 4) NOT NULL,
    fft_anomaly_score NUMERIC(5, 4),
    matched_asset_id UUID REFERENCES immunization_ledger(asset_id),
    hamming_distance INT,
    verdict VARCHAR(30) NOT NULL CHECK (verdict IN ('AUTHENTIC', 'SUSPICIOUS', 'SYNTHETIC_DEEPFAKE', 'STOLEN_IDENTITY_MATCH')),
    forensic_report_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scam_incidents (
    incident_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    channel VARCHAR(20) NOT NULL CHECK (channel IN ('LIVE_CALL', 'WHATSAPP_MSG', 'SMS', 'VOICE_NOTE')),
    transcript_snippet TEXT,
    voice_clone_score NUMERIC(5, 4),
    coercion_risk_score NUMERIC(5, 4) NOT NULL,
    detected_tactics TEXT[],
    flagged_urls TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS osint_canary_alerts (
    alert_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES immunization_ledger(asset_id) ON DELETE CASCADE,
    detected_source_domain VARCHAR(255) NOT NULL,
    similarity_score NUMERIC(5, 4) NOT NULL,
    status VARCHAR(20) DEFAULT 'UNREAD' CHECK (status IN ('UNREAD', 'ACKNOWLEDGED', 'TAKEDOWN_GENERATED')),
    detected_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sub-5 ms hardware-popcount attribution: who owns a photo whose watermark came back with <= 7 flipped bits?
-- (The API runs exactly this query via app/core/db.py::match_watermark on PostgreSQL.)
-- SELECT l.asset_id, u.full_name, u.email, l.created_at,
--        bit_count(l.watermark_bitstring # B'1011...'::bit(64)) AS hamming_distance
-- FROM immunization_ledger l JOIN users u ON l.user_id = u.id
-- WHERE bit_count(l.watermark_bitstring # B'1011...'::bit(64)) <= 7
-- ORDER BY hamming_distance ASC LIMIT 1;
