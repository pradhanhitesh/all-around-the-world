"""Extract the indicators we show from World Bank WDI bulk downloads.

The downloads stay out of the repo; this script writes small CSVs to data/raw/ that
build_data.py reads. It recognises each download by its contents:

Health topic (API_8_DS2_*, ~41 MB):
  worldbank_health.csv            iso3, indicator, year, value  (latest value since 2015)
  worldbank_life_expectancy.csv   iso3, year, value             (every year, for the chart)
  worldbank_income.csv            iso3, income_group

GDP, current US$ (API_NY.GDP.MKTP.CD_*):
  worldbank_gdp.csv               iso3, year, value             (every year, US$)

Usage:
    .venv/bin/python src/backend/extract_worldbank.py <download folder> [<download folder> ...]

Source: World Bank, World Development Indicators (CC BY 4.0).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"

# Indicators shown in the Health tab. Labels/units live in the frontend (health.js).
HEALTH_INDICATORS = [
    "SP.DYN.LE00.IN",  # Life expectancy at birth, total (years)
    "SP.DYN.LE00.FE.IN",  # Life expectancy, female
    "SP.DYN.LE00.MA.IN",  # Life expectancy, male
    "SP.DYN.IMRT.IN",  # Infant mortality (per 1,000 live births)
    "SH.STA.MMRT",  # Maternal mortality (per 100,000 live births)
    "SP.DYN.TFRT.IN",  # Fertility rate (births per woman)
    "SP.POP.65UP.TO.ZS",  # Population aged 65+ (%)
    "SH.MED.PHYS.ZS",  # Physicians (per 1,000)
    "SH.MED.NUMW.P3",  # Nurses and midwives (per 1,000)
    "SH.MED.BEDS.ZS",  # Hospital beds (per 1,000)
    "SH.XPD.CHEX.GD.ZS",  # Health expenditure (% of GDP)
    "SH.XPD.CHEX.PC.CD",  # Health expenditure per capita (current US$)
    "SH.IMM.MEAS",  # Measles immunization (% of children 12-23 months)
    "SH.H2O.BASW.ZS",  # Basic drinking water (% of population)
    "SH.STA.BASS.ZS",  # Basic sanitation (% of population)
    "SH.PRV.SMOK",  # Tobacco use (% of adults)
]
LIFE_EXPECTANCY = "SP.DYN.LE00.IN"
GDP = "NY.GDP.MKTP.CD"
MIN_YEAR = 2015  # older "latest" values are too stale to show


def find(folder: Path, prefix: str) -> Path:
    matches = sorted(folder.glob(f"{prefix}*.csv"))
    if not matches:
        sys.exit(f"No {prefix}*.csv in {folder}")
    return matches[0]


def load(folder: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = pd.read_csv(find(folder, "Metadata_Country_"))
    # Aggregates (regions, income groups, "World") have no income group; keep real countries only.
    meta = meta[meta["IncomeGroup"].notna()]
    # First 4 lines are a title block ("Data Source", "Last Updated Date").
    df = pd.read_csv(find(folder, "API_"), skiprows=4)
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    return df[df["Country Code"].isin(set(meta["Country Code"]))], meta


def to_long(df: pd.DataFrame) -> pd.DataFrame:
    years = [c for c in df.columns if c.isdigit()]
    long = df.melt(
        id_vars=["Country Code", "Indicator Code"], value_vars=years, var_name="year", value_name="value"
    ).dropna(subset=["value"])
    long = long.rename(columns={"Country Code": "iso3", "Indicator Code": "indicator"})
    long["year"] = long["year"].astype(int)
    return long


def write(df: pd.DataFrame, name: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    df.to_csv(path, index=False)
    print(f"{path.stat().st_size / 1024:7.1f} KB  {path.relative_to(ROOT)}")


def extract_gdp(folder: Path) -> None:
    df, _ = load(folder)
    gdp = to_long(df[df["Indicator Code"] == GDP])[["iso3", "year", "value"]].sort_values(["iso3", "year"])
    gdp["value"] = gdp["value"].round(0).astype("int64")
    write(gdp, "worldbank_gdp.csv")


def main(folder: Path) -> None:
    df, meta = load(folder)
    if GDP in set(df["Indicator Code"]):
        return extract_gdp(folder)
    df = df[df["Indicator Code"].isin(HEALTH_INDICATORS)]
    long = to_long(df)

    latest = (
        long[long["year"] >= MIN_YEAR]
        .sort_values("year")
        .groupby(["iso3", "indicator"], as_index=False)
        .last()
        .sort_values(["iso3", "indicator"])
    )
    latest["value"] = latest["value"].round(3)
    series = long[long["indicator"] == LIFE_EXPECTANCY][["iso3", "year", "value"]].sort_values(["iso3", "year"])
    series["value"] = series["value"].round(2)
    income = meta[["Country Code", "IncomeGroup"]].rename(
        columns={"Country Code": "iso3", "IncomeGroup": "income_group"}
    ).sort_values("iso3")

    write(latest, "worldbank_health.csv")
    write(series, "worldbank_life_expectancy.csv")
    write(income, "worldbank_income.csv")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        main(Path(arg).expanduser())
