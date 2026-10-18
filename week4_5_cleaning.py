"""
Weeks 4-5 - Data Cleaning and Preparation

Cleans the two mortgage-enriched datasets and adds explicit quality flags, so
analysts can choose which records to include for each analysis. Nothing is
filled in, no row is removed, and no date or coordinate is altered or repaired.

Input (read only, never modified):
  output/mortgage_rates/sold_with_rates.csv       year_month comes from CloseDate
  output/mortgage_rates/listings_with_rates.csv   year_month comes from ListingContractDate
Output: output/cleaned/
  sold_cleaned.csv        cleaned sold data + audit columns + quality flags
  listings_cleaned.csv    cleaned listings data + audit columns + quality flags
  cleaning_summary.csv    every count this script reports, for both datasets

Steps (the reason for each is in the comments next to it):
  1. Read every column as text, so nothing is guessed (identifiers keep leading zeros).
  2. Drop only columns that hold no values at all, and ListingKeyNumeric when it is an
     exact copy of ListingKey. High missingness alone is never a reason to drop.
  3. Remove the ".0" an earlier float conversion added to StreetNumberNumeric.
  4. Parse the four date columns as YYYY-MM-DD, the only format in the inputs.
  5. Convert numeric columns; whole-number fields become nullable integers.
  6. Convert the True/False text fields (*YN, latfilled, lonfilled) to booleans.
  7. Flag impossible values, keep the original in an audit column, and set the
     analytical value to null.
  8. Flag date-order problems, geographic issues, exact duplicate rows and repeated
     ListingKeys. Nothing is repaired, reordered or deleted.
  9. Validate, then save and reload each file to check it.

CSV files do not store pandas dtypes: dates, numbers and flags come back as text
unless they are parsed on reload (see the README section on reloading).

Requires: pandas; week1_aggregate.py (for OUTPUT_DIR); the two input files above
(run week2_3_mortgage_rates.py first).
"""

import math
import os
import sys

import pandas as pd

from week1_aggregate import OUTPUT_DIR

IN_DIR = OUTPUT_DIR / "mortgage_rates"
OUT_DIR = OUTPUT_DIR / "cleaned"

# name: (input file, output file, date column that year_month was built from)
DATASETS = {
    "sold": ("sold_with_rates.csv", "sold_cleaned.csv", "CloseDate"),
    "listings": ("listings_with_rates.csv", "listings_cleaned.csv", "ListingContractDate"),
}

DATE_FORMAT = "%Y-%m-%d"  # every date in the inputs is YYYY-MM-DD, with no time part
DATE_COLUMNS = ["CloseDate", "PurchaseContractDate", "ListingContractDate",
                "ContractStatusChangeDate"]
NUMERIC_COLUMNS = [
    "ClosePrice", "ListPrice", "OriginalListPrice", "AssociationFee", "BuyerAgencyCompensation",
    "LivingArea", "BuildingAreaTotal", "BelowGradeFinishedArea", "LotSizeAcres",
    "LotSizeSquareFeet", "LotSizeArea", "DaysOnMarket", "BedroomsTotal",
    "BathroomsTotalInteger", "MainLevelBedrooms", "YearBuilt", "Stories", "GarageSpaces",
    "ParkingTotal", "Latitude", "Longitude", "rate_30yr_fixed"]
# Stored as nullable integers when every value is a whole number (else left as decimals)
WHOLE_NUMBER_COLUMNS = ["DaysOnMarket", "BedroomsTotal", "BathroomsTotalInteger",
                        "MainLevelBedrooms", "YearBuilt", "Stories"]
# Never dropped, even if a future input left them empty
PROTECTED_COLUMNS = {
    "ListingKey", "ListingId", "PropertyType", "MlsStatus", "ClosePrice", "ListPrice",
    "OriginalListPrice", "LivingArea", "DaysOnMarket", "BedroomsTotal",
    "BathroomsTotalInteger", "Latitude", "Longitude", "City", "CountyOrParish",
    "PostalCode", "year_month", "rate_30yr_fixed", *DATE_COLUMNS}

# Impossible values: (flag, column, rule). The original value is kept in
# <column>_invalid_original and the analytical column is set to null.
# Zero bedrooms or bathrooms are allowed (studios, non-dwellings), so only
# negative counts are flagged.
INVALID_RULES = [
    ("invalid_close_price_flag", "ClosePrice", "ClosePrice <= 0", lambda s: s <= 0),
    ("invalid_living_area_flag", "LivingArea", "LivingArea <= 0", lambda s: s <= 0),
    ("negative_days_on_market_flag", "DaysOnMarket", "DaysOnMarket < 0", lambda s: s < 0),
    ("negative_bedrooms_flag", "BedroomsTotal", "BedroomsTotal < 0", lambda s: s < 0),
    ("negative_bathrooms_flag", "BathroomsTotalInteger", "BathroomsTotalInteger < 0",
     lambda s: s < 0),
]

# Date-order flags: (flag, first, second, definition). A row is flagged when the
# first date is later than the second. Equal dates are allowed. A row missing
# either date is not evaluated: its flag is False and it is counted separately.
# On listings that are not Closed, what CloseDate means is unverified (it may be
# a scheduled date), so the two close-date flags on those rows are diagnostic
# only. Completed-sale timelines should use Closed records with valid dates.
DATE_RULES = [
    ("listing_after_close_flag", "ListingContractDate", "CloseDate",
     "ListingContractDate > CloseDate"),
    ("purchase_after_close_flag", "PurchaseContractDate", "CloseDate",
     "PurchaseContractDate > CloseDate"),
    ("negative_timeline_flag", "ListingContractDate", "PurchaseContractDate",
     "PurchaseContractDate < ListingContractDate"),
]

# Approximate California bounding box (California spans about 32.53 to 42.01 N
# and 114.13 to 124.41 W). A box is only a screen: it also covers parts of Nevada,
# Arizona, Oregon, Mexico and the ocean, so a point inside it is not proven to be
# in California, and a point outside it is a potential issue, not a proven error.
CA_BOX = {"lat_min": 32.5, "lat_max": 42.1, "lon_min": -124.5, "lon_max": -114.1}

summary_rows = []


def record(dataset, section, item, count=None, detail="", show=True):
    """Keep a line for cleaning_summary.csv and print it."""
    summary_rows.append({"dataset": dataset, "section": section, "item": item,
                         "count": count, "detail": detail})
    if show:
        value = "" if count is None else f"{count:,}" if isinstance(count, int) else str(count)
        print(f"  {section:<20} {item:<48} {value:>10}  {detail}")


# ---- 1-2. Load and choose columns --------------------------------------------------

def load(path):
    """Read every column as text. Only empty cells count as missing."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


def columns_to_drop(df):
    """Columns with no information: completely empty, or an exact copy of another column."""
    drops = []
    for col in df.columns:
        if df[col].isna().all():
            if col in PROTECTED_COLUMNS:
                continue  # reported as missing, but kept
            drops.append((col, "contains no values in this dataset (0 non-missing)"))
    if {"ListingKey", "ListingKeyNumeric"} <= set(df.columns) and \
            df["ListingKeyNumeric"].equals(df["ListingKey"]):
        drops.append(("ListingKeyNumeric", "exact copy of ListingKey in every row"))
    return drops


# ---- 3-6. Normalize and convert types --------------------------------------------

def normalize_street_number(df, name):
    """'2811.0' -> '2811': the '.0' came from an earlier float conversion. Kept as text."""
    col = "StreetNumberNumeric"
    if col not in df:
        return
    artifact = df[col].str.fullmatch(r"\d+\.0").fillna(False).astype(bool)
    df.loc[artifact, col] = df.loc[artifact, col].str[:-2]
    record(name, "normalization", col, int(artifact.sum()),
           "removed a trailing '.0'; kept as text")


def parse_dates(df, name):
    """Parse YYYY-MM-DD dates. Missing stays missing; text that fails is kept in an audit column."""
    failures = []
    for col in DATE_COLUMNS:
        if col not in df:
            record(name, "dates", col, None, "not in this dataset")
            continue
        text = df[col]
        parsed = pd.to_datetime(text, format=DATE_FORMAT, errors="coerce")
        failed = text.notna() & parsed.isna()
        record(name, "dates", f"{col}: originally missing", int(text.isna().sum()))
        record(name, "dates", f"{col}: failed to parse", int(failed.sum()),
               "non-missing values that are not a valid YYYY-MM-DD date")
        if failed.any():
            df[f"{col}_unparsed_original"] = text.where(failed)
        failures.append(failed)
        df[col] = parsed
    return failures


def to_float(value):
    """
    Text -> float, or NaN if it isn't a finite number.

    Python's float() returns the binary floating-point value nearest to the text
    (it is correctly rounded). The inputs were written in shortest round-trip
    form, so each value reads back as the same float and is written out as the
    same text. pandas' faster parser is not always correctly rounded: it reads
    6.1899999999999995 as the neighbouring float, which prints as 6.19, so a
    mortgage rate's text would change. Neither parser does exact decimal
    arithmetic; floats are binary approximations either way.
    """
    try:
        number = float(value)
    except ValueError:
        return math.nan
    return number if math.isfinite(number) else math.nan


def convert_numeric(df, name):
    """Convert to numbers. '$' and commas are removed only in a column where they occur."""
    failures = []
    for col in NUMERIC_COLUMNS:
        if col not in df:
            continue
        text = df[col]
        formatted = text.str.contains(r"[$,]", regex=True).fillna(False).astype(bool)
        if formatted.any():
            text = text.str.replace(r"[$,]", "", regex=True)
        values = text.map(to_float, na_action="ignore").astype("float64")
        failed = text.notna() & values.isna()
        record(name, "numeric conversion", f"{col}: failed to convert", int(failed.sum()),
               f"{int(text.notna().sum()):,} non-missing; {int(formatted.sum())} had $ or commas")
        if failed.any():
            df[f"{col}_unparsed_original"] = df[col].where(failed)
        failures.append(failed)
        df[col] = values
    return failures


def convert_booleans(df, name):
    """'True'/'False' text -> nullable boolean. Blanks stay missing: their meaning is not documented."""
    failures = []
    for col in [c for c in df.columns if c.endswith("YN") or c in ("latfilled", "lonfilled")]:
        text = df[col]
        mapped = text.map({"True": True, "False": False})
        failed = text.notna() & mapped.isna()
        record(name, "boolean conversion", f"{col}: failed to convert", int(failed.sum()),
               f"{int(text.isna().sum()):,} blank, left missing", show=False)
        if failed.any():
            df[f"{col}_unparsed_original"] = text.where(failed)
        failures.append(failed)
        df[col] = mapped.astype("boolean")
    return failures


def use_whole_numbers(df, name):
    for col in WHOLE_NUMBER_COLUMNS:
        if col not in df:
            continue
        if (df[col].dropna() % 1 == 0).all():
            df[col] = df[col].astype("Int64")
        else:
            record(name, "numeric conversion", f"{col}: kept as decimal", None,
                   "has values that are not whole numbers")


# ---- 7-8. Quality flags ------------------------------------------------------------

def flag_invalid_values(df, name, original_text):
    """Impossible values: flag them, keep the original text, set the analytical value to null."""
    for flag, col, rule, test in INVALID_RULES:
        bad = test(df[col]).fillna(False).astype(bool)
        df[f"{col}_invalid_original"] = original_text[col].where(bad)
        df.loc[bad, col] = float("nan")
        df[flag] = bad
        record(name, "invalid values", flag, int(bad.sum()),
               f"{rule}; original kept in {col}_invalid_original, value set to null")


def flag_dates(df, name):
    """Date-order flags on rows where both dates are present and valid; nothing is reordered."""
    for flag, first, second, definition in DATE_RULES:
        evaluable = df[first].notna() & df[second].notna()
        df[flag] = (evaluable & (df[first] > df[second])).astype(bool)
        record(name, "date flags", flag, int(df[flag].sum()), f"{definition}; equal dates allowed")
        record(name, "date flags", f"{flag}: not evaluable", int((~evaluable).sum()),
               f"{first} or {second} missing or unparseable; flag left False, NOT checked")
    flags = [r[0] for r in DATE_RULES]
    broken = df[flags].sum(axis=1)
    record(name, "date flags", "rows with any date flag", int((broken > 0).sum()))
    record(name, "date flags", "rows with two or more date flags", int((broken >= 2).sum()))


def flag_geography(df, name):
    """Coordinate screens. Coordinates are never changed, swapped or geocoded."""
    lat, lon = df["Latitude"], df["Longitude"]
    present = lat.notna() & lon.notna()
    inside_box = (lat.between(CA_BOX["lat_min"], CA_BOX["lat_max"])
                  & lon.between(CA_BOX["lon_min"], CA_BOX["lon_max"]))
    checks = {
        "missing_coordinates_flag": (~present, "Latitude or Longitude missing"),
        "zero_coordinate_flag": ((lat == 0) | (lon == 0), "Latitude = 0 or Longitude = 0"),
        "positive_longitude_flag": (lon > 0, "Longitude > 0 (California longitudes are negative)"),
        "invalid_coordinate_range_flag": ((lat < -90) | (lat > 90) | (lon < -180) | (lon > 180),
                                          "outside [-90, 90] latitude or [-180, 180] longitude"),
        "outside_ca_bbox_flag": (present & ~inside_box,
                                 "potential geographic issue: outside lat {lat_min}-{lat_max}, "
                                 "lon {lon_min} to {lon_max} (screening only)".format(**CA_BOX)),
    }
    for flag, (mask, definition) in checks.items():
        df[flag] = mask.fillna(False).astype(bool)
        record(name, "geographic flags", flag, int(df[flag].sum()), definition)
    record(name, "geographic flags", "coordinate checks: not evaluable", int((~present).sum()),
           "rows missing a coordinate; their other geographic flags are False, NOT checked")
    record(name, "geographic flags", "rows with any geographic flag",
           int(df[list(checks)].any(axis=1).sum()))


# ---- 9. Validation and saving ------------------------------------------------------

def validate(df, name, key_col, original, rows_before):
    """In-memory checks. Raises if the month key, rates or row count changed."""
    problems = []
    if len(df) != rows_before:
        problems.append("row count changed")
    key_month = df[key_col].dt.to_period("M")
    mismatch = key_month.notna() & (df["year_month"] != key_month)
    record(name, "validation", f"year_month matches {key_col} month",
           int((~mismatch & key_month.notna()).sum()),
           f"mismatches: {int(mismatch.sum())}; rows without {key_col}: {int(key_month.isna().sum())}")
    if mismatch.any():
        problems.append(f"year_month differs from {key_col} month in {int(mismatch.sum())} rows")
    same_rate = df["rate_30yr_fixed"].eq(original["rate_30yr_fixed"].map(float))
    record(name, "validation", "rate_30yr_fixed unchanged and non-null", int(same_rate.sum()),
           f"nulls: {int(df['rate_30yr_fixed'].isna().sum())}")
    if not same_rate.all():
        problems.append("rate_30yr_fixed changed or became null")
    for col in df.columns:
        record(name, "dtype in memory", col, None, str(df[col].dtype), show=False)
    if problems:
        raise ValueError(f"{name}: " + "; ".join(problems))


def save_and_check(df, path, name, original, flags):
    """Write, reload as text, and confirm rows, key fields and flag counts before replacing."""
    tmp = path.with_name(path.name + ".tmp")
    # Dates are written as YYYY-MM-DD text column by column: a to_csv date_format
    # would also reformat the year_month period (2024-01 would become 2024-01-31).
    as_text = {c: df[c].dt.strftime(DATE_FORMAT) for c in DATE_COLUMNS if c in df}
    try:
        df.assign(**as_text).to_csv(tmp, index=False)
        back = load(tmp)
        problems = []
        if len(back) != len(df) or list(back.columns) != list(df.columns):
            problems.append("shape changed on reload")
        for col in ["ListingKey", "year_month", "rate_30yr_fixed",
                    *[c for c in DATE_COLUMNS if c in original]]:
            if not back[col].equals(original[col]):
                problems.append(f"{col} text differs from the input")
        for flag in flags:
            if (back[flag] == "True").sum() != df[flag].sum() or not back[flag].isin(["True", "False"]).all():
                problems.append(f"{flag} did not reload correctly")
        if problems:
            raise ValueError(f"{path.name}: " + "; ".join(problems))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    record(name, "saved file", path.name, len(back),
           f"reloaded: {len(back):,} rows x {back.shape[1]} columns; ListingKey, year_month, "
           "rate_30yr_fixed and dates identical to the input text; flag counts match")


def clean(name, in_file, out_file, key_col):
    print(f"\n=== {name}")
    raw = load(IN_DIR / in_file)
    rows_before, cols_before = raw.shape
    record(name, "shape", "rows before", rows_before)
    record(name, "shape", "columns before", cols_before)
    for col in raw.columns:
        record(name, "missing (original)", col, int(raw[col].isna().sum()), show=False)
    print(f"  {'missing (original)':<20} {'columns with any missing value':<48} "
          f"{int((raw.isna().sum() > 0).sum()):>10}  per-column counts in cleaning_summary.csv")

    # Duplicates: every input column is compared as raw text, before any conversion.
    # duplicate_record_flag marks only the later copies (the first occurrence is not
    # flagged), so its count is the number of excess rows. repeated_listing_key_flag
    # marks every row whose ListingKey appears more than once. No row is dropped.
    duplicate = raw.duplicated(keep="first")
    repeated_key = raw["ListingKey"].duplicated(keep=False)
    original = raw[["ListingKey", "year_month", "rate_30yr_fixed",
                    *[c for c in DATE_COLUMNS if c in raw]]].copy()
    invalid_text = raw[[col for _, col, _, _ in INVALID_RULES]].copy()

    drops = columns_to_drop(raw)
    for col, reason in drops:
        record(name, "dropped column", col, None, reason)
    df = raw.drop(columns=[c for c, _ in drops])
    del raw

    normalize_street_number(df, name)
    failures = parse_dates(df, name) + convert_numeric(df, name) + convert_booleans(df, name)
    df["year_month"] = pd.to_datetime(df["year_month"], format="%Y-%m").dt.to_period("M")

    flag_invalid_values(df, name, invalid_text)
    use_whole_numbers(df, name)
    flag_dates(df, name)
    flag_geography(df, name)
    df["duplicate_record_flag"] = duplicate.to_numpy()
    df["repeated_listing_key_flag"] = repeated_key.to_numpy()
    record(name, "duplicates", "duplicate_record_flag", int(duplicate.sum()),
           "identical to an earlier row in every input column; kept, not dropped")
    record(name, "duplicates", "repeated_listing_key_flag", int(repeated_key.sum()),
           f"rows whose ListingKey appears more than once ({raw_key_count(repeated_key, original)} keys)")
    parse_failure = pd.concat(failures, axis=1).any(axis=1) if failures else False
    df["parse_failure_flag"] = parse_failure
    record(name, "parse failures", "parse_failure_flag", int(df["parse_failure_flag"].sum()),
           "any date, number or True/False value that could not be converted")

    flags = [c for c in df.columns if c.endswith("_flag")]
    df["any_quality_issue_flag"] = df[flags].any(axis=1)
    flags.append("any_quality_issue_flag")
    record(name, "quality", "rows with any quality flag", int(df["any_quality_issue_flag"].sum()),
           "unique rows; individual flag counts overlap")

    audit = [c for c in df.columns if c.endswith("_original")]
    df = df[[c for c in df.columns if c not in audit and c not in flags] + audit + flags]
    record(name, "shape", "rows after", len(df))
    record(name, "shape", "columns after", df.shape[1],
           f"{cols_before} - {len(drops)} dropped + {len(audit)} audit + {len(flags)} flag columns")
    for col in df.columns:
        if not col.endswith("_flag"):
            record(name, "missing (after)", col, int(df[col].isna().sum()), show=False)

    validate(df, name, key_col, original, rows_before)
    save_and_check(df, OUT_DIR / out_file, name, original, flags)


def raw_key_count(mask, original):
    return f"{original.loc[mask.to_numpy(), 'ListingKey'].nunique():,}"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (in_file, out_file, key_col) in DATASETS.items():
        if not (IN_DIR / in_file).exists():
            raise FileNotFoundError(f"{IN_DIR / in_file} not found. Run week2_3_mortgage_rates.py first.")
        clean(name, in_file, out_file, key_col)
    pd.DataFrame(summary_rows).to_csv(OUT_DIR / "cleaning_summary.csv", index=False)
    print(f"\nSaved {len(summary_rows):,} summary lines to {OUT_DIR / 'cleaning_summary.csv'}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as err:
        sys.exit(f"ERROR: {err}")
