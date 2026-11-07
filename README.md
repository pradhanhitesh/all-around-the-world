# All Around the World

Mobile-first globe explorer for countries, capitals and geographic facts.
Spin the globe, tap a country (or search / 🎲), get a facts sheet.

## Layout

```
data/raw/countries.csv        source data
data/countries.parquet        single source of truth for the API (generated)
src/backend/build_data.py     CSV -> parquet (types, parsed timezones, ranks, derived facts)
api/index.py                  Vercel serverless entrypoint (re-exports the FastAPI app)
vercel.json                   Vercel build, rewrites, security + cache headers
src/backend/app.py            FastAPI: /api/countries, /api/countries/{iso3}, /api/countries/{iso3}/wiki, /api/countries/{iso3}/news, serves built SPA
src/backend/upstream.py       cache + single-flight + concurrency cap for Wikipedia / Google News
src/backend/security.py       per-IP rate limit + security headers (CSP etc.)
src/frontend/                 Vite + globe.gl SPA
tests/                        pytest suite (.venv/bin/python -m pytest -q)
```

## Setup

```bash
.venv/bin/pip install -r requirements-dev.txt   # runtime deps + pandas, uvicorn, pytest
.venv/bin/python src/backend/build_data.py
cd src/frontend && npm install
```

## Run

Dev (hot reload, two terminals):

```bash
.venv/bin/uvicorn src.backend.app:app --reload --port 8000
cd src/frontend && npm run dev          # http://localhost:5173 (also on LAN for phone testing)
```

Prod (single server):

```bash
cd src/frontend && npm run build && cd ../..
.venv/bin/uvicorn src.backend.app:app --host 0.0.0.0 --port 8000
```

## Deploy (Vercel)

Import the GitHub repo in Vercel; `vercel.json` handles the rest:
- builds the SPA from `src/frontend` and serves `dist/` from the CDN (hashed assets cached immutably);
- `/api/*` runs `api/index.py` as a Python function, installing only `requirements.txt`;
- API responses carry `s-maxage` so the CDN absorbs traffic (static data until next deploy,
  Wikipedia 24 h, news 15 min, stale-while-revalidate); errors and 429s are `no-store`.
- Rebuild `data/countries.parquet` locally and commit it when the CSV changes.
- Add a Vercel Firewall rate-limit rule on `/api/countries/*/news` and `/wiki`: the in-app
  limiter is per function instance, so it's only a backstop on serverless.

Deploy env vars: `APP_CONTACT` (URL/email for the outbound User-Agent — Wikimedia's robot
policy asks for one), `ENABLE_DOCS=1` to expose `/docs`. Behind a reverse proxy, add
`--proxy-headers --forwarded-allow-ips=<proxy ip>` so rate limiting sees real client IPs.

Deep links: `/#/IND` (facts), `/#/IND/news` (headlines), `/#/IND/wiki` (Wikipedia article).

## Notes

- Country shapes: `world-atlas` 110m, joined on ISO numeric code. Small countries/islands
  not in that atlas render as dots.
- Wikipedia: `build_data.py` resolves exact enwiki titles from each Wikidata ID (needs network;
  falls back to the country name). Articles are fetched live with Wikipedia-API, cached in memory,
  and sanitized client-side before rendering.
- News: Google News RSS search feed (English, past 7 days) using the `news_query` column;
  ambiguous names (Georgia, Jordan, Chad, …) have overrides in `NEWS_QUERY_OVERRIDES`. Cached 15 min.
- GDP in the source CSV is in millions of USD (`gdp_musd`).
- To add facts: add columns in `build_data.py`, rebuild parquet, render them in `src/frontend/src/facts.js`.

## Security model

- No user input reaches upstream services: routes accept only the 250 ISO3 codes in the parquet.
- Upstream calls (Wikipedia, Google News) go through `UpstreamCache`: one in-flight fetch per
  country, TTL cache (wiki 24 h, news 15 min), max 4 concurrent upstream calls, stale-on-error.
  Upstream traffic is bounded no matter how much traffic the API gets.
- `/api/countries/*/wiki` and `/news` are rate-limited per IP (burst 40, 20/min); other routes
  are in-memory and unlimited.
- CSP (`script-src 'self'`, no framing), nosniff, referrer and permissions policies on every response.
- Wikipedia HTML is sanitized client-side (allowlist); news text is escaped, links must be http(s).
- Errors returned to clients are generic; details go to server logs.
