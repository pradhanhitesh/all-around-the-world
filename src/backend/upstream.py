"""Caching + concurrency control for calls to third-party services.

Guarantees, independent of how much traffic the API receives:
  * single-flight: concurrent requests for the same key share one upstream call;
  * TTL cache: each key is fetched at most once per TTL (keys are bounded by the
    250 country codes, so the cache is naturally bounded too);
  * global concurrency cap: at most UPSTREAM_CONCURRENCY upstream calls run at
    once, so slow upstreams can't exhaust the server's worker threads;
  * stale-on-error: if a refresh fails, the last good value is served.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Hashable

log = logging.getLogger("upstream")

UPSTREAM_CONCURRENCY = 4
_upstream_slots = threading.BoundedSemaphore(UPSTREAM_CONCURRENCY)


class UpstreamBusy(Exception):
    """All upstream slots are taken; caller should answer 503 and retry later."""


class UpstreamError(Exception):
    """The upstream call failed and there is no cached value to fall back on."""


class UpstreamCache:
    def __init__(
        self,
        name: str,
        fetch: Callable[[Hashable], Any],
        ttl_seconds: float,
        slot_wait_seconds: float = 5.0,
        key_wait_seconds: float = 20.0,
    ) -> None:
        self.name = name
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._slot_wait = slot_wait_seconds
        self._key_wait = key_wait_seconds
        self._values: dict[Hashable, tuple[float, Any]] = {}
        self._key_locks: dict[Hashable, threading.Lock] = {}
        self._guard = threading.Lock()

    def _fresh(self, key: Hashable) -> tuple[bool, Any]:
        hit = self._values.get(key)
        if hit and time.monotonic() - hit[0] < self._ttl:
            return True, hit[1]
        return False, hit[1] if hit else None

    def get(self, key: Hashable) -> Any:
        fresh, value = self._fresh(key)
        if fresh:
            return value

        with self._guard:
            key_lock = self._key_locks.setdefault(key, threading.Lock())

        # Single-flight: the first caller fetches, the rest wait for its result.
        if not key_lock.acquire(timeout=self._key_wait):
            if value is not None:
                return value
            raise UpstreamBusy(f"{self.name}: timed out waiting for in-flight fetch")
        try:
            fresh, value = self._fresh(key)  # someone may have fetched while we waited
            if fresh:
                return value
            if not _upstream_slots.acquire(timeout=self._slot_wait):
                if value is not None:
                    return value
                raise UpstreamBusy(f"{self.name}: upstream concurrency limit reached")
            try:
                result = self._fetch(key)
            except Exception as exc:  # noqa: BLE001 - any upstream failure
                log.warning("%s fetch failed for %r: %s", self.name, key, exc)
                if value is not None:
                    return value  # stale beats nothing
                raise UpstreamError(self.name) from exc
            finally:
                _upstream_slots.release()
            self._values[key] = (time.monotonic(), result)
            return result
        finally:
            key_lock.release()
