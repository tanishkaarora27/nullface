"""Hash-only persistence layer.

Zero-retention rule: no raw media is ever written here — only 64-bit watermark signatures, perceptual hashes,
quality metrics and audit rows.  SQLite is used out of the box; set DATABASE_URL=postgresql://... (Supabase/Neon)
to use PostgreSQL 16, where watermark attribution runs as a hardware-popcount ``bit_count`` query (see
deploy/schema.sql).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from .config import settings

_IS_PG = settings.DATABASE_URL.startswith(("postgres://", "postgresql://"))

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL,
    user_crypto_salt TEXT NOT NULL, api_key_hash TEXT UNIQUE, protection_tier TEXT DEFAULT 'FREE',
    created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS immunization_ledger (
    asset_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, watermark_bitstring TEXT NOT NULL,
    perceptual_hash TEXT NOT NULL, sha256_checksum TEXT UNIQUE NOT NULL, ssim_score REAL NOT NULL,
    psnr_db REAL NOT NULL, identity_shift_cosine REAL NOT NULL, protection_profile TEXT DEFAULT 'WHATSAPP_ROBUST',
    created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_ledger_user_id ON immunization_ledger(user_id);
CREATE INDEX IF NOT EXISTS idx_ledger_phash ON immunization_ledger(perceptual_hash);
CREATE TABLE IF NOT EXISTS forensic_scans (
    scan_id TEXT PRIMARY KEY, scanned_by_user_id TEXT, media_type TEXT NOT NULL, file_sha256 TEXT NOT NULL,
    deepfake_probability REAL NOT NULL, fft_anomaly_score REAL, matched_asset_id TEXT, hamming_distance INTEGER,
    verdict TEXT NOT NULL, forensic_report_json TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS scam_incidents (
    incident_id TEXT PRIMARY KEY, user_id TEXT, channel TEXT NOT NULL, transcript_snippet TEXT,
    voice_clone_score REAL, coercion_risk_score REAL NOT NULL, detected_tactics TEXT, flagged_urls TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS osint_canary_alerts (
    alert_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, asset_id TEXT NOT NULL, detected_source_domain TEXT NOT NULL,
    similarity_score REAL NOT NULL, status TEXT DEFAULT 'UNREAD', detected_at TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        if _IS_PG:
            import psycopg  # type: ignore

            self._pg = psycopg
            self._conn = psycopg.connect(settings.DATABASE_URL, autocommit=True)
            self.dialect = "postgresql"
        else:
            path = settings.DATABASE_URL.replace("sqlite:///", "")
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SQLITE_SCHEMA)
            self.dialect = "sqlite"

    # ------------------------------------------------------------------ helpers
    def _q(self, sql: str) -> str:
        return sql if self.dialect == "sqlite" else sql.replace("?", "%s")

    @contextmanager
    def cursor(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                if self.dialect == "sqlite":
                    self._conn.commit()
            finally:
                cur.close()

    def _row(self, cur, row) -> dict[str, Any] | None:
        if row is None:
            return None
        if self.dialect == "sqlite":
            return dict(row)
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    # ------------------------------------------------------------------ users
    def upsert_user(self, email: str, full_name: str, salt: str) -> dict:
        with self.cursor() as cur:
            cur.execute(self._q("SELECT * FROM users WHERE email = ?"), (email,))
            row = self._row(cur, cur.fetchone())
            if row:
                return row
            uid = str(uuid.uuid4())
            cur.execute(
                self._q("INSERT INTO users (id, email, full_name, user_crypto_salt, created_at, updated_at) VALUES (?,?,?,?,?,?)"),
                (uid, email, full_name, salt, _now(), _now()),
            )
            cur.execute(self._q("SELECT * FROM users WHERE id = ?"), (uid,))
            return self._row(cur, cur.fetchone())

    def get_user(self, user_id: str) -> dict | None:
        with self.cursor() as cur:
            cur.execute(self._q("SELECT * FROM users WHERE id = ?"), (user_id,))
            return self._row(cur, cur.fetchone())

    def user_by_api_key_hash(self, key_hash: str) -> dict | None:
        with self.cursor() as cur:
            cur.execute(self._q("SELECT * FROM users WHERE api_key_hash = ?"), (key_hash,))
            return self._row(cur, cur.fetchone())

    def set_api_key_hash(self, user_id: str, key_hash: str) -> None:
        with self.cursor() as cur:
            cur.execute(self._q("UPDATE users SET api_key_hash = ?, updated_at = ? WHERE id = ?"), (key_hash, _now(), user_id))

    # ------------------------------------------------------------------ ledger
    def insert_ledger(self, user_id: str, bits: str, phash: str, sha: str, ssim: float, psnr: float,
                      shift: float, profile: str) -> str:
        asset_id = str(uuid.uuid4())
        bit_val = bits if self.dialect == "sqlite" else bits  # PG: BIT(64) accepts a '0101..' literal via cast
        with self.cursor() as cur:
            if self.dialect == "sqlite":
                cur.execute(
                    "INSERT OR IGNORE INTO immunization_ledger (asset_id,user_id,watermark_bitstring,perceptual_hash,"
                    "sha256_checksum,ssim_score,psnr_db,identity_shift_cosine,protection_profile,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (asset_id, user_id, bit_val, phash, sha, ssim, psnr, shift, profile, _now()),
                )
            else:
                cur.execute(
                    "INSERT INTO immunization_ledger (asset_id,user_id,watermark_bitstring,perceptual_hash,"
                    "sha256_checksum,ssim_score,psnr_db,identity_shift_cosine,protection_profile) "
                    "VALUES (%s,%s,%s::bit(64),%s,%s,%s,%s,%s,%s) ON CONFLICT (sha256_checksum) DO NOTHING",
                    (asset_id, user_id, bit_val, phash, sha, ssim, psnr, shift, profile),
                )
        return asset_id

    def match_watermark(self, bits: str, max_hamming: int = 7) -> dict | None:
        """Error-tolerant attribution: nearest ledger signature within ``max_hamming`` flipped bits."""
        with self.cursor() as cur:
            if self.dialect == "postgresql":
                cur.execute(
                    "SELECT l.asset_id, l.user_id, u.full_name, u.email, l.created_at, l.protection_profile, "
                    "bit_count(l.watermark_bitstring # %s::bit(64)) AS hamming_distance "
                    "FROM immunization_ledger l JOIN users u ON l.user_id = u.id "
                    "WHERE bit_count(l.watermark_bitstring # %s::bit(64)) <= %s ORDER BY hamming_distance ASC LIMIT 1",
                    (bits, bits, max_hamming),
                )
                return self._row(cur, cur.fetchone())
            cur.execute(
                "SELECT l.asset_id, l.user_id, l.watermark_bitstring, u.full_name, u.email, l.created_at, l.protection_profile "
                "FROM immunization_ledger l JOIN users u ON l.user_id = u.id"
            )
            best = None
            for row in cur.fetchall():
                d = sum(a != b for a, b in zip(row["watermark_bitstring"], bits))
                if d <= max_hamming and (best is None or d < best["hamming_distance"]):
                    best = {k: row[k] for k in row.keys() if k != "watermark_bitstring"}
                    best["hamming_distance"] = d
            return best

    def ledger_for_user(self, user_id: str, limit: int = 50) -> list[dict]:
        with self.cursor() as cur:
            cur.execute(self._q("SELECT asset_id, perceptual_hash, ssim_score, psnr_db, identity_shift_cosine, protection_profile, created_at "
                                "FROM immunization_ledger WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"), (user_id, limit))
            return [self._row(cur, r) for r in cur.fetchall()]

    # ------------------------------------------------------------------ audit logs
    def insert_scan(self, user_id: str | None, media_type: str, sha: str, prob: float, fft: float | None,
                    matched_asset: str | None, hamming: int | None, verdict: str, report: dict) -> str:
        sid = str(uuid.uuid4())
        with self.cursor() as cur:
            cur.execute(
                self._q("INSERT INTO forensic_scans (scan_id,scanned_by_user_id,media_type,file_sha256,deepfake_probability,"
                        "fft_anomaly_score,matched_asset_id,hamming_distance,verdict,forensic_report_json,created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)"),
                (sid, user_id, media_type, sha, prob, fft, matched_asset, hamming, verdict, json.dumps(report), _now()),
            )
        return sid

    def insert_incident(self, user_id: str | None, channel: str, snippet: str | None, clone: float | None,
                        risk: float, tactics: list[str], urls: list[str]) -> str:
        iid = str(uuid.uuid4())
        with self.cursor() as cur:
            if self.dialect == "sqlite":
                cur.execute(
                    "INSERT INTO scam_incidents (incident_id,user_id,channel,transcript_snippet,voice_clone_score,"
                    "coercion_risk_score,detected_tactics,flagged_urls,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (iid, user_id, channel, snippet, clone, risk, json.dumps(tactics), json.dumps(urls), _now()),
                )
            else:
                cur.execute(
                    "INSERT INTO scam_incidents (incident_id,user_id,channel,transcript_snippet,voice_clone_score,"
                    "coercion_risk_score,detected_tactics,flagged_urls) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (iid, user_id, channel, snippet, clone, risk, tactics, urls),
                )
        return iid

    def stats(self) -> dict:
        with self.cursor() as cur:
            out = {}
            for t in ("users", "immunization_ledger", "forensic_scans", "scam_incidents", "osint_canary_alerts"):
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                out[t] = cur.fetchone()[0]
            return out


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
