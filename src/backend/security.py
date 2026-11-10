"""HTTP hardening: per-IP rate limiting and security headers (pure ASGI middleware)."""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time

# Only endpoints that can trigger third-party calls are rate limited; the rest
# are served from memory and are cheap.
LIMITED_PATH = re.compile(r"^/api/countries/[^/]+/(wiki|news|air)$")

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        # Inline style attributes are used by the globe tooltip; no inline scripts are allowed.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ]
)

SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
]


class TokenBucketLimiter:
    """Per-key token bucket: `burst` requests at once, refilling at `per_minute`."""

    def __init__(self, per_minute: float, burst: int, max_keys: int = 10_000) -> None:
        self.rate = per_minute / 60.0
        self.burst = burst
        self.max_keys = max_keys
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)
        self._lock = threading.Lock()

    def take(self, key: str) -> float:
        """Consume one token. Returns 0 if allowed, else seconds until a token is available."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                allowed = 0.0
            else:
                self._buckets[key] = (tokens, now)
                allowed = (1 - tokens) / self.rate
            if len(self._buckets) > self.max_keys:
                self._prune(now)
            return allowed

    def _prune(self, now: float) -> None:
        # Drop buckets that have fully refilled (idle clients); they'd start full anyway.
        full_after = self.burst / self.rate
        self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < full_after}


class SecurityMiddleware:
    """Adds security headers to every response and rate-limits upstream-backed endpoints.

    Client IP: on Vercel (VERCEL=1) from the `x-real-ip` header, which Vercel's edge sets
    and overwrites, so clients can't spoof it. Elsewhere from the ASGI scope; behind your
    own reverse proxy, run uvicorn with --proxy-headers --forwarded-allow-ips=<proxy ip>.

    Note: on serverless the buckets live per function instance, so this is only a
    backstop. Configure Vercel Firewall rate-limit rules for a global limit.
    """

    ON_VERCEL = os.environ.get("VERCEL") == "1"

    def __init__(self, app, limiter: TokenBucketLimiter) -> None:
        self.app = app
        self.limiter = limiter

    def _client_ip(self, scope) -> str:
        if self.ON_VERCEL:
            for name, value in scope.get("headers", []):
                if name == b"x-real-ip":
                    return value.decode("latin-1").strip()
        return (scope.get("client") or ("unknown", 0))[0]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        if LIMITED_PATH.match(scope.get("path", "")):
            client = self._client_ip(scope)
            wait = self.limiter.take(client)
            if wait:
                body = json.dumps({"detail": "Too many requests. Please slow down."}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 429,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"retry-after", str(math.ceil(wait)).encode()),
                            (b"cache-control", b"no-store"),
                            *SECURITY_HEADERS,
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    h for h in SECURITY_HEADERS if h[0] not in existing
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)
