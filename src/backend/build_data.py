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
# SimpleMaps Basic World Countries Database (CC BY 4.0, attribution required).
SIMPLEMAPS_CSV = ROOT / "data" / "raw" / "simplemaps_countries.csv"
# World Bank WDI health extracts (CC BY 4.0), produced by extract_worldbank.py.
WB_HEALTH_CSV = ROOT / "data" / "raw" / "worldbank_health.csv"
WB_LIFE_EXP_CSV = ROOT / "data" / "raw" / "worldbank_life_expectancy.csv"
WB_INCOME_CSV = ROOT / "data" / "raw" / "worldbank_income.csv"
WB_GDP_CSV = ROOT / "data" / "raw" / "worldbank_gdp.csv"
# World Happiness Report 2026, Figure 2.1 (from extract_whr.py).
WHR_CSV = ROOT / "data" / "raw" / "whr_happiness.csv"
# WHR country names that differ from ours. "North Cyprus" and "Somaliland Region" have their own
# survey results and aren't separate entries here, so they're left out rather than merged.
WHR_ALIASES = {
    "Czechia": "CZE", "Côte d’Ivoire": "CIV", "DR Congo": "COD", "Gambia": "GMB",
    "Hong Kong SAR of China": "HKG", "Lao PDR": "LAO", "Republic of Korea": "KOR",
    "Republic of Moldova": "MDA", "Russian Federation": "RUS", "State of Palestine": "PSE",
    "Swaziland": "SWZ", "Taiwan Province of China": "TWN", "Türkiye": "TUR", "Viet Nam": "VNM",
}
WHR_SKIP = {"North Cyprus", "Somaliland Region"}
WHR_FACTORS = ["gdp", "social_support", "healthy_life", "freedom", "generosity", "corruption", "dystopia_residual"]
# Capital-city coordinates from geocode_capitals.py (Open-Meteo / GeoNames, CC BY 4.0).
CAPITAL_COORDS_CSV = ROOT / "data" / "raw" / "capital_coords.csv"
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


def load_simplemaps() -> pd.DataFrame:
    """Extra per-country fields, keyed by ISO2. Only fields the main CSV lacks are used."""
    # keep_default_na=False: Namibia's ISO2 code is "NA", which pandas would read as missing.
    sm = pd.read_csv(SIMPLEMAPS_CSV, dtype=str, keep_default_na=False)
    sm = sm.apply(lambda s: s.str.strip()).replace("", pd.NA)
    sm = sm[sm["iso2"].notna()]  # drops a few territories without an ISO code
    # Some codes cover several rows (e.g. PS = West Bank + Gaza Strip): keep the most complete one.
    sm = (
        sm.assign(_filled=sm.notna().sum(axis=1))
        .sort_values("_filled", ascending=False, kind="stable")
        .drop_duplicates("iso2")
    )
    website = sm["website"].where(sm["website"].str.match(r"^https?://", na=False))
    return pd.DataFrame(
        {
            "iso2": sm["iso2"],
            "primary_language": sm["language"],
            "main_religion": sm["religion"],
            "median_age": pd.to_numeric(sm["median_age"]).astype("float64"),
            "driving_side": sm["driving_side"],
            "un_member": sm["un_member"].map({"TRUE": True, "FALSE": False}).astype("boolean"),
            "gov_website": website,
        }
    )


def load_worldbank() -> pd.DataFrame:
    """Per-country health indicators (latest value + world rank), life-expectancy series, income group."""
    health = pd.read_csv(WB_HEALTH_CSV)
    # Rank within each indicator among countries that report it: 1 = highest value.
    health["rank"] = health.groupby("indicator")["value"].rank(ascending=False, method="min").astype(int)
    health["count"] = health.groupby("indicator")["value"].transform("size")
    health_lists = (
        health.sort_values(["iso3", "indicator"])
        .groupby("iso3")[["indicator", "value", "year", "rank", "count"]]
        .apply(lambda g: g.rename(columns={"indicator": "code"}).to_dict("records"))
        .rename("health")
    )
    series = (
        pd.read_csv(WB_LIFE_EXP_CSV)
        .sort_values(["iso3", "year"])
        .groupby("iso3")[["year", "value"]]
        .apply(lambda g: g.to_dict("records"))
        .rename("life_expectancy_series")
    )
    income = pd.read_csv(WB_INCOME_CSV).set_index("iso3")["income_group"]
    return pd.concat([health_lists, series, income], axis=1).rename_axis("iso3").reset_index()


def sig3(x: float) -> float:
    """Round to 3 significant figures: plenty for a chart, and compresses far better."""
    return float(f"{x:.3g}")


def load_gdp() -> pd.DataFrame:
    """World Bank GDP (current US$): latest value + year, and the full yearly series."""
    gdp = pd.read_csv(WB_GDP_CSV).sort_values(["iso3", "year"])
    latest = gdp.groupby("iso3").last().rename(columns={"value": "wb_gdp_usd", "year": "gdp_year"})
    series = (
        gdp.groupby("iso3")[["year", "value"]]
        .apply(lambda g: g.assign(value=g["value"].map(sig3)).to_dict("records"))
        .rename("gdp_series")
    )
    return latest.join(series).reset_index()


def load_whr(countries: pd.DataFrame) -> pd.DataFrame:
    """Latest happiness score/rank/interval/factors per ISO3, plus the score trend."""
    import unicodedata

    def norm(s):
        return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()

    lookup = {}
    for iso3, name, title in zip(countries["iso3"], countries["name"], countries["wikipedia_title"]):
        for n in (name, title):
            if isinstance(n, str):
                lookup[norm(n)] = iso3
    whr = pd.read_csv(WHR_CSV)
    whr = whr[~whr["country"].isin(WHR_SKIP)]
    whr["iso3"] = whr["country"].map(lambda n: WHR_ALIASES.get(n) or lookup.get(norm(n)))
    unmatched = sorted(whr.loc[whr["iso3"].isna(), "country"].unique())
    if unmatched:
        raise SystemExit(f"Unmatched World Happiness Report names (add to WHR_ALIASES): {unmatched}")

    counts = whr.groupby("year")["rank"].count()
    latest = whr.sort_values("year").groupby("iso3").last()
    out = pd.DataFrame(
        {
            "happiness_score": latest["score"].round(3),
            "happiness_rank": latest["rank"].astype("Int16"),
            "happiness_count": latest["year"].map(counts).astype("Int16"),
            "happiness_year": latest["year"].astype("Int16"),
            "happiness_lower": latest["lower"].round(3),
            "happiness_upper": latest["upper"].round(3),
        }
    )
    out["happiness_factors"] = [
        {f: (None if pd.isna(row[f]) else round(float(row[f]), 3)) for f in WHR_FACTORS} for _, row in latest.iterrows()
    ]
    out["happiness_series"] = (
        whr.sort_values("year")
        .groupby("iso3")[["year", "score"]]
        .apply(lambda g: [{"year": int(y), "value": round(float(v), 3)} for y, v in zip(g["year"], g["score"])])
    )
    return out.rename_axis("iso3").reset_index()


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

    extra = load_simplemaps()
    out = out.merge(extra, on="iso2", how="left", validate="one_to_one")
    extra_cols = [c for c in extra.columns if c != "iso2"]
    unmatched = out.loc[out[extra_cols].isna().all(axis=1), "name"].tolist()
    if unmatched:
        print(f"note: no SimpleMaps match for {unmatched}")

    wb = load_worldbank()
    out = out.merge(wb, on="iso3", how="left", validate="one_to_one")
    for col in ("health", "life_expectancy_series"):
        out[col] = out[col].apply(lambda v: v if isinstance(v, list) else [])
    print(f"World Bank health data for {sum(bool(h) for h in out['health'])} of {len(out)} countries")

    # Capital coordinates (for air quality). Missing ones fall back to the country centre in the API.
    caps = pd.read_csv(CAPITAL_COORDS_CSV, usecols=["iso3", "latitude", "longitude"]).rename(
        columns={"latitude": "capital_latitude", "longitude": "capital_longitude"}
    )
    out = out.merge(caps, on="iso3", how="left", validate="one_to_one")
    print(f"Capital coordinates for {int(out['capital_latitude'].notna().sum())} of {len(out)} countries")

    # Flat copies of two health indicators, for colouring the globe by metric.
    def latest(code):
        return out["health"].apply(lambda hs: next((h["value"] for h in hs if h["code"] == code), None)).astype("float64")

    out["life_expectancy"] = latest("SP.DYN.LE00.IN").round(1)
    out["fertility_rate"] = latest("SP.DYN.TFRT.IN").round(2)

    # GDP: World Bank (newer, with a year) where available; the original CSV otherwise.
    out = out.merge(load_gdp(), on="iso3", how="left", validate="one_to_one")
    out["gdp_series"] = out["gdp_series"].apply(lambda v: v if isinstance(v, list) else [])
    from_csv = out["wb_gdp_usd"].isna() & out["gdp_musd"].notna()
    out["gdp_usd"] = out["wb_gdp_usd"].fillna(out["gdp_musd"].astype("float64") * 1_000_000)
    out["gdp_year"] = out["gdp_year"].astype("Int16")
    print(f"GDP: {int(out['wb_gdp_usd'].notna().sum())} from World Bank, {int(from_csv.sum())} from countries.csv "
          f"({', '.join(out.loc[from_csv, 'name'])})")
    out = out.drop(columns=["wb_gdp_usd", "gdp_musd"])

    # Derived facts
    area = out["area_sq_km"].where(out["area_sq_km"] > 0)
    out["population_density"] = (out["population"].astype("float64") / area).round(1)
    out["gdp_per_capita_usd"] = (
        out["gdp_usd"] / out["population"].astype("float64")
    ).round(0)
    out["hemisphere"] = [hemisphere(a, b) for a, b in zip(out["latitude"], out["longitude"])]
    for col, rank_col in [
        ("area_sq_km", "area_rank"),
        ("population", "population_rank"),
        ("gdp_usd", "gdp_rank"),
        ("population_density", "density_rank"),
    ]:
        out[rank_col] = out[col].astype("float64").rank(ascending=False, method="min").astype("Int32")
    # 1 = youngest population
    out["median_age_rank"] = out["median_age"].rank(ascending=True, method="min").astype("Int32")
    out["median_age_rank_oldest"] = out["median_age"].rank(ascending=False, method="min").astype("Int32")
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

    # World Happiness Report: latest life evaluation, rank and what explains it, plus the trend.
    out = out.merge(load_whr(out), on="iso3", how="left", validate="one_to_one")
    out["happiness_series"] = out["happiness_series"].apply(lambda v: v if isinstance(v, list) else [])
    out["happiness_factors"] = out["happiness_factors"].apply(lambda v: v if isinstance(v, dict) else None)
    print(f"Happiness data for {int(out['happiness_score'].notna().sum())} of {len(out)} countries")

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
    health_type = pa.list_(
        pa.struct(
            [
                ("code", pa.string()),
                ("value", pa.float64()),
                ("year", pa.int16()),
                ("rank", pa.int16()),
                ("count", pa.int16()),
            ]
        )
    )
    series_type = pa.list_(pa.struct([("year", pa.int16()), ("value", pa.float64())]))
    nested = {
        "timezones": tz_type,
        "health": health_type,
        "life_expectancy_series": series_type,
        "gdp_series": series_type,
        "happiness_series": series_type,
        "happiness_factors": pa.struct([(f, pa.float64()) for f in WHR_FACTORS]),
    }
    table = pa.Table.from_pandas(out.drop(columns=list(nested)), preserve_index=False)
    for name, typ in nested.items():
        table = table.append_column(name, pa.array(out[name].tolist(), type=typ))

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, OUT_PARQUET, compression="zstd")
    print(f"Wrote {len(out)} rows, {len(out.columns)} columns -> {OUT_PARQUET}")


if __name__ == "__main__":
    main()
