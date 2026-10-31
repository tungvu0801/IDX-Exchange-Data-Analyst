"""
Week 6 - Feature Engineering and Market Metrics

Adds the Week 6 market metrics and California school districts to both cleaned
datasets, and summarizes the metrics by segment. Every input row and column is
kept exactly as it was (same text); the new columns are appended at the end.

Input (read only, never modified):
  output/cleaned/sold_cleaned.csv       Closed sales (year_month comes from CloseDate)
  output/cleaned/listings_cleaned.csv   listings of every status
  output/week6/school_districts/school_district_areas_2024_25.geojson
      CDE school district boundaries, downloaded once if missing (BOUNDARY_SOURCE)
Output: output/week6/
  sold_engineered.csv, listings_engineered.csv   input columns + metrics + districts
  sample_engineered.csv      a few rows showing the new columns
  summary_by_<segment>.csv   segmented summaries for both datasets
  validation_report.md       formulas, missingness, exclusions, row counts,
                             district coverage and limitations
  validation_summary.csv     every count this script reports, one per row

Metrics (handbook Week 6 table). A metric is null when an input is missing or
invalid; <metric>_null_reason gives the first check that failed.
  price_ratio                   ClosePrice / OriginalListPrice  (*)
  close_to_original_list_ratio  ClosePrice / OriginalListPrice
  price_per_sqft                ClosePrice / LivingArea
  DaysOnMarket                  the MLS field itself, as cleaned (not recomputed from dates)
  Year, Month, YrMo             from CloseDate
  listing_to_contract_days      PurchaseContractDate - ListingContractDate
  contract_to_close_days        CloseDate - PurchaseContractDate
Extra analytical metric (not a handbook requirement and not a replacement for one):
  close_to_current_list_ratio   ClosePrice / ListPrice
(*) The handbook gives ClosePrice / OriginalListPrice for both Price Ratio and
Close to Original List Ratio, and it is followed literally, so the two columns
are identical (same values, nulls and reasons; checked on every run).

Completed-sale metrics (everything that uses ClosePrice or CloseDate) are only
filled for Closed records: on other listings CloseDate may be a future or
scheduled date. Listing-to-contract days uses no close field, so it is filled
for any status with valid dates.

Tests: python test_week6_feature_engineering.py (synthetic data, no real files needed).

Requires: pandas, numpy, matplotlib (point-in-polygon), requests (one-time boundary
download); week1_aggregate.py and week4_5_cleaning.py; the cleaned inputs above
(run week4_5_cleaning.py first).
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
from matplotlib.path import Path as PolygonPath

from week1_aggregate import OUTPUT_DIR
from week4_5_cleaning import CA_BOX, DATE_FORMAT, load, same_text, to_float

IN_DIR = OUTPUT_DIR / "cleaned"
OUT_DIR = OUTPUT_DIR / "week6"
BOUNDARY_DIR = OUT_DIR / "school_districts"
BOUNDARY_FILE = BOUNDARY_DIR / "school_district_areas_2024_25.geojson"

# name: (input file, output file, date column that year_month was built from)
DATASETS = {
    "sold": ("sold_cleaned.csv", "sold_engineered.csv", "CloseDate"),
    "listings": ("listings_cleaned.csv", "listings_engineered.csv", "ListingContractDate"),
}

PRICE_RATIO_DENOMINATOR = "OriginalListPrice"  # the handbook's formula, followed literally

RATIO_METRICS = [  # (metric, denominator); the numerator is always ClosePrice
    ("price_ratio", PRICE_RATIO_DENOMINATOR),
    ("close_to_original_list_ratio", "OriginalListPrice"),
    ("close_to_current_list_ratio", "ListPrice"),  # extra; not a handbook metric
    ("price_per_sqft", "LivingArea"),
]
# metric column -> its null-reason column (Year, Month and YrMo share one)
REASON_COLUMN = {
    "price_ratio": "price_ratio_null_reason",
    "close_to_original_list_ratio": "close_to_original_list_ratio_null_reason",
    "close_to_current_list_ratio": "close_to_current_list_ratio_null_reason",
    "price_per_sqft": "price_per_sqft_null_reason",
    "Year": "YrMo_null_reason", "Month": "YrMo_null_reason", "YrMo": "YrMo_null_reason",
    "listing_to_contract_days": "listing_to_contract_days_null_reason",
    "contract_to_close_days": "contract_to_close_days_null_reason",
}
METRICS = list(REASON_COLUMN)
COMPLETED_SALE_METRICS = [m for m in METRICS if m != "listing_to_contract_days"]

# The CDE layer the handbook links to (a shapefile in Web Mercator, EPSG:3857). The
# same layer's GeoJSON export is used: GeoJSON is longitude/latitude (WGS 84, CRS84)
# by definition, so no reprojection library is needed. Both exports were checked
# to hold the same 937 districts (CDSCode, DistrictType and DistrictName).
# The MLS Latitude/Longitude are ASSUMED to be WGS 84 too: the export states no CRS,
# so this is unverified, and no transformation is applied to them.
BOUNDARY_SOURCE = {
    "title": "California School District Areas 2024-25",
    "publisher": "California Department of Education",
    "vintage": "2024-25 academic year",
    "handbook_link": "https://data.ca.gov/dataset/california-school-district-areas-2024-25/"
                     "resource/7dfaf005-58eb-45db-93b1-7aff091b2172",
    "download_url": "https://gis.data.ca.gov/api/download/v1/items/"
                    "b0e3b936426a47ce9d9a2e77e2bb86cc/geojson?layers=0",
    "layer_url": "https://services3.arcgis.com/fdvHcZVgB2QSRNkL/arcgis/rest/services/"
                 "SchoolDistrictAreas2425/FeatureServer/0",
    "crs": "GeoJSON CRS84 (WGS 84 longitude/latitude)",
}
GEOJSON_CRS = {None, "urn:ogc:def:crs:OGC:1.3:CRS84"}  # None: RFC 7946 default, CRS84
# Elementary and High districts overlap by design (each serves part of the grade
# range in the same territory); Unified districts serve all grades. Each type gets
# its own columns, so a point inside one Elementary and one High district is one row.
DISTRICT_TYPES = ["Elementary", "High", "Unified"]
DISTRICT_COLUMNS = [
    "school_district_match_status", "school_district_match_count", "school_district_match_note",
    *[f"{t.lower()}_district_{x}" for t in DISTRICT_TYPES for x in ("name", "cds")]]
COORDINATE_FLAGS = ["zero_coordinate_flag", "invalid_coordinate_range_flag",
                    "positive_longitude_flag"]
COORDINATE_COLUMNS = ["Latitude", "Longitude", "missing_coordinates_flag", *COORDINATE_FLAGS]

REQUIRED_COLUMNS = [
    "MlsStatus", "ClosePrice", "ListPrice", "OriginalListPrice", "LivingArea", "DaysOnMarket",
    "CloseDate", "PurchaseContractDate", "ListingContractDate", "year_month", "rate_30yr_fixed",
    "negative_timeline_evaluable", "negative_timeline_flag",
    "purchase_after_close_evaluable", "purchase_after_close_flag",
    "duplicate_record_flag", "repeated_listing_key_flag", *COORDINATE_COLUMNS]

# Segment name -> grouping columns (handbook: PropertyType and PropertySubType,
# CountyOrParish and MLSAreaMajor, ListOfficeName and BuyerOfficeName)
SEGMENTS = {
    "property_type": ["PropertyType"],
    "property_subtype": ["PropertyType", "PropertySubType"],
    "county": ["CountyOrParish"],
    "county_mls_area": ["CountyOrParish", "MLSAreaMajor"],
    "list_office": ["ListOfficeName"],
    "buyer_office": ["BuyerOfficeName"],
}
SUMMARY_METRICS = ["ClosePrice", "price_ratio", "close_to_original_list_ratio",
                   "close_to_current_list_ratio", "price_per_sqft",
                   "DaysOnMarket", "listing_to_contract_days", "contract_to_close_days"]
SAMPLE_COLUMNS = ["ListingKey", "MlsStatus", "PropertySubType", "CountyOrParish", "ClosePrice",
                  "ListPrice", "OriginalListPrice", "LivingArea", "DaysOnMarket",
                  "ListingContractDate", "PurchaseContractDate", "CloseDate", "year_month"]

summary_rows = []


def record(dataset, section, item, count=None, detail="", show=True):
    """Keep a line for validation_summary.csv and print it."""
    summary_rows.append({"dataset": dataset, "section": section, "item": item,
                         "count": count, "detail": detail})
    if show:
        value = "" if count is None else f"{count:,}" if isinstance(count, int) else str(count)
        print(f"  {section:<20} {item:<52} {value:>10}  {detail}")


# ---- Reading inputs -------------------------------------------------------------

def as_bool(text):
    """'True'/'False' text (as the cleaning wrote it) -> bool. Anything else is an error."""
    mapped = text.map({"True": True, "False": False})
    if mapped.isna().any():
        raise ValueError(f"{text.name}: expected only True/False, found {int(mapped.isna().sum())} other values")
    return mapped.astype(bool)


def is_closed(df):
    return df["MlsStatus"].fillna("").eq("Closed")


def positive_number(df, col):
    """
    A numeric input that must be > 0 (all prices and LivingArea): its values, and
    (condition, reason) checks that make it unusable, in the order they are reported.
    """
    text = df[col]
    value = text.map(to_float, na_action="ignore").astype("float64")
    checks = []
    for suffix, why in [("_invalid_original", "set to null in cleaning as invalid"),
                        ("_unparsed_original", "could not be converted in cleaning")]:
        if col + suffix in df:
            checks.append((text.isna() & df[col + suffix].notna(), f"{col} {why} (original in {col}{suffix})"))
    checks += [(text.isna(), f"{col} missing"),
               (text.notna() & value.isna(), f"{col} is not a number"),
               (value <= 0, f"{col} <= 0")]  # a zero denominator never reaches the division
    return value, checks


def date_value(df, col):
    """A YYYY-MM-DD date input: its values, and the checks that make it unusable."""
    text = df[col]
    value = pd.to_datetime(text, format=DATE_FORMAT, errors="coerce")
    checks = []
    if f"{col}_unparsed_original" in df:
        checks.append((text.isna() & df[f"{col}_unparsed_original"].notna(),
                       f"{col} could not be parsed in cleaning (original in {col}_unparsed_original)"))
    checks += [(text.isna(), f"{col} missing"),
               (text.notna() & value.isna(), f"{col} is not a YYYY-MM-DD date")]
    return value, checks


def first_reason(index, checks):
    """The first check that applies to each row, or <NA> when none does."""
    reason = pd.Series(pd.NA, index=index, dtype="string")
    for condition, text in checks:
        reason = reason.mask(reason.isna() & condition, text)
    return reason


def finish(value, checks):
    """Null the metric wherever a check applies, and say which one."""
    reason = first_reason(value.index, checks)
    return value.where(reason.isna()), reason


def order_checks(df, rule, first, second, failure):
    """
    Use the cleaning's date-order check for a pair of dates: only rows where it
    could be evaluated (<rule>_evaluable) and passed (<rule>_flag False) get a value.
    """
    evaluable = as_bool(df[f"{rule}_evaluable"])
    if not evaluable.equals(first.notna() & second.notna()):
        raise ValueError(f"{rule}_evaluable does not match the dates in this file")
    return [(~evaluable, f"not evaluable ({rule}_evaluable = False)"),
            (as_bool(df[f"{rule}_flag"]), f"{failure} ({rule}_flag)")]


def days_between(start, end):
    return (end - start).dt.days.astype("Int64")


# ---- Metrics ----------------------------------------------------------------------

def engineer(df):
    """The Week 6 metric columns for df (same index), each with its null reason."""
    status = df["MlsStatus"].fillna("missing").astype("string")
    not_closed = [(~is_closed(df), "not Closed (MlsStatus " + status + ")")]
    new = {}

    price, price_checks = positive_number(df, "ClosePrice")
    for metric, denominator in RATIO_METRICS:
        value, checks = positive_number(df, denominator)
        new[metric], new[REASON_COLUMN[metric]] = finish(price / value,
                                                         not_closed + price_checks + checks)

    close, close_checks = date_value(df, "CloseDate")
    contract, contract_checks = date_value(df, "PurchaseContractDate")
    listed, listed_checks = date_value(df, "ListingContractDate")

    # Year / Month / YrMo: the close month. The date-order flags are about the
    # other dates in the pair, so they don't block the month (as for year_month).
    reason = first_reason(df.index, not_closed + close_checks)
    new["Year"] = close.dt.year.astype("Int64").where(reason.isna())
    new["Month"] = close.dt.month.astype("Int64").where(reason.isna())
    new["YrMo"] = close.dt.strftime("%Y-%m").where(reason.isna())
    new["YrMo_null_reason"] = reason

    new["listing_to_contract_days"], new["listing_to_contract_days_null_reason"] = finish(
        days_between(listed, contract),
        listed_checks + contract_checks + order_checks(
            df, "negative_timeline", listed, contract, "PurchaseContractDate before ListingContractDate"))
    new["contract_to_close_days"], new["contract_to_close_days_null_reason"] = finish(
        days_between(contract, close),
        not_closed + contract_checks + close_checks + order_checks(
            df, "purchase_after_close", contract, close, "PurchaseContractDate after CloseDate"))

    order = ["price_ratio", "price_ratio_null_reason", "close_to_original_list_ratio",
             "close_to_original_list_ratio_null_reason", "close_to_current_list_ratio",
             "close_to_current_list_ratio_null_reason", "price_per_sqft", "price_per_sqft_null_reason",
             "Year", "Month", "YrMo", "YrMo_null_reason", "listing_to_contract_days",
             "listing_to_contract_days_null_reason", "contract_to_close_days",
             "contract_to_close_days_null_reason"]
    return pd.DataFrame(new, index=df.index)[order]


# ---- School districts -------------------------------------------------------------

def get_boundaries():
    """The boundary file's source description; downloads the file once. None if unavailable."""
    meta_path = BOUNDARY_DIR / "source.json"
    if BOUNDARY_FILE.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else \
            {**BOUNDARY_SOURCE, "downloaded_utc": None, "note": "file provided locally"}
        return {**meta, "sha256_now": hashlib.sha256(BOUNDARY_FILE.read_bytes()).hexdigest()}
    BOUNDARY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BOUNDARY_FILE.with_name(BOUNDARY_FILE.name + ".tmp")
    try:
        with requests.get(BOUNDARY_SOURCE["download_url"], stream=True, timeout=300) as response:
            response.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in response.iter_content(1 << 20):
                    f.write(chunk)
    except requests.RequestException as err:
        tmp.unlink(missing_ok=True)
        print(f"  school districts: download failed ({type(err).__name__}); enrichment NOT done")
        return None
    os.replace(tmp, BOUNDARY_FILE)
    try:  # the layer's last edit date, for the record; optional
        layer = requests.get(BOUNDARY_SOURCE["layer_url"], params={"f": "json"}, timeout=60).json()
        edited = layer["editingInfo"]["dataLastEditDate"]
        edited = datetime.fromtimestamp(edited / 1000, timezone.utc).isoformat(timespec="seconds")
    except (requests.RequestException, ValueError, KeyError, TypeError):
        edited = None
    meta = {**BOUNDARY_SOURCE,
            "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "layer_data_last_edited_utc": edited,
            "bytes": BOUNDARY_FILE.stat().st_size,
            "sha256": hashlib.sha256(BOUNDARY_FILE.read_bytes()).hexdigest()}
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {**meta, "sha256_now": meta["sha256"]}


def load_districts(path):
    """District polygons: type, name, CDS code and parts (exterior ring, hole rings)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    crs = (data.get("crs") or {}).get("properties", {}).get("name")
    if crs not in GEOJSON_CRS:
        raise ValueError(f"{path.name}: CRS is {crs}; expected longitude/latitude (CRS84)")
    districts = []
    for feature in data["features"]:
        props, geometry = feature["properties"], feature["geometry"]
        if props["DistrictType"] not in DISTRICT_TYPES:
            raise ValueError(f"{path.name}: unknown DistrictType {props['DistrictType']!r}")
        if geometry["type"] not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"{path.name}: unexpected geometry {geometry['type']}")
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        parts = [(np.asarray(rings[0], dtype=float)[:, :2],
                  [np.asarray(hole, dtype=float)[:, :2] for hole in rings[1:]]) for rings in polygons]
        districts.append({"type": props["DistrictType"], "name": props["DistrictName"],
                          "cds": str(props["CDSCode"]), "year": props.get("Year"), "parts": parts})
    xy = np.concatenate([exterior for d in districts for exterior, _ in d["parts"]])
    if not ((xy[:, 0] > -125).all() and (xy[:, 0] < -113).all() and (xy[:, 1] > 32).all() and (xy[:, 1] < 43).all()):
        raise ValueError(f"{path.name}: coordinates are not California longitude/latitude")
    if len({d["cds"] for d in districts}) != len(districts):
        raise ValueError(f"{path.name}: CDSCode is not unique")
    return districts


def districts_containing(lon, lat, districts):
    """(point, district) index pairs for every district polygon that contains a point."""
    order = np.argsort(lon, kind="stable")
    lon_sorted = lon[order]
    points = np.column_stack([lon, lat])
    found_points, found_districts = [np.empty(0, int)], [np.empty(0, int)]
    for d, district in enumerate(districts):
        inside = np.zeros(len(lon), dtype=bool)
        for exterior, holes in district["parts"]:
            (x0, y0), (x1, y1) = exterior.min(axis=0), exterior.max(axis=0)
            candidates = order[np.searchsorted(lon_sorted, x0, "left"):np.searchsorted(lon_sorted, x1, "right")]
            candidates = candidates[(lat[candidates] >= y0) & (lat[candidates] <= y1)]
            if candidates.size == 0:
                continue
            hit = PolygonPath(exterior).contains_points(points[candidates])
            for hole in holes:
                hit &= ~PolygonPath(hole).contains_points(points[candidates])
            inside[candidates[hit]] = True
        found = np.flatnonzero(inside)
        found_points.append(found)
        found_districts.append(np.full(found.size, d))
    return np.concatenate(found_points), np.concatenate(found_districts)


def coordinate_keys(df):
    """
    'Latitude|Longitude' text for rows whose coordinates can be matched. Rows the
    cleaning flagged as missing or invalid are not matched (coordinates are never
    repaired); for them the status and reason are returned instead.
    """
    missing = as_bool(df["missing_coordinates_flag"])
    bad = pd.DataFrame({f: as_bool(df[f]) for f in COORDINATE_FLAGS})
    invalid = ~missing & bad.any(axis=1)
    status = pd.Series(pd.NA, index=df.index, dtype="string")
    status = status.mask(missing, "missing coordinates").mask(invalid, "invalid coordinates")
    note = pd.Series(pd.NA, index=df.index, dtype="string")
    note = note.mask(missing, "Latitude or Longitude missing (missing_coordinates_flag)")
    if invalid.any():
        note[invalid] = bad[invalid].apply(lambda row: ", ".join(row.index[row]), axis=1)
    key = (df["Latitude"] + "|" + df["Longitude"]).where(status.isna())
    return key, status, note


def match_coordinates(keys, districts):
    """
    District columns for each distinct 'Latitude|Longitude' key (index of the result).
    Matching once per location and then looking rows up by key means the spatial
    join can never add or drop a property row.
    """
    keys = pd.Index(keys).unique()
    lat = np.array([to_float(k.split("|")[0]) for k in keys], dtype=float)
    lon = np.array([to_float(k.split("|")[1]) for k in keys], dtype=float)
    usable = np.flatnonzero(np.isfinite(lat) & np.isfinite(lon))
    point, district = districts_containing(lon[usable], lat[usable], districts)
    hits = pd.DataFrame({"point": usable[point],
                         "type": [districts[i]["type"] for i in district],
                         "name": [districts[i]["name"] for i in district],
                         "cds": [districts[i]["cds"] for i in district]})
    n = len(keys)
    out = pd.DataFrame(index=pd.RangeIndex(n))
    per_type = {}
    ambiguous_notes = {}
    for t in DISTRICT_TYPES:
        h = hits[hits["type"] == t]
        per_type[t] = h.groupby("point").size().reindex(out.index, fill_value=0).to_numpy()
        first = h.drop_duplicates("point").set_index("point").reindex(out.index)
        single = per_type[t] == 1
        out[f"{t.lower()}_district_name"] = first["name"].astype("string").where(single)
        out[f"{t.lower()}_district_cds"] = first["cds"].astype("string").where(single)
        for p, codes in h[per_type[t][h["point"]] > 1].groupby("point")["cds"]:
            ambiguous_notes.setdefault(p, []).append(f"{len(codes)} {t} districts ({'|'.join(codes)})")
    total = sum(per_type.values())
    ambiguous = np.isin(np.arange(n), list(ambiguous_notes))
    usable_mask = np.isin(np.arange(n), usable)
    out["school_district_match_status"] = pd.Series(np.select(
        [~usable_mask, ambiguous, total == 0], ["invalid coordinates", "ambiguous", "unmatched"],
        "matched"), dtype="string")
    out["school_district_match_count"] = pd.Series(total, dtype="Int64").where(usable_mask)
    outside = ~((lat >= CA_BOX["lat_min"]) & (lat <= CA_BOX["lat_max"]) &
                (lon >= CA_BOX["lon_min"]) & (lon <= CA_BOX["lon_max"]))
    notes = []
    for i in range(n):
        if not usable_mask[i]:
            notes.append("Latitude or Longitude is not a number")
        elif i in ambiguous_notes:
            notes.append("; ".join(ambiguous_notes[i]))
        elif total[i] == 0:
            notes.append("no district contains this point" +
                         (" (outside the CA bounding box)" if outside[i] else ""))
        else:
            notes.append(" + ".join(t for t in DISTRICT_TYPES if per_type[t][i] == 1))
    out["school_district_match_note"] = pd.Series(notes, dtype="string")
    out.index = keys
    return out[DISTRICT_COLUMNS]


def district_lookup(paths, districts):
    """Match every distinct usable coordinate pair in the input files, once."""
    keys = []
    for path in paths:
        coords = pd.read_csv(path, usecols=COORDINATE_COLUMNS, dtype=str,
                             keep_default_na=False, na_values=[""])
        keys.append(coordinate_keys(coords)[0].dropna())
    return match_coordinates(pd.concat(keys), districts)


def add_districts(df, matches):
    """District columns for each row of df, looked up by its coordinate key."""
    key, status, note = coordinate_keys(df)
    if not matches.index.is_unique:
        raise ValueError("district lookup has repeated coordinate keys")
    found = matches.reindex(key.to_numpy())  # one result per input row, never more
    found.index = df.index
    found["school_district_match_status"] = found["school_district_match_status"].where(key.notna(), status)
    found["school_district_match_note"] = found["school_district_match_note"].where(key.notna(), note)
    if len(found) != len(df) or found["school_district_match_status"].isna().any():
        raise ValueError("district lookup did not give exactly one status per row")
    return found[DISTRICT_COLUMNS]


# ---- Checks and saving -------------------------------------------------------------

def same_strings(a, b):
    """Strict text comparison: same missing cells and the same text everywhere else."""
    na_a, na_b = a.isna().to_numpy(), b.isna().to_numpy()
    return bool((na_a == na_b).all() and
                (a[~na_a].astype(str).to_numpy() == b[~na_b].astype(str).to_numpy()).all())


def same_numbers(a, b):
    """Exact numeric comparison: same missing cells and the same float everywhere else."""
    a, b = a.astype("Float64").to_numpy(dtype=float, na_value=np.nan), \
        b.astype("Float64").to_numpy(dtype=float, na_value=np.nan)
    return bool(np.array_equal(a, b, equal_nan=True))


def validate(df, new, name, key_col):
    """Formula, null-reason and preservation checks in memory, before saving."""
    problems = []
    closed = is_closed(df)
    for metric in METRICS:
        reason = new[REASON_COLUMN[metric]]
        if not (new[metric].isna() == reason.notna()).all():
            problems.append(f"{metric}: a null value without a reason, or a reason on a value")
    for metric in COMPLETED_SALE_METRICS:
        if new.loc[~closed, metric].notna().any():
            problems.append(f"{metric} filled for a record that isn't Closed")
    for metric, denominator in RATIO_METRICS:
        value = new[metric].dropna()
        if not np.isfinite(value).all() or (value <= 0).any():
            problems.append(f"{metric} has an infinite or non-positive value")
        # independent recomputation with pandas' own parser (may differ in the last digit)
        check = pd.to_numeric(df["ClosePrice"]) / pd.to_numeric(df[denominator])
        if not np.allclose(value, check.loc[value.index], rtol=1e-12, atol=0):
            problems.append(f"{metric} differs from ClosePrice / {denominator}")
    for metric, start, end in [("listing_to_contract_days", "ListingContractDate", "PurchaseContractDate"),
                               ("contract_to_close_days", "PurchaseContractDate", "CloseDate")]:
        value = new[metric].dropna()
        if (value < 0).any():
            problems.append(f"{metric} has a negative value")
        check = (pd.to_datetime(df[end]) - pd.to_datetime(df[start])).dt.days
        if not (value == check.loc[value.index]).all():
            problems.append(f"{metric} differs from {end} - {start}")
    if PRICE_RATIO_DENOMINATOR == "OriginalListPrice":  # the handbook's two ratios are one formula
        if not (same_numbers(new["price_ratio"], new["close_to_original_list_ratio"]) and
                same_strings(new["price_ratio_null_reason"], new["close_to_original_list_ratio_null_reason"])):
            problems.append("price_ratio differs from close_to_original_list_ratio")
        record(name, "validation", "price_ratio identical to close_to_original_list_ratio", len(df),
               "same values, nulls and null reasons in every row")

    # year_month was built from key_col (CloseDate for sold, ListingContractDate for
    # listings); YrMo is always the CloseDate month, and only for Closed records.
    basis = pd.to_datetime(df[key_col], format=DATE_FORMAT, errors="coerce").dt.strftime("%Y-%m")
    wrong = basis.notna() & (df["year_month"] != basis)
    record(name, "validation", f"year_month equals the {key_col} month", int((basis.notna() & ~wrong).sum()),
           f"mismatches: {int(wrong.sum())}; rows without {key_col}: {int(basis.isna().sum())}")
    if wrong.any():
        problems.append(f"year_month differs from the {key_col} month in {int(wrong.sum())} rows")
    close_month = pd.to_datetime(df["CloseDate"], format=DATE_FORMAT, errors="coerce").dt.strftime("%Y-%m")
    if not same_strings(new["YrMo"], close_month.where(closed)):
        problems.append("YrMo differs from the CloseDate month of Closed records")
    month = new["YrMo"].dropna()
    same = month == df.loc[month.index, "year_month"]
    record(name, "validation", "YrMo equals the CloseDate month", len(month), "every Closed record with a CloseDate")
    if key_col == "CloseDate":  # same date basis, so they must agree in every row
        if not same.all():
            problems.append(f"YrMo differs from year_month in {int((~same).sum())} rows")
        record(name, "validation", "YrMo equals year_month (both from CloseDate)", int(same.sum()),
               f"differences: {int((~same).sum())}")
    else:  # different date bases, so differences are expected
        record(name, "validation", f"YrMo equals year_month (year_month is from {key_col})", int(same.sum()),
               f"of {len(month):,} rows with a YrMo; the other {int((~same).sum()):,} closed in a "
               f"different month from the {key_col} month (expected, not an error)")
    clash = [c for c in new.columns if c in df.columns]
    if clash:
        problems.append(f"new columns already exist in the input: {clash}")
    if problems:
        raise ValueError(f"{name}: " + "; ".join(problems))
    record(name, "validation", "metric formulas and null reasons", len(df),
           "every null metric has a reason; ratios finite and > 0; day counts >= 0; "
           "completed-sale metrics only on Closed; values match an independent recomputation")


def save_and_check(df, new, path, name):
    """
    Write, reload as text, and check before replacing any earlier file:
      - same rows; the input columns first and unchanged (identical text), new columns after;
      - every metric reloads to exactly the value computed in memory;
      - reasons and district columns reload as the same text (CDS codes keep leading zeros).
    """
    out = pd.concat([df, new], axis=1)
    tmp = path.with_name(path.name + ".tmp")
    try:
        out.to_csv(tmp, index=False)
        back = load(tmp)
        problems = []
        if len(back) != len(df) or list(back.columns) != list(out.columns):
            problems.append("shape or column order changed on reload")
        changed = [c for c in df.columns if not same_text(back[c], df[c])]
        if changed:
            problems.append(f"input columns changed: {changed}")
        for col in new.columns:
            if pd.api.types.is_numeric_dtype(new[col]):
                ok = same_numbers(back[col].map(to_float, na_action="ignore").astype("float64"), new[col])
            else:
                ok = same_strings(back[col], new[col])
            if not ok:
                problems.append(f"{col} did not reload to the same values")
        if back[[c for c in new.columns if pd.api.types.is_numeric_dtype(new[c])]].isin(
                ["inf", "-inf", "nan"]).any().any():
            problems.append("an infinite or 'nan' value was written")
        if problems:
            raise ValueError(f"{path.name}: " + "; ".join(problems))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    record(name, "saved file", path.name, len(back),
           f"reloaded: {len(back):,} rows x {back.shape[1]} columns; all {df.shape[1]} input columns "
           f"identical to the input text (identifiers, year_month, rate_30yr_fixed, coordinates, "
           f"audit values and flags); {new.shape[1]} new columns reload to the same values")


# ---- Summaries ----------------------------------------------------------------------

def summary_frame(df, new):
    """One row per record: segment columns, metrics, Closed and duplicate markers."""
    closed = is_closed(df)
    price, checks = positive_number(df, "ClosePrice")
    dom = df["DaysOnMarket"].map(to_float, na_action="ignore").astype("float64")
    frame = pd.DataFrame({
        "closed": closed,
        "duplicate": as_bool(df["duplicate_record_flag"]),
        # Completed-sale fields only count for Closed records
        "ClosePrice": price.where(first_reason(df.index, checks).isna() & closed),
        "DaysOnMarket": dom.where(closed & (dom >= 0)),
        **{m: new[m].astype("float64") for m in SUMMARY_METRICS if m in new}})
    for col in {c for keys in SEGMENTS.values() for c in keys if c in df}:
        frame[col] = df[col].fillna("(missing)")
    return frame


def summarize(frame, keys):
    """
    Counts and statistics per segment. Exact later duplicates (duplicate_record_flag)
    are excluded; repeated ListingKeys that aren't exact duplicates are kept. Each
    metric uses only the rows where it has a value, so exclusions are per metric.
    """
    used = frame[~frame["duplicate"]]
    groups = used.groupby(keys, sort=False)
    out = pd.DataFrame({"records": frame.groupby(keys, sort=False).size()})
    out["duplicate_rows_excluded"] = frame[frame["duplicate"]].groupby(keys).size().reindex(out.index, fill_value=0)
    out["records_used"] = groups.size().reindex(out.index, fill_value=0)
    out["closed_records_used"] = groups["closed"].sum().reindex(out.index, fill_value=0).astype(int)
    for metric in SUMMARY_METRICS:
        values = groups[metric]
        stats = pd.DataFrame({"n": values.count(), "median": values.median(), "mean": values.mean(),
                              "p25": values.quantile(0.25), "p75": values.quantile(0.75)}).reindex(out.index)
        stats["n"] = stats["n"].fillna(0).astype(int)
        digits = 4 if "ratio" in metric else 2
        for stat in stats:
            out[f"{metric}_{stat}"] = stats[stat] if stat == "n" else stats[stat].round(digits)
    return out.reset_index().sort_values(["records_used", *keys], ascending=[False, *[True] * len(keys)],
                                         kind="stable")


def make_sample(df, new, name):
    """Rows with every metric filled, then one example of each common null reason."""
    shown = pd.concat([df[[c for c in SAMPLE_COLUMNS if c in df]], new], axis=1)
    filled = new[METRICS].notna().all(axis=1)
    if "school_district_match_status" in new:
        filled &= new["school_district_match_status"].eq("matched").fillna(False)
    parts = [shown[filled].sample(n=min(8, int(filled.sum())), random_state=6)
             .assign(sample_group="every metric filled")]
    for reason_col in dict.fromkeys(REASON_COLUMN.values()):
        for reason in new[reason_col].value_counts().head(3).index:
            parts.append(shown[new[reason_col].eq(reason).fillna(False)].head(1)
                         .assign(sample_group=f"{reason_col}: {reason}"))
    sample = pd.concat(parts)
    sample = sample[~sample.index.duplicated()]
    return sample.assign(dataset=name)[["dataset", "sample_group", *shown.columns]]


# ---- One dataset ----------------------------------------------------------------------

def describe(values):
    """n, min, 1st/25th/50th/75th/99th percentile, max of the non-null values."""
    v = values.dropna().astype("float64")
    if v.empty:
        return {"n": 0}
    q = v.quantile([0.01, 0.25, 0.5, 0.75, 0.99])
    return {"n": len(v), "min": v.min(), "p1": q[0.01], "p25": q[0.25], "median": q[0.5],
            "p75": q[0.75], "p99": q[0.99], "max": v.max()}


def process(name, in_path, out_path, key_col, matches=None):
    """Engineer, check, save and summarize one dataset. Returns what the report needs."""
    print(f"\n=== {name}")
    df = load(in_path)
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df]
    if missing_cols:
        raise ValueError(f"{in_path.name}: required columns missing: {missing_cols}")
    record(name, "shape", "rows in", len(df))
    record(name, "shape", "columns in", df.shape[1])
    closed = is_closed(df)
    record(name, "records", "Closed", int(closed.sum()), f"not Closed: {int((~closed).sum()):,}")

    new = engineer(df)
    for metric in METRICS:
        reason = new[REASON_COLUMN[metric]]
        record(name, "metric coverage", f"{metric}: filled", int(new[metric].notna().sum()),
               f"null: {int(new[metric].isna().sum()):,}")
        if metric in ("Month", "YrMo"):
            continue  # same reasons as Year
        for why, count in reason.value_counts().items():
            record(name, "null reasons", f"{metric}: {why}", int(count), show=False)

    dom_text = df["DaysOnMarket"]
    dom_audit = df["DaysOnMarket_invalid_original"] if "DaysOnMarket_invalid_original" in df else \
        pd.Series(pd.NA, index=df.index)
    record(name, "DaysOnMarket", "Closed records with a value", int((closed & dom_text.notna()).sum()),
           "the MLS field as cleaned; not recomputed from dates")
    record(name, "DaysOnMarket", "Closed records, value 0", int((closed & dom_text.eq("0")).sum()),
           "0 is kept as a valid value")
    record(name, "DaysOnMarket", "missing in the input", int((dom_text.isna() & dom_audit.isna()).sum()))
    record(name, "DaysOnMarket", "negative, set to null in cleaning", int(dom_audit.notna().sum()),
           "original kept in DaysOnMarket_invalid_original")
    record(name, "DaysOnMarket", "records not Closed (excluded from summaries)", int((~closed).sum()),
           "for these, DaysOnMarket is days so far, not time to sell")

    districts = None
    if matches is not None:
        districts = add_districts(df, matches)
        new = pd.concat([new, districts], axis=1)
        for status in ["matched", "ambiguous", "unmatched", "missing coordinates", "invalid coordinates"]:
            record(name, "school districts", status, int(districts["school_district_match_status"].eq(status).sum()))
        matched = districts["school_district_match_status"].eq("matched").fillna(False)
        for combo, count in districts.loc[matched, "school_district_match_note"].value_counts().items():
            record(name, "district types matched", combo, int(count))
        outside = as_bool(df["outside_ca_bbox_flag"]) if "outside_ca_bbox_flag" in df else \
            pd.Series(False, index=df.index)
        unmatched = districts["school_district_match_status"].eq("unmatched").fillna(False)
        record(name, "school districts", "unmatched and outside the CA bounding box",
               int((unmatched & outside).sum()), f"inside the box: {int((unmatched & ~outside).sum()):,}")
        if "HighSchoolDistrict" in df:  # a rough cross-check against the MLS's own field
            mls = df["HighSchoolDistrict"].astype("string").str.strip().str.casefold()
            found_name = districts["high_district_name"].fillna(districts["unified_district_name"])
            found = found_name.str.casefold()
            compared = mls.notna() & ~mls.isin(["other", "none", "unknown"]) & found.notna()
            agree = compared & (mls == found).fillna(False)
            record(name, "school districts", "MLS HighSchoolDistrict agrees with match", int(agree.sum()),
                   f"of {int(compared.sum()):,} rows with both (case-insensitive exact name; "
                   f"'Other'/'None'/'Unknown' skipped)")
            pairs = pd.DataFrame({"mls": df["HighSchoolDistrict"], "matched": found_name})[compared & ~agree]
            for (mls_name, found_name), count in pairs.value_counts().head(8).items():
                record(name, "district disagreements", f"{mls_name} -> {found_name}", int(count), show=False)

    validate(df, new, name, key_col)
    save_and_check(df, new, out_path, name)
    record(name, "shape", "rows out", len(df), "no row added or removed")
    record(name, "shape", "columns out", df.shape[1] + new.shape[1], f"{new.shape[1]} new columns")

    frame = summary_frame(df, new)
    duplicate = frame["duplicate"]
    record(name, "summary exclusions", "exact later duplicates excluded", int(duplicate.sum()),
           "duplicate_record_flag; the first copy of each is kept")
    record(name, "summary exclusions", "repeated-ListingKey rows kept",
           int(as_bool(df["repeated_listing_key_flag"]).sum()), "not exact duplicates; not deduplicated")
    record(name, "summary exclusions", "records used in summaries", int((~duplicate).sum()))
    summaries = {}
    for segment, keys in SEGMENTS.items():
        if all(k in df for k in keys):
            summaries[segment] = summarize(frame, keys).assign(dataset=name)
            record(name, "summaries", segment, len(summaries[segment]), f"groups by {' + '.join(keys)}")
        else:
            record(name, "summaries", segment, None, "not in this dataset")
    distribution = pd.DataFrame({m: describe(frame.loc[~duplicate, m]) for m in SUMMARY_METRICS}).T
    return {"summaries": summaries, "sample": make_sample(df, new, name), "distribution": distribution,
            "rows": len(df), "columns_in": df.shape[1], "columns_out": df.shape[1] + new.shape[1]}


# ---- Report -------------------------------------------------------------------------

def cell_text(v):
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, float):
        if np.isnan(v):
            return ""
        if v != 0 and abs(v) < 0.01:
            return f"{v:.2e}"  # small but positive values must not print as 0
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return str(v)


def md_table(df, index=True):
    if df.empty:
        return "_none_"
    cols = ([df.index.name or ""] if index else []) + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for idx, row in df.iterrows():
        cells = ([str(idx)] if index else []) + [cell_text(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def counts(dataset, section):
    rows = [r for r in summary_rows if r["dataset"] == dataset and r["section"] == section]
    return pd.DataFrame([{"item": r["item"], "count": "" if r["count"] is None else int(r["count"]),
                          "detail": r["detail"]} for r in rows])


def write_report(path, results, meta):
    started = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Week 6 – Feature Engineering validation report", "",
        f"Generated by `week6_feature_engineering.py` on {started}. Every count is also in "
        "`validation_summary.csv`.", "",
        "## Requirements (IDX Exchange Intern Handbook, Week 6)", "",
        "Verified from the handbook: the metric table (names, formulas, purposes), school districts "
        "from latitude/longitude using the linked data.ca.gov resource, segment analysis by "
        "PropertyType and PropertySubType, CountyOrParish and MLSAreaMajor, ListOfficeName and "
        "BuyerOfficeName, and the deliverable (a .py script, a sample output table and at least one "
        "summary grouped by PropertyType or CountyOrParish).", "",
        f"The handbook gives ClosePrice / OriginalListPrice for both Price Ratio and Close to Original "
        f"List Ratio. It is followed literally (price_ratio = ClosePrice / {PRICE_RATIO_DENOMINATOR}), "
        "so `price_ratio` and `close_to_original_list_ratio` are identical; the Checks below confirm it.", "",
        "Added beyond the handbook: `close_to_current_list_ratio` = ClosePrice / ListPrice, an extra "
        "analytical metric. It is not a handbook requirement and does not replace either required ratio.", "",
        "Choices not stated in the handbook: completed-sale metrics only for Closed records; null-reason "
        "columns; column names other than Year, Month and YrMo; YrMo written as YYYY-MM; the summary "
        "statistics; exact duplicates excluded from summaries.", "",
        "## Formulas and null rules", "",
        "| Column | Formula | Null when |", "|---|---|---|",
        f"| `price_ratio` (handbook) | ClosePrice / {PRICE_RATIO_DENOMINATOR} | not Closed; ClosePrice or "
        f"{PRICE_RATIO_DENOMINATOR} missing, invalid or <= 0 |",
        "| `close_to_original_list_ratio` (handbook) | ClosePrice / OriginalListPrice | not Closed; "
        "either price missing, invalid or <= 0 |",
        "| `close_to_current_list_ratio` (extra) | ClosePrice / ListPrice | not Closed; either price "
        "missing, invalid or <= 0 |",
        "| `price_per_sqft` | ClosePrice / LivingArea | not Closed; ClosePrice or LivingArea missing, "
        "invalid or <= 0 |",
        "| `DaysOnMarket` | the MLS field, unchanged | (existing column) negative values were set to null "
        "in cleaning, originals in `DaysOnMarket_invalid_original` |",
        "| `Year`, `Month`, `YrMo` | CloseDate year, month, YYYY-MM | not Closed; CloseDate missing |",
        "| `listing_to_contract_days` | PurchaseContractDate − ListingContractDate (days); any status, "
        "since it uses no close field | a date missing; `negative_timeline_evaluable` False; "
        "`negative_timeline_flag` True |",
        "| `contract_to_close_days` | CloseDate − PurchaseContractDate (days) | not Closed; a date "
        "missing; `purchase_after_close_evaluable` False; `purchase_after_close_flag` True |", "",
        "A denominator must be > 0, so no division by zero happens and no infinite value is written. "
        "`<metric>_null_reason` holds the first failing check, in the order listed.", ""]
    for name, res in results.items():
        lines += [f"## {name}", "",
                  f"Rows: {res['rows']:,} in, {res['rows']:,} out. Columns: {res['columns_in']} in, "
                  f"{res['columns_out']} out.", "",
                  "### Coverage", "", md_table(counts(name, "metric coverage"), index=False), "",
                  "### Null reasons", "", md_table(counts(name, "null reasons"), index=False), "",
                  "### Days on market", "", md_table(counts(name, "DaysOnMarket"), index=False), "",
                  "### Distributions (records used in summaries)", "",
                  "Not outlier-filtered; outliers are Week 7.", "",
                  md_table(res["distribution"].rename_axis("metric")), "",
                  "### Summary exclusions", "", md_table(counts(name, "summary exclusions"), index=False), ""]
        if meta:
            lines += ["### School districts", "", md_table(counts(name, "school districts"), index=False), "",
                      "District types matched (see Limitations for Elementary only and Elementary + Unified):", "",
                      md_table(counts(name, "district types matched"), index=False), ""]
            dis = counts(name, "district disagreements")
            if len(dis):
                lines += ["Most common disagreements with the MLS HighSchoolDistrict field "
                          "(MLS -> matched):", "", md_table(dis, index=False), ""]
        lines += ["### Checks", "", md_table(pd.concat([counts(name, "validation"), counts(name, "saved file")]),
                                             index=False), ""]
    if meta:
        lines += ["## Boundary source", "",
                  f"- {meta['title']}, {meta['publisher']} ({meta['vintage']}).",
                  f"- Handbook link: {meta['handbook_link']}",
                  f"- Downloaded from: {meta['download_url']} on {meta.get('downloaded_utc')} (UTC); "
                  f"layer data last edited {meta.get('layer_data_last_edited_utc')}.",
                  f"- Boundary CRS (documented in the file): {meta['crs']}.",
                  "- MLS Latitude/Longitude CRS (assumed, not verified): treated as WGS 84 decimal "
                  "degrees with no transformation. The MLS export does not state a datum or CRS.",
                  f"- SHA-256: {meta.get('sha256_now')}", "",
                  md_table(counts("boundaries", "boundaries"), index=False), ""]
    else:
        lines += ["## School districts: NOT DONE", "",
                  "The boundary file could not be downloaded, so the enrichment is incomplete.", ""]
    lines += [
        "## Limitations", "",
        "- `price_ratio` duplicates `close_to_original_list_ratio` because the handbook gives both the "
        "same formula.",
        "- Outliers are not removed (Week 7). Some ratios and prices per square foot are extreme (see "
        "the distributions), for example where OriginalListPrice or ListPrice is $1.",
        "- Points exactly on a district boundary may match both neighbours (reported as ambiguous) or "
        "neither.",
        "- Boundary vintage: the 2024-25 boundaries are used for sales and listings from every year "
        "(2024 to 2026); boundary changes in other years are not reflected.",
        "- MLS coordinates are assumed to be WGS 84; their source CRS is unverified. Only the boundary "
        "file's CRS is documented.",
        "- \"Elementary + Unified\" is kept as matched: the CDE layer overlaps some elementary districts "
        "with a unified district that serves their upper grades (for example Garvey Elementary and "
        "Alhambra Unified). \"Elementary\" alone means no High or Unified polygon contains the point; "
        "in this data it is almost all Hermosa Beach City Elementary, so high_district_name and "
        "unified_district_name are blank there.",
        "- Some points are unmatched within the California bounding box; cause not verified. "
        "Coordinates are not moved to the nearest district.",
        "- Repeated ListingKeys are kept in the summaries; why they repeat is unverified.",
        "- On listings that aren't Closed, CloseDate's meaning is unverified, so completed-sale "
        "metrics are left null there.",
        "- The HighSchoolDistrict comparison is a sanity check on names, not ground truth.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---- Main -------------------------------------------------------------------------

def main():
    for name, (in_file, _, _) in DATASETS.items():
        if not (IN_DIR / in_file).exists():
            raise FileNotFoundError(f"{IN_DIR / in_file} not found. Run week4_5_cleaning.py first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== school district boundaries")
    meta = get_boundaries()
    matches = None
    if meta:
        districts = load_districts(BOUNDARY_FILE)
        for t in DISTRICT_TYPES:
            record("boundaries", "boundaries", f"{t} districts", sum(d["type"] == t for d in districts))
        record("boundaries", "boundaries", "school years in the file", None,
               ", ".join(sorted({str(d["year"]) for d in districts})))
        if meta.get("sha256") and meta["sha256"] != meta["sha256_now"]:
            raise ValueError(f"{BOUNDARY_FILE.name} changed since it was downloaded (SHA-256 differs)")
        matches = district_lookup([IN_DIR / f for f, _, _ in DATASETS.values()], districts)
        record("boundaries", "boundaries", "distinct coordinate pairs matched", len(matches),
               "both datasets; each matched once and looked up per row")

    results = {}
    for name, (in_file, out_file, key_col) in DATASETS.items():
        results[name] = process(name, IN_DIR / in_file, OUT_DIR / out_file, key_col, matches)

    for segment in SEGMENTS:
        tables = [r["summaries"][segment] for r in results.values() if segment in r["summaries"]]
        table = pd.concat(tables)
        table = table[["dataset", *[c for c in table.columns if c != "dataset"]]]
        table.to_csv(OUT_DIR / f"summary_by_{segment}.csv", index=False)
    sample = pd.concat([r["sample"] for r in results.values()])
    sample.to_csv(OUT_DIR / "sample_engineered.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(OUT_DIR / "validation_summary.csv", index=False)
    write_report(OUT_DIR / "validation_report.md", results, meta)

    county = results["sold"]["summaries"]["county"]
    show = ["CountyOrParish", "records_used", "ClosePrice_median", "price_ratio_median",
            "close_to_original_list_ratio_median", "close_to_current_list_ratio_median",
            "price_per_sqft_median", "DaysOnMarket_median", "listing_to_contract_days_median",
            "contract_to_close_days_median"]
    print("\nSold, by CountyOrParish (top 10 by records; exact duplicates excluded):")
    print(county[show].head(10).to_string(index=False))
    print("\nSample (sold, every metric filled):")
    cols = ["ListingKey", "ClosePrice", "ListPrice", "OriginalListPrice", "LivingArea", "price_ratio",
            "close_to_original_list_ratio", "close_to_current_list_ratio", "price_per_sqft",
            "DaysOnMarket", "YrMo", "listing_to_contract_days", "contract_to_close_days"]
    print(sample[(sample["dataset"] == "sold") & (sample["sample_group"] == "every metric filled")][cols]
          .to_string(index=False))
    print(f"\nSaved to {OUT_DIR}")
    if not meta:
        print("School-district enrichment is INCOMPLETE: boundaries unavailable.")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as err:
        sys.exit(f"ERROR: {err}")
