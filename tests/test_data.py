"""Checks on the built parquet (run build_data.py first)."""

import pyarrow.parquet as pq
import pytest

from src.backend.build_data import OUT_PARQUET


@pytest.fixture(scope="module")
def countries():
    return {r["iso3"]: r for r in pq.read_table(OUT_PARQUET).to_pylist()}


def test_all_countries_present_and_unique(countries):
    assert len(countries) == 250


def test_namibia_iso2_na_not_treated_as_missing(countries):
    nam = countries["NAM"]
    assert nam["iso2"] == "NA"
    assert nam["primary_language"] == "English"


def test_simplemaps_fields_merged(countries):
    ind = countries["IND"]
    assert ind["primary_language"] == "Hindi"
    assert ind["driving_side"] == "left"
    assert ind["un_member"] is True
    assert ind["median_age"] > 0


def test_duplicate_source_rows_collapsed(countries):
    # SimpleMaps lists West Bank and Gaza Strip under the same ISO2 (PS).
    assert countries["PSE"]["main_religion"] == "Islam"


def test_websites_are_http_only(countries):
    for c in countries.values():
        url = c["gov_website"]
        assert url is None or url.startswith(("http://", "https://"))


def test_median_age_ranks(countries):
    youngest = min((c for c in countries.values() if c["median_age_rank"]), key=lambda c: c["median_age_rank"])
    oldest = min((c for c in countries.values() if c["median_age_rank_oldest"]), key=lambda c: c["median_age_rank_oldest"])
    assert youngest["median_age"] < oldest["median_age"]


def test_world_bank_health_merged(countries):
    ind = countries["IND"]
    assert ind["income_group"] == "Lower middle income"
    codes = {h["code"] for h in ind["health"]}
    assert "SP.DYN.LE00.IN" in codes
    for h in ind["health"]:
        assert h["year"] >= 2015 and 1 <= h["rank"] <= h["count"]
    years = [p["year"] for p in ind["life_expectancy_series"]]
    assert years == sorted(years) and years[0] == 1960


def test_world_bank_missing_countries_have_empty_lists(countries):
    # The World Bank publishes no figures for Taiwan; the tab shows a message instead.
    twn = countries["TWN"]
    assert twn["health"] == [] and twn["life_expectancy_series"] == []
    assert twn["income_group"] is None
    assert sum(bool(c["health"]) for c in countries.values()) == 216


def test_gdp_from_world_bank_with_year(countries):
    ind = countries["IND"]
    assert ind["gdp_year"] >= 2024 and ind["gdp_usd"] > 1e12
    assert ind["gdp_series"][0]["year"] == 1960
    assert countries["USA"]["gdp_rank"] == 1
    # Per-capita uses the same GDP figure.
    assert abs(ind["gdp_per_capita_usd"] - ind["gdp_usd"] / ind["population"]) < 1


def test_gdp_falls_back_to_original_csv(countries):
    # The World Bank has no Taiwan figures; GDP comes from countries.csv, without a year.
    twn = countries["TWN"]
    assert twn["gdp_usd"] > 0 and twn["gdp_year"] is None and twn["gdp_series"] == []


def test_parquet_has_every_column_the_api_lists():
    # Guards the deploy: code that lists a column must ship with a parquet that has it
    # (a missing column once took the whole API down on Vercel).
    from src.backend.app import SUMMARY_FIELDS

    columns = set(pq.read_schema(OUT_PARQUET).names)
    missing = [f for f in SUMMARY_FIELDS if f not in columns]
    assert not missing, f"Rebuild and commit data/countries.parquet; missing columns: {missing}"
