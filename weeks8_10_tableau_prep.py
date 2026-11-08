"""
Weeks 8-10 - Tableau data preparation

Builds the two Tableau data sources (sales and listings), reference calculations to
check the dashboards against, a ZIP geography check and a validation report. The
workbooks themselves are built by hand in Tableau: see weeks8_10_tableau_build_guide.md.

Inputs (read only, never modified):
  output/week7/sold_flagged.csv        sold rows + Week 6 metrics + Week 7 flags
  output/week7/listings_flagged.csv    listings of every status + flags
  output/run_report.txt, csv/download_manifest.csv   which file each month came from
  output/weeks8_10/reference/2024_Gaz_zcta_national.zip
      Census ZCTA list, downloaded once if missing (used only to predict which ZIP
      codes Tableau may fail to place; Tableau's own geocoding is what counts)
Outputs: output/weeks8_10/
  tableau_sales.csv       one row per sold record (exact later duplicates removed)
  tableau_listings.csv    one row per listing record, every status
  reference_monthly.csv, reference_agents_top100.csv, reference_offices_top100.csv,
  reference_zip.csv, reference_segments.csv     numbers the dashboards should show
  zip_geography_check.csv  ZIP codes Tableau may not place, with row counts
  month_coverage.csv       months in each source and where each month's file came from
  validation_report.md

Counting policy (evidence in the validation report)
  - Exact later duplicates (duplicate_record_flag) are dropped.
  - A ListingKey identifies one listing, so it counts as one sale (sales) or one new
    listing (listings). The repeated keys are snapshots of the same listing from
    different monthly files; the most recently updated one (latest
    ContractStatusChangeDate, then the later date, then the later file row) is the
    counted row: transaction_row = 1. The other rows stay in the files with 0.
Sales modes (both stored as 0/1 columns; a Tableau parameter picks one)
  - "Valid before IQR": metric-specific validity. A sale counts if it closed; price
    metrics need a valid ClosePrice, DaysOnMarket metrics a valid DaysOnMarket and the
    ratio a valid close_to_original_list_ratio. A missing LivingArea or DaysOnMarket
    never removes a sale from counts or volume.
  - "Week 7 IQR-filtered": the Week 7 filtered population (analysis_include).
  New-listing counts never depend on either mode.

Tests: python test_weeks8_10_tableau_prep.py (synthetic data, no real files needed).
Requires: pandas, numpy, requests; week1_aggregate.py, week4_5_cleaning.py,
week6_feature_engineering.py, week7_outlier_detection.py (helpers); the Week 7 outputs.
"""

import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

from week1_aggregate import BASE_DIR, OUTPUT_DIR
from week4_5_cleaning import load, same_text
from week6_feature_engineering import md_table
from week7_outlier_detection import sha256

IN_DIR = OUTPUT_DIR / "week7"
OUT_DIR = OUTPUT_DIR / "weeks8_10"
REFERENCE_DIR = OUT_DIR / "reference"
ZCTA_FILE = REFERENCE_DIR / "2024_Gaz_zcta_national.zip"
ZCTA_URL = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/"
            "2024_Gaz_zcta_national.zip")
SOLD_IN, LISTINGS_IN = IN_DIR / "sold_flagged.csv", IN_DIR / "listings_flagged.csv"

MODE_IQR = "Week 7 IQR-filtered"
MODE_VALID = "Valid before IQR"
VALID_VALUE = {"within bounds", "below lower bound", "above upper bound"}  # Week 7: a valid value
MISSING_LABEL = "(missing)"
UNATTRIBUTED = "(unattributed)"
# Placeholder agent/office names seen in the data ("Non-Member", "PWNONMEMBER",
# "Unknown Office", ...). They are kept in the files but never ranked as competitors.
PLACEHOLDER = re.compile(r"non[\s\-/]*member|^unknown(?: office| agent)?$", re.IGNORECASE)
TOP_N = 100

SALES_COLUMNS = [
    "ListingKey", "ListingId", "transaction_row", "listing_key_repeat_class",
    "CloseDate", "sale_month", "sale_yrmo",
    "county_label", "city_label", "zip_code", "state_label", "property_subtype_label",
    "CountyOrParish", "City", "PostalCode", "StateOrProvince", "PropertyType", "PropertySubType",
    "zip_status", "zip_in_census_zcta", "zip_in_california_range", "zcta_latitude", "zcta_longitude",
    "Latitude", "Longitude",
    "ClosePrice", "ListPrice", "OriginalListPrice", "LivingArea", "DaysOnMarket",
    "close_to_original_list_ratio",
    "listing_agent_key", "listing_agent_label", "listing_agent_name", "listing_agent_identified",
    "ListAgentFullName", "listing_office_key", "listing_office_label", "listing_office_identified",
    "ListOfficeName",
    "ClosePrice_iqr_status", "LivingArea_iqr_status", "DaysOnMarket_iqr_status", "iqr_outlier_flag",
    "analysis_include", "analysis_exclusion_reasons",
    "valid_sale_count", "valid_price", "valid_dom", "valid_ratio",
    "iqr_sale_count", "iqr_price", "iqr_dom", "iqr_ratio"]
LISTINGS_COLUMNS = [
    "ListingKey", "ListingId", "MlsStatus", "transaction_row", "listing_key_repeat_class",
    "new_listing_event", "ListingContractDate", "listing_month", "listing_yrmo",
    "county_label", "city_label", "zip_code", "state_label", "property_subtype_label",
    "CountyOrParish", "City", "PostalCode", "StateOrProvince", "PropertyType", "PropertySubType",
    "zip_status", "zip_in_census_zcta", "zip_in_california_range",
    "ListPrice", "OriginalListPrice"]
ZERO_ONE = ["transaction_row", "zip_in_census_zcta", "zip_in_california_range",
            "listing_agent_identified", "listing_office_identified", "new_listing_event",
            "valid_sale_count", "valid_price", "valid_dom", "valid_ratio",
            "iqr_sale_count", "iqr_price", "iqr_dom", "iqr_ratio"]
# Original columns that must reach Tableau exactly as they were
PRESERVED = ["ListingKey", "ListingId", "PostalCode", "City", "CountyOrParish", "StateOrProvince",
             "PropertyType", "PropertySubType", "ClosePrice", "ListPrice", "OriginalListPrice",
             "LivingArea", "DaysOnMarket", "CloseDate", "ListingContractDate", "MlsStatus",
             "ListAgentFullName", "ListOfficeName", "close_to_original_list_ratio", "Latitude", "Longitude",
             "ClosePrice_iqr_status", "LivingArea_iqr_status", "DaysOnMarket_iqr_status",
             "iqr_outlier_flag", "analysis_include", "analysis_exclusion_reasons"]

notes = []  # (section, item, value) lines for the validation report


def note(section, item, value=""):
    notes.append((section, item, value))
    print(f"  {section:<22} {item:<58} {value}")


# ---- Labels and geography -----------------------------------------------------------

def tidy(series):
    """Trim and collapse inner whitespace; blank stays missing."""
    return series.str.strip().str.replace(r"\s+", " ", regex=True).mask(lambda s: s == "")


def label_map(*series):
    """
    Conservative label: values equal after trimming and ignoring case share one label,
    the most frequent spelling across all the given columns (ties: alphabetical).
    Returns {casefolded value: label}. Originals are kept in their own columns.
    """
    values = pd.concat([tidy(s) for s in series]).dropna()
    counts = values.value_counts().rename_axis("spelling").reset_index(name="n")
    counts["key"] = counts["spelling"].str.casefold()
    counts = counts.sort_values(["key", "n", "spelling"], ascending=[True, False, True])
    return dict(zip(counts.drop_duplicates("key")["key"], counts.drop_duplicates("key")["spelling"]))


def apply_label(series, mapping):
    return tidy(series).str.casefold().map(mapping).fillna(MISSING_LABEL)


def zip_fields(postal):
    """5-digit ZIP as text (never a number) and how it was derived from PostalCode."""
    text = postal.str.strip()
    five = text.str.extract(r"^(\d{5})(?:-(\d*))?$")
    zip_code = five[0]
    status = pd.Series("invalid format (not mapped)", index=postal.index, dtype="string")
    status = status.mask(text.isna(), "missing")
    status = status.mask(zip_code.notna() & five[1].isna(), "5-digit")
    status = status.mask(zip_code.notna() & five[1].str.len().eq(4), "ZIP+4 trimmed to 5 digits")
    status = status.mask(zip_code.notna() & five[1].notna() & ~five[1].str.len().eq(4),
                         "5 digits + malformed suffix, trimmed")
    in_ca = zip_code.str[:3].astype("float").between(900, 961)  # USPS prefixes 900-961 are California
    return zip_code, status, in_ca


def get_zcta():
    """Census ZCTA codes with their internal point, or None if the file can't be had."""
    if not ZCTA_FILE.exists():
        REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = ZCTA_FILE.with_name(ZCTA_FILE.name + ".tmp")
        try:
            with requests.get(ZCTA_URL, timeout=120) as r:
                r.raise_for_status()
                tmp.write_bytes(r.content)
        except requests.RequestException as err:
            tmp.unlink(missing_ok=True)
            note("geography", "Census ZCTA list", f"download failed ({type(err).__name__}); ZIP check skipped")
            return None
        os.replace(tmp, ZCTA_FILE)
        (REFERENCE_DIR / "zcta_source.json").write_text(json.dumps({
            "url": ZCTA_URL, "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": sha256(ZCTA_FILE)}, indent=2), encoding="utf-8")
    with zipfile.ZipFile(ZCTA_FILE) as z:
        with z.open(z.namelist()[0]) as f:
            raw = pd.read_csv(f, sep="\t", dtype=str, keep_default_na=False, na_values=[""])
    zcta, failures = parse_zcta(raw)
    note("geography", "Census ZCTA areas read", f"{len(zcta):,}")
    for item, n in failures.items():
        note("geography", f"ZCTA {item}", f"{n:,}")
    return zcta


def parse_zcta(raw):
    """
    ZCTA code -> numeric internal-point latitude/longitude. The Census file pads its last
    column (INTPTLONG) with spaces, so every value is trimmed before conversion. A value
    that still isn't a number, or is outside the valid range, becomes missing and is
    counted; ZIP codes not in the list stay missing (genuinely no point).
    """
    raw = raw.rename(columns=lambda c: c.strip())
    text = raw[["GEOID", "INTPTLAT", "INTPTLONG"]].apply(lambda s: s.str.strip().mask(lambda v: v == ""))
    failures = {}
    out = pd.DataFrame(index=pd.Index(text["GEOID"], name="GEOID"))
    for col, name, limit in [("INTPTLAT", "latitude", 90), ("INTPTLONG", "longitude", 180)]:
        value = pd.to_numeric(text[col], errors="coerce")
        not_number = text[col].notna() & value.isna()
        out_of_range = value.notna() & ~value.abs().le(limit)
        failures[f"{name}: blank"] = int(text[col].isna().sum())
        failures[f"{name}: not a number after trimming (set to missing)"] = int(not_number.sum())
        failures[f"{name}: outside ±{limit} (set to missing)"] = int(out_of_range.sum())
        out[name] = value.mask(out_of_range).to_numpy(dtype="float64")
    return out, failures


# ---- Counting grain and identities --------------------------------------------------

def transaction_rows(df, later_date):
    """
    1 for the row that counts for its ListingKey, 0 for other snapshots, and why.
    Order: latest ContractStatusChangeDate, then latest later_date, then the later row.
    """
    order = pd.DataFrame({
        "key": df["ListingKey"],
        "status_change": pd.to_datetime(df["ContractStatusChangeDate"], format="%Y-%m-%d", errors="coerce"),
        "date": pd.to_datetime(df[later_date], format="%Y-%m-%d", errors="coerce"),
        "position": np.arange(len(df))})
    keyed = order[order["key"].notna()].sort_values(["key", "status_change", "date", "position"],
                                                    na_position="first")
    chosen = keyed.drop_duplicates("key", keep="last")["position"]
    counted = pd.Series(0, index=df.index)
    counted.iloc[chosen.to_numpy()] = 1
    counted[order["key"].isna().to_numpy()] = 1  # no key to group on: each row counts
    size = df.groupby("ListingKey")["ListingKey"].transform("size")
    repeat = size.gt(1)
    if later_date == "CloseDate":
        prices = df.groupby("ListingKey")["ClosePrice"].transform("nunique")
        cls = np.where(~repeat, "single row",
                       np.where(prices.gt(1), "repeated key: ClosePrice differs (possible separate closing; unresolved)",
                                "repeated key: same ClosePrice, dates differ (snapshot)"))
    else:
        cls = np.where(~repeat, "single row", "repeated key: snapshots of one listing (dates or status differ)")
    cls = pd.Series(cls, index=df.index, dtype="string").mask(df["ListingKey"].isna(), "ListingKey missing")
    return counted, cls


def most_frequent(keys, values, counted):
    """For each key, its most frequent value on counted rows (ties: alphabetical)."""
    frame = pd.DataFrame({"key": keys, "value": values})[counted.astype(bool) & keys.notna() & values.notna()]
    counts = frame.value_counts().rename("n").reset_index()
    counts = counts.sort_values(["key", "n", "value"], ascending=[True, False, True])
    return counts.drop_duplicates("key").set_index("key")["value"]


def hashed(text):
    return text.map(lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()[:12], na_action="ignore")


def office_identity(df, counted):
    """Office key = case/space-normalized name (no office ID exists); placeholders unattributed."""
    name = tidy(df["ListOfficeName"])
    identified = name.notna() & ~name.fillna("").str.contains(PLACEHOLDER)
    key = ("O" + hashed(name.str.casefold())).where(identified)
    label = key.map(most_frequent(key, name, counted)).fillna(UNATTRIBUTED)
    return key, label, identified


def agent_identity(df, counted, office_key, office_label):
    """
    Agent key = normalized name + listing office (no listing-agent ID exists; evidence in
    the report). Email is not used: it is missing in some monthly files, team emails are
    shared by several agents, and most agents with two emails used them one after the
    other. The label is the name plus the office, so namesakes in different offices stay
    apart; an agent who moved office appears once per office.
    """
    name = tidy(df["ListAgentFullName"])
    identified = name.notna() & ~name.fillna("").str.contains(PLACEHOLDER)
    key = ("A" + hashed(name.str.casefold() + "|" + office_key.fillna("(no office)"))).where(identified)
    display = key.map(most_frequent(key, name, counted))
    label = (display + " · " + office_label).where(identified)
    per_key = pd.DataFrame({"key": key, "label": label}).dropna().drop_duplicates("key")
    clash = per_key["label"].duplicated(keep=False)
    fix = dict(zip(per_key.loc[clash, "key"], per_key.loc[clash, "label"] + " #" + per_key.loc[clash, "key"].str[1:5]))
    label = label.where(~key.isin(list(fix)), key.map(fix)).fillna(UNATTRIBUTED)
    return key, label, display.where(identified), identified, int(clash.sum())


# ---- Building the two sources -------------------------------------------------------

def geography(df, labels, zcta):
    out = pd.DataFrame(index=df.index)
    for target, source in [("county_label", "CountyOrParish"), ("city_label", "City"),
                           ("state_label", "StateOrProvince"), ("property_subtype_label", "PropertySubType")]:
        out[target] = apply_label(df[source], labels[source])
    zip_code, status, in_ca = zip_fields(df["PostalCode"])
    out["zip_code"], out["zip_status"] = zip_code, status
    out["zip_in_california_range"] = in_ca.astype(int)
    if zcta is not None:
        out["zip_in_census_zcta"] = zip_code.isin(zcta.index).astype(int)
        out["zcta_latitude"] = zip_code.map(zcta["latitude"]).astype("float64")
        out["zcta_longitude"] = zip_code.map(zcta["longitude"]).astype("float64")
    else:
        out["zip_in_census_zcta"], out["zcta_latitude"], out["zcta_longitude"] = 0, np.nan, np.nan
    return out


def build_sales(sold, labels, zcta):
    """Tableau sales source: sold rows minus exact later duplicates, with mode columns."""
    df = sold[sold["duplicate_record_flag"] != "True"].copy()
    counted, cls = transaction_rows(df, "CloseDate")
    out = df[[c for c in PRESERVED if c in df]].copy()
    out["transaction_row"], out["listing_key_repeat_class"] = counted, cls
    out["sale_month"] = df["CloseDate"].str[:7] + "-01"
    out["sale_yrmo"] = df["CloseDate"].str[:7]
    out = out.join(geography(df, labels, zcta))
    office_key, office_label, office_ok = office_identity(df, counted)
    agent_key, agent_label, agent_name, agent_ok, clashes = agent_identity(df, counted, office_key, office_label)
    out["listing_office_key"], out["listing_office_label"] = office_key, office_label
    out["listing_office_identified"] = office_ok.astype(int)
    out["listing_agent_key"], out["listing_agent_label"] = agent_key, agent_label
    out["listing_agent_name"], out["listing_agent_identified"] = agent_name, agent_ok.astype(int)

    t = counted.astype(bool)
    closed = df["MlsStatus"].eq("Closed")
    price_ok = df["ClosePrice_iqr_status"].isin(VALID_VALUE)
    dom_ok = df["DaysOnMarket_iqr_status"].isin(VALID_VALUE)
    ratio_ok = price_ok & df["close_to_original_list_ratio"].notna()
    include = df["analysis_include"].eq("True")
    out["valid_sale_count"] = (t & closed & df["CloseDate"].notna()).astype(int)
    out["valid_price"] = (t & closed & price_ok).astype(int)
    out["valid_dom"] = (t & closed & dom_ok).astype(int)
    out["valid_ratio"] = (t & closed & ratio_ok).astype(int)
    out["iqr_sale_count"] = (t & include).astype(int)
    out["iqr_price"] = (t & include).astype(int)
    out["iqr_dom"] = (t & include).astype(int)
    out["iqr_ratio"] = (t & include & ratio_ok).astype(int)
    return out[SALES_COLUMNS], {"exact_duplicates_dropped": int(len(sold) - len(df)), "agent_label_clashes": clashes}


def build_listings(listings, labels, zcta):
    """Tableau listings source: every status, minus exact later duplicates."""
    df = listings[listings["duplicate_record_flag"] != "True"].copy()
    counted, cls = transaction_rows(df, "ListingContractDate")
    out = df[[c for c in PRESERVED if c in df]].copy()
    out["transaction_row"], out["listing_key_repeat_class"] = counted, cls
    out["new_listing_event"] = (counted.astype(bool) & df["ListingContractDate"].notna()).astype(int)
    out["listing_month"] = df["ListingContractDate"].str[:7] + "-01"
    out["listing_yrmo"] = df["ListingContractDate"].str[:7]
    out = out.join(geography(df, labels, zcta))
    return out[LISTINGS_COLUMNS], {"exact_duplicates_dropped": int(len(listings) - len(df))}


# ---- Reference calculations (what Tableau should show) ----------------------------------

MODES = {MODE_VALID: ("valid_sale_count", "valid_price", "valid_dom", "valid_ratio"),
         MODE_IQR: ("iqr_sale_count", "iqr_price", "iqr_dom", "iqr_ratio")}


def sales_metrics(s, mode):
    """Closed sales, volume, median price, average DOM and average ratio for one mode."""
    count, price, dom, ratio = MODES[mode]
    p = pd.to_numeric(s["ClosePrice"]).where(s[price].eq(1))
    d = pd.to_numeric(s["DaysOnMarket"]).where(s[dom].eq(1))
    r = pd.to_numeric(s["close_to_original_list_ratio"]).where(s[ratio].eq(1))
    return {"closed_sales": int(s[count].sum()), "sales_volume": p.sum(), "median_close_price": p.median(),
            "avg_days_on_market": d.mean(), "avg_close_to_original_list_ratio": r.mean(),
            "median_close_to_original_list_ratio": r.median(), "max_close_to_original_list_ratio": r.max()}


def monthly_reference(sales, listings):
    months = sorted(set(sales["sale_month"].dropna()) | set(listings["listing_month"].dropna()))
    new = listings.groupby("listing_month")["new_listing_event"].sum()
    rows_listing = listings.groupby("listing_month").size()
    rows = []
    for month in months:
        s = sales[sales["sale_month"] == month]
        row = {"month": month, "new_listings": int(new.get(month, 0)) if month in new.index else np.nan,
               "listing_rows_all": int(rows_listing.get(month, 0)) if month in rows_listing.index else np.nan,
               "sold_rows_all": len(s) if len(s) else np.nan}
        for mode in MODES:
            tag = "iqr" if mode == MODE_IQR else "valid"
            for k, v in sales_metrics(s, mode).items():
                row[f"{k}_{tag}"] = v if len(s) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def ranking(sales, mode, entity):
    """Top 100 by volume and by units; ties share a rank (competition ranking, like Tableau RANK)."""
    count, price, _, _ = MODES[mode]
    key, label, ok = f"listing_{entity}_key", f"listing_{entity}_label", f"listing_{entity}_identified"
    p = pd.to_numeric(sales["ClosePrice"]).where(sales[price].eq(1))
    frame = pd.DataFrame({"key": sales[key], "label": sales[label], "identified": sales[ok],
                          "units": sales[count], "volume": p.fillna(0), "price": p})
    market_units, market_volume = frame["units"].sum(), frame["volume"].sum()
    g = frame[frame["identified"].eq(1)].groupby(["key", "label"]).agg(
        units=("units", "sum"), volume=("volume", "sum"), largest_sale=("price", "max")).reset_index()
    g["largest_sale_share_of_volume"] = g["largest_sale"] / g["volume"]
    g["share_of_market_units"] = g["units"] / market_units if market_units else np.nan
    g["share_of_market_volume"] = g["volume"] / market_volume if market_volume else np.nan
    out = []
    for by in ("volume", "units"):
        r = g.assign(rank=g[by].rank(method="min", ascending=False).astype(int))
        r = r[r["rank"] <= TOP_N].sort_values(["rank", "label"])
        out.append(r.assign(mode=mode, ranked_by=by))
    unattributed = frame[frame["identified"].eq(0)]
    summary = {"mode": mode, "entity": entity, "ranked_competitors": len(g),
               "unattributed_units": int(unattributed["units"].sum()),
               "unattributed_volume": float(unattributed["volume"].sum()),
               "market_units": int(market_units), "market_volume": float(market_volume)}
    return pd.concat(out), summary


def zip_reference(sales, listings):
    rows = []
    for zip_code, s in sales.groupby("zip_code"):
        row = {"zip_code": zip_code, "zip_in_census_zcta": int(s["zip_in_census_zcta"].iloc[0]),
               "zip_in_california_range": int(s["zip_in_california_range"].iloc[0])}
        for mode in MODES:
            tag = "iqr" if mode == MODE_IQR else "valid"
            m = sales_metrics(s, mode)
            row[f"homes_sold_{tag}"], row[f"median_close_price_{tag}"] = m["closed_sales"], m["median_close_price"]
        rows.append(row)
    return pd.DataFrame(rows).sort_values("homes_sold_valid", ascending=False)


def segment_reference(sales, listings):
    """Totals for a few representative filter selections, both modes, all months and the latest one."""
    top_zip = sales[sales["valid_sale_count"].eq(1)]["zip_code"].value_counts().index[0]
    latest = sales["sale_month"].max()
    selections = [("all data", {}), ("County = Los Angeles", {"county_label": "Los Angeles"}),
                  ("City = San Diego", {"city_label": "San Diego"}),
                  (f"ZIP = {top_zip} (most sales)", {"zip_code": top_zip}),
                  ("PropertySubType = Condominium", {"property_subtype_label": "Condominium"}),
                  ("County = Orange and PropertySubType = SingleFamilyResidence",
                   {"county_label": "Orange", "property_subtype_label": "SingleFamilyResidence"})]
    rows = []
    for label, filters in selections:
        for period in ("all months", f"latest month {latest[:7]}"):
            s, l = sales, listings
            for col, value in filters.items():
                s, l = s[s[col] == value], l[l[col] == value]
            if period != "all months":
                s, l = s[s["sale_month"] == latest], l[l["listing_month"] == latest]
            row = {"selection": label, "period": period, "new_listings": int(l["new_listing_event"].sum())}
            for mode in MODES:
                tag = "iqr" if mode == MODE_IQR else "valid"
                for k, v in sales_metrics(s, mode).items():
                    if k != "max_close_to_original_list_ratio":
                        row[f"{k}_{tag}"] = v
                top = ranking(s, mode, "office")[0] if len(s) else pd.DataFrame()
                vol = top[top["ranked_by"] == "volume"] if len(top) else top
                row[f"top_office_by_volume_{tag}"] = vol["label"].iloc[0] if len(vol) else ""
            rows.append(row)
    return pd.DataFrame(rows)


def month_coverage(sales, listings):
    """Months in each source and where each month's file came from (Week 1 run report + manifest)."""
    used = {}
    report = OUTPUT_DIR / "run_report.txt"
    section = None
    for line in report.read_text(encoding="utf-8").splitlines() if report.exists() else []:
        if line.strip() in ("LISTINGS", "SOLD"):
            section = line.strip().lower()
        m = re.match(r"\s+(CRMLS(?:Listing|Sold)(\d{6})\S*\.csv)\s+([\d,]+) rows", line)
        if m and section:
            used[(section, m.group(2))] = (m.group(1), int(m.group(3).replace(",", "")))
    manifest_path = BASE_DIR / "csv" / "download_manifest.csv"
    manifest = pd.read_csv(manifest_path, dtype=str) if manifest_path.exists() else pd.DataFrame(
        columns=["dataset", "month", "file", "rows", "downloaded_at"])
    rows = []
    for source, frame, col in [("sales", sales, "sale_month"), ("listings", listings, "listing_month")]:
        counts = frame.groupby(col).size()
        for month, n in counts.items():
            yyyymm = month[:7].replace("-", "")
            file, file_rows = used.get(("sold" if source == "sales" else "listings", yyyymm), ("", None))
            m = manifest[(manifest["file"] == file) & (manifest["rows"].astype(float) == (file_rows or -1))]
            origin = f"API download {m['downloaded_at'].iloc[-1][:10]}" if len(m) else \
                ("not in the download manifest (FileZilla export or unknown; see README)" if file else "")
            rows.append({"source": source, "month": month, "rows": int(n), "week1_file": file, "file_origin": origin})
    return pd.DataFrame(rows)


def agent_key_evidence(sold, counted_sales):
    """
    Why agents are keyed by name + office: how often one name + office has several
    emails, and how much the Top 100 by volume (valid mode) changes with other keys.
    Emails are read here only to measure this; they are not written to any output.
    """
    rows = counted_sales[counted_sales["valid_price"].eq(1) & counted_sales["listing_agent_identified"].eq(1)]
    frame = pd.DataFrame({"price": pd.to_numeric(rows["ClosePrice"]),
                          "name": rows["listing_agent_name"].str.casefold(),
                          "office": rows["listing_office_key"].fillna("(no office)"),
                          "email": sold.loc[rows.index, "ListAgentEmail"].str.strip().str.casefold(),
                          "date": rows["CloseDate"], "key": rows["listing_agent_key"]})
    multi = frame.dropna(subset=["email"]).groupby("key")["email"].nunique()
    multi = multi[multi > 1].index
    spans = frame[frame["key"].isin(multi)].groupby(["key", "email"])["date"].agg(["min", "max"]).reset_index()
    overlapping = 0
    for _, g in spans.groupby("key"):
        g = g.sort_values("min")
        overlapping += bool((g["min"].iloc[1:].to_numpy() <= g["max"].iloc[:-1].to_numpy()).any())
    keys = {"name + office (used)": frame["key"], "email + name": frame["email"].fillna("-") + "|" + frame["name"],
            "name only": frame["name"], "email only": frame["email"]}
    names = {}
    for label, key in keys.items():
        top = set(frame.groupby(key)["price"].sum().nlargest(TOP_N).index)
        names[label] = set(frame.loc[key.isin(top), "name"])
    out = [{"item": "agent keys (name + office) with more than one email", "value": f"{len(multi):,}"},
           {"item": "...of which the emails were used one after another (likely one person)",
            "value": f"{len(multi) - overlapping:,}"},
           {"item": "...of which the emails overlap in time (namesakes or two emails; unresolved)",
            "value": f"{overlapping:,}"}]
    for label in keys:
        out.append({"item": f"Top 100 by volume keyed by {label}: agent names shared with the name + office Top 100",
                    "value": f"{len(names[label] & names['name + office (used)'])} of {len(names[label])}"})
    return pd.DataFrame(out)


# ---- Saving and checking -------------------------------------------------------------

def save_checked(frame, path, original):
    """Write, reload as text, and check identifiers and 0/1 columns before replacing the file."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        frame.to_csv(tmp, index=False)
        back = load(tmp)
        problems = []
        if len(back) != len(frame) or list(back.columns) != list(frame.columns):
            problems.append("shape changed on reload")
        for col in [c for c in PRESERVED if c in frame]:
            if not same_text(back[col], original[col]):
                problems.append(f"{col} text differs from the input")
        for col in [c for c in ZERO_ONE if c in frame]:
            if not back[col].isin(["0", "1"]).all():
                problems.append(f"{col} is not 0/1")
        if not back["zip_code"].dropna().str.fullmatch(r"\d{5}").all():
            problems.append("zip_code not 5 digits")
        # every computed number must reload as plain numeric text (no padding), and blanks
        # must stay exactly where the value is missing
        numeric = {c for c in frame.columns if pd.api.types.is_float_dtype(frame[c])} | \
            {c for c in ("zcta_latitude", "zcta_longitude") if c in frame}
        for col in sorted(numeric):
            text = back[col]
            if not text.dropna().str.fullmatch(r"-?\d+(\.\d+)?(e-?\d+)?").all():
                problems.append(f"{col} has values that are not plain numbers")
            if not (text.isna().to_numpy() == frame[col].isna().to_numpy()).all():
                problems.append(f"{col} missing values moved on reload")
        text_cols = back.select_dtypes(exclude="number").columns
        if back[text_cols].apply(lambda s: s.str.contains(r"[\r\n]", regex=True, na=False)).any().any():
            problems.append("a cell contains a line break (Tableau's text connector may split the row)")
        if problems:
            raise ValueError(f"{path.name}: " + "; ".join(problems))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    return back


def validate(sales, listings, sold, listings_in):
    """Consistency checks on the prepared frames."""
    problems = []
    for name, f in [("sales", sales), ("listings", listings)]:
        keyed = f[f["ListingKey"].notna()]
        per_key = keyed.groupby("ListingKey")["transaction_row"].sum()
        if not (per_key == 1).all():
            problems.append(f"{name}: a ListingKey without exactly one counted row")
    for col_iqr, col_valid in [("iqr_sale_count", "valid_sale_count"), ("iqr_price", "valid_price"),
                               ("iqr_dom", "valid_dom"), ("iqr_ratio", "valid_ratio")]:
        if (sales[col_iqr] > sales[col_valid]).any():
            problems.append(f"{col_iqr} counts a row the valid mode doesn't")
    if (sales["valid_ratio"].eq(1) & sales["close_to_original_list_ratio"].isna()).any():
        problems.append("valid_ratio set without a ratio")
    if (sales["valid_price"].eq(1) & ~(pd.to_numeric(sales["ClosePrice"]) > 0)).any():
        problems.append("valid_price set on a ClosePrice that isn't > 0")
    if len(sales) != int((sold["duplicate_record_flag"] != "True").sum()):
        problems.append("sales row count")
    if len(listings) != int((listings_in["duplicate_record_flag"] != "True").sum()):
        problems.append("listings row count")
    if problems:
        raise ValueError("; ".join(problems))


# ---- Report ---------------------------------------------------------------------------

def write_report(path, ctx):
    lines = ["# Weeks 8–10 – Tableau data preparation: validation report", "",
             f"Generated by `weeks8_10_tableau_prep.py` on {datetime.now():%Y-%m-%d %H:%M}. "
             "The Tableau workbooks are built by hand (see `weeks8_10_tableau_build_guide.md`); this report "
             "covers only the prepared data and the reference numbers.", ""]
    section = None
    for sec, item, value in notes:
        if sec != section:
            lines += ["", f"## {sec}", "", "| Item | Value |", "|---|---|"]
            section = sec
        lines.append(f"| {item} | {value} |")
    lines += ["", "## Repeated ListingKeys (counting grain)", "",
              "After exact later duplicates are removed, a repeated ListingKey always has the same ListingId and "
              "its rows come from different monthly files. They are snapshots of one listing: the CloseDate "
              "(sales) or ListingContractDate (listings) moved between snapshots, often with updated status, "
              "price or buyer fields. A listing closes once, so each key counts once; the most recently updated "
              "snapshot is the counted row. Where ClosePrice differs between snapshots it is unresolved whether "
              "the price was corrected or a closing fell through and the home closed again; those keys still "
              "count once.", "",
              md_table(ctx["repeat_classes"], index=False), "",
              "## Analysis modes (sales source, counted rows only)", "",
              md_table(ctx["mode_counts"], index=False), "",
              "## Rankings: market totals and unattributed sales", "",
              md_table(ctx["ranking_summary"], index=False), "",
              "## Agent identity (no listing-agent ID exists)", "",
              "Agents are keyed by normalized name + listing office. `ListAgentEmail` is missing for every "
              "listing from 2026-06 on, some team emails are shared by several agents, and most agents with two "
              "emails used them one after the other, so email would split or merge people. The Top 100 by "
              "volume (valid mode) under other keys:", "",
              md_table(ctx["agent_sensitivity"], index=False), "",
              "## Known quality issues that affect averages and rankings", "",
              "- No low-price, low-area or ratio cutoffs are applied (none are documented).",
              "- **Average close-to-original-list ratio:** single records with a tiny OriginalListPrice "
              "(e.g. $1) produce ratios in the thousands or millions and can dominate a monthly average, in "
              "both modes. `reference_monthly.csv` reports the median and maximum ratio next to the average "
              "so the effect is visible.", "",
              md_table(ctx["ratio_effect"], index=False), "",
              "- **Sales volume rankings (valid mode):** a single implausible ClosePrice (the largest is "
              f"{ctx['largest_sale']}) can put an agent or office at the top. The ranking references "
              "include each competitor's largest sale and its share of their volume.", "",
              md_table(ctx["volume_leaders"], index=False), "",
              "## Month coverage", "",
              "Both sources run from the first to the last month below; months without data are absent, never "
              "zero. Recent months may still change (late closings and status updates); trends can step where "
              "a month's file came from a different source.", "",
              md_table(ctx["coverage_summary"], index=False), "",
              "## ZIP geography", "",
              md_table(ctx["zip_summary"], index=False), "",
              "ZIP codes not in the Census ZCTA list are the ones Tableau is most likely to show as unknown; "
              "`zip_geography_check.csv` lists them with row counts. Tableau's own match is what counts: check "
              "its unknown-locations indicator.", "",
              "## Checks", "",
              *[f"- {c}" for c in ctx["checks"]], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---- Main ---------------------------------------------------------------------------

def main():
    for path in (SOLD_IN, LISTINGS_IN):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run week7_outlier_detection.py first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inputs = [SOLD_IN, LISTINGS_IN, OUTPUT_DIR / "week6" / "sold_engineered.csv",
              OUTPUT_DIR / "week6" / "listings_engineered.csv"]
    before = {p: sha256(p) for p in inputs if p.exists()}

    print("=== loading")
    sold, listings_in = load(SOLD_IN), load(LISTINGS_IN)
    note("inputs", "sold_flagged.csv", f"{len(sold):,} rows × {sold.shape[1]} columns")
    note("inputs", "listings_flagged.csv", f"{len(listings_in):,} rows × {listings_in.shape[1]} columns")
    for name, df in [("sold", sold), ("listings", listings_in)]:
        note("inputs", f"{name}: PropertyType values", ", ".join(f"{k} {v:,}" for k, v in df["PropertyType"].value_counts(dropna=False).items()))
        note("inputs", f"{name}: MlsStatus values", ", ".join(f"{k} {v:,}" for k, v in df["MlsStatus"].value_counts().items()))
    if not (sold["PropertyType"].eq("Residential").all() and listings_in["PropertyType"].eq("Residential").all()):
        raise ValueError("an input row is not Residential")

    zcta = get_zcta()
    labels = {c: label_map(sold[c], listings_in[c]) for c in ["CountyOrParish", "City", "StateOrProvince", "PropertySubType"]}
    for c in ["CountyOrParish", "City", "StateOrProvince", "PropertySubType"]:
        spellings = pd.concat([tidy(sold[c]), tidy(listings_in[c])]).dropna().nunique()
        note("labels", f"{c}: spellings -> labels", f"{spellings:,} -> {len(labels[c]):,} (case/space variants merged)")

    print("=== building")
    sales, s_info = build_sales(sold, labels, zcta)
    listings, l_info = build_listings(listings_in, labels, zcta)
    validate(sales, listings, sold, listings_in)
    note("row counts", "sales source rows", f"{len(sales):,} ({s_info['exact_duplicates_dropped']} exact later duplicates dropped)")
    note("row counts", "sales: counted rows (one per ListingKey)", f"{int(sales['transaction_row'].sum()):,}")
    note("row counts", "listings source rows", f"{len(listings):,} ({l_info['exact_duplicates_dropped']} exact later duplicates dropped)")
    note("row counts", "listings: new-listing events (one per ListingKey)", f"{int(listings['new_listing_event'].sum()):,}")
    note("identity", "listing agents identified (counted sales)",
         f"{int((sales['listing_agent_identified'] * sales['transaction_row']).sum()):,} of {int(sales['transaction_row'].sum()):,}")
    note("identity", "listing offices identified (counted sales)",
         f"{int((sales['listing_office_identified'] * sales['transaction_row']).sum()):,} of {int(sales['transaction_row'].sum()):,}")
    placeholders = pd.concat([tidy(sold["ListOfficeName"]), tidy(sold["ListAgentFullName"])]).dropna()
    placeholders = placeholders[placeholders.str.contains(PLACEHOLDER)].value_counts()
    note("identity", "placeholder names treated as unattributed", ", ".join(f"{k} ({v})" for k, v in placeholders.items()) or "none")
    note("identity", "agent labels made unique with a key suffix", f"{s_info['agent_label_clashes']:,} keys")
    has_point = sales["zcta_latitude"].notna() & sales["zcta_longitude"].notna()
    note("geography", "sales rows with a numeric ZCTA point", f"{int(has_point.sum()):,} of {len(sales):,}")
    note("geography", "sales rows without one (ZIP missing, invalid or not a ZCTA)", f"{int((~has_point).sum()):,}")

    print("=== saving")
    sold_kept = sold[sold["duplicate_record_flag"] != "True"].reset_index(drop=True)
    listings_kept = listings_in[listings_in["duplicate_record_flag"] != "True"].reset_index(drop=True)
    save_checked(sales.reset_index(drop=True), OUT_DIR / "tableau_sales.csv", sold_kept)
    save_checked(listings.reset_index(drop=True), OUT_DIR / "tableau_listings.csv", listings_kept)

    print("=== references")
    monthly = monthly_reference(sales, listings)
    monthly.to_csv(OUT_DIR / "reference_monthly.csv", index=False)
    rank_frames, rank_summary = {}, []
    for entity in ("agent", "office"):
        frames = []
        for mode in MODES:
            frame, summary = ranking(sales, mode, entity)
            frames.append(frame)
            rank_summary.append(summary)
        rank_frames[entity] = pd.concat(frames)
        cols = ["mode", "ranked_by", "rank", "label", "key", "units", "volume", "largest_sale",
                "largest_sale_share_of_volume", "share_of_market_units", "share_of_market_volume"]
        rank_frames[entity][cols].to_csv(OUT_DIR / f"reference_{entity}s_top100.csv", index=False)
    zips = zip_reference(sales, listings)
    zips.to_csv(OUT_DIR / "reference_zip.csv", index=False)
    segment_reference(sales, listings).to_csv(OUT_DIR / "reference_segments.csv", index=False)
    coverage = month_coverage(sales, listings)
    coverage.to_csv(OUT_DIR / "month_coverage.csv", index=False)

    # ZIP check: codes Tableau may not place (bad format or not a Census ZCTA)
    zip_rows = []
    for source, frame in [("sales", sales), ("listings", listings)]:
        counted = frame[frame["transaction_row"].eq(1)]
        bad = counted[counted["zip_code"].isna() | counted["zip_in_census_zcta"].eq(0)]
        for (postal, zip_code, status, zcta_ok), n in bad.groupby(["PostalCode", "zip_code", "zip_status", "zip_in_census_zcta"], dropna=False).size().items():
            zip_rows.append({"source": source, "PostalCode": postal, "zip_code": zip_code, "zip_status": status,
                             "zip_in_census_zcta": zcta_ok, "counted_rows": n})
    zip_check = pd.DataFrame(zip_rows).sort_values(["source", "counted_rows"], ascending=[True, False])
    zip_check.to_csv(OUT_DIR / "zip_geography_check.csv", index=False)

    # report context
    after = {p: sha256(p) for p in before}
    unchanged = all(before[p] == after[p] for p in before)
    if not unchanged:
        raise ValueError("an input file changed during the run")
    counted_sales = sales[sales["transaction_row"].eq(1)]
    repeat_classes = pd.concat([
        sales.groupby("listing_key_repeat_class").agg(rows=("ListingKey", "size"), counted=("transaction_row", "sum"),
                                                     keys=("ListingKey", "nunique")).reset_index().assign(source="sales"),
        listings.groupby("listing_key_repeat_class").agg(rows=("ListingKey", "size"), counted=("transaction_row", "sum"),
                                                        keys=("ListingKey", "nunique")).reset_index().assign(source="listings")])
    mode_counts = pd.DataFrame([{"mode": mode, "closed sales": int(sales[c].sum()), "with valid price": int(sales[p].sum()),
                                 "with valid DOM": int(sales[d].sum()), "with valid ratio": int(sales[r].sum())}
                                for mode, (c, p, d, r) in MODES.items()])
    ratio_effect = monthly[["month", "avg_close_to_original_list_ratio_valid", "median_close_to_original_list_ratio_valid",
                            "max_close_to_original_list_ratio_valid", "avg_close_to_original_list_ratio_iqr",
                            "max_close_to_original_list_ratio_iqr"]]
    ratio_effect = ratio_effect.sort_values("max_close_to_original_list_ratio_valid", ascending=False).head(5)
    leaders = rank_frames["office"]
    leaders = leaders[(leaders["ranked_by"] == "volume") & (leaders["rank"] <= 5)][
        ["mode", "rank", "label", "units", "volume", "largest_sale", "largest_sale_share_of_volume"]]
    agent_sensitivity = agent_key_evidence(sold, counted_sales)
    zip_summary = counted_sales.groupby("zip_status").size().rename("counted sales").to_frame().join(
        listings[listings["transaction_row"].eq(1)].groupby("zip_status").size().rename("counted listings"), how="outer").fillna(0).astype(int).reset_index()
    zip_summary = pd.concat([zip_summary, pd.DataFrame([
        {"zip_status": "valid ZIP not in the Census ZCTA list", "counted sales": int((counted_sales["zip_code"].notna() & counted_sales["zip_in_census_zcta"].eq(0)).sum()),
         "counted listings": int((listings["transaction_row"].eq(1) & listings["zip_code"].notna() & listings["zip_in_census_zcta"].eq(0)).sum())},
        {"zip_status": "ZIP outside California's 900–961 range", "counted sales": int((counted_sales["zip_code"].notna() & counted_sales["zip_in_california_range"].eq(0)).sum()),
         "counted listings": int((listings["transaction_row"].eq(1) & listings["zip_code"].notna() & listings["zip_in_california_range"].eq(0)).sum())}])])
    coverage_summary = coverage.groupby("source").agg(first_month=("month", "min"), last_month=("month", "max"),
                                                      months=("month", "nunique"), rows=("rows", "sum")).reset_index()
    api = coverage[coverage["file_origin"].str.startswith("API")].groupby("source")["month"].apply(
        lambda s: ", ".join(m[:7] for m in sorted(s)))
    coverage_summary["months from a dated API snapshot"] = coverage_summary["source"].map(api).fillna("none")
    checks = [
        f"Inputs unchanged (SHA-256 before and after): {unchanged} ({len(before)} files: Week 7 flagged and Week 6 engineered).",
        "Every input row is Residential; sold rows are all Closed.",
        "Exactly one counted row (transaction_row = 1) per ListingKey in both sources.",
        "IQR-mode columns never count a row the valid mode doesn't; valid_price only on ClosePrice > 0; valid_ratio only with a ratio.",
        "Saved files reload with the same rows and columns; ListingKey, ListingId, PostalCode, the geography originals, "
        "prices, dates and Week 7 flags are text-identical to the input; zip_code is always 5 digits; 0/1 columns hold only 0 or 1; "
        "zcta_latitude and zcta_longitude reload as plain numbers (no padding) with blanks only where there is no Census point; "
        "no cell contains a line break.",
        f"Monthly closed sales (valid mode) sum to {int(monthly['closed_sales_valid'].sum()):,} = counted closed sales; "
        f"monthly new listings sum to {int(monthly['new_listings'].sum()):,} = new-listing events."]
    if int(monthly["closed_sales_valid"].sum()) != int(sales["valid_sale_count"].sum()) or \
            int(monthly["new_listings"].sum()) != int(listings["new_listing_event"].sum()):
        raise ValueError("monthly reference totals don't add up")
    write_report(OUT_DIR / "validation_report.md", {
        "repeat_classes": repeat_classes, "mode_counts": mode_counts, "ranking_summary": pd.DataFrame(rank_summary),
        "agent_sensitivity": agent_sensitivity, "ratio_effect": ratio_effect, "volume_leaders": leaders,
        "largest_sale": f"${pd.to_numeric(counted_sales['ClosePrice']).max():,.0f}",
        "coverage_summary": coverage_summary, "zip_summary": zip_summary, "checks": checks})
    print(f"\nSaved to {OUT_DIR}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as err:
        sys.exit(f"ERROR: {err}")
