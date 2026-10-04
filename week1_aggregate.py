"""
Week 1 - Monthly Dataset Aggregation

Concatenates every monthly CRMLS file from January 2024 through the most
recently completed calendar month into two combined datasets (listings and
sold), filters both to PropertyType == 'Residential', and saves them as CSVs.

Input:  csv/CRMLSListing{YYYYMM}.csv
        csv/CRMLSSold{YYYYMM}.csv  or  csv/CRMLSSold{YYYYMM}_filled.csv
Output: output/combined_listings_residential.csv
        output/combined_sold_residential.csv
        output/run_report.txt   (coverage, file problems, row counts)

If any month is missing or any file looks damaged, the output name gets an
'_INCOMPLETE' suffix so it can't be mistaken for the full dataset.
"""

import csv
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "csv"
OUTPUT_DIR = BASE_DIR / "output"

START = date(2024, 1, 1)
# Most recently completed calendar month = the month before today's month
END = date.today().replace(day=1) - timedelta(days=1)

MAX_PROBLEMS_SHOWN = 10

report_lines = []


def report(line=""):
    """Print a line and keep it for output/run_report.txt."""
    print(line)
    report_lines.append(line)


def months_in_range(start, end):
    """Return 'YYYYMM' strings from start's month through end's month."""
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def find_monthly_file(prefix, ym):
    """Return the file for this month, preferring the '_filled' version if present."""
    for name in (f"{prefix}{ym}_filled.csv", f"{prefix}{ym}.csv"):
        path = DATA_DIR / name
        if path.exists():
            return path
    return None


def check_file_structure(path):
    """
    Look for signs of a damaged file without changing anything.
    Returns (problems, notes):
      problems - rows with fewer fields than the header, so the file is damaged
      notes    - harmless details worth knowing, e.g. no newline after the last row
    Raises ValueError for files pandas can't load as-is (empty, extra fields, not UTF-8).
    """
    if path.stat().st_size == 0:
        raise ValueError(f"{path.name} is empty (0 bytes). Download it again.")

    problems = []
    try:
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            n_header = len(next(reader))
            for row in reader:
                if len(row) > n_header:
                    # pandas can't load this row without dropping or editing values
                    raise ValueError(
                        f"{path.name} line {reader.line_num} has {len(row)} fields but the "
                        f"header has {n_header}. Fix or re-download this file."
                    )
                if len(row) < n_header:
                    problems.append(
                        f"line {reader.line_num} has {len(row)} of {n_header} fields "
                        f"(kept; the missing fields will be blank)"
                    )
    except UnicodeDecodeError:
        raise ValueError(
            f"{path.name} is not UTF-8 text. Re-download it with encoding='utf-8' "
            f"in the fetch script's open() call."
        )

    # A missing final newline is valid CSV, so it's only a note. A row cut off
    # mid-download shows up above as a row with too few fields.
    notes = []
    with open(path, "rb") as f:
        f.seek(-1, 2)
        if f.read(1) != b"\n":
            notes.append("no newline after the last row (not damage on its own)")
    return problems, notes


def same_values(a, b):
    """True when two columns match in every row, counting blank == blank as a match."""
    return bool(((a == b) | (a.isna() & b.isna())).all())


def drop_identical_duplicates(df):
    """
    The fetch script wrote some fields twice; pandas renames the second copy
    'Name.1'. Drop a copy only if it matches the original in every row.
    Returns (df, dropped_columns, kept_columns).
    """
    dropped, kept = [], []
    for col in df.columns:
        match = re.fullmatch(r"(.+)\.\d+", col)
        if match is None or match.group(1) not in df.columns:
            continue
        if same_values(df[col], df[match.group(1)]):
            dropped.append(col)
        else:
            kept.append(col)
    return df.drop(columns=dropped), dropped, kept


def combine(prefix):
    """
    Load every available monthly file for `prefix` and concatenate them.
    Returns (combined, missing_months, damaged_files).
    """
    frames, missing, damaged = [], [], []
    rows_before = 0

    for ym in months_in_range(START, END):
        path = find_monthly_file(prefix, ym)
        if path is None:
            missing.append(ym)
            continue

        problems, notes = check_file_structure(path)
        df = pd.read_csv(path, low_memory=False)
        if "PropertyType" not in df.columns:
            raise ValueError(
                f"{path.name} has no 'PropertyType' column, so it can't be filtered "
                f"to Residential. Check the file's header row."
            )
        df, dropped, kept = drop_identical_duplicates(df)

        report(f"  {path.name:32} {len(df):>8,} rows")
        for note in notes:
            report(f"    Note: {note}")
        if kept:
            report(f"    Duplicate columns kept because values differ from the original: {', '.join(kept)}")
        if problems:
            damaged.append(path.name)
            report(f"    WARNING - possible damage in {path.name}:")
            for problem in problems[:MAX_PROBLEMS_SHOWN]:
                report(f"      - {problem}")
            if len(problems) > MAX_PROBLEMS_SHOWN:
                report(f"      ... and {len(problems) - MAX_PROBLEMS_SHOWN} more")

        rows_before += len(df)
        frames.append(df)

    if not frames:
        raise FileNotFoundError(
            f"No {prefix} files found in {DATA_DIR} for {START:%Y-%m} through {END:%Y-%m}."
        )

    found = len(frames)
    total = found + len(missing)
    report(f"  Months found: {found} of {total}")
    if missing:
        report(f"  Missing months ({len(missing)}): {', '.join(missing)}")

    # Months have slightly different column sets; concat keeps every column
    # and leaves it blank for months that didn't have it.
    combined = pd.concat(frames, ignore_index=True)
    report(f"  Rows before concat (sum of monthly files): {rows_before:,}")
    report(f"  Rows after concat:                         {len(combined):,}")
    if len(combined) != rows_before:
        raise RuntimeError("Row count changed during concat")
    return combined, missing, damaged


def filter_residential(df):
    residential = df[df["PropertyType"] == "Residential"]
    report(f"  Rows before Residential filter:            {len(df):,}")
    report(f"  Rows after Residential filter:             {len(residential):,}")
    return residential


def save(df, label, complete):
    """
    Write the dataset to a temporary file and read it back to confirm the row
    count and PropertyType. Only then replace results from earlier runs.
    """
    suffix = "" if complete else "_INCOMPLETE"
    path = OUTPUT_DIR / f"combined_{label}_residential{suffix}.csv"
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_csv(tmp, index=False)
        saved = pd.read_csv(tmp, usecols=["PropertyType"])
        if len(saved) != len(df) or not (saved["PropertyType"] == "Residential").all():
            raise RuntimeError(f"{path.name} didn't save correctly; earlier results were left in place")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    # Remove earlier results (e.g. an old _INCOMPLETE file) so they can't be mistaken for this one
    for old in OUTPUT_DIR.glob(f"combined_{label}_residential*.csv"):
        if old != path:
            old.unlink()
    os.replace(tmp, path)
    report(f"  Saved {path.name}: {len(saved):,} rows, all PropertyType == 'Residential' (checked)")


def process(label, prefix):
    report(f"\n{label.upper()}")
    combined, missing, damaged = combine(prefix)
    residential = filter_residential(combined)
    complete = not missing and not damaged
    save(residential, label, complete)
    if complete:
        report("  STATUS: ALL MONTHS PRESENT - every monthly file found and readable")
        report("          (file coverage only; this doesn't prove the source data itself is complete)")
    else:
        reasons = []
        if missing:
            reasons.append(f"{len(missing)} missing month(s)")
        if damaged:
            reasons.append(f"damaged file(s): {', '.join(damaged)}")
        report(f"  STATUS: INCOMPLETE - {'; '.join(reasons)}")


def main():
    if not DATA_DIR.is_dir():
        raise FileNotFoundError(f"Input folder not found: {DATA_DIR}. Put the monthly CRMLS CSV files there.")
    OUTPUT_DIR.mkdir(exist_ok=True)
    report(f"Required coverage: {START:%Y-%m} through {END:%Y-%m} ({len(months_in_range(START, END))} months)")

    # ---- Listings -----------------------------------------------------------
    # Run on 2026-10-03 (required range 2024-01 .. 2026-09), 33 of 33 months found:
    #   Rows before concat (sum of monthly files): 1,046,606
    #   Rows after concat:                         1,046,606
    #   Rows before Residential filter:            1,046,606
    #   Rows after Residential filter:             665,579
    #   Saved as combined_listings_residential.csv (665,579 rows)
    process("listings", "CRMLSListing")

    # ---- Sold ---------------------------------------------------------------
    # Run on 2026-10-03 (required range 2024-01 .. 2026-09), 33 of 33 months found:
    #   Rows before concat (sum of monthly files): 736,168
    #   Rows after concat:                         736,168
    #   Rows before Residential filter:            736,168
    #   Rows after Residential filter:             495,070
    #   Saved as combined_sold_residential.csv (495,070 rows)
    process("sold", "CRMLSSold")

    report_path = OUTPUT_DIR / "run_report.txt"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as err:
        sys.exit(f"ERROR: {err}")
