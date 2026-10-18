"""
Weeks 2-3 (continued) - Mortgage Rate Enrichment

Adds the national 30-year fixed mortgage rate (FRED series MORTGAGE30US,
published weekly by Freddie Mac) to both Week 1 combined datasets:

  1. Fetches MORTGAGE30US directly from FRED as a CSV (no API key needed).
  2. Averages the weekly rates by calendar month.
  3. Builds a year_month key on each dataset: CloseDate for sold,
     ListingContractDate for listings.
  4. Left-merges the monthly rate onto each dataset.
  5. Validates the merge: every row has a rate, and no row was added or lost.
     A dataset that fails is not saved.
  6. Saves both enriched datasets as new CSVs, plus the weekly observations
     used to calculate the monthly averages.

Input:  output/combined_sold_residential.csv      (Week 1)
        output/combined_listings_residential.csv  (Week 1)
Output: output/mortgage_rates/
          mortgage30us_weekly.csv    weekly observations used to calculate monthly averages
          mortgage30us_monthly.csv   monthly average rate and the number of weekly readings
          sold_with_rates.csv        sold dataset + year_month + rate_30yr_fixed
          listings_with_rates.csv    listings dataset + year_month + rate_30yr_fixed

Requires:
  - pandas and requests
  - week1_aggregate.py in the same folder (this script imports OUTPUT_DIR from it)
  - both Week 1 combined CSVs listed under Input (run week1_aggregate.py first)
  - an internet connection, to fetch the series from FRED

The outputs are saved locally under output/mortgage_rates/, which is git-ignored,
so the enriched CSVs are not in the repository. Submit them separately if required.
"""

import io
import os
import sys
from datetime import datetime

import pandas as pd
import requests

from week1_aggregate import OUTPUT_DIR

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US"
OUT_DIR = OUTPUT_DIR / "mortgage_rates"

# name: (Week 1 combined file, date column the year_month key comes from)
DATASETS = {
    "sold": (OUTPUT_DIR / "combined_sold_residential.csv", "CloseDate"),
    "listings": (OUTPUT_DIR / "combined_listings_residential.csv", "ListingContractDate"),
}
PREVIEW_COLUMNS = {
    "sold": ["CloseDate", "year_month", "ClosePrice", "rate_30yr_fixed"],
    "listings": ["ListingContractDate", "year_month", "ListPrice", "rate_30yr_fixed"],
}


class ValidationError(Exception):
    """The merge left rows without a rate, or changed the row count."""


# ---- Step 1: fetch ---------------------------------------------------------------

def fetch_mortgage_rates():
    """Download MORTGAGE30US from FRED: one row per week, rate in percent."""
    try:
        response = requests.get(FRED_URL, timeout=60)
        response.raise_for_status()
    except requests.RequestException as err:
        raise ConnectionError(f"Could not download {FRED_URL} ({type(err).__name__}). "
                              "Check the internet connection and try again.") from None
    mortgage = pd.read_csv(io.StringIO(response.text))
    if list(mortgage.columns) != ["observation_date", "MORTGAGE30US"]:
        raise ValueError(f"FRED returned unexpected columns: {list(mortgage.columns)}")
    mortgage.columns = ["date", "rate_30yr_fixed"]
    mortgage["date"] = pd.to_datetime(mortgage["date"], format="%Y-%m-%d")
    # A week without a reading comes through as a blank (or "."), so make it NaN
    mortgage["rate_30yr_fixed"] = pd.to_numeric(mortgage["rate_30yr_fixed"], errors="coerce")
    return mortgage


# ---- Step 2: weekly -> monthly -------------------------------------------------------

def monthly_averages(mortgage):
    """Average the weekly readings in each calendar month (weeks without a reading are skipped)."""
    weekly = mortgage.dropna(subset=["rate_30yr_fixed"]).copy()
    weekly["year_month"] = weekly["date"].dt.to_period("M")
    return (weekly.groupby("year_month")["rate_30yr_fixed"]
            .agg(rate_30yr_fixed="mean", weekly_readings="size")
            .reset_index())


# ---- Steps 3-5: key, merge, validate ------------------------------------------------

def enrich(name, path, date_col, mortgage_monthly):
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run week1_aggregate.py first.")
    df = pd.read_csv(path, low_memory=False)

    # Step 3: year_month key from the transaction date
    dates = pd.to_datetime(df[date_col], format="%Y-%m-%d", errors="coerce")
    df["year_month"] = dates.dt.to_period("M")

    # Step 4: left merge; many rows per month, exactly one rate per month
    merged = df.merge(mortgage_monthly[["year_month", "rate_30yr_fixed"]],
                      on="year_month", how="left", validate="many_to_one")

    # Step 5: validate
    no_date = int(dates.isna().sum())
    no_rate = merged["rate_30yr_fixed"].isna()
    months = merged["year_month"].dropna()
    print(f"\n{name}: {len(df):,} rows, year_month from {date_col}")
    print(f"  months covered: {months.min()} to {months.max()} ({months.nunique()} months)")
    print(f"  rows before merge: {len(df):,} | after: {len(merged):,}")
    print(f"  rows without a usable {date_col}: {no_date:,}")
    print(f"  null rate_30yr_fixed after merge: {int(no_rate.sum()):,}")
    if len(merged) != len(df):
        raise ValidationError(f"{name}: the merge changed the row count")
    if no_rate.any():
        unmatched = merged.loc[no_rate, "year_month"].value_counts(dropna=False).head(10)
        raise ValidationError(f"{name}: {int(no_rate.sum()):,} rows have no rate. Missing dates: "
                              f"{no_date:,}; months without a FRED rate: {unmatched.to_dict()}. "
                              "Nothing was saved for this dataset.")
    print("  validation passed: every row has a rate and no row was added or lost")
    return merged


def save_checked(df, path):
    """Write to a temporary file, reload it to confirm rows and rates, then put it in place."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_csv(tmp, index=False)
        check = pd.read_csv(tmp, usecols=["year_month", "rate_30yr_fixed"])
        if len(check) != len(df) or check["rate_30yr_fixed"].isna().any():
            raise ValidationError(f"{path.name} didn't save correctly; any earlier copy was left in place")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    print(f"  saved {path.name}: {len(check):,} rows x {df.shape[1]} columns (reloaded and checked)")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    mortgage = fetch_mortgage_rates()
    print(f"Fetched MORTGAGE30US from FRED at {datetime.now():%Y-%m-%d %H:%M}: "
          f"{len(mortgage):,} weekly readings, {mortgage['date'].min():%Y-%m-%d} to "
          f"{mortgage['date'].max():%Y-%m-%d} ({int(mortgage['rate_30yr_fixed'].isna().sum())} blank)")
    mortgage.to_csv(OUT_DIR / "mortgage30us_weekly.csv", index=False)

    mortgage_monthly = monthly_averages(mortgage)
    mortgage_monthly.to_csv(OUT_DIR / "mortgage30us_monthly.csv", index=False)
    print(f"Monthly averages: {len(mortgage_monthly):,} months")

    used_months = set()
    for name, (path, date_col) in DATASETS.items():
        merged = enrich(name, path, date_col, mortgage_monthly)
        print(merged[PREVIEW_COLUMNS[name]].head().to_string(index=False))
        save_checked(merged, OUT_DIR / f"{name}_with_rates.csv")
        used_months |= set(merged["year_month"].dropna())
        del merged  # free memory before loading the next dataset

    used = mortgage_monthly[mortgage_monthly["year_month"].isin(used_months)]
    print(f"\nMonthly rates used ({len(used)} months; weekly readings per month "
          f"{used['weekly_readings'].min()} to {used['weekly_readings'].max()}):")
    print(used.assign(rate_30yr_fixed=used["rate_30yr_fixed"].round(3)).to_string(index=False))


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, ConnectionError, ValidationError) as err:
        sys.exit(f"ERROR: {err}")
