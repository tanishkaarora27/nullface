# NullFace (Kavach-AI): Master System Specification

> **Hackathon:** CodeBuild 2.0 National Hackathon  
> **Official PS Title:** Real-Time Adversarial Image Immunization, Cryptographic Deepfake Invalidation & Multimodal Fraud Defense Protocol  
> **Tagline:** *"Don’t just detect deepfakes after the damage is done—make your photos mathematically immune to AI, trace stolen identities cryptographically, and intercept coercive scam calls in real time."*

---

## 1. Executive Problem Statement & Measurable Pain Metrics

With generative AI and one-click face-swapping tools widely accessible, citizens face a dual synthetic threat that existing security tools fail to address at the root:

- **Identity Exploitation & Non-Consensual Morphing:** Personal photos uploaded to social media (Instagram, WhatsApp, LinkedIn) are scraped and fed into face-swap and diffusion models to create non-consensual deepfakes, fake KYC profiles, and extortion material. Victims can only react *after* the damage is done.
- **The Compression Blind Spot in Existing Defenses:** Academic tools like *Glaze* or *Nightshade* are built for desktop artists—they take minutes per image and their high-frequency adversarial noise is completely wiped out the moment WhatsApp or Instagram applies JPEG compression. None protect a mobile user's selfie against real-time face-swapping or video-call injection.
- **Hyper-Personalized "Digital Arrest" & Voice Scams:** Fraudsters combine cloned voices of family members, deepfake police/CBI video calls, and coercive phishing messages to extort money in real time.
- **Quantified Pain Measure (I4C Data):** Indians lost over **₹1,700+ Crore** in recent quarters to "Digital Arrest" video/voice scams and fraudulent links alone, with thousands of daily complaints logged on the 1930 helpline. Over **90% of deepfake victims** have no preventive client-side tool to protect their photos prior to sharing.

---

## 2. Competitive Moat & Technical Differentiation

| Feature Dimension | Standard Deepfake Detectors | Academic Cloakers (Glaze) | NullFace (Our Solution) |
| :--- | :--- | :--- | :--- |
| **Defense Timing** | Reactive (Post-Attack only) | Proactive (Desktop Art only) | **Proactive Cloak + Reactive Forensics + Live Call Shield** |
| **Social Media Compression** | N/A | Fails under WhatsApp/IG JPEG compression | **Survives JPEG Q=50 via YCbCr DCT Mid-Frequency Trapping** |
| **Processing Latency** | 3–10 seconds | 2–5 minutes per image | **1.2–1.8 seconds (Real-Time Mobile / Edge)** |
| **Forensic Attribution** | Visual heatmap only | None | **64-Bit Blind DWT Canary Watermark Extraction (<50ms)** |
| **Privacy Guarantee** | Stores user uploads on disk/S3 | Requires heavy local GPU | **Zero-Retention Ephemeral RAM (`/dev/shm`)** |

---

## 3. High-Level System Architecture

```text
+---------------------------------------------------------------------------------------------------+
|                                      CLIENT & EDGE LAYER                                          |
|  [Mobile PWA / Next.js Web]       [Chrome Extension (MV3)]       [WhatsApp / Telecom Webhook]     |
|   - WebRTC Audio Streamer          - DOM Upload Interceptor       - Media / Voice Note Forwarder  |
|   - Before/After Canvas UI         - Context-Menu Quick Cloak     - Instant Threat Alert Bot      |
+-----------------+-----------------------------+---------------------------------+-----------------+
                  | HTTPS / REST (JWT)          | HTTPS (Multipart)               | WSS (Audio Chunks)
                  v                             v                                 v
+---------------------------------------------------------------------------------------------------+
|                                  API GATEWAY & SECURITY LAYER                                     |
|  [Cloudflare WAF & CDN] ---> [Nginx Reverse Proxy] ---> [FastAPI Async Gateway]                   |
|                                                          |-- Auth Middleware (Supabase JWT/OAuth2)|
|                                                          |-- Rate Limiter (Upstash Redis Token)   |
|                                                          |-- Ephemeral RAM Buffer (/dev/shm)      |
+-----------------+-----------------------------+---------------------------------+-----------------+
                  |                             |                                 |
      +-----------+                             |                                 +-----------+
      | (Async GPU Worker)                      | (Sync/Async GPU Worker)                     | (WebSocket Stream)
      v                                         v                                             v
+-------------------------------+ +-----------------------------------+ +---------------------------+
| SERVICE 1: PHOTOCLOAK ENGINE  | | SERVICE 2: DEEPLENS FORENSICS     | | SERVICE 3: SCAMRADAR      |
| (Adversarial & Watermarking)  | | (Detection & Traceability)        | | (Live Call/Msg Shield)    |
|                               | |                                   | |                           |
| - YCbCr DCT-PGD Perturbation  | | - Blind DWT Hash Extractor        | | - Whisper-v3 Streaming ASR|
| - InsightFace / CLIP Poisoner | | - 2D-FFT Spectrum Analyzer        | | - Wav2Vec2 Clone Detector |
| - DWT Spread-Spectrum Signer  | | - ViT Deepfake + Grad-CAM         | | - ChromaDB Coercion RAG   |
| - SSIM Quality Gate (>=0.96)  | | - C2PA Metadata Auditor           | | - Google SafeBrowsing API |
+---------------+---------------+ +-----------------+-----------------+ +-------------+-------------+
                |                                   |                                 |
                +-----------------------------------+---------------------------------+
                                                    |
                                                    v
+---------------------------------------------------------------------------------------------------+
|                              PERSISTENCE, VECTOR & BROKER LAYER                                   |
|  [PostgreSQL 16 (Supabase)]          [ChromaDB Vector Store]          [Redis Cluster (Upstash)]   |
|   - Users, Auth & API Key Hashes      - I4C Scam Script Embeddings     - Celery Task Queue Broker |
|   - 64-Bit Watermark Hash Ledger      - Protected Face pHash Index     - Live Call Session State  |
|   - Forensic & Scam Audit Logs        - OSINT Scraper Vectors          - Rate Limit Counters      |
+---------------------------------------------------------------------------------------------------+
```

---

## 4. Authentication, Security & Zero-Retention Privacy Architecture

### Authentication & Access Control
- **Identity Provider:** Supabase Auth implementing **OAuth 2.0 / OIDC** (Google/GitHub) and **WebAuthn Passkeys** (biometric login).
- **Token Strategy:** Short-lived **RS256 JWT Access Tokens** (15-min TTL) + HTTP-only, `SameSite=Strict` rotating Refresh Tokens (7-day TTL).
- **Extension API Keys:** Scoped keys (`nf_live_...`) where only the `SHA-256` hash is persisted in PostgreSQL.

### Zero-Retention Ephemeral RAM Lifecycle
- **Volatile Memory Processing:** Uploaded photos stream directly into `/dev/shm` (RAM disk) and never touch SSDs or S3 buckets.
- **Immediate Purge:** Once the immunized image streams back to the client, a `finally` block zeroes out the RAM buffer and frees GPU tensors.
- **Hash-Only Persistence:** Only the 64-bit watermark signature and perceptual hash (`pHash`) are logged to PostgreSQL.

---

## 5. Core AI & Cryptographic Microservices (Mathematical Specification)

### Service 1: PhotoCloak Engine (YCbCr Mid-Frequency DCT-PGD Immunization)
Standard pixel-space adversarial noise is destroyed by social media JPEG quantization. PhotoCloak transforms input RGB image $I$ into $YCbCr$ color space and restricts Projected Gradient Descent (PGD) perturbations $\delta$ to the **$8 \times 8$ Discrete Cosine Transform (DCT) mid-frequency coefficients** ($C_{DCT}$), simultaneously maximizing separation in `InsightFace` ArcFace embedding space ($f_{id}$) and `CLIP`/VAE latent space ($f_{clip}$) while preserving perceptual quality ($\text{SSIM} \ge 0.96$):

$$\max_{\delta \in C_{DCT}} \mathcal{L} = \| f_{id}(I) - f_{id}(I + \delta) \|_2^2 + \lambda_1 \| f_{clip}(I) - f_{clip}(I + \delta) \|_2^2 - \lambda_2 (1 - \text{SSIM}(I, I + \delta))$$

### Service 2: Canary-Link (64-Bit 2-Level Haar DWT Cryptographic Watermarking)
Each user's cryptographic salt derives a 64-bit signature: 
$$W_{payload} = \text{Trunc}_{64}(\text{HMAC-SHA256}(\text{User\_ID} \parallel \text{Timestamp}, \text{Server\_Secret}))$$

The immunized luminance channel $Y'$ undergoes a 2-level Haar Discrete Wavelet Transform yielding sub-bands $\{LL_2, HL_2, LH_2, HH_2\}$. The 64 bits are embedded into mid-frequency wavelet coefficients $C_k \in \{HL_2, LH_2\}$ via Quantization Index Modulation (QIM) with step size $\Delta$:

$$C'_k = \text{round}\left(\frac{C_k}{\Delta}\right) \cdot \Delta + (-1)^{W_k} \cdot \left(\frac{\Delta}{4}\right)$$

### Service 3: DeepLens Multimodal Forensics & Traceability Lab
- **Stage 1 — Blind DWT Watermark Extraction (<50ms):** Extracts the 64-bit payload from suspected deepfake frames and runs a bitwise Hamming Distance check against PostgreSQL. If Bit Error Rate (BER) < 12%, it mathematically proves which user's protected photo was stolen.
- **Stage 2 — 2D-FFT & ViT + Grad-CAM:** Computes the 2D Fast Fourier Transform azimuthal power spectrum to expose GAN/Diffusion upsampling grids, paired with `dima806/deepfake_vs_real_image_detection` and Grad-CAM heatmaps.
- **Stage 3 — Audio Clone Forensics:** Converts voice notes into Mel-Spectrograms via `librosa` and scores synthetic vocoder phase discontinuities using `Wav2Vec2`.

### Service 4: ScamRadar Live Call & Message Coercion Shield
- **Bi-Directional WebSocket Pipeline:** Streams 16kHz PCM audio chunks every 2 seconds into parallel `Wav2Vec2` voice-clone scoring and **Groq Whisper-Large-v3** Hinglish transcription.
- **ChromaDB Coercion RAG:** Cross-references live transcripts against vectorized I4C "Digital Arrest" scripts across three axes:
  1. *Authority Impersonation*
  2. *Isolation Commands*
  3. *Urgent Financial Extraction*

### Services 5 & 6: OSINT Scraper Sentinel & Chrome Extension (MV3) Interceptor
- **OSINT Sentinel:** Cron-agent matching public profile perceptual hashes (`pHash`) against indexed synthetic media repositories to issue proactive re-immunization alerts.
- **Chrome Extension (MV3):** Intercepts browser `<input type="file">` events to cloak and watermark uploads on the fly before they reach Instagram, WhatsApp Web, or LinkedIn.

---

## 6. Verified, Public & Clean APIs / Datasets Stack (100% Free)

| Module | Public Dataset / Pre-Trained Model | External Free API / Open-Source Library |
| :--- | :--- | :--- |
| **1. PhotoCloak** | **LFW (Labeled Faces in the Wild)** & **CelebA** for SSIM/PSNR/ArcFace benchmarks | `torchattacks` (PGD/FGSM), `InsightFace` (ArcFace + `inswapper_128.onnx`), `PyWavelets` (`pywt`) |
| **2. DeepLens Vision** | **CIFAKE Dataset** (120k real vs AI images) & **FaceForensics++ / Celeb-DF** | Hugging Face `dima806/deepfake_vs_real_image_detection` (ViT) + OpenCV 2D-FFT + C2PA check |
| **3. DeepLens Audio** | **ASVspoof 2019 / 2021 Dataset** & **In-the-Wild Audio Deepfake Dataset** | Hugging Face `MelodyMachine/Deepfake-audio-detection-V2` (`Wav2Vec2`) + `librosa` |
| **4. ScamRadar** | **UCI SMS Spam Dataset** + **Indian I4C "Digital Arrest" Scam Transcripts** | **Groq API** (Free tier `whisper-large-v3` & `llama-3.3-70b`) + **Google Safe Browsing API** + ChromaDB |

---

## 7. Production Database Architecture (PostgreSQL 16 + ChromaDB + Redis)

### A. Complete Relational Schema (PostgreSQL 16 on Supabase / Neon)

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. USERS TABLE
CREATE TABLE users (
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

-- 2. IMMUNIZATION LEDGER (Zero-Retention Proof Store - No Raw Images Stored!)
CREATE TABLE immunization_ledger (
    asset_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    watermark_bitstring BIT(64) NOT NULL, -- 64-bit DWT embedded signature
    perceptual_hash VARCHAR(64) NOT NULL, -- 64-bit pHash of the cloaked image
    sha256_checksum VARCHAR(64) UNIQUE NOT NULL,
    ssim_score NUMERIC(5, 4) NOT NULL, -- e.g., 0.9742
    psnr_db NUMERIC(5, 2) NOT NULL, -- e.g., 38.40 dB
    identity_shift_cosine NUMERIC(5, 4) NOT NULL, -- ArcFace embedding shift (e.g., 0.6820)
    protection_profile VARCHAR(30) DEFAULT 'WHATSAPP_ROBUST',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_ledger_user_id ON immunization_ledger(user_id);
CREATE INDEX idx_ledger_phash ON immunization_ledger(perceptual_hash);

-- 3. FORENSIC SCANS & TRACEABILITY LOGS
CREATE TABLE forensic_scans (
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

-- 4. SCAMRADAR CALL & MESSAGE INCIDENT LOGS
CREATE TABLE scam_incidents (
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

-- 5. OSINT SCRAPER CANARY ALERTS
CREATE TABLE osint_canary_alerts (
    alert_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES immunization_ledger(asset_id) ON DELETE CASCADE,
    detected_source_domain VARCHAR(255) NOT NULL,
    similarity_score NUMERIC(5, 4) NOT NULL,
    status VARCHAR(20) DEFAULT 'UNREAD' CHECK (status IN ('UNREAD', 'ACKNOWLEDGED', 'TAKEDOWN_GENERATED')),
    detected_at TIMESTAMPTZ DEFAULT NOW()
);
```

### B. Sub-5ms Hardware Popcount SQL Query for Error-Tolerant Watermark Attribution

```sql
-- Finds the original owner of a stolen photo from a compressed deepfake video frame
-- even if video compression flipped up to 7 bits out of the 64-bit DWT signature:
SELECT 
    l.asset_id, u.full_name, u.email, l.created_at AS original_immunization_date,
    bit_count(l.watermark_bitstring # B'1011001110001111000010101101001010110011100011110000101011010010') AS hamming_distance
FROM immunization_ledger l
JOIN users u ON l.user_id = u.id
WHERE bit_count(l.watermark_bitstring # B'1011001110001111000010101101001010110011100011110000101011010010') <= 7
ORDER BY hamming_distance ASC
LIMIT 1;
```

### C. ChromaDB Collections & Redis State
- **ChromaDB `scam_coercion_kb`:** 384-dim embeddings (`BAAI/bge-small-en-v1.5`) of I4C "Digital Arrest" scripts, fake CBI/RBI notices, and extortion templates with metadata (`scam_category`, `severity`, `i4c_advisory_ref`).
- **ChromaDB `protected_face_signatures`:** 512-dim embeddings of cloaked facial vectors + pHashes for OSINT matching.
- **Redis Cluster:** Token-bucket rate limiter (`ratelimit:{user_id}:{endpoint}`) and rolling 30-second WebSocket call state (`call_session:{session_uuid}`).

---

## 8. REST & WebSocket API Contract (FastAPI Gateway)

| Method | Endpoint | Description | Auth | Latency SLA |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/session` | Exchanges Supabase OAuth/Passkey token & provisions user crypto salt | Public | < 80ms |
| `POST` | `/api/v1/cloak/immunize` | In-RAM YCbCr DCT-PGD + 64-bit DWT watermark; logs hash; streams protected image | Bearer JWT / Key | **1.2s – 1.8s** |
| `POST` | `/api/v1/cloak/stress-test` | Side-by-side sandbox feeding Original vs Cloaked image into `InsightFace` swapper | Bearer JWT | **1.5s** |
| `POST` | `/api/v1/forensics/inspect` | 3-stage check: (1) Blind DWT extraction, (2) 2D-FFT + ViT + Grad-CAM, (3) C2PA audit | Bearer JWT | **800ms** |
| `POST` | `/api/v1/scam/audit-text` | Audits SMS/WhatsApp text + URLs via ChromaDB Coercion RAG & Google Safe Browsing | Bearer JWT | **250ms** |
| `WS` | `/ws/v1/scam/call-stream` | Streams 2-sec PCM audio chunks; returns live Hinglish ASR, Wav2Vec2 score & alerts | WebSocket JWT | **350ms / chunk** |

---

## 9. Deployment Strategy & 3-Minute Live Judge Demo Script

### Containerized Cloud-Edge Deployment
Packaged via `docker-compose.yml` (Next.js/Streamlit UI + FastAPI Gateway + PyTorch GPU Worker + ChromaDB/Redis + Supabase PostgreSQL). Stateless `/dev/shm` processing enables horizontal auto-scaling on Modal Serverless GPUs or AWS ECS.

### 3-Minute Live Judge Demo Script
- **Act 1 — PhotoCloak Stress-Test (60s):** Run live `InsightFace` face-swap on an unprotected selfie (succeeds) vs. NullFace-immunized selfie (SSIM = 0.974 to human eyes, but outputs a broken glitch in AI).
- **Act 2 — Canary-Link Attribution (30s):** Upload a compressed fake frame into DeepLens; extract the 64-bit DWT watermark in 50ms via PostgreSQL bitwise `XOR` to prove ownership alongside 2D-FFT and Grad-CAM visuals.
- **Act 3 — ScamRadar Live Call Shield (45s):** Play a Hinglish "Digital Arrest" audio clip into the mic; watch real-time transcription flag *89% Voice Clone* + *CRITICAL: Authority Impersonation & Isolation Pattern*.
