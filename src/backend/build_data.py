"""Build data/countries.parquet from data/raw/countries.csv.

The parquet file is the single source of truth for the API. Run this whenever
the raw CSV changes (or when new enrichment columns are added):

    .venv/bin/python src/backend/build_data.py
"""

from __future__ import annotations

import re
from pathlib import Path

import requests
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
RAW_CSV = ROOT / "data" / "raw" / "countries.csv"
OUT_PARQUET = ROOT / "data" / "countries.parquet"

# Timezones column is a JS-style literal: [{zoneName:'Asia\/Kabul',gmtOffset:16200,...}]
TZ_OBJ_RE = re.compile(r"\{([^}]*)\}")
TZ_FIELD_RE = re.compile(r"(\w+):(?:'((?:[^'\\]|\\.)*)'|(-?\d+))")


UNICODE_ESC_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def unescape_js(s: str) -> str:
    s = UNICODE_ESC_RE.sub(lambda m: chr(int(m.group(1), 16)), s)
    return s.replace("\\/", "/").replace("\\'", "'")


def parse_timezones(raw: str) -> list[dict]:
    if not isinstance(raw, str):
        return []
    zones = []
    for obj in TZ_OBJ_RE.findall(raw):
        fields = {}
        for key, sval, nval in TZ_FIELD_RE.findall(obj):
            fields[key] = int(nval) if nval else unescape_js(sval)
        zones.append(
            {
                "zone_name": fields.get("zoneName"),
                "gmt_offset": fields.get("gmtOffset"),
                "gmt_offset_name": fields.get("gmtOffsetName"),
                "abbreviation": fields.get("abbreviation"),
                "tz_name": fields.get("tzName"),
            }
        )
    return zones


USER_AGENT = "AllAroundTheWorld/0.1 (weekend project)"


def resolve_wikipedia_titles(qids: list[str]) -> dict[str, str]:
    """Map Wikidata QIDs -> English Wikipedia article titles (50 ids per request)."""
    titles: dict[str, str] = {}
    with requests.Session() as client:
        client.headers["User-Agent"] = USER_AGENT
        for i in range(0, len(qids), 50):
            res = client.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(qids[i : i + 50]),
                    "props": "sitelinks",
                    "sitefilter": "enwiki",
                    "format": "json",
                },
                timeout=30,
            )
            res.raise_for_status()
            for qid, entity in res.json().get("entities", {}).items():
                link = entity.get("sitelinks", {}).get("enwiki")
                if link:
                    titles[qid] = link["title"]
    return titles


# Google News search queries for names that collide with other places/words.
NEWS_QUERY_OVERRIDES = {
    "GEO": "Georgia (Tbilisi OR Georgian)",
    "JEY": '("States of Jersey" OR "Jersey, Channel Islands" OR "Jersey Airport") -"New Jersey"',
    "JOR": "Jordan Amman",
    "TCD": 'Chad (Chadian OR "N\'Djamena")',
    "DMA": 'Dominica -"Dominican Republic"',
    "GIN": "Guinea Conakry",
    "NER": '"Niger" -Nigeria',
    "TUR": '("Turkey" OR "Türkiye") (Ankara OR Turkish)',
}
PAREN_RE = re.compile(r"\s*\([^)]*\)")


def news_query(iso3: str, title: str) -> str:
    if iso3 in NEWS_QUERY_OVERRIDES:
        return NEWS_QUERY_OVERRIDES[iso3]
    return f'"{PAREN_RE.sub("", title).strip()}"'


def hemisphere(lat: float, lng: float) -> str:
    ns = "Northern" if lat >= 0 else "Southern"
    ew = "Eastern" if lng >= 0 else "Western"
    return f"{ns} & {ew}"


def main() -> None:
    df = pd.read_csv(RAW_CSV, dtype=str, keep_default_na=False)
    df = df.apply(lambda s: s.str.strip())
    df = df.replace("", pd.NA)

    out = pd.DataFrame(
        {
            "id": df["id"].astype("int32"),
            "name": df["name"],
            "iso3": df["iso3"],
            "iso2": df["iso2"],
            "numeric_code": df["numeric_code"].astype("int32"),
            "phonecode": df["phonecode"],
            "capital": df["capital"],
            "currency": df["currency"],
            "currency_name": df["currency_name"],
            "tld": df["tld"],
            "population": pd.to_numeric(df["population"]).astype("Int64"),
            # Source GDP is in millions of USD.
            "gdp_musd": pd.to_numeric(df["gdp"]).astype("Int64"),
            "region": df["region"],
            "subregion": df["subregion"],
            "nationality": df["nationality"],
            "area_sq_km": pd.to_numeric(df["area_sq_km"]).astype("float64"),
            "latitude": pd.to_numeric(df["latitude"]).astype("float64"),
            "longitude": pd.to_numeric(df["longitude"]).astype("float64"),
            "wikidata_id": df["wikiDataId"],
        }
    )

    # Derived facts
    area = out["area_sq_km"].where(out["area_sq_km"] > 0)
    out["population_density"] = (out["population"].astype("float64") / area).round(1)
    out["gdp_per_capita_usd"] = (
        out["gdp_musd"].astype("float64") * 1_000_000 / out["population"].astype("float64")
    ).round(0)
    out["hemisphere"] = [hemisphere(a, b) for a, b in zip(out["latitude"], out["longitude"])]
    for col, rank_col in [
        ("area_sq_km", "area_rank"),
        ("population", "population_rank"),
        ("gdp_musd", "gdp_rank"),
        ("population_density", "density_rank"),
    ]:
        out[rank_col] = out[col].astype("float64").rank(ascending=False, method="min").astype("Int32")
    out["timezones"] = df["timezones"].map(parse_timezones)

    # Exact English Wikipedia titles via Wikidata (avoids disambiguation pages,
    # e.g. "Georgia"). Falls back to the country name when offline.
    try:
        titles = resolve_wikipedia_titles(out["wikidata_id"].dropna().unique().tolist())
    except requests.RequestException as exc:
        print(f"warning: could not resolve Wikipedia titles ({exc}); using names")
        titles = {}
    out["wikipedia_title"] = [titles.get(q, n) for q, n in zip(out["wikidata_id"], out["name"])]
    out["news_query"] = [news_query(i, t) for i, t in zip(out["iso3"], out["wikipedia_title"])]

    tz_type = pa.list_(
        pa.struct(
            [
                ("zone_name", pa.string()),
                ("gmt_offset", pa.int32()),
                ("gmt_offset_name", pa.string()),
                ("abbreviation", pa.string()),
                ("tz_name", pa.string()),
            ]
        )
    )
    table = pa.Table.from_pandas(out, preserve_index=False)
    table = table.set_column(
        table.schema.get_field_index("timezones"),
        "timezones",
        pa.array(out["timezones"].tolist(), type=tz_type),
    )

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, OUT_PARQUET, compression="zstd")
    print(f"Wrote {len(out)} rows, {len(out.columns)} columns -> {OUT_PARQUET}")


if __name__ == "__main__":
    main()
