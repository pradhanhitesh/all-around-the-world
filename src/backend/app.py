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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .security import SecurityMiddleware, TokenBucketLimiter
from .upstream import UpstreamBusy, UpstreamCache, UpstreamError

ROOT = Path(__file__).resolve().parents[2]
PARQUET = ROOT / "data" / "countries.parquet"
DIST = ROOT / "src" / "frontend" / "dist"

SUMMARY_FIELDS = [
    "iso3", "iso2", "numeric_code", "name", "capital",
    "region", "subregion", "latitude", "longitude", "population", "area_sq_km",
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
    ({k: c[k] for k in SUMMARY_FIELDS} for c in COUNTRIES.values()),
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
# Per IP: bursts of 40, then 20/min sustained, on /wiki and /news only.
# (Opening a country prefetches both, so that's ~10 countries/min sustained.)
app.add_middleware(SecurityMiddleware, limiter=TokenBucketLimiter(per_minute=20, burst=40))


# CDN caching (Vercel or any CDN honouring s-maxage). Browsers keep a short copy;
# the CDN keeps a long one and serves stale while it refreshes in the background.
# Vercel purges its CDN cache on every deploy, so static data can be cached "forever".
CACHE_STATIC = "public, max-age=3600, s-maxage=31536000"
CACHE_WIKI = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800"
CACHE_NEWS = "public, max-age=300, s-maxage=900, stale-while-revalidate=3600"
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


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = DIST / path
        if path and file.is_file() and DIST in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(DIST / "index.html")
