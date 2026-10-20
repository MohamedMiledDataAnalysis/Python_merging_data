"""
merge_public_data.py
--------------------
Extract data from two public sources, build one DataFrame for each,
and merge them on one or several columns.

    Source 1  World Bank API (JSON)   GDP per capita, by country and year
    Source 2  Our World in Data (CSV) CO2 emissions per capita, by country and year

Both are free and need no API key.

Two merges are shown:
    1. On MULTIPLE columns: country_code + year
       -> one row per country and year, with GDP and CO2 side by side
    2. On ONE column: country_code
       -> each country's average CO2 attached to every GDP row

Install:  pip install requests pandas
Run:      python merge_public_data.py
Output:   merged_gdp_co2.csv
"""

import io

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
START_YEAR = 2010
END_YEAR = 2022

WORLD_BANK_URL = "https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD"
OWID_URL = ("https://ourworldindata.org/grapher/co-emissions-per-capita.csv"
            "?v=1&csvType=full&useColumnShortNames=false")

HEADERS = {"User-Agent": "merge-public-data/1.0"}   # identify the script to the servers
OUTPUT_FILE = "merged_gdp_co2.csv"


# ---------------------------------------------------------------------------
# 1. EXTRACT: source 1, World Bank (JSON)
# ---------------------------------------------------------------------------
def extract_world_bank() -> pd.DataFrame:
    """GDP per capita (current US$) for every country and year in the period."""
    print("[1/4] World Bank: GDP per capita")
    params = {"format": "json", "date": f"{START_YEAR}:{END_YEAR}", "per_page": 1000}
    records, page, pages = [], 1, 1

    # The API returns results page by page: keep asking until the last page.
    while page <= pages:
        response = requests.get(WORLD_BANK_URL, params={**params, "page": page},
                                headers=HEADERS, timeout=30)
        response.raise_for_status()
        # The response is a list of two items: [page information, list of records].
        info, rows = response.json()
        pages = info["pages"]
        records.extend(rows or [])
        page += 1

    # Keep only the fields needed, with clear column names.
    df = pd.DataFrame({
        "country_code": [r.get("countryiso3code") for r in records],
        "country_name": [(r.get("country") or {}).get("value") for r in records],
        "year": [r.get("date") for r in records],
        "gdp_per_capita": [r.get("value") for r in records],
    })
    print(f"      {len(df):,} rows received")
    return df


# ---------------------------------------------------------------------------
# 2. EXTRACT: source 2, Our World in Data (CSV)
# ---------------------------------------------------------------------------
def extract_owid() -> pd.DataFrame:
    """CO2 emissions per capita (tonnes) for every country and year."""
    print("[2/4] Our World in Data: CO2 emissions per capita")
    response = requests.get(OWID_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))

    # The CSV has the columns Entity, Code, Year and one value column.
    # The value column's name is long and may change, so take whichever column remains.
    value_column = [c for c in df.columns if c not in ("Entity", "Code", "Year")][0]
    df = df.rename(columns={
        "Entity": "country_name_owid",
        "Code": "country_code",
        "Year": "year",
        value_column: "co2_per_capita",
    })
    print(f"      {len(df):,} rows received (all available years)")
    return df


# ---------------------------------------------------------------------------
# 3. PREPARE: make the two DataFrames compatible before merging
# ---------------------------------------------------------------------------
def prepare(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Give the key columns the same type and format in both DataFrames.

    A merge only matches values that are exactly equal: the year "2015" (text)
    never matches 2015 (number), and "fra" never matches "FRA".
    """
    out = df.copy()
    out["country_code"] = out["country_code"].astype("string").str.strip().str.upper()
    out["year"] = pd.to_numeric(out["year"], errors="coerce").astype("Int64")

    # Rows without a key cannot be merged: drop them, and say how many.
    before = len(out)
    out = out.dropna(subset=["country_code", "year"])
    out = out[out["country_code"] != ""]
    # Our World in Data uses codes starting with OWID_ for regions (OWID_WRL = World).
    out = out[~out["country_code"].str.startswith("OWID_")]
    out = out[out["year"].between(START_YEAR, END_YEAR)]
    print(f"      {name}: {len(out):,} rows kept, {before - len(out):,} dropped "
          f"(no country code, a region, or outside {START_YEAR}-{END_YEAR})")
    return out.reset_index(drop=True)


def check_unique(df: pd.DataFrame, keys: list[str], name: str) -> None:
    """Stop if the key columns do not identify each row uniquely.

    Duplicated keys would multiply rows in the merge: 2 rows x 2 rows = 4 rows.
    """
    duplicates = df.duplicated(subset=keys, keep=False)
    if duplicates.any():
        sample = df.loc[duplicates, keys].drop_duplicates().head(5).to_dict("records")
        raise ValueError(f"{name}: {int(duplicates.sum())} rows share the same {keys}, e.g. {sample}")


# ---------------------------------------------------------------------------
# 4. MERGE
# ---------------------------------------------------------------------------
def merge_frames(left: pd.DataFrame, right: pd.DataFrame, on: list[str],
                 how: str = "inner", validate: str = "one_to_one") -> pd.DataFrame:
    """Merge two DataFrames on one or several columns and report the matching.

    on       : the key column(s), e.g. ["country_code"] or ["country_code", "year"]
    how      : "inner" keeps rows found in both; "left" keeps every left row;
               "right" keeps every right row; "outer" keeps all rows.
    validate : the expected relationship; pandas raises an error if the data
               breaks it. "one_to_one": each key at most once on each side.
               "many_to_one": keys may repeat on the left, but not on the right.
    """
    # First an outer merge with indicator=True: the _merge column says, for each
    # row, whether its key was found in both DataFrames, only left, or only right.
    full = pd.merge(left, right, on=on, how="outer", validate=validate, indicator=True)
    counts = full["_merge"].value_counts()
    print(f"      keys {on}: {counts['both']:,} matched, "
          f"{counts['left_only']:,} only in left, {counts['right_only']:,} only in right")

    # Show which values of the first key are unmatched: they often reveal a coding
    # difference between sources (Kosovo is XKX at the World Bank, OWID_KOS at OWID).
    for side in ("left_only", "right_only"):
        unmatched = full.loc[full["_merge"] == side, on[0]].astype(str).unique()
        if len(unmatched):
            more = f" (+{len(unmatched) - 8} more)" if len(unmatched) > 8 else ""
            print(f"      {on[0]} values {side}: {', '.join(sorted(unmatched)[:8])}{more}")

    # Then keep the rows required by `how`.
    keep = {"inner": ["both"], "left": ["both", "left_only"],
            "right": ["both", "right_only"], "outer": ["both", "left_only", "right_only"]}[how]
    return full[full["_merge"].isin(keep)].drop(columns="_merge").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    gdp = extract_world_bank()
    co2 = extract_owid()

    print("[3/4] Preparing the keys")
    gdp = prepare(gdp, "World Bank")
    co2 = prepare(co2, "Our World in Data")
    gdp = gdp.dropna(subset=["gdp_per_capita"])   # the newest years are often empty

    # --- Merge 1: on MULTIPLE columns -------------------------------------------
    keys = ["country_code", "year"]
    print(f"[4/4] Merging on {keys}")
    check_unique(gdp, keys, "World Bank")
    check_unique(co2, keys, "Our World in Data")
    merged = merge_frames(gdp, co2, on=keys, how="inner", validate="one_to_one")

    merged = merged[["country_code", "country_name", "year", "gdp_per_capita", "co2_per_capita"]]
    merged = merged.sort_values(keys).reset_index(drop=True)
    merged.to_csv(OUTPUT_FILE, index=False)
    print(f"\nMerged on {keys}: {len(merged):,} rows saved to {OUTPUT_FILE}")
    print(merged[merged["country_code"].isin(["FRA", "GBR", "USA"])].tail(6).to_string(index=False))

    correlation = merged["gdp_per_capita"].corr(merged["co2_per_capita"])
    print(f"\nCorrelation between GDP per capita and CO2 per capita: {correlation:.2f}")

    # --- Merge 2: on ONE column ----------------------------------------------------
    # One row per country on the right side: the average CO2 over the period.
    avg_co2 = (co2.groupby("country_code", as_index=False)["co2_per_capita"].mean()
                  .rename(columns={"co2_per_capita": "avg_co2_per_capita"}))
    print("\nMerging on ['country_code'] (average CO2 per country attached to each GDP row)")
    # many_to_one: a country appears in many GDP rows (one per year) but once in avg_co2.
    with_avg = merge_frames(gdp, avg_co2, on=["country_code"], how="left", validate="many_to_one")
    print(with_avg[with_avg["country_code"] == "FRA"].head(3).to_string(index=False))


if __name__ == "__main__":
    main()
