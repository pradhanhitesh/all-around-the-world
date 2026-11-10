"""Security/robustness tests: upstream caching guarantees, rate limiting, headers.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from src.backend import app as app_module
from src.backend import upstream
from src.backend.security import TokenBucketLimiter
from src.backend.upstream import UpstreamBusy, UpstreamCache, UpstreamError


# ---------------------------------------------------------------- UpstreamCache


def test_single_flight_concurrent_requests_share_one_fetch():
    calls = 0

    def fetch(key):
        nonlocal calls
        calls += 1
        time.sleep(0.2)
        return f"value-{key}"

    cache = UpstreamCache("t", fetch, ttl_seconds=60)
    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda _: cache.get("IND"), range(20)))
    assert results == ["value-IND"] * 20
    assert calls == 1


def test_ttl_cache_serves_from_memory_until_expiry():
    calls = 0

    def fetch(key):
        nonlocal calls
        calls += 1
        return calls

    cache = UpstreamCache("t", fetch, ttl_seconds=0.2)
    assert cache.get("A") == 1
    assert cache.get("A") == 1
    time.sleep(0.25)
    assert cache.get("A") == 2


def test_stale_value_served_when_refresh_fails():
    state = {"fail": False}

    def fetch(key):
        if state["fail"]:
            raise RuntimeError("upstream down")
        return "good"

    cache = UpstreamCache("t", fetch, ttl_seconds=0.05)
    assert cache.get("A") == "good"
    state["fail"] = True
    time.sleep(0.1)
    assert cache.get("A") == "good"


def test_error_without_cached_value_raises_upstream_error():
    cache = UpstreamCache("t", lambda k: 1 / 0, ttl_seconds=60)
    with pytest.raises(UpstreamError):
        cache.get("A")


def test_global_concurrency_cap(monkeypatch):
    monkeypatch.setattr(upstream, "_upstream_slots", threading.BoundedSemaphore(2))
    active = peak = 0
    lock = threading.Lock()

    def fetch(key):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.15)
        with lock:
            active -= 1
        return key

    cache = UpstreamCache("t", fetch, ttl_seconds=60, slot_wait_seconds=5)
    with ThreadPoolExecutor(8) as pool:
        assert sorted(pool.map(cache.get, range(8))) == list(range(8))
    assert peak == 2


def test_busy_when_no_slot_frees_up(monkeypatch):
    monkeypatch.setattr(upstream, "_upstream_slots", threading.BoundedSemaphore(1))
    release = threading.Event()
    cache = UpstreamCache("t", lambda k: release.wait(2) or k, ttl_seconds=60, slot_wait_seconds=0.1)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(cache.get, "A")
        time.sleep(0.05)
        with pytest.raises(UpstreamBusy):
            cache.get("B")
        release.set()
        assert first.result() is True


# ---------------------------------------------------------------- rate limiter


def test_token_bucket_burst_then_limit_then_refill():
    limiter = TokenBucketLimiter(per_minute=600, burst=3)  # 10 tokens/s
    assert [limiter.take("ip") for _ in range(3)] == [0, 0, 0]
    wait = limiter.take("ip")
    assert 0 < wait <= 0.1
    assert limiter.take("other-ip") == 0  # buckets are per client
    time.sleep(0.12)
    assert limiter.take("ip") == 0


def test_token_bucket_prunes_idle_clients():
    limiter = TokenBucketLimiter(per_minute=6000, burst=1, max_keys=5)
    for i in range(5):
        limiter.take(f"ip{i}")
    time.sleep(0.02)  # all buckets refill (idle)
    limiter.take("new")
    assert len(limiter._buckets) <= 2


# ---------------------------------------------------------------- HTTP layer


@pytest.fixture
def client(monkeypatch):
    # Never touch the network in tests.
    monkeypatch.setattr(app_module.NEWS_CACHE, "_fetch", lambda iso3: {"items": [], "iso3": iso3})
    monkeypatch.setattr(app_module.WIKI_CACHE, "_fetch", lambda iso3: {"title": iso3})
    monkeypatch.setattr(app_module.AIR_CACHE, "_fetch", lambda iso3: {"current": {"us_aqi": 42}, "iso3": iso3})
    return TestClient(app_module.app)


def test_security_headers_on_api_and_spa(client):
    for path in ["/api/countries", "/"]:
        res = client.get(path)
        assert "default-src 'self'" in res.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in res.headers["content-security-policy"]
        assert res.headers["x-content-type-options"] == "nosniff"
        assert res.headers["x-frame-options"] == "DENY"


def test_docs_disabled_by_default(client):
    assert client.get("/openapi.json").headers["content-type"].startswith("text/html")  # falls to SPA
    assert "openapi" not in client.get("/docs").text.lower()


def test_unknown_country_does_not_echo_input(client):
    res = client.get("/api/countries/<script>/wiki")
    assert res.status_code == 404
    assert "<script>" not in res.text


def test_upstream_failure_message_is_generic(client, monkeypatch):
    monkeypatch.setattr(app_module.NEWS_CACHE, "_values", {})
    monkeypatch.setattr(
        app_module.NEWS_CACHE, "_fetch", lambda k: (_ for _ in ()).throw(RuntimeError("secret internal url"))
    )
    res = client.get("/api/countries/FRA/news")
    assert res.status_code == 502
    assert "secret" not in res.text


def test_rate_limit_applies_only_to_upstream_endpoints(client, monkeypatch):
    # Swap in a tiny limiter for this test.
    mw = client.app.middleware_stack
    while not hasattr(mw, "limiter"):
        mw = mw.app
    monkeypatch.setattr(mw, "limiter", TokenBucketLimiter(per_minute=1, burst=3))

    codes = [client.get("/api/countries/IND/news").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    res = client.get("/api/countries/IND/wiki")
    assert res.status_code == 429 and int(res.headers["retry-after"]) >= 1
    assert "content-security-policy" in res.headers
    # Cheap in-memory endpoints are never limited.
    assert all(client.get("/api/countries/IND").status_code == 200 for _ in range(10))


# ---------------------------------------------------------------- CDN caching / Vercel


def test_cache_control_headers(client):
    assert "s-maxage=31536000" in client.get("/api/countries").headers["cache-control"]
    assert "s-maxage=31536000" in client.get("/api/countries/IND").headers["cache-control"]
    assert "s-maxage=86400" in client.get("/api/countries/IND/wiki").headers["cache-control"]
    assert "s-maxage=900" in client.get("/api/countries/IND/news").headers["cache-control"]


def test_errors_are_never_cached(client, monkeypatch):
    monkeypatch.setattr(app_module.NEWS_CACHE, "_values", {})
    monkeypatch.setattr(app_module.NEWS_CACHE, "_fetch", lambda k: 1 / 0)
    assert client.get("/api/countries/BRA/news").headers["cache-control"] == "no-store"
    assert "s-maxage" not in client.get("/api/countries/XXX").headers.get("cache-control", "")


def test_vercel_client_ip_from_x_real_ip(client, monkeypatch):
    mw = client.app.middleware_stack
    while not hasattr(mw, "limiter"):
        mw = mw.app
    monkeypatch.setattr(mw, "ON_VERCEL", True)
    monkeypatch.setattr(mw, "limiter", TokenBucketLimiter(per_minute=1, burst=1))
    get = lambda ip: client.get("/api/countries/IND/news", headers={"x-real-ip": ip}).status_code
    assert [get("1.1.1.1"), get("1.1.1.1"), get("2.2.2.2")] == [200, 429, 200]
    assert client.get("/api/countries/IND/news", headers={"x-real-ip": "1.1.1.1"}).headers["cache-control"] == "no-store"


def test_vercel_entrypoint_exposes_app():
    import importlib.util

    spec = importlib.util.spec_from_file_location("vercel_entry", "api/index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.app is app_module.app


def test_air_endpoint_cached_and_rate_limited(client, monkeypatch):
    res = client.get("/api/countries/IND/air")
    assert res.status_code == 200 and res.json()["current"]["us_aqi"] == 42
    assert "s-maxage=1800" in res.headers["cache-control"]
    mw = client.app.middleware_stack
    while not hasattr(mw, "limiter"):
        mw = mw.app
    monkeypatch.setattr(mw, "limiter", TokenBucketLimiter(per_minute=1, burst=1))
    assert [client.get("/api/countries/IND/air").status_code for _ in range(2)] == [200, 429]


def test_air_uses_capital_then_country_centre(monkeypatch):
    calls = []

    class FakeResp:
        def __init__(self, params):
            self.params = params
            self.raw = self
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def raise_for_status(self):
            pass
        def read(self, n, decode_content=True):
            import json
            return json.dumps({"current": {"time": "2026-01-01T12:00", "us_aqi": 10}, "hourly": {"time": [], "us_aqi": []}}).encode()

    def fake_get(url, params, **kw):
        calls.append(params)
        return FakeResp(params)

    monkeypatch.setattr(app_module.requests, "get", fake_get)
    ind = app_module._fetch_air("IND")
    assert ind["location"]["kind"] == "capital" and ind["location"]["name"] == "New Delhi"
    assert abs(calls[-1]["latitude"] - 28.62) < 0.1
    iot = app_module._fetch_air("IOT")  # Diego Garcia isn't geocoded -> country centre
    assert iot["location"]["kind"] == "country centre"


def test_share_page_has_country_preview_and_redirect(client):
    res = client.get("/c/IND/health")
    assert res.status_code == 200
    body = res.text
    assert "<title>India: health &amp; air quality</title>" in body
    assert 'property="og:url" content="https://worldfly.vercel.app/c/IND/health"' in body
    assert 'http-equiv="refresh" content="0; url=/#/IND/health"' in body
    assert "<script" not in body  # CSP: no inline scripts
    assert client.get("/c/zzz").status_code == 404
    assert "/#/FRA\"" in client.get("/c/fra/bogus-view").text  # unknown view -> facts
