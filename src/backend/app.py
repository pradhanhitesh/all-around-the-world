"""FastAPI backend serving country facts from a single parquet file.

Dev:   .venv/bin/uvicorn src.backend.app:app --reload --port 8000
Prod:  build the frontend (npm run build in src/frontend), then run the same
       command; the built SPA is served from /.

Environment:
  APP_CONTACT   contact URL or email added to the outbound User-Agent
                (Wikimedia's robot policy asks for one).
  ENABLE_DOCS   set to 1 to expose /docs and /openapi.json.
"""

from __future__ import annotations

import html
import json
import math
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pyarrow.parquet as pq
import requests
import wikipediaapi
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .security import SecurityMiddleware, TokenBucketLimiter
from .upstream import UpstreamBusy, UpstreamCache, UpstreamError

ROOT = Path(__file__).resolve().parents[2]
PARQUET = ROOT / "data" / "countries.parquet"
DIST = ROOT / "src" / "frontend" / "dist"

SUMMARY_FIELDS = [
    "iso3", "iso2", "numeric_code", "name", "capital",
    "region", "subregion", "latitude", "longitude", "population", "area_sq_km",
    "capital_latitude", "capital_longitude",
    # Metrics the globe can be coloured by.
    "life_expectancy", "gdp_per_capita_usd", "median_age", "population_density", "fertility_rate",
    "happiness_score",
]


def _clean(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def load_countries() -> dict[str, dict]:
    rows = pq.read_table(PARQUET).to_pylist()
    return {r["iso3"]: {k: _clean(v) for k, v in r.items()} for r in rows}


COUNTRIES = load_countries()
SUMMARY = sorted(
    # .get: a column missing from an older parquet leaves that field empty instead of crashing startup.
    ({k: c.get(k) for k in SUMMARY_FIELDS} for c in COUNTRIES.values()),
    key=lambda c: c["name"],
)

_contact = os.environ.get("APP_CONTACT", "").strip()
USER_AGENT = f"AllAroundTheWorld/0.2 ({_contact})" if _contact else "AllAroundTheWorld/0.2"

_docs = os.environ.get("ENABLE_DOCS") == "1"
app = FastAPI(
    title="All Around the World",
    docs_url="/docs" if _docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs else None,
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
# Per IP on upstream-backed routes (wiki, news, air, weather): bursts of 60, then 30/min.
# Opening a country fetches news + wiki + weather, so that's ~10 countries/min sustained.
app.add_middleware(SecurityMiddleware, limiter=TokenBucketLimiter(per_minute=30, burst=60))


# CDN caching (Vercel or any CDN honouring s-maxage). Browsers keep a short copy;
# the CDN keeps a long one and serves stale while it refreshes in the background.
# Vercel purges its CDN cache on every deploy, so static data can be cached "forever".
# Browsers revalidate static data every time (max-age=0) so a deploy with new data shows
# up immediately; the CDN (purged on each deploy) still answers those requests instantly.
CACHE_STATIC = "public, max-age=0, must-revalidate, s-maxage=31536000"
CACHE_WIKI = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800"
CACHE_NEWS = "public, max-age=300, s-maxage=900, stale-while-revalidate=3600"
CACHE_AIR = "public, max-age=600, s-maxage=1800, stale-while-revalidate=1800"
NO_STORE = {"Cache-Control": "no-store"}  # never cache errors / throttling


def _country_or_404(iso3: str) -> dict:
    country = COUNTRIES.get(iso3.upper())
    if not country:
        raise HTTPException(404, "Unknown country code")
    return country


def _upstream_get(cache: UpstreamCache, key: str):
    try:
        return cache.get(key)
    except UpstreamBusy:
        raise HTTPException(503, "Service busy, please retry shortly", headers={"Retry-After": "5", **NO_STORE})
    except UpstreamError:
        # Details are logged in upstream.py; don't leak them to clients.
        raise HTTPException(502, "Upstream service unavailable", headers=NO_STORE)


@app.get("/api/countries")
def list_countries(response: Response):
    response.headers["Cache-Control"] = CACHE_STATIC
    return {"count": len(SUMMARY), "countries": SUMMARY}


@app.get("/api/countries/{iso3}")
def get_country(iso3: str, response: Response):
    response.headers["Cache-Control"] = CACHE_STATIC
    return {**_country_or_404(iso3), "total_countries": len(COUNTRIES)}


WIKI = wikipediaapi.Wikipedia(
    user_agent=USER_AGENT,
    language="en",
    extract_format=wikipediaapi.ExtractFormat.HTML,
    timeout=8.0,
    max_retries=1,
)
SKIP_SECTIONS = {
    "see also", "references", "notes", "external links", "further reading",
    "bibliography", "citations", "sources", "footnotes", "general bibliography",
}


def _flatten(sections, out):
    for s in sections:
        if s.title.strip().lower() in SKIP_SECTIONS:
            continue
        out.append({"title": s.title, "level": s.level, "html": s.text})
        _flatten(s.sections, out)
    return out


def _fetch_wiki(iso3: str) -> dict | None:
    country = COUNTRIES[iso3]
    page = WIKI.page(country.get("wikipedia_title") or country["name"])
    if not page.exists():
        return None
    sections = [s for s in _flatten(page.sections, []) if s["html"].strip() or s["level"] <= 1]
    return {
        "title": page.title,
        "url": page.fullurl,
        "summary_html": page.summary,
        "sections": sections,
        "license": "Text from Wikipedia, available under CC BY-SA 4.0.",
    }


WIKI_CACHE = UpstreamCache("wikipedia", _fetch_wiki, ttl_seconds=24 * 3600)


@app.get("/api/countries/{iso3}/wiki")
def get_country_wiki(iso3: str, response: Response):
    country = _country_or_404(iso3)
    article = _upstream_get(WIKI_CACHE, country["iso3"])
    if not article:
        raise HTTPException(404, "No Wikipedia article found")
    response.headers["Cache-Control"] = CACHE_WIKI
    return article


NEWS_TTL_SECONDS = 15 * 60
NEWS_LIMIT = 20
NEWS_MAX_BYTES = 2 * 1024 * 1024  # Google's feeds are ~15-100 KB; refuse anything absurd


def _parse_news(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iterfind("./channel/item"):
        title = (it.findtext("title") or "").strip()
        source_el = it.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        # Google appends " - Source" to every title; drop it since we show the source separately.
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        try:
            published = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(timezone.utc)
        except (TypeError, ValueError):
            published = None
        items.append(
            {
                "title": title,
                "url": it.findtext("link"),
                "source": source,
                "source_url": source_el.get("url") if source_el is not None else None,
                "published": published.isoformat() if published else None,
            }
        )
    items.sort(key=lambda i: i["published"] or "", reverse=True)
    return items[:NEWS_LIMIT]


def _fetch_news(iso3: str) -> dict:
    country = COUNTRIES[iso3]
    query = country.get("news_query") or f'"{country["name"]}"'
    with requests.get(
        "https://news.google.com/rss/search",
        params={"q": f"{query} when:7d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        headers={"User-Agent": USER_AGENT},
        timeout=8,
        stream=True,
    ) as res:
        res.raise_for_status()
        body = res.raw.read(NEWS_MAX_BYTES + 1, decode_content=True)
    if len(body) > NEWS_MAX_BYTES:
        raise ValueError("news feed too large")
    return {
        "query": query,
        "items": _parse_news(body),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "attribution": "Headlines via Google News",
    }


NEWS_CACHE = UpstreamCache("google-news", _fetch_news, ttl_seconds=NEWS_TTL_SECONDS)


@app.get("/api/countries/{iso3}/news")
def get_country_news(iso3: str, response: Response):
    payload = _upstream_get(NEWS_CACHE, _country_or_404(iso3)["iso3"])
    response.headers["Cache-Control"] = CACHE_NEWS
    return payload


# ---------------------------------------------------------------- air quality (Open-Meteo)
AIR_API = "https://air-quality-api.open-meteo.com/v1/air-quality"
AIR_CURRENT = [
    "us_aqi", "european_aqi", "pm2_5", "pm10", "ozone",
    "nitrogen_dioxide", "sulphur_dioxide", "carbon_monoxide",
]
AIR_MAX_BYTES = 256 * 1024


def _place(c: dict) -> tuple[float, float, dict]:
    """Where to sample live conditions: the capital (where people live), else the country's centre."""
    if c.get("capital_latitude") is not None and c.get("capital_longitude") is not None:
        return c["capital_latitude"], c["capital_longitude"], {"name": c["capital"], "kind": "capital"}
    return c["latitude"], c["longitude"], {"name": c["name"], "kind": "country centre"}


def _fetch_air(iso3: str) -> dict:
    lat, lon, place = _place(COUNTRIES[iso3])
    with requests.get(
        AIR_API,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": ",".join(AIR_CURRENT),
            "hourly": "us_aqi",
            "past_hours": 12,
            "forecast_hours": 24,
            "timezone": "auto",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=8,
        stream=True,
    ) as res:
        res.raise_for_status()
        body = res.raw.read(AIR_MAX_BYTES + 1, decode_content=True)
    if len(body) > AIR_MAX_BYTES:
        raise ValueError("air quality response too large")
    data = json.loads(body)
    hourly = data.get("hourly", {})
    return {
        "location": {**place, "latitude": round(lat, 3), "longitude": round(lon, 3)},
        "time": data["current"]["time"],
        "timezone": data.get("timezone"),
        "current": {k: data["current"].get(k) for k in AIR_CURRENT},
        "units": {k: data.get("current_units", {}).get(k) for k in AIR_CURRENT},
        "hourly": [
            {"time": t, "us_aqi": v}
            for t, v in zip(hourly.get("time", []), hourly.get("us_aqi", []))
            if v is not None
        ],
        "attribution": "Air quality: Open-Meteo, CAMS (Copernicus Atmosphere Monitoring Service)",
    }


# Model data updates hourly; 30 min keeps Open-Meteo calls to at most ~250 countries x 48/day.
AIR_CACHE = UpstreamCache("open-meteo-air", _fetch_air, ttl_seconds=30 * 60)


@app.get("/api/countries/{iso3}/air")
def get_country_air(iso3: str, response: Response):
    payload = _upstream_get(AIR_CACHE, _country_or_404(iso3)["iso3"])
    response.headers["Cache-Control"] = CACHE_AIR
    return payload


# ---------------------------------------------------------------- current weather (Open-Meteo)
WEATHER_API = "https://api.open-meteo.com/v1/forecast"
WEATHER_FIELDS = [
    "temperature_2m", "apparent_temperature", "relative_humidity_2m", "weather_code",
    "is_day", "cloud_cover", "precipitation", "wind_speed_10m",
]
WEATHER_MAX_BYTES = 64 * 1024
CACHE_WEATHER = "public, max-age=300, s-maxage=900, stale-while-revalidate=900"


def _fetch_weather(iso3: str) -> dict:
    lat, lon, place = _place(COUNTRIES[iso3])
    with requests.get(
        WEATHER_API,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": ",".join(WEATHER_FIELDS),
            "timezone": "auto",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=8,
        stream=True,
    ) as res:
        res.raise_for_status()
        body = res.raw.read(WEATHER_MAX_BYTES + 1, decode_content=True)
    if len(body) > WEATHER_MAX_BYTES:
        raise ValueError("weather response too large")
    data = json.loads(body)
    current = data["current"]
    return {
        "location": {**place, "latitude": round(lat, 3), "longitude": round(lon, 3)},
        "time": current["time"],
        "timezone": data.get("timezone"),
        "current": {k: current.get(k) for k in WEATHER_FIELDS},
        "units": {k: data.get("current_units", {}).get(k) for k in WEATHER_FIELDS},
        "attribution": "Weather: Open-Meteo",
    }


# The model updates every 15 min; caching for 15 min keeps calls to <= ~250 countries x 96/day.
WEATHER_CACHE = UpstreamCache("open-meteo-weather", _fetch_weather, ttl_seconds=15 * 60)


@app.get("/api/countries/{iso3}/weather")
def get_country_weather(iso3: str, response: Response):
    payload = _upstream_get(WEATHER_CACHE, _country_or_404(iso3)["iso3"])
    response.headers["Cache-Control"] = CACHE_WEATHER
    return payload


# ---------------------------------------------------------------- share links with per-country previews
# /c/IND, /c/IND/health ... : link-preview crawlers read the tags below; people are sent on to the
# app view (/#/IND/health) by a meta refresh (no inline script, so the CSP stays strict).
SITE_URL = os.environ.get("PUBLIC_SITE_URL", "https://worldfly.vercel.app").rstrip("/")
SHARE_VIEWS = {"facts": "", "health": "/health", "news": "/news", "wiki": "/wiki"}
_compact = lambda n: (  # noqa: E731 - tiny formatter
    f"{n / 1e12:.1f}T" if n >= 1e12 else f"{n / 1e9:.1f}B" if n >= 1e9 else f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n:,.0f}"
)


def _share_text(c: dict, view: str) -> tuple[str, str]:
    name = c["name"]
    bits = []
    if c.get("capital"):
        bits.append(f"Capital {c['capital']}")
    if c.get("population"):
        bits.append(f"{_compact(c['population'])} people")
    if c.get("life_expectancy"):
        bits.append(f"life expectancy {c['life_expectancy']:.1f} years")
    if c.get("gdp_usd"):
        bits.append(f"GDP ${_compact(c['gdp_usd'])}")
    facts = " · ".join(bits)
    if view == "health":
        return f"{name}: health & air quality", f"Life expectancy, healthcare and live air quality for {name}. {facts}."
    if view == "news":
        return f"{name}: latest news", f"The latest headlines about {name}, on an interactive 3D globe. {facts}."
    if view == "wiki":
        return f"{name} on Wikipedia", f"Read about {name} without leaving the globe. {facts}."
    return f"{name} · All Around the World", f"{facts}. Explore {name} on an interactive 3D globe."


@app.get("/c/{iso3}", include_in_schema=False)
@app.get("/c/{iso3}/{view}", include_in_schema=False)
def share_page(iso3: str, view: str = "facts"):
    c = _country_or_404(iso3)
    view = view if view in SHARE_VIEWS else "facts"
    title, desc = _share_text(c, view)
    url = f"{SITE_URL}/c/{c['iso3']}{SHARE_VIEWS[view]}"
    app_url = f"/#/{c['iso3']}{SHARE_VIEWS[view]}"
    e = html.escape
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="All Around the World">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(SITE_URL)}/og.jpg">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{e(SITE_URL)}/og.jpg">
<meta http-equiv="refresh" content="0; url={e(app_url)}">
<style>body{{background:#070b14;color:#e8edf7;font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0}}a{{color:#ffd166}}</style>
</head><body><p>Opening <a href="{e(app_url)}">{e(c['name'])}</a>…</p></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": CACHE_STATIC})


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = DIST / path
        if path and file.is_file() and DIST in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(DIST / "index.html")
