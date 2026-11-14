"""Extract World Happiness Report data (Figure 2.1 workbook) to data/raw/whr_happiness.csv.

The workbook stays out of the repo; build_data.py reads the CSV (also gitignored) and matches
WHR country names to our ISO3 codes.

Usage:
    .venv/bin/python src/backend/extract_whr.py ~/Downloads/WHR26_Data_Figure_2.1.xlsx

Source: World Happiness Report 2026 (Gallup World Poll life evaluations), Figure 2.1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "whr_happiness.csv"

COLUMNS = {
    "Year": "year",
    "Rank": "rank",
    "Country name": "country",
    "Life evaluation (3-year average)": "score",
    "Lower whisker": "lower",
    "Upper whisker": "upper",
    "Explained by: Log GDP per capita": "gdp",
    "Explained by: Social support": "social_support",
    "Explained by: Healthy life expectancy": "healthy_life",
    "Explained by: Freedom to make life choices": "freedom",
    "Explained by: Generosity": "generosity",
    "Explained by: Perceptions of corruption": "corruption",
    "Dystopia + residual": "dystopia_residual",
}


def main(path: Path) -> None:
    df = pd.read_excel(path)  # first sheet: "Data for Figure 2.1 (2011–2025)"
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        sys.exit(f"Unexpected workbook layout; missing columns: {sorted(missing)}")
    df = df[list(COLUMNS)].rename(columns=COLUMNS).dropna(subset=["country", "year", "score"])
    df["year"] = df["year"].astype(int)
    df["rank"] = df["rank"].astype("Int64")
    df = df.sort_values(["country", "year"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    years = sorted(df["year"].unique())
    print(f"Wrote {len(df)} rows ({df['country'].nunique()} countries, {years[0]}-{years[-1]}) -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]).expanduser())
