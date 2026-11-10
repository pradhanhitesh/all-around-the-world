"""Look up capital-city coordinates with the Open-Meteo Geocoding API (free, no key).

Writes data/raw/capital_coords.csv (iso3, capital, latitude, longitude, match), which
build_data.py merges into the parquet. Air quality is then fetched for the capital rather
than the country's geographic centre (India's centre is rural; New Delhi is where people live).

Usage:
    .venv/bin/python src/backend/geocode_capitals.py           # only countries not yet in the CSV
    .venv/bin/python src/backend/geocode_capitals.py --all     # redo everything

Geocoding data: GeoNames via Open-Meteo (CC BY 4.0).
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import pyarrow.parquet as pq
import requests

ROOT = Path(__file__).resolve().parents[2]
PARQUET = ROOT / "data" / "countries.parquet"
OUT = ROOT / "data" / "raw" / "capital_coords.csv"
API = "https://geocoding-api.open-meteo.com/v1/search"
USER_AGENT = "AllAroundTheWorld/0.2 (data build)"

# Capital names in countries.csv that the geocoder doesn't recognise.
ALIASES = {
    "ATG": "Saint John's",
    "LBY": "Tripoli",
    "MEX": "Mexico City",
    "SGP": "Singapore",
    "ESH": "Laayoune",
}


def geocode(session: requests.Session, capital: str, iso2: str) -> tuple[dict | None, str]:
    """Best match for a capital: a GeoNames capital (PPLC) in the right country if possible."""
    res = session.get(
        API, params={"name": capital, "count": 10, "language": "en", "format": "json", "countryCode": iso2}, timeout=15
    )
    res.raise_for_status()
    results = res.json().get("results") or []
    for r in results:
        if r.get("feature_code") == "PPLC":
            return r, "capital"
    if results:
        return results[0], "best match in country"
    return None, "not found"


def main(redo_all: bool) -> None:
    countries = [
        r for r in pq.read_table(PARQUET, columns=["iso3", "iso2", "capital"]).to_pylist() if r["capital"]
    ]
    done: dict[str, dict] = {}
    if OUT.exists() and not redo_all:
        with OUT.open() as f:
            done = {row["iso3"]: row for row in csv.DictReader(f)}

    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        for c in countries:
            if c["iso3"] in done and done[c["iso3"]]["match"] != "not found":
                continue
            hit, match = geocode(session, ALIASES.get(c["iso3"], c["capital"]), c["iso2"])
            done[c["iso3"]] = {
                "iso3": c["iso3"],
                "capital": c["capital"],
                "latitude": hit["latitude"] if hit else "",
                "longitude": hit["longitude"] if hit else "",
                "match": match,
            }
            print(f"{c['iso3']}  {c['capital']:<24} {match}")
            time.sleep(0.15)  # be polite to the free API

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["iso3", "capital", "latitude", "longitude", "match"])
        writer.writeheader()
        writer.writerows(sorted(done.values(), key=lambda r: r["iso3"]))
    counts: dict[str, int] = {}
    for r in done.values():
        counts[r["match"]] = counts.get(r["match"], 0) + 1
    print(f"Wrote {OUT.relative_to(ROOT)}: {counts}")


if __name__ == "__main__":
    main("--all" in sys.argv)
