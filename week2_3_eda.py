"""
Weeks 2-3 - Dataset Structuring and Validation (sold transactions)

Loads every monthly CRMLS sold file from January 2024 through the most recently
completed calendar month (the same files week1_aggregate.py selects), then:

  1. Describes the dataset: rows, columns, data types, market vs metadata fields.
  2. Documents every PropertyType value (count and share) and applies the filter
     PropertyType == 'Residential'.
  3. Builds a null-count table for every column, flags columns with more than
     90% missing values, and decides keep or drop (core fields are always kept).
     It also counts values that may stand in for missing data, such as zeros.
  4. Summarises nine numeric fields (min, max, mean, median, percentiles,
     skewness), draws a histogram + boxplot for each, and flags impossible values
     and values beyond review thresholds.
  5. Answers the handbook's EDA questions, stating which sales each answer uses.
  6. Saves the filtered dataset as a new CSV, then reloads it to check it.

Only non-Residential rows and columns more than 90% missing are removed. Flagged
rows stay in the saved dataset and are listed in review_flags.csv for the
cleaning step. An EDA answer that leaves some values out says which, and how many.

Input:  csv/CRMLSSold{YYYYMM}.csv or csv/CRMLSSold{YYYYMM}_filled.csv
Output: output/week2_3/
          sold_residential_filtered.csv   the filtered dataset (deliverable)
          column_summary.csv              null-count table: count, %, >90% flag, decision
          possible_hidden_missing.csv     values that may stand in for missing data
          numeric_summary.csv             distribution summary and review thresholds
          county_median_prices.csv        median close price per county
          review_flags.csv                rows flagged for the cleaning step
          figures/<field>.png             histogram + boxplot per numeric field
          eda_report.md                   all of the above as a readable report

Requires pandas and matplotlib.
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")  # write PNG files without opening a window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, MaxNLocator

from week1_aggregate import (END, OUTPUT_DIR, START, check_file_structure,
                             drop_identical_duplicates, find_monthly_file, months_in_range)

PREFIX = "CRMLSSold"
OUT_DIR = OUTPUT_DIR / "week2_3"
FIG_DIR = OUT_DIR / "figures"
WEEK1_SOLD = OUTPUT_DIR / "combined_sold_residential.csv"

MISSING_THRESHOLD = 90.0   # a column is flagged when MORE than this % of its values are missing
MIN_COUNTY_SALES = 100     # counties with fewer sales are left out of the price ranking
PERCENTILES = [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
CENTRAL_RANGE = (0.01, 0.99)  # skewness is also measured on values between these percentiles

# Market analysis fields describe what sold, where, when and for how much.
# Metadata fields identify the record or describe agents, offices and systems.
FIELD_GROUPS = {
    "market: price": [
        "ClosePrice", "ListPrice", "OriginalListPrice", "AssociationFee",
        "AssociationFeeFrequency", "TaxAnnualAmount", "TaxYear"],
    "market: timing": [
        "CloseDate", "ListingContractDate", "PurchaseContractDate",
        "ContractStatusChangeDate", "DaysOnMarket"],
    "market: property": [
        "PropertyType", "PropertySubType", "LivingArea", "BuildingAreaTotal",
        "AboveGradeFinishedArea", "BelowGradeFinishedArea", "LotSizeAcres",
        "LotSizeSquareFeet", "LotSizeArea", "LotSizeDimensions", "BedroomsTotal",
        "MainLevelBedrooms", "BathroomsTotalInteger", "YearBuilt", "NewConstructionYN",
        "Stories", "Levels", "GarageSpaces", "CoveredSpaces", "ParkingTotal",
        "AttachedGarageYN", "PoolPrivateYN", "ViewYN", "WaterfrontYN", "BasementYN",
        "FireplaceYN", "FireplacesTotal", "Flooring", "BuilderName"],
    "market: location": [
        "City", "CountyOrParish", "StateOrProvince", "PostalCode", "Latitude", "Longitude",
        "MLSAreaMajor", "SubdivisionName", "ElementarySchool", "ElementarySchoolDistrict",
        "MiddleOrJuniorSchool", "MiddleOrJuniorSchoolDistrict", "HighSchool",
        "HighSchoolDistrict"],
    "metadata: identifier": [
        "ListingKey", "ListingKeyNumeric", "ListingId", "UnparsedAddress", "StreetNumberNumeric"],
    "metadata: status": ["MlsStatus"],
    "metadata: agent/office": [
        "ListAgentFirstName", "ListAgentLastName", "ListAgentFullName", "ListAgentEmail",
        "ListAgentAOR", "ListOfficeName", "CoListAgentFirstName", "CoListAgentLastName",
        "CoListOfficeName", "BuyerAgentFirstName", "BuyerAgentLastName", "BuyerAgentMlsId",
        "BuyerAgentAOR", "BuyerOfficeName", "BuyerOfficeAOR", "CoBuyerAgentFirstName"],
    "metadata: transaction terms": [
        "BuyerAgencyCompensation", "BuyerAgencyCompensationType", "BusinessType"],
    "metadata: system/processing": [
        "OriginatingSystemName", "OriginatingSystemSubName", "latfilled", "lonfilled",
        "SourceFile"],
}
COLUMN_GROUP = {col: group for group, cols in FIELD_GROUPS.items() for col in cols}

# Core analysis fields: always kept, even above the missing-value threshold
CORE_FIELDS = [
    "ListingKey", "SourceFile", "CloseDate", "ListingContractDate", "PurchaseContractDate",
    "ClosePrice", "ListPrice", "OriginalListPrice", "DaysOnMarket", "PropertyType",
    "PropertySubType", "LivingArea", "LotSizeAcres", "BedroomsTotal",
    "BathroomsTotalInteger", "YearBuilt", "City", "CountyOrParish", "PostalCode",
    "Latitude", "Longitude"]

# impossible: (rule, test) - values that cannot be right for the field.
# review:     an extra review threshold (rule, test) chosen for this project: values
#             beyond it are unusual and worth checking, not proven errors.
# scale:      how the 3 x IQR review thresholds are measured (see review_thresholds).
# low:        whether unusually LOW values are checked. Not where small values are
#             normal (0 bedrooms, 0 days on market, tiny condo lots).
# plot:       percentile range drawn in the histogram (values outside are counted, not drawn).
ABOVE_ZERO = ("must be above 0", lambda s: s <= 0)
NOT_NEGATIVE = ("cannot be negative", lambda s: s < 0)
DEFAULT_PLOT_RANGE = (0.005, 0.995)
NUMERIC_FIELDS = {
    "ClosePrice": dict(label="Final sale price", unit="usd", impossible=ABOVE_ZERO,
                       scale="log", low=True),
    "ListPrice": dict(label="List price at sale", unit="usd", impossible=ABOVE_ZERO,
                      scale="log", low=True),
    "OriginalListPrice": dict(label="First list price", unit="usd", impossible=ABOVE_ZERO,
                              scale="log", low=True),
    "LivingArea": dict(label="Living area", unit="sqft", impossible=ABOVE_ZERO,
                       scale="log", low=True),
    "LotSizeAcres": dict(label="Lot size", unit="acres", impossible=NOT_NEGATIVE,
                         scale="log", low=False, plot=(0.0, 0.95)),
    "BedroomsTotal": dict(label="Bedrooms", unit="count", impossible=NOT_NEGATIVE,
                          scale="log", low=False, plot=(0.0, 0.999)),
    "BathroomsTotalInteger": dict(label="Bathrooms", unit="count", impossible=NOT_NEGATIVE,
                                  scale="log", low=False, plot=(0.0, 0.999)),
    "DaysOnMarket": dict(label="Days on market", unit="days", impossible=NOT_NEGATIVE,
                         scale="log", low=False,
                         review=("over 3,650 days (10 years)", lambda s: s > 3650)),
    "YearBuilt": dict(label="Year built", unit="year", impossible=None, scale="linear",
                      low=True),
}
DELIVERABLE_FIELDS = ["ClosePrice", "LivingArea", "DaysOnMarket"]
UNIT_TEXT = {"usd": "US dollars", "sqft": "square feet", "acres": "acres", "count": "count",
             "days": "days", "year": "year"}

# Values a null count doesn't catch but that may mean "missing" (counted, not changed)
ZERO_NOTES = {
    "LivingArea": "also counted as an impossible value (living area must be above 0)",
    "LotSizeAcres": "0 may mean no separate lot (common for condos) or not recorded",
    "BedroomsTotal": "0 may mean a studio or not recorded",
    "BathroomsTotalInteger": "0 may mean none or not recorded",
}
NON_SPECIFIC_FIELDS = ["City", "CountyOrParish", "MLSAreaMajor", "SubdivisionName",
                       "ElementarySchool", "MiddleOrJuniorSchool", "HighSchool",
                       "HighSchoolDistrict"]
NON_SPECIFIC_VALUES = {"other", "unknown", "not applicable", "see remarks", "none", "n/a",
                       "na", "tbd"}

# Residential subtypes that are not dwellings; flagged for the cleaning step, not removed
NOT_A_HOME_SUBTYPES = ["BoatSlip", "DeededParking", "Timeshare"]

DATE_FIELDS = ["ListingContractDate", "PurchaseContractDate", "CloseDate"]
DATE_ORDER_RULES = [  # (earlier, later): the later date should not come before the earlier one
    ("ListingContractDate", "PurchaseContractDate"),
    ("PurchaseContractDate", "CloseDate"),
    ("ListingContractDate", "CloseDate"),
]

# Chart colours (dataviz reference palette, light surface; series slot 1)
SURFACE, SERIES, SERIES_LIGHT = "#fcfcfb", "#2a78d6", "#9ec5f4"
INK, INK_2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

report_lines = []


# ---- Report helpers ----------------------------------------------------------

def report(line=""):
    """Print a line and keep it for eda_report.md."""
    print(line)
    report_lines.append(line)


def heading(title, level=2):
    report()
    report(f"{'#' * level} {title}")
    report()


def table(df):
    """Add a DataFrame to the report as a Markdown table (index becomes the first column)."""
    df = df.reset_index()
    report("| " + " | ".join(str(c) for c in df.columns) + " |")
    report("|" + "|".join("---" for _ in df.columns) + "|")
    for row in df.itertuples(index=False):
        report("| " + " | ".join("(blank)" if pd.isna(v) else str(v) for v in row) + " |")


def fmt_value(value, unit):
    """Format a number in its field's natural unit."""
    if value is None or pd.isna(value):
        return ""
    if unit == "usd":
        return f"${value:,.0f}"
    if unit == "year":
        return f"{value:.0f}"
    if unit == "acres":
        return f"{value:,.2f}"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def pct(part, whole):
    return f"{part / whole * 100:.2f}%" if whole else "n/a"


def flag_rows(df, mask, category, field, values, detail):
    """
    Rows matching `mask`, in the long format of review_flags.csv. RowNumber is the
    row's position in sold_residential_filtered.csv (1 = first data row); it is the
    reliable row id because a ListingKey can appear in more than one row.
    """
    if not mask.any():
        return None
    out = df.loc[mask, ["ListingKey", "SourceFile", "CloseDate"]].copy()
    out.insert(0, "RowNumber", out.index + 1)
    out["category"] = category
    out["field"] = field
    out["value"] = values[mask]
    out["detail"] = detail
    return out


# ---- 1. Load -------------------------------------------------------------------

def load_sold():
    """
    Load every monthly sold file in the coverage period, choosing files the same
    way Week 1 does (a _filled file wins over a plain one for the same month).
    Adds a SourceFile column so each row can be traced to its file.
    """
    frames, columns_per_file, missing, damaged = [], {}, [], []
    for ym in months_in_range(START, END):
        path = find_monthly_file(PREFIX, ym)
        if path is None:
            missing.append(ym)
            continue
        problems, _ = check_file_structure(path)
        if problems:
            damaged.append(f"{path.name}: {problems[0]}")
        df = pd.read_csv(path, low_memory=False)
        df, _, _ = drop_identical_duplicates(df)
        columns_per_file[path.name] = set(df.columns)
        df["SourceFile"] = path.name
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No {PREFIX} files found for {START:%Y-%m} through {END:%Y-%m}.")
    return pd.concat(frames, ignore_index=True), columns_per_file, missing, damaged


# ---- 2. Property types and the Residential filter --------------------------------

def filter_residential(sold):
    """Document every PropertyType value, then keep only exact 'Residential' rows."""
    heading("3. Property types and filtering logic")
    types = sold["PropertyType"].value_counts(dropna=False)
    types_table = pd.DataFrame({"rows": types.map("{:,}".format),
                                "share": [pct(n, len(sold)) for n in types]})
    types_table.index.name = "PropertyType"
    report(f"Unique PropertyType values before filtering: {types.size}, across {len(sold):,} "
           "rows (shares are of all rows).")
    report()
    table(types_table)

    normalized = sold["PropertyType"].astype("string").str.strip().str.lower()
    near_miss = int(((normalized == "residential").fillna(False)
                     & (sold["PropertyType"] != "Residential")).sum())
    res = sold[sold["PropertyType"] == "Residential"].reset_index(drop=True)
    report()
    report("Filter: `sold[sold['PropertyType'] == 'Residential']`, an exact, case-sensitive "
           "match. Every other type is removed.")
    report(f"- Values that differ from 'Residential' only by case or spaces (the exact match "
           f"would miss them): {near_miss}")
    report(f"- Rows with a blank PropertyType: {int(sold['PropertyType'].isna().sum())}")
    report(f"- Rows before the filter: {len(sold):,}")
    report(f"- Rows after the filter: {len(res):,} ({pct(len(res), len(sold))} kept; "
           f"{len(sold) - len(res):,} removed)")
    if WEEK1_SOLD.exists():
        week1_rows = len(pd.read_csv(WEEK1_SOLD, usecols=["PropertyType"]))
        verdict = "matches" if week1_rows == len(res) else "DIFFERS from"
        report(f"- Cross-check: {verdict} the Week 1 output ({week1_rows:,} rows)")
    report()
    subtypes = res["PropertySubType"].value_counts(dropna=False)
    sub_table = pd.DataFrame({"rows": subtypes.map("{:,}".format),
                              "share": [pct(n, len(res)) for n in subtypes]})
    sub_table.index.name = "PropertySubType (Residential rows)"
    table(sub_table)
    return res


# ---- 3. Missing values ---------------------------------------------------------

def column_summary(df, columns_per_file):
    """
    One row per column: null count and %, whether it is over the threshold, the
    share of rows whose source file doesn't have the column at all, and the
    keep/drop decision with its reason.
    """
    rows_per_file = df["SourceFile"].value_counts()
    rows = []
    for col in df.columns:
        nulls = int(df[col].isna().sum())
        null_pct = nulls / len(df) * 100
        absent = sum(n for f, n in rows_per_file.items()
                     if col != "SourceFile" and col not in columns_per_file[f])
        over = null_pct > MISSING_THRESHOLD
        core = col in CORE_FIELDS
        if over and core:
            decision, reason = "keep", f"core field, kept despite {null_pct:.2f}% missing"
        elif over:
            decision, reason = "drop", f"{null_pct:.2f}% missing, over the {MISSING_THRESHOLD:g}% threshold"
        else:
            decision, reason = "keep", f"{null_pct:.2f}% missing, not over the {MISSING_THRESHOLD:g}% threshold"
        rows.append({
            "column": col, "group": COLUMN_GROUP.get(col, "unclassified"), "core_field": core,
            "dtype": str(df[col].dtype), "non_null": len(df) - nulls, "null_count": nulls,
            "null_pct": round(null_pct, 2), "absent_from_file_pct": round(absent / len(df) * 100, 2),
            "unique_values": int(df[col].nunique()), "over_90pct_missing": over,
            "decision": decision, "reason": reason,
        })
    summary = pd.DataFrame(rows).set_index("column").sort_index()
    return summary.sort_values("null_count", ascending=False, kind="stable")


def possible_hidden_missing(df):
    """
    Values a null count doesn't catch but that may mean "missing". They are only
    counted: whether they really mean missing is not documented in the data.
    """
    rows, flags = [], []
    single_family = df["PropertySubType"] == "SingleFamilyResidence"

    zero_coords = (df["Latitude"] == 0) & (df["Longitude"] == 0)
    rows.append({"field": "Latitude and Longitude", "value": "both 0",
                 "rows": int(zero_coords.sum()),
                 "note": "impossible for a California address (0, 0 is in the Atlantic); flagged"})
    flags.append(flag_rows(df, zero_coords, "impossible value", "Latitude/Longitude",
                           df["Latitude"].astype(str) + ", " + df["Longitude"].astype(str),
                           "0, 0 is not in California"))

    for field, note in ZERO_NOTES.items():
        zero = df[field] == 0
        rows.append({"field": field, "value": "0", "rows": int(zero.sum()),
                     "note": f"{note}; {int((zero & single_family).sum()):,} on single-family homes"})

    for field in NON_SPECIFIC_FIELDS:
        text = df[field].dropna().astype(str).str.strip()
        hit = text.str.lower().isin(NON_SPECIFIC_VALUES)
        if hit.any():
            found = text[hit].value_counts()
            blank = int(df[field].isna().sum())
            rows.append({"field": field,
                         "value": ", ".join(f"{k} ({v:,})" for k, v in found.head(4).items()),
                         "rows": int(hit.sum()),
                         "note": f"non-specific; with the {blank:,} blanks, "
                                 f"{pct(int(hit.sum()) + blank, len(df))} of rows have no specific value"})

    for field in [c for c in df.columns if c.endswith("YN")]:
        recorded = df[field].dropna().unique()
        if len(recorded) == 1:
            rows.append({"field": field, "value": f"blank (only {recorded[0]} is ever recorded)",
                         "rows": int(df[field].isna().sum()),
                         "note": "whether a blank means No or unknown is not documented; unresolved"})
    return pd.DataFrame(rows).set_index("field"), flags


def missing_values(df, columns_per_file):
    heading("4. Missing values (Residential rows)")
    summary = column_summary(df, columns_per_file)
    flagged = summary[summary["over_90pct_missing"]]
    report(f"Columns with more than {MISSING_THRESHOLD:g}% missing values: **{len(flagged)}** of "
           f"{len(summary)}. The test is strictly greater than {MISSING_THRESHOLD:g}%, so a "
           f"column at exactly {MISSING_THRESHOLD:g}% would not be flagged.")
    report()
    table(flagged[["group", "core_field", "null_count", "null_pct", "decision", "reason"]]
          .assign(null_count=lambda t: t["null_count"].map("{:,}".format)))

    core = summary.loc[summary["core_field"]]
    report()
    report(f"Core analysis fields ({len(core)}) are kept even when they are more than "
           f"{MISSING_THRESHOLD:g}% missing. None is near the threshold; the least complete is "
           f"{core['null_pct'].idxmax()} at {core['null_pct'].max():.2f}%. Core fields with any "
           "missing values:")
    report()
    table(core[core["null_count"] > 0][["null_count", "null_pct", "decision"]]
          .assign(null_count=lambda t: t["null_count"].map("{:,}".format)))

    structural = summary[summary["absent_from_file_pct"] >= 50]
    report()
    report("Mostly missing because the column isn't in most source files (not because values "
           "are blank): " + ", ".join(f"{c} ({p:.2f}% of rows)" for c, p in
                                      structural["absent_from_file_pct"].items()))
    drop_cols = list(summary.index[summary["decision"] == "drop"])
    report()
    report(f"Decision: drop {len(drop_cols)} columns over {MISSING_THRESHOLD:g}% missing; keep "
           f"the other {len(summary) - len(drop_cols)}, including partly empty core fields.")

    hidden, hidden_flags = possible_hidden_missing(df)
    report()
    report("Values that may stand in for missing data. They are not counted as nulls above "
           "and are left unchanged:")
    report()
    table(hidden.assign(rows=hidden["rows"].map("{:,}".format)))

    report()
    report("Null-count summary table (every column, most missing first):")
    report()
    table(summary[["group", "core_field", "dtype", "null_count", "null_pct",
                   "absent_from_file_pct", "over_90pct_missing", "decision", "reason"]]
          .assign(null_count=lambda t: t["null_count"].map("{:,}".format)))
    return summary, drop_cols, hidden, hidden_flags


# ---- 4. Numeric distributions --------------------------------------------------

def review_thresholds(values, scale):
    """
    Tukey's 'far out' fences, used as review thresholds: values beyond them are
    unusual enough to check, not proven errors.
    Linear scale: 25th percentile - 3 x IQR and 75th percentile + 3 x IQR.
    Log scale: the same rule applied to log(value), for right-skewed fields. It
    works out to low = Q1 / (Q3/Q1)**3 and high = Q3 * (Q3/Q1)**3, so 'unusual'
    means many times the typical value rather than a fixed amount above it.
    Zeros can't be logged, so they are left out of the log-scale check.
    """
    if scale == "log":
        q1, q3 = values[values > 0].quantile([0.25, 0.75])
        spread = (q3 / q1) ** 3
        return float(q1 / spread), float(q3 * spread)
    q1, q3 = values.quantile([0.25, 0.75])
    return float(q1 - 3 * (q3 - q1)), float(q3 + 3 * (q3 - q1))


def describe_shape(skew):
    """A common rule of thumb: |skewness| under 0.5 is roughly symmetric, 0.5-1 moderate, over 1 strong."""
    if pd.isna(skew):
        return "not enough variation"
    if abs(skew) < 0.5:
        return "roughly symmetric"
    side = "right" if skew > 0 else "left"
    return f"{'moderately' if abs(skew) <= 1 else 'strongly'} {side}-skewed"


def summarize_numeric(df):
    """Raw distribution summary, skewness and review counts per field, plus the flagged rows."""
    rows, flags = [], []
    for field, cfg in NUMERIC_FIELDS.items():
        s = pd.to_numeric(df[field], errors="coerce")
        present = s.dropna()
        q = present.quantile(PERCENTILES)
        lo_c, hi_c = present.quantile(CENTRAL_RANGE)
        central = present[present.between(lo_c, hi_c)]
        iqr = q[0.75] - q[0.25]

        impossible_rule, impossible = "none", pd.Series(False, index=s.index)
        if cfg["impossible"]:
            impossible_rule, test = cfg["impossible"]
            impossible = test(s)
        checked = s.notna() & ~impossible
        if cfg["scale"] == "log":
            checked &= s > 0
        low, high = review_thresholds(s[checked], cfg["scale"])
        if not cfg["low"]:
            low = np.nan
        below = checked & (s < low)  # always False when low is NaN
        above = checked & (s > high)
        extra_rule, extra = "none", pd.Series(False, index=s.index)
        if cfg.get("review"):
            extra_rule, test = cfg["review"]
            extra = test(s)

        rows.append({
            "field": field, "count": int(present.size), "missing": int(s.isna().sum()),
            "zeros": int((s == 0).sum()), "min": present.min(),
            "p1": q[0.01], "p5": q[0.05], "p25": q[0.25], "median": q[0.50], "p75": q[0.75],
            "p95": q[0.95], "p99": q[0.99], "max": present.max(),
            "mean": present.mean(), "std": present.std(),
            "skewness_all": present.skew(), "skewness_p1_p99": central.skew(),
            "quartile_skewness": (q[0.75] + q[0.25] - 2 * q[0.50]) / iqr if iqr else np.nan,
            "shape": describe_shape(central.skew()),
            "impossible_rule": impossible_rule, "impossible": int(impossible.sum()),
            "threshold_scale": cfg["scale"], "low_threshold": low, "high_threshold": high,
            "below_low": int(below.sum()), "above_high": int(above.sum()),
            "extra_review_rule": extra_rule, "extra_review": int(extra.sum()),
        })
        unit = cfg["unit"]
        how = "3 x IQR on a log scale" if cfg["scale"] == "log" else "3 x IQR"
        flags += [
            flag_rows(df, impossible, "impossible value", field, s, impossible_rule),
            flag_rows(df, below, "review threshold", field, s,
                      f"below {fmt_value(low, unit)} ({how})"),
            flag_rows(df, above, "review threshold", field, s,
                      f"above {fmt_value(high, unit)} ({how})"),
            flag_rows(df, extra, "review threshold", field, s, extra_rule),
        ]
    return pd.DataFrame(rows).set_index("field"), flags


def setup_chart_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "text.parse_math": False,  # treat '$' as a dollar sign, not a math-mode marker
    })


def axis_formatter(unit):
    if unit == "usd":
        def money(x, _):
            if abs(x) >= 1e6:
                return f"${x / 1e6:,.1f}M".replace(".0M", "M")
            if abs(x) >= 1e3:
                return f"${x / 1e3:,.0f}K"
            return f"${x:,.0f}"
        return FuncFormatter(money)
    if unit == "year":
        return FuncFormatter(lambda x, _: f"{x:.0f}")
    if unit == "acres":
        return FuncFormatter(lambda x, _: f"{x:,.2f}")
    return FuncFormatter(lambda x, _: f"{x:,.0f}")


def plot_distribution(values, field, cfg, path):
    """Histogram (top) and boxplot (bottom) on a shared x-axis, saved as a PNG."""
    v = values.dropna()
    lo_q, hi_q = cfg.get("plot", DEFAULT_PLOT_RANGE)
    lo, hi = (float(x) for x in v.quantile([lo_q, hi_q]))
    shown = v[(v >= lo) & (v <= hi)]
    hidden_low, hidden_high = int((v < lo).sum()), int((v > hi).sum())
    unit = cfg["unit"]

    width_in, dpi, left, right = 9, 150, 0.1, 0.97
    rwidth = None
    if unit == "count":
        # Whole numbers: one column per value, capped at 24px wide with air between
        bins = np.arange(np.floor(lo) - 0.5, np.ceil(hi) + 1.0, 1.0)
        slot_px = width_in * dpi * (right - left) / (len(bins) - 1)
        rwidth = min(1.0, 24 / slot_px)
    elif unit == "year":
        bins = np.arange(np.floor(lo), np.ceil(hi) + 2.0, 2.0)
    else:
        bins = np.linspace(lo, hi, 61)

    fig = plt.figure(figsize=(width_in, 5.4), dpi=dpi, facecolor=SURFACE)
    grid = fig.add_gridspec(2, 1, height_ratios=[4.2, 1], hspace=0.06,
                            left=left, right=right, top=0.78, bottom=0.18)
    ax_hist = fig.add_subplot(grid[0])
    ax_box = fig.add_subplot(grid[1], sharex=ax_hist)

    # Surface-coloured bar edges leave a ~2px gap between neighbouring bins
    counts, _, _ = ax_hist.hist(shown, bins=bins, rwidth=rwidth, color=SERIES,
                                edgecolor=SURFACE, linewidth=1.0)
    ax_hist.set_ylim(0, counts.max() * 1.15)  # headroom so the median label clears the bars
    median = float(v.median())
    ax_hist.axvline(median, color=INK, linewidth=1.0)
    ax_hist.annotate(f"Median {fmt_value(median, unit)}", xy=(median, 1.0),
                     xycoords=("data", "axes fraction"), xytext=(5, -4),
                     textcoords="offset points", ha="left", va="top", fontsize=9, color=INK,
                     bbox=dict(boxstyle="round,pad=0.25", facecolor=SURFACE, edgecolor="none",
                               alpha=0.9))
    ax_box.boxplot(v, orientation="horizontal", widths=0.25, whis=1.5, showfliers=False,
                   patch_artist=True,
                   boxprops=dict(facecolor=SERIES_LIGHT, edgecolor="none"),
                   medianprops=dict(color=INK, linewidth=1.5),
                   whiskerprops=dict(color=INK_2, linewidth=0.8),
                   capprops=dict(color=INK_2, linewidth=0.8))

    for ax in (ax_hist, ax_box):
        ax.set_facecolor(SURFACE)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(AXIS)
        ax.spines["bottom"].set_linewidth(0.8)
        ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    ax_hist.grid(axis="y", color=GRID, linewidth=0.6)
    ax_hist.set_axisbelow(True)
    ax_hist.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:,.0f}"))
    ax_hist.set_ylabel("Number of sales", color=INK_2, fontsize=9)
    ax_hist.tick_params(axis="x", labelbottom=False)
    ax_hist.set_xlim(bins[0], bins[-1])
    ax_box.set_yticks([])
    ax_box.xaxis.set_major_formatter(axis_formatter(unit))
    if unit == "count":
        ax_box.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax_box.set_xlabel(f"{cfg['label']} ({UNIT_TEXT[unit]})", color=INK_2, fontsize=9)

    fig.text(0.1, 0.935, f"{field}: {cfg['label'].lower()}", fontsize=13, weight="semibold",
             color=INK)
    fig.text(0.1, 0.885, f"Residential closed sales, {START:%b %Y} to {END:%b %Y}. "
             f"{len(v):,} sales have a value.", fontsize=9.5, color=INK_2)
    fig.text(0.1, 0.845, f"Shown: {fmt_value(lo, unit)} to {fmt_value(hi, unit)} "
             f"({lo_q * 100:g}th to {hi_q * 100:g}th percentile). Not shown: "
             f"{hidden_low:,} lower and {hidden_high:,} higher values.", fontsize=9, color=INK_2)
    fig.text(0.1, 0.04, "Box: middle 50% of values (25th to 75th percentile). Line: median. "
             "Whiskers: 1.5 x IQR. Review thresholds are listed in numeric_summary.csv.",
             fontsize=8, color=MUTED)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def numeric_distributions(df):
    heading("5. Numeric distributions (Residential rows)")
    numeric, flags = summarize_numeric(df)

    def formatted(fields, cols):
        out = pd.DataFrame(index=pd.Index(fields, name="field"))
        for col in cols:
            out[col] = [f"{numeric.loc[f, col]:,}" if col in ("count", "missing")
                        else fmt_value(numeric.loc[f, col], NUMERIC_FIELDS[f]["unit"])
                        for f in fields]
        return out

    dist_cols = ["count", "missing", "min", "p1", "p5", "p25", "median", "p75", "p95", "p99",
                 "max", "mean"]
    report("Raw summary: every non-missing value, including zeros, impossible values and "
           "values beyond the review thresholds. Nothing is excluded here.")
    report()
    report("Deliverable fields:")
    report()
    table(formatted(DELIVERABLE_FIELDS, dist_cols))
    report()
    report("All nine fields:")
    report()
    table(formatted(list(NUMERIC_FIELDS), dist_cols))
    report()

    report("Shape. Skewness over all values is dominated by a few huge entries, so the shape "
           "is judged on values between the 1st and 99th percentiles, using the rule of thumb "
           "|skewness| < 0.5 roughly symmetric, 0.5 to 1 moderate, over 1 strong:")
    report()
    shapes = pd.DataFrame({
        "mean": [fmt_value(numeric.loc[f, "mean"], NUMERIC_FIELDS[f]["unit"]) for f in numeric.index],
        "median": [fmt_value(numeric.loc[f, "median"], NUMERIC_FIELDS[f]["unit"]) for f in numeric.index],
        "skewness (all values)": numeric["skewness_all"].map("{:.2f}".format),
        "skewness (1st-99th percentile)": numeric["skewness_p1_p99"].map("{:.2f}".format),
        "shape": numeric["shape"]}, index=numeric.index)
    table(shapes)
    report()

    report("Impossible values break the field's definition. Review thresholds are cut-offs "
           "chosen for this project: values beyond them are unusual and worth checking, not "
           "proven errors. The 3 x IQR thresholds use a log scale for right-skewed fields: "
           "low = Q1 / (Q3/Q1)^3 and high = Q3 x (Q3/Q1)^3, where Q1 and Q3 are the 25th and "
           "75th percentiles of the values above 0. Low values aren't checked where small "
           "values are normal.")
    report()
    review = pd.DataFrame(index=numeric.index)
    review["impossible rule"] = numeric["impossible_rule"]
    review["impossible"] = numeric["impossible"].map("{:,}".format)
    review["threshold scale"] = numeric["threshold_scale"]
    review["low threshold"] = [fmt_value(numeric.loc[f, "low_threshold"], NUMERIC_FIELDS[f]["unit"])
                               or "not checked" for f in numeric.index]
    review["high threshold"] = [fmt_value(numeric.loc[f, "high_threshold"], NUMERIC_FIELDS[f]["unit"])
                                for f in numeric.index]
    review["below low"] = numeric["below_low"].map("{:,}".format)
    review["above high"] = numeric["above_high"].map("{:,}".format)
    review["extra review rule"] = numeric["extra_review_rule"]
    review["extra review"] = numeric["extra_review"].map("{:,}".format)
    table(review)

    setup_chart_style()
    for field, cfg in NUMERIC_FIELDS.items():
        plot_distribution(pd.to_numeric(df[field], errors="coerce"), field, cfg,
                          FIG_DIR / f"{field}.png")
    report()
    report(f"Histogram + boxplot per field: `figures/<field>.png` ({len(NUMERIC_FIELDS)} files). "
           "Percentile summaries: the tables above and `numeric_summary.csv`.")
    return numeric, flags


# ---- 5. EDA questions ------------------------------------------------------------

def date_checks(df):
    """
    Count date problems. One row can break several rules, so violations and the
    distinct rows affected are reported separately.
    """
    dates = {c: pd.to_datetime(df[c], format="%Y-%m-%d", errors="coerce") for c in DATE_FIELDS}
    rows, flags = [], []
    for col in DATE_FIELDS:
        rows.append({"check": f"{col} missing", "rows": int(df[col].isna().sum())})
        unreadable = df[col].notna() & dates[col].isna()
        rows.append({"check": f"{col} not a valid date", "rows": int(unreadable.sum())})
        flags.append(flag_rows(df, unreadable, "date check", col, df[col], "not a valid YYYY-MM-DD date"))

    broken = pd.Series(0, index=df.index)
    for earlier, later in DATE_ORDER_RULES:
        mask = dates[later] < dates[earlier]
        broken += mask.astype(int)
        name = f"{later} before {earlier}"
        rows.append({"check": name, "rows": int(mask.sum())})
        flags.append(flag_rows(df, mask, "date check", name,
                               df[earlier].astype(str) + " -> " + df[later].astype(str),
                               f"{earlier} -> {later}"))

    outside = (dates["CloseDate"] < pd.Timestamp(START)) | (dates["CloseDate"] > pd.Timestamp(END))
    rows.append({"check": f"CloseDate outside {START:%Y-%m} to {END:%Y-%m}", "rows": int(outside.sum())})
    flags.append(flag_rows(df, outside, "date check", "CloseDate", df["CloseDate"],
                           "outside the coverage period"))
    after = df["YearBuilt"] > dates["CloseDate"].dt.year
    rows.append({"check": "YearBuilt after the close year (review; may be a pre-construction sale)",
                 "rows": int(after.sum())})
    flags.append(flag_rows(df, after, "review threshold", "YearBuilt", df["YearBuilt"],
                           "built after the sale year; may be a pre-construction sale"))
    order = {"violations": int(broken.sum()), "rows": int((broken > 0).sum()),
             "rows_2plus": int((broken >= 2).sum()),
             "keys": int(df.loc[broken > 0, "ListingKey"].nunique())}
    return pd.DataFrame(rows).set_index("check"), order, flags


def eda_questions(sold, res, numeric):
    heading("6. EDA questions")
    report("Each answer states the rows it uses. Rows left out of one answer stay in the "
           "dataset and in every other answer.")
    report()
    flags = []

    # Q1 - property type share
    n_res = len(res)
    report(f"**Residential vs other property types** (all {len(sold):,} closed sales; none "
           f"excluded): {n_res:,} are Residential ({pct(n_res, len(sold))}) and "
           f"{len(sold) - n_res:,} are other types ({pct(len(sold) - n_res, len(sold))}).")
    report()

    # Q2 - close price
    close = res["ClosePrice"]
    valid = close[close > 0]
    raw_mean = numeric.loc["ClosePrice", "mean"]
    low, high = numeric.loc["ClosePrice", ["low_threshold", "high_threshold"]]
    within = valid[valid.between(low, high)]
    report(f"**Close price** (sales with a price above $0: {len(valid):,} of {n_res:,}; "
           f"excluded {int(close.isna().sum())} missing and {int((close <= 0).sum())} at $0 or "
           f"less): median {fmt_value(valid.median(), 'usd')}, mean {fmt_value(valid.mean(), 'usd')}.")
    report(f"- The raw summary mean, {fmt_value(raw_mean, 'usd')}, is over all "
           f"{int(close.notna().sum()):,} non-missing prices, so it includes the $0 sale; that is "
           f"the only difference between the two means.")
    report(f"- Sensitivity: leaving out the {len(valid) - len(within):,} prices beyond the review "
           f"thresholds ({fmt_value(low, 'usd')} to {fmt_value(high, 'usd')}) gives a mean of "
           f"{fmt_value(within.mean(), 'usd')} and a median of {fmt_value(within.median(), 'usd')}. "
           "Those prices are unusual, not proven errors.")
    report()

    # Q3 - days on market
    dom = res["DaysOnMarket"]
    ok = dom[dom >= 0]
    buckets = pd.cut(ok, [-0.5, 0.5, 7.5, 30.5, 90.5, 180.5, 365.5, np.inf],
                     labels=["0 days", "1-7", "8-30", "31-90", "91-180", "181-365", "over 365"])
    dom_table = buckets.value_counts(sort=False).to_frame("sales")
    dom_table["share"] = [pct(n, len(ok)) for n in dom_table["sales"]]
    dom_table["sales"] = dom_table["sales"].map("{:,}".format)
    dom_table.index.name = "days on market"
    long_waits = int((ok > 3650).sum())
    report(f"**Days on market** (sales with 0 days or more: {len(ok):,} of {n_res:,}; excluded "
           f"{int((dom < 0).sum())} negative values, which are impossible): median "
           f"{ok.median():.0f} days, mean {ok.mean():.1f}. 75% went under contract within "
           f"{ok.quantile(0.75):.0f} days and 95% within {ok.quantile(0.95):.0f}. Sales over "
           f"3,650 days ({long_waits:,}) stay in: that cut-off is a review threshold, not proof "
           f"of an error. Shape: {numeric.loc['DaysOnMarket', 'shape']}.")
    report()
    table(dom_table)
    report()

    # Q4 - sold above vs below list price
    price_rows, sensitivity = [], []
    for list_col in ("ListPrice", "OriginalListPrice"):
        both_present = res["ClosePrice"].notna() & res[list_col].notna()
        eligible = both_present & (res["ClosePrice"] > 0) & (res[list_col] > 0)
        ratio = res.loc[eligible, "ClosePrice"] / res.loc[eligible, list_col]
        shares = [(ratio > 1).mean(), (ratio == 1).mean(), (ratio < 1).mean()]
        price_rows.append({"compared with": list_col, "eligible sales": f"{len(ratio):,}",
                           "excluded: missing": f"{int((~both_present).sum()):,}",
                           "excluded: $0 or less": f"{int((both_present & ~eligible).sum()):,}",
                           "above list": f"{shares[0] * 100:.2f}%",
                           "at list": f"{shares[1] * 100:.2f}%",
                           "below list": f"{shares[2] * 100:.2f}%",
                           "median close/list": f"{ratio.median():.3f}"})
        typical = ratio[ratio.between(1 / 3, 3)]
        typical_shares = [(typical > 1).mean(), (typical == 1).mean(), (typical < 1).mean()]
        sensitivity.append(f"{list_col}: {len(ratio) - len(typical):,} ratios outside 1/3 to 3, "
                           f"shares change by at most "
                           f"{max(abs(a - b) for a, b in zip(shares, typical_shares)) * 100:.2f} "
                           "percentage points")
        if list_col == "ListPrice":
            outside = pd.Series(False, index=res.index)
            outside[ratio.index] = ~ratio.between(1 / 3, 3)
            flags.append(flag_rows(res, outside, "review threshold", "ClosePrice/ListPrice",
                                   (res["ClosePrice"] / res["ListPrice"]).round(3),
                                   "potential anomaly requiring review: sold for more than 3 "
                                   "times or less than a third of the list price"))
    report("**Sold above vs below list price** (sales where both prices are present and above $0):")
    report()
    table(pd.DataFrame(price_rows).set_index("compared with"))
    report()
    report("Sensitivity, leaving out close/list ratios outside 1/3 to 3 (potential anomalies "
           "requiring review): " + "; ".join(sensitivity) + ".")
    report()

    # Q5 - date consistency
    date_table, order, date_flags = date_checks(res)
    flags += date_flags
    report(f"**Date consistency** (all {n_res:,} Residential rows): the three date-order rules "
           f"are broken {order['violations']:,} times by {order['rows']:,} distinct rows "
           f"({order['keys']:,} distinct ListingKeys); {order['rows_2plus']:,} rows break two or "
           "more rules.")
    report()
    table(date_table.assign(rows=date_table["rows"].map("{:,}".format)))
    report()

    # Q6 - counties
    priced = res[(res["ClosePrice"] > 0) & res["CountyOrParish"].notna()]
    county = (priced.groupby("CountyOrParish")["ClosePrice"]
              .agg(sales="size", median_close_price="median")
              .sort_values("median_close_price", ascending=False))
    county.round(0).to_csv(OUT_DIR / "county_median_prices.csv")
    small = county[county["sales"] < MIN_COUNTY_SALES]
    top = county[county["sales"] >= MIN_COUNTY_SALES].head(10)
    report(f"**Counties with the highest median close price** (sales priced above $0 with a "
           f"county: {len(priced):,}; {len(county)} counties, of which {len(small)} with fewer "
           f"than {MIN_COUNTY_SALES} sales ({int(small['sales'].sum()):,} sales) are left out of "
           "the ranking; full list in `county_median_prices.csv`):")
    report()
    table(pd.DataFrame({"sales": top["sales"].map("{:,}".format),
                        "median close price": top["median_close_price"].map(
                            lambda v: fmt_value(v, "usd"))}))
    return flags


# ---- 6. Other checks ----------------------------------------------------------

def other_checks(res):
    heading("7. Other checks for the cleaning step")
    flags = []
    not_ca = res["StateOrProvince"] != "CA"
    flags.append(flag_rows(res, not_ca, "outside California", "StateOrProvince",
                           res["StateOrProvince"], "StateOrProvince is not CA"))
    report(f"- {int(not_ca.sum())} rows are not in California (StateOrProvince other than CA, "
           "or blank).")
    not_home = res["PropertySubType"].isin(NOT_A_HOME_SUBTYPES)
    flags.append(flag_rows(res, not_home, "non-dwelling subtype", "PropertySubType",
                           res["PropertySubType"], "filed as Residential but not a dwelling"))
    counts = res.loc[not_home, "PropertySubType"].value_counts()
    report(f"- {int(not_home.sum())} Residential rows are not dwellings: "
           + ", ".join(f"{k} {v}" for k, v in counts.items()) + ".")

    exact_copy = res.duplicated(keep=False)  # identical in every column, file included
    files_per_key = res.groupby("ListingKey")["SourceFile"].transform("nunique")
    other_file = files_per_key > 1
    shared = res["ListingKey"].duplicated(keep=False)
    flags.append(flag_rows(res, exact_copy, "repeated ListingKey", "ListingKey", res["ListingKey"],
                           "exact copy of another row in the same file"))
    flags.append(flag_rows(res, other_file, "repeated ListingKey", "ListingKey", res["ListingKey"],
                           "same ListingKey also in another monthly file"))
    repeats = pd.DataFrame([
        {"kind": "exact copies within one monthly file", "rows": int(exact_copy.sum()),
         "ListingKeys": int(res.loc[exact_copy, "ListingKey"].nunique()),
         "extra rows": int(res[exact_copy].duplicated().sum())},
        {"kind": "same ListingKey in two or more monthly files", "rows": int(other_file.sum()),
         "ListingKeys": int(res.loc[other_file, "ListingKey"].nunique()),
         "extra rows": int(other_file.sum()) - int(res.loc[other_file, "ListingKey"].nunique())},
        {"kind": "any repeated ListingKey", "rows": int(shared.sum()),
         "ListingKeys": int(res.loc[shared, "ListingKey"].nunique()),
         "extra rows": int(res["ListingKey"].duplicated().sum())},
    ]).set_index("kind")
    report("- Repeated ListingKeys (rows are all rows involved; extra rows are those beyond "
           "the first per key). The cause of the cross-file repeats has not been checked:")
    report()
    table(repeats.apply(lambda c: c.map("{:,}".format)))
    return flags


# ---- 7. Save -------------------------------------------------------------------------

def save_filtered(df, path):
    """Write to a temporary file, reload it to check its shape and contents, then put it in place."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_csv(tmp, index=False)
        header = list(pd.read_csv(tmp, nrows=0).columns)
        types = pd.read_csv(tmp, usecols=["PropertyType"])["PropertyType"]
        if header != list(df.columns) or len(types) != len(df) or not (types == "Residential").all():
            raise RuntimeError(f"{path.name} didn't save correctly; any earlier copy was left in place")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    return len(types), len(header), types.value_counts().to_dict()


def save_outputs(res, drop_cols, summary, hidden, numeric, flags):
    heading("8. Review flags and saved files")
    review = pd.concat([f for f in flags if f is not None], ignore_index=True)
    by_category = review.groupby("category").agg(flags=("RowNumber", "size"),
                                                  rows=("RowNumber", "nunique"),
                                                  ListingKeys=("ListingKey", "nunique"))
    by_category.loc["all categories"] = [len(review), review["RowNumber"].nunique(),
                                         review["ListingKey"].nunique()]
    report("A row can carry several flags, so flags, distinct rows and distinct ListingKeys "
           "are counted separately. Every flagged row stays in the saved dataset.")
    report()
    table(by_category.apply(lambda c: c.map(lambda v: f"{int(v):,}")))
    report()

    filtered = res.drop(columns=drop_cols)
    filtered.insert(0, "RowNumber", np.arange(1, len(filtered) + 1))
    rows, cols, types = save_filtered(filtered, OUT_DIR / "sold_residential_filtered.csv")
    summary.to_csv(OUT_DIR / "column_summary.csv")
    hidden.to_csv(OUT_DIR / "possible_hidden_missing.csv")
    numeric.round(4).to_csv(OUT_DIR / "numeric_summary.csv")
    review.to_csv(OUT_DIR / "review_flags.csv", index=False)
    type_text = ", ".join(f"{k} {v:,}" for k, v in types.items())
    report(f"- `sold_residential_filtered.csv`: reloaded after saving: {rows:,} rows x {cols} "
           f"columns; PropertyType values: {type_text}. It has the {res.shape[1] - len(drop_cols)} "
           "kept columns plus `RowNumber` (1 = first data row), which review_flags.csv uses "
           "to point at rows.")
    report("- `column_summary.csv` (null-count table), `possible_hidden_missing.csv`, "
           "`numeric_summary.csv`, `county_median_prices.csv`")
    report(f"- `review_flags.csv`: {len(review):,} flags on {review['RowNumber'].nunique():,} "
           f"rows ({review['ListingKey'].nunique():,} ListingKeys)")
    report(f"- `figures/`: {len(NUMERIC_FIELDS)} PNG files")


# ---- Main ------------------------------------------------------------------------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(exist_ok=True)
    report("# Weeks 2-3: dataset structuring and validation (sold)")
    report()
    report(f"Generated by `week2_3_eda.py` for closed sales from {START:%Y-%m} through {END:%Y-%m}. "
           "Only non-Residential rows and columns more than 90% missing are removed; flagged "
           "rows stay in the saved dataset.")

    # ---- 1. Load ------------------------------------------------------------------
    sold, columns_per_file, missing, damaged = load_sold()
    heading("1. Data loaded")
    report(f"- Monthly sold files: {len(columns_per_file)} of {len(months_in_range(START, END))}")
    report(f"- Missing months: {', '.join(missing) if missing else 'none'}")
    report(f"- Files with structural problems: {'; '.join(damaged) if damaged else 'none'}")

    # ---- 2. Dataset understanding ----------------------------------------------------
    heading("2. Dataset understanding")
    report(f"- All property types: **{len(sold):,} rows x {sold.shape[1] - 1} columns** "
           f"from the source files, plus `SourceFile` added by this script.")
    report(f"- Columns: {', '.join(c for c in sold.columns)}")
    report()
    report("First 5 rows (market fields only; agent names and addresses left out):")
    report()
    sample_cols = ["CloseDate", "ClosePrice", "ListPrice", "PropertyType", "PropertySubType",
                   "City", "CountyOrParish", "BedroomsTotal", "BathroomsTotalInteger",
                   "LivingArea", "YearBuilt", "DaysOnMarket"]
    table(sold[sample_cols].head().rename_axis("row"))
    report()
    dtypes = sold.dtypes.astype(str).value_counts().rename("columns")
    dtypes.index.name = "data type"
    table(dtypes.to_frame())
    report()
    report("Notes: dates are stored as text (YYYY-MM-DD) and are parsed only for the date "
           "checks; Y/N fields load as `object` (True, False or blank); `PostalCode` is text.")
    groups = pd.Series(COLUMN_GROUP).loc[lambda g: g.index.isin(sold.columns)]
    group_table = groups.groupby(groups).apply(lambda g: ", ".join(g.index)).rename("columns")
    group_table.index.name = "group"
    report()
    table(group_table.to_frame().assign(count=groups.value_counts())[["count", "columns"]])
    unclassified = [c for c in sold.columns if c not in COLUMN_GROUP]
    report()
    report(f"Unclassified columns: {', '.join(unclassified) if unclassified else 'none'}")

    # ---- 3. Property types and the Residential filter ---------------------------------
    # Last run, 2026-10-09: 8 PropertyType values in 736,168 sold rows, e.g.
    # Residential 495,070 (67.25%) and ResidentialLease 169,403 (23.01%).
    # Filter: PropertyType == 'Residential' -> 736,168 rows before, 495,070 after.
    res = filter_residential(sold)

    # ---- 4. Missing values -----------------------------------------------------------
    # Last run, 2026-10-09: 15 of 85 columns are more than 90% missing and are dropped;
    # no core field is near the threshold (LotSizeAcres is the least complete, 7.67%).
    summary, drop_cols, hidden, hidden_flags = missing_values(res, columns_per_file)

    # ---- 5. Numeric distributions ----------------------------------------------------
    # Last run, 2026-10-09 (raw summary, every non-missing value):
    #   ClosePrice   min $0, median $825,000, mean $1,189,912, max $989,500,000
    #   LivingArea   min 0, median 1,648, mean 1,902.7, max 17,021,321
    #   DaysOnMarket min -288, median 19, mean 37.6, max 12,430
    numeric, numeric_flags = numeric_distributions(res)

    # ---- 6. EDA questions and other checks --------------------------------------------
    eda_flags = eda_questions(sold, res, numeric)
    other_flags = other_checks(res)

    # ---- 7. Save -----------------------------------------------------------------------
    save_outputs(res, drop_cols, summary, hidden, numeric,
                 hidden_flags + numeric_flags + eda_flags + other_flags)
    (OUT_DIR / "eda_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"\nReport saved to {OUT_DIR / 'eda_report.md'}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as err:
        sys.exit(f"ERROR: {err}")
