# Data sources

The CSV files listed here are **not committed** (`data/raw/*.csv` is gitignored). Only the built
`data/countries.parquet` is in the repo; place the CSVs here to rebuild it with `build_data.py`.

| File | Source | License |
|---|---|---|
| `countries.csv` | Countries dataset (ISO codes, capitals, currency, population, GDP, timezones, Wikidata IDs) | See the original publisher's terms |
| `worldbank_health.csv`, `worldbank_life_expectancy.csv`, `worldbank_income.csv` | [World Bank, World Development Indicators](https://data.worldbank.org/) (Health topic, updated 2026-10-08), extracted by `src/backend/extract_worldbank.py` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — attribution required |
| `worldbank_gdp.csv` | [World Bank, World Development Indicators](https://data.worldbank.org/indicator/NY.GDP.MKTP.CD) — GDP (current US$), 1960–2025, extracted by `src/backend/extract_worldbank.py` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `simplemaps_countries.csv` | [SimpleMaps Basic World Countries Database](https://simplemaps.com/data/countries) v1.1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — attribution required |

From SimpleMaps we use only fields the main dataset lacks: primary language, largest religion,
median age, driving side, UN membership and the official government website.

From the World Bank we keep 16 health indicators (latest value since 2015, with its year), the
full life-expectancy series since 1960, and each country's income group. To refresh, download
the WDI Health topic CSV and run `extract_worldbank.py <folder>`, then `build_data.py`. The same script handles the GDP download (`API_NY.GDP.MKTP.CD_*`):
GDP comes from the World Bank where available and falls back to `countries.csv` (Taiwan).
