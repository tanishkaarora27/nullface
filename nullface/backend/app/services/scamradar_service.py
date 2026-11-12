"""Service 3 — ScamRadar: live call & message coercion shield.

* Coercion RAG: live transcript chunks are embedded (``BAAI/bge-small-en-v1.5`` via sentence-transformers when
  installed, otherwise a char-n-gram TF-IDF index that handles Hinglish spelling variance well) and matched
  against the I4C "Digital Arrest" script corpus stored in ChromaDB (or an in-memory index) across three axes:
  Authority Impersonation · Isolation Commands · Urgent Financial Extraction (+ legal-threat / family-emergency /
  phishing).  A keyword lexicon provides an explainable second signal.
* URL audit: Google Safe Browsing v4 when a key is set, plus local look-alike/shortener/APK heuristics.
* ASR: Groq ``whisper-large-v3`` for Hinglish when GROQ_API_KEY is set.  Without it the PWA streams the browser's
  own SpeechRecognition (hi-IN) transcript as text frames, so the demo still runs fully offline.
* Call session state: rolling 30-second window per WebSocket (Redis when REDIS_URL is set, else in-process).
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlparse

import numpy as np

from ..core.config import DATA_DIR, settings
from ..core.db import get_db

# ---------------------------------------------------------------------------
# knowledge base & embeddings
# ---------------------------------------------------------------------------

def load_kb() -> dict:
    with open(DATA_DIR / "coercion_kb.json", encoding="utf-8") as f:
        return json.load(f)


class _TfidfEmbedder:
    backend = "tfidf-char-ngram"

    def __init__(self, texts: list[str]) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, sublinear_tf=True)
        self.vec.fit(texts)

    def encode(self, texts: list[str]) -> np.ndarray:
        m = self.vec.transform(texts).toarray().astype(np.float32)
        n = np.linalg.norm(m, axis=1, keepdims=True) + 1e-8
        return m / n


class _SbertEmbedder:
    backend = settings.EMBEDDING_MODEL

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model = SentenceTransformer(settings.EMBEDDING_MODEL)

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts, normalize_embeddings=True), dtype=np.float32)


class CoercionIndex:
    """ChromaDB-backed when chromadb is importable, otherwise a NumPy cosine index with the same interface."""

    def __init__(self) -> None:
        kb = load_kb()
        self.docs = kb["scripts"]
        self.tactic_desc = kb["tactics"]
        texts = [d["text"] for d in self.docs]
        try:
            self.embedder = _SbertEmbedder()
        except Exception:
            self.embedder = _TfidfEmbedder(texts)
        self.matrix = self.embedder.encode(texts)
        self.store = "numpy"
        try:
            import chromadb  # type: ignore

            client = chromadb.PersistentClient(path=str(settings.CHROMA_DIR))
            self.col = client.get_or_create_collection("scam_coercion_kb", metadata={"hnsw:space": "cosine"})
            if self.col.count() != len(self.docs):
                self.col.upsert(
                    ids=[d["id"] for d in self.docs], embeddings=self.matrix.tolist(), documents=texts,
                    metadatas=[{"scam_category": d["category"], "severity": d["severity"],
                                "i4c_advisory_ref": d.get("i4c_ref") or "", "tactics": ",".join(d["tactics"])} for d in self.docs],
                )
            self.store = "chromadb"
        except Exception:
            self.col = None

    def query(self, text: str, k: int = 4) -> list[dict]:
        q = self.embedder.encode([text])[0]
        if self.col is not None:
            res = self.col.query(query_embeddings=[q.tolist()], n_results=k)
            out = []
            for i, doc_id in enumerate(res["ids"][0]):
                d = next(x for x in self.docs if x["id"] == doc_id)
                out.append({"id": doc_id, "similarity": round(1 - float(res["distances"][0][i]), 4),
                            "category": d["category"], "severity": d["severity"], "tactics": d["tactics"],
                            "i4c_ref": d.get("i4c_ref"), "text": d["text"]})
            return out
        sims = self.matrix @ q
        idx = np.argsort(-sims)[:k]
        return [{"id": self.docs[i]["id"], "similarity": round(float(sims[i]), 4), "category": self.docs[i]["category"],
                 "severity": self.docs[i]["severity"], "tactics": self.docs[i]["tactics"],
                 "i4c_ref": self.docs[i].get("i4c_ref"), "text": self.docs[i]["text"]} for i in idx]


@lru_cache(maxsize=1)
def index() -> CoercionIndex:
    return CoercionIndex()


# ---------------------------------------------------------------------------
# explainable lexicon (Hinglish + English)
# ---------------------------------------------------------------------------

_LEXICON = {
    "AUTHORITY_IMPERSONATION": [
        r"\bcbi\b", r"\bed\b", r"enforcement directorate", r"\bpolice\b", r"crime branch", r"\brbi\b", r"\btrai\b",
        r"customs", r"narcotics", r"supreme court", r"\bcourt\b", r"inspector", r"\bofficer\b", r"cyber ?cell",
        r"\bfedex\b", r"\bcourier\b", r"income tax", r"\bsebi\b", r"\bdot\b", r"telecom department", r"government",
        r"sarkari", r"thana", r"adhikari",
    ],
    "ISOLATION_COMMANDS": [
        r"(don'?t|do not|mat|nahi) (tell|inform|batana|bata|disclose)", r"kisi ko (mat|nahi) batana",
        r"(don'?t|do not|mat) (hang up|disconnect|cut|band)", r"(call|video|camera) (band|on|chalu) (mat|rakh)",
        r"stay on (the )?(call|line|video)", r"akele", r"alone", r"private room", r"confidential", r"secret",
        r"gupt", r"share your screen", r"screen share", r"camera on", r"ghar wale ko (bhi )?nahi",
    ],
    "URGENT_FINANCIAL_EXTRACTION": [
        r"\botp\b", r"\bupi\b", r"\bpin\b", r"\bcvv\b", r"transfer", r"\brtgs\b", r"\bneft\b", r"\bimps\b",
        r"deposit", r"bhej(o|iye|do|na)", r"send (the )?money", r"paisa", r"paise", r"rupaye", r"\blakh\b", r"\bhazar\b",
        r"safe account", r"secure account", r"verification account", r"government account", r"abhi", r"turant",
        r"immediately", r"right now", r"within (\d+|an?) (hour|minute|ghante|ghanta)", r"processing fee",
        r"balance (dikha|show)", r"account number", r"\bgift card\b", r"\bcrypto\b", r"\busdt\b",
    ],
    "FEAR_LEGAL_THREAT": [
        r"arrest", r"warrant", r"\bfir\b", r"money laundering", r"\bdrugs?\b", r"\bmdma\b", r"narcotics", r"illegal",
        r"case (darj|filed|registered)", r"jail", r"freeze", r"block(ed)?", r"cancel", r"passport", r"aadhaar",
        r"trafficking", r"terror", r"summons", r"digital arrest", r"giraftar", r"mukadma", r"kanooni",
    ],
    "FAMILY_EMERGENCY": [
        r"\b(papa|mummy|mom|dad|beta|bhai|didi|son|daughter|uncle|aunty|nana|nani|dada|dadi)\b", r"accident",
        r"hospital", r"surgery", r"operation", r"emergency", r"police station me hoon", r"phone (broken|toot|kho)",
        r"i'?ll explain later", r"baad me batata",
    ],
    "PHISHING_LINK": [
        r"https?://", r"\bwww\.", r"\.apk\b", r"click (the )?link", r"link par", r"\bkyc\b", r"update your",
        r"verify (your|now)", r"e-?challan", r"lottery", r"congratulations", r"prize", r"redelivery", r"download the app",
        r"bit\.ly", r"tinyurl",
    ],
}
_COMPILED = {t: [re.compile(p, re.I) for p in pats] for t, pats in _LEXICON.items()}
_WEIGHTS = {"AUTHORITY_IMPERSONATION": 0.9, "ISOLATION_COMMANDS": 1.0, "URGENT_FINANCIAL_EXTRACTION": 1.0,
            "FEAR_LEGAL_THREAT": 0.8, "FAMILY_EMERGENCY": 0.7, "PHISHING_LINK": 0.6}


def lexicon_hits(text: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for tactic, pats in _COMPILED.items():
        found = []
        for p in pats:
            m = p.search(text)
            if m:
                found.append(m.group(0))
        if found:
            hits[tactic] = found[:5]
    return hits


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def score_text(text: str, k: int = 4) -> dict:
    """Coercion risk in [0,1] with tactic breakdown and the retrieved I4C scripts (RAG evidence)."""
    t0 = time.perf_counter()
    text = (text or "").strip()
    if not text:
        return {"coercion_risk_score": 0.0, "tactics": [], "tactic_scores": {}, "evidence": [], "lexicon": {},
                "latency_ms": 0}
    idx = index()
    neighbours = idx.query(text, k)
    lex = lexicon_hits(text)

    tactic_scores: dict[str, float] = {t: 0.0 for t in _WEIGHTS}
    for n in neighbours:
        if n["category"] == "BENIGN":
            continue
        for t in n["tactics"]:
            tactic_scores[t] = max(tactic_scores[t], n["similarity"])
    for t, found in lex.items():
        if t in ("FAMILY_EMERGENCY", "PHISHING_LINK") and len(found) < 2:
            continue  # a lone 'mom' or bare link is not evidence of coercion
        tactic_scores[t] = max(tactic_scores[t], min(1.0, 0.45 + 0.18 * len(found)))

    benign_sim = max([n["similarity"] for n in neighbours if n["category"] == "BENIGN"] or [0.0])
    scam_sim = max([n["similarity"] for n in neighbours if n["category"] != "BENIGN"] or [0.0])
    active = {t: round(s, 4) for t, s in tactic_scores.items() if s >= 0.4}

    combo = 0.0
    if active:
        weighted = sum(_WEIGHTS[t] * s for t, s in active.items()) / sum(_WEIGHTS[t] for t in active)
        # several tactics stacked together is the hallmark of a Digital Arrest script
        combo = min(1.0, weighted * (0.75 + 0.1 * len(active)))
    rag = max(0.0, scam_sim - 0.5 * benign_sim)
    risk = float(np.clip(0.6 * combo + 0.4 * rag, 0, 1))
    if {"AUTHORITY_IMPERSONATION", "ISOLATION_COMMANDS", "URGENT_FINANCIAL_EXTRACTION"} <= set(active):
        risk = max(risk, 0.9)

    level = "CRITICAL" if risk >= 0.75 else "HIGH" if risk >= 0.55 else "MEDIUM" if risk >= 0.35 else "LOW"
    return {
        "coercion_risk_score": round(risk, 4),
        "risk_level": level,
        "tactics": sorted(active, key=lambda t: -active[t]),
        "tactic_scores": active,
        "lexicon": lex,
        "evidence": [{k: v for k, v in n.items()} for n in neighbours[:3]],
        "backend": {"embedder": idx.embedder.backend, "store": idx.store},
        "latency_ms": round((time.perf_counter() - t0) * 1000),
    }


# ---------------------------------------------------------------------------
# URL audit
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|\b[a-z0-9-]+\.(?:com|in|net|org|xyz|top|club|site|online|app|co|info|me|link|ly|gl|cc|gy|at|io|icu|buzz|tk|ml|ga|cf|gq|work|rest)(?:/[^\s<>\"']*)?", re.I)
_BRANDS = ["sbi", "hdfc", "icici", "axis", "paytm", "phonepe", "gpay", "rbi", "incometax", "uidai", "bsnl", "airtel", "jio",
           "amazon", "flipkart", "fedex", "bluedart", "irctc", "epfo", "npci"]
_SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "cutt.ly", "rb.gy", "is.gd", "tiny.cc", "shorturl.at"}
_RISKY_TLDS = {"xyz", "top", "club", "site", "online", "icu", "buzz", "tk", "ml", "ga", "cf", "gq", "work", "rest"}


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0).rstrip(".,)") for m in _URL_RE.finditer(text or "")))


def _safe_browsing(urls: list[str]) -> dict[str, list[str]]:
    if not settings.SAFE_BROWSING_API_KEY or not urls:
        return {}
    import httpx

    body = {"client": {"clientId": "nullface", "clientVersion": settings.VERSION},
            "threatInfo": {"threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
                           "platformTypes": ["ANY_PLATFORM"], "threatEntryTypes": ["URL"],
                           "threatEntries": [{"url": u if u.startswith("http") else "http://" + u} for u in urls]}}
    try:
        r = httpx.post(f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={settings.SAFE_BROWSING_API_KEY}",
                       json=body, timeout=4.0)
        out: dict[str, list[str]] = {}
        for m in r.json().get("matches", []):
            out.setdefault(m["threat"]["url"], []).append(m["threatType"])
        return out
    except Exception:
        return {}


def audit_urls(text: str) -> list[dict]:
    urls = extract_urls(text)
    sb = _safe_browsing(urls)
    out = []
    for u in urls:
        host = urlparse(u if u.startswith("http") else "http://" + u).hostname or ""
        host = host.lower()
        reasons = []
        parts = host.split(".")
        tld = parts[-1] if parts else ""
        if host in _SHORTENERS:
            reasons.append("link shortener hides destination")
        if tld in _RISKY_TLDS:
            reasons.append(f"high-abuse TLD .{tld}")
        if u.lower().endswith(".apk") or ".apk" in u.lower():
            reasons.append("APK sideload link")
        if host.replace("-", "").replace(".", "").isdigit():
            reasons.append("raw IP address host")
        for b in _BRANDS:
            if b in host and not (host == f"{b}.com" or host.endswith(f".{b}.com") or host.endswith(f".{b}.in") or host.endswith(f".{b}.co.in")):
                reasons.append(f"look-alike of brand '{b}'")
                break
        if host.count("-") >= 2 or len(parts) >= 4:
            reasons.append("suspicious sub-domain depth / hyphenation")
        hits = sb.get(u) or sb.get("http://" + u) or []
        if hits:
            reasons.append("Google Safe Browsing: " + ", ".join(hits))
        risk = min(1.0, 0.25 * len(reasons) + (0.5 if hits else 0.0))
        out.append({"url": u, "host": host, "risk": round(risk, 2), "reasons": reasons,
                    "safe_browsing": "checked" if settings.SAFE_BROWSING_API_KEY else "not configured"})
    return out


def audit_text(text: str, user: dict | None, channel: str = "WHATSAPP_MSG") -> dict:
    s = score_text(text)
    urls = audit_urls(text)
    url_risk = max([u["risk"] for u in urls] or [0.0])
    risk = max(s["coercion_risk_score"], url_risk * 0.9)
    if urls and "PHISHING_LINK" not in s["tactics"] and url_risk >= 0.25:
        s["tactics"].append("PHISHING_LINK")
    level = "CRITICAL" if risk >= 0.75 else "HIGH" if risk >= 0.55 else "MEDIUM" if risk >= 0.35 else "LOW"
    rec = _recommendation(level, s["tactics"])
    incident_id = None
    if risk >= 0.35:
        incident_id = get_db().insert_incident(user["id"] if user else None, channel, text[:500], None, risk,
                                               s["tactics"], [u["url"] for u in urls if u["risk"] >= 0.25])
    return {**s, "coercion_risk_score": round(risk, 4), "risk_level": level, "urls": urls,
            "recommendation": rec, "incident_id": incident_id}


def _recommendation(level: str, tactics: list[str]) -> str:
    if level in ("CRITICAL", "HIGH"):
        return ("Hang up / do not reply. No agency conducts a 'digital arrest' or asks for money on a call. "
                "Call 1930 (National Cyber Crime Helpline) and report at cybercrime.gov.in. Tell a family member now.")
    if level == "MEDIUM":
        return "Treat as suspicious. Verify the sender through an official number you look up yourself; never share OTP/UPI PIN."
    return "No coercion pattern detected. Stay alert for urgency, secrecy and payment demands."


# ---------------------------------------------------------------------------
# live call session (rolling 30 s window)
# ---------------------------------------------------------------------------

@dataclass
class CallSession:
    session_id: str
    user_id: str | None
    started: float = field(default_factory=time.time)
    transcript: deque = field(default_factory=lambda: deque(maxlen=15))  # (ts, text)
    clone_scores: deque = field(default_factory=lambda: deque(maxlen=15))
    peak_risk: float = 0.0
    tactics_seen: set = field(default_factory=set)
    chunks: int = 0

    def window_text(self, seconds: float = 30.0) -> str:
        now = time.time()
        return " ".join(t for ts, t in self.transcript if now - ts <= seconds)

    def snapshot(self) -> dict:
        return {"session_id": self.session_id, "chunks": self.chunks, "elapsed_s": round(time.time() - self.started, 1),
                "peak_risk": round(self.peak_risk, 4), "tactics_seen": sorted(self.tactics_seen),
                "mean_clone_score": round(float(np.mean(self.clone_scores)) if self.clone_scores else 0.0, 4)}


class SessionStore:
    def __init__(self) -> None:
        self._mem: dict[str, CallSession] = {}
        self._redis = None
        if settings.REDIS_URL:
            try:
                import redis  # type: ignore

                self._redis = redis.from_url(settings.REDIS_URL)
            except Exception:
                self._redis = None

    def get(self, sid: str, user_id: str | None) -> CallSession:
        if sid not in self._mem:
            self._mem[sid] = CallSession(sid, user_id)
        return self._mem[sid]

    def persist(self, s: CallSession) -> None:
        if self._redis is not None:
            try:
                self._redis.setex(f"call_session:{s.session_id}", 60, json.dumps(s.snapshot()))
            except Exception:
                pass

    def drop(self, sid: str) -> CallSession | None:
        s = self._mem.pop(sid, None)
        if self._redis is not None and s is not None:
            try:
                self._redis.delete(f"call_session:{sid}")
            except Exception:
                pass
        return s


sessions = SessionStore()


# ---------------------------------------------------------------------------
# ASR (Groq whisper-large-v3) — optional
# ---------------------------------------------------------------------------

def transcribe_pcm16(pcm: bytes, sample_rate: int = 16000, language: str | None = None) -> dict:
    if not settings.GROQ_API_KEY:
        return {"text": "", "backend": "none (set GROQ_API_KEY or stream browser transcript)"}
    import io
    import wave

    import httpx

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    try:
        r = httpx.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            files={"file": ("chunk.wav", buf.getvalue(), "audio/wav")},
            data={"model": settings.GROQ_WHISPER_MODEL, "response_format": "json", **({"language": language} if language else {}),
                  "prompt": "Hinglish phone call. CBI, police, RBI, OTP, UPI, paisa, transfer, arrest."},
            timeout=8.0,
        )
        r.raise_for_status()
        return {"text": r.json().get("text", ""), "backend": f"groq:{settings.GROQ_WHISPER_MODEL}"}
    except Exception as exc:
        return {"text": "", "backend": "groq-error", "error": str(exc)[:160]}
