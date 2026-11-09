"""Auth middleware: short-lived JWT access tokens, Supabase-issued tokens (when SUPABASE_JWT_SECRET is set),
and scoped extension API keys (``nf_live_...``) of which only the SHA-256 hash is stored."""
from __future__ import annotations

import hashlib
import secrets
import time

import jwt
from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .db import get_db

_bearer = HTTPBearer(auto_error=False)


def issue_token(user: dict) -> str:
    now = int(time.time())
    payload = {"sub": user["id"], "email": user["email"], "name": user["full_name"], "tier": user.get("protection_tier", "FREE"),
               "iat": now, "exp": now + settings.JWT_TTL_SECONDS, "iss": "nullface"}
    return jwt.encode(payload, settings.SERVER_SECRET, algorithm=settings.JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SERVER_SECRET, algorithms=[settings.JWT_ALG], issuer="nullface")
    except jwt.PyJWTError:
        pass
    if settings.SUPABASE_JWT_SECRET:
        try:
            return jwt.decode(token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        except jwt.PyJWTError:
            pass
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")


def new_api_key() -> tuple[str, str]:
    raw = "nf_live_" + secrets.token_urlsafe(24)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def _user_from_credential(token: str | None, api_key: str | None) -> dict:
    db = get_db()
    if api_key:
        user = db.user_by_api_key_hash(hashlib.sha256(api_key.encode()).hexdigest())
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
        return user
    if token:
        claims = decode_token(token)
        user = db.get_user(claims["sub"])
        if user:
            return user
        # Supabase-issued token for a user we haven't seen: provision them
        email = claims.get("email") or f"{claims['sub']}@supabase.local"
        return db.upsert_user(email, claims.get("name") or email.split("@")[0], secrets.token_hex(32))
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing credentials")


async def current_user(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    api_key = request.headers.get("X-API-Key")
    token = cred.credentials if cred else None
    return _user_from_credential(token, api_key)


async def optional_user(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict | None:
    try:
        return await current_user(request, cred)
    except HTTPException:
        return None


def ws_user(ws: WebSocket) -> dict | None:
    token = ws.query_params.get("token") or (ws.headers.get("authorization", "").removeprefix("Bearer ").strip() or None)
    api_key = ws.query_params.get("api_key") or ws.headers.get("x-api-key")
    try:
        return _user_from_credential(token, api_key)
    except HTTPException:
        return None
