"""Token-bucket rate limiter keyed ``ratelimit:{user_or_ip}:{endpoint}`` — Upstash/Redis when REDIS_URL is set,
in-process otherwise."""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Request, status

from .config import settings


class TokenBucket:
    def __init__(self, rate_per_minute: int) -> None:
        self.capacity = rate_per_minute
        self.refill = rate_per_minute / 60.0
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        self._redis = None
        if settings.REDIS_URL:
            try:
                import redis  # type: ignore

                self._redis = redis.from_url(settings.REDIS_URL)
            except Exception:
                self._redis = None

    def allow(self, key: str) -> bool:
        if self._redis is not None:
            try:
                p = self._redis.pipeline()
                p.incr(key)
                p.expire(key, 60)
                count, _ = p.execute()
                return int(count) <= self.capacity
            except Exception:
                pass
        now = time.time()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1, now)
            return True


_bucket = TokenBucket(settings.RATE_LIMIT_PER_MINUTE)


async def rate_limit(request: Request) -> None:
    ident = request.headers.get("X-API-Key") or request.headers.get("authorization") or (request.client.host if request.client else "anon")
    key = f"ratelimit:{ident[-24:]}:{request.url.path}"
    if not _bucket.allow(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded — try again in a minute")
