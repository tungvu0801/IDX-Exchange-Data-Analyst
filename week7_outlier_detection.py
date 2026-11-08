"""
Week 7 - Outlier Detection and Data Quality

Flags statistical outliers in ClosePrice, LivingArea and DaysOnMarket with the
IQR method, keeps business-rule failures separate from them, and saves a full
flagged dataset and a Closed-only filtered analysis dataset for both sold and
listings. The flagged files keep every input row and value exactly as it was
(same text, same order); the new columns are appended at the end.

Input (read only, never modified):
  output/week6/sold_engineered.csv
  output/week6/listings_engineered.csv
Output: output/week7/
  sold_flagged.csv, listings_flagged.csv     every input row and column + flag columns
  sold_filtered.csv, listings_filtered.csv   exactly the rows with analysis_include = True
  iqr_thresholds.csv                        thresholds, percentiles and counts per field
  before_after_summary.csv                  population flow, exclusion reasons, medians
  validation_report.md                      policy, results, checks and limitations

Policy
  1. Business rules come first and are separate from IQR: ClosePrice <= 0 is invalid
     for Closed records, LivingArea <= 0 and DaysOnMarket < 0 are invalid (0 days is
     valid). Values the cleaning already set to null for breaking these rules (their
     originals are in <field>_invalid_original) count as invalid, not as missing.
  2. Thresholds, per dataset and per field: Q1 and Q3 (pandas' default linear
     interpolation, as in the handbook) of the Closed records that are not exact later
     duplicates and have a valid value for that field. lower = Q1 - 1.5 * IQR and
     upper = Q3 + 1.5 * IQR; a value equal to a bound is within the bounds.
  3. Only Closed records are evaluated. Other records keep status "not Closed": a
     missing sale price is expected there, and their DaysOnMarket is days so far.
  4. Filtered = Closed, not an exact later duplicate, all three fields valid and within
     all three bounds. Repeated ListingKeys that aren't exact duplicates are kept.
  5. IQR = 0: the formula is applied as written (both bounds equal Q1 = Q3) and the
     field is reported. No eligible values: no thresholds are invented; the field is
     reported as having none and no record can pass it.
  An IQR outlier is an unusual value, not a proven error. Price per square foot and the
  close-to-list ratios are reported as diagnostics only, never used to exclude rows.

Tests: python test_week7_outlier_detection.py (synthetic data, no real files needed).

Requires: pandas, numpy; week1_aggregate.py, week4_5_cleaning.py and
week6_feature_engineering.py (helpers); the Week 6 outputs above
(run week6_feature_engineering.py first).
"""

import hashlib
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from week1_aggregate import OUTPUT_DIR
from week4_5_cleaning import load, same_text, to_float
from week6_feature_engineering import as_bool, is_closed, md_table, same_strings

IN_DIR = OUTPUT_DIR / "week6"
OUT_DIR = OUTPUT_DIR / "week7"

# name: (input file, flagged output, filtered output)
DATASETS = {
    "sold": ("sold_engineered.csv", "sold_flagged.csv", "sold_filtered.csv"),
    "listings": ("listings_engineered.csv", "listings_flagged.csv", "listings_filtered.csv"),
}

# field: (rule shown in reports, test that makes a value invalid)
BUSINESS_RULES = {
    "ClosePrice": ("ClosePrice <= 0", lambda v: v <= 0),       # applied to Closed records
    "LivingArea": ("LivingArea <= 0", lambda v: v <= 0),
    "DaysOnMarket": ("DaysOnMarket < 0", lambda v: v < 0),     # 0 days is valid
}
FIELDS = list(BUSINESS_RULES)
IQR_MULTIPLIER = 1.5
PERCENTILES = [0.01, 0.05, 0.50, 0.95, 0.99]
SUPPLEMENTARY = ["price_per_sqft", "close_to_original_list_ratio", "close_to_current_list_ratio"]
REQUIRED_COLUMNS = ["MlsStatus", *FIELDS, "duplicate_record_flag"]

# <field>_iqr_status values. Only "within bounds" means the value was compared with
# the bounds and passed; every other value says why it failed or wasn't evaluated.
STATUS_NOT_CLOSED = "not Closed"
STATUS_UNPARSEABLE = "unparseable"
STATUS_INVALID = "business invalid"
STATUS_MISSING = "missing"
STATUS_NO_THRESHOLDS = "no thresholds"
STATUS_BELOW = "below lower bound"
STATUS_ABOVE = "above upper bound"
STATUS_WITHIN = "within bounds"

THRESHOLD_COLUMNS = [
    "dataset", "field", "business_rule", "population", "population_n", "q1", "q3", "iqr",
    "lower_bound", "upper_bound", "iqr_is_zero", "threshold_status", "p1", "p5", "p50", "p95", "p99",
    "min", "max", "population_below_lower", "population_above_upper", "population_share_outside",
    "lower_bound_percentile_rank", "upper_bound_percentile_rank", "flagged_below_lower",
    "flagged_above_upper", "closed_records", "closed_duplicates_not_used", "closed_missing",
    "closed_business_invalid", "closed_unparseable", "all_records_business_invalid"]

STAGE_LABELS = [
    "all input records",
    "Closed",
    "Closed, not an exact later duplicate",
    "...and ClosePrice, LivingArea and DaysOnMarket all valid (eligible; before IQR)",
    "...and within all three IQR bounds (filtered dataset)",
]


def audit_present(df, col):
    """True where the cleaning kept an original value in this audit column."""
    return df[col].notna() if col in df else pd.Series(False, index=df.index)


# ---- Thresholds and flags -----------------------------------------------------------

def iqr_thresholds(values):
    """Q1, Q3, IQR, bounds and percentiles of the non-null values; no bounds if there are none."""
    v = values.dropna()
    row = {"population_n": int(len(v))}
    if v.empty:
        row["threshold_status"] = "no eligible observations: no thresholds, field not evaluated"
        return row
    q1, q3 = float(v.quantile(0.25)), float(v.quantile(0.75))
    iqr = q3 - q1
    row.update(q1=q1, q3=q3, iqr=iqr, lower_bound=q1 - IQR_MULTIPLIER * iqr,
               upper_bound=q3 + IQR_MULTIPLIER * iqr, iqr_is_zero=bool(iqr == 0))
    row["threshold_status"] = ("IQR = 0: both bounds equal Q1 = Q3, so every other value is flagged"
                               if iqr == 0 else "ok")
    for p in PERCENTILES:
        row[f"p{round(p * 100)}"] = float(v.quantile(p))
    row["min"], row["max"] = float(v.min()), float(v.max())
    return row


def evaluate_field(df, field, closed, duplicate):
    """Business-rule and IQR evaluation of one field. Returns its columns, thresholds and masks."""
    rule, broken = BUSINESS_RULES[field]
    text = df[field]
    value = text.map(to_float, na_action="ignore").astype("float64")
    blanked = text.isna() & audit_present(df, f"{field}_invalid_original")
    unparseable = (text.notna() & value.isna()) | (text.isna() & audit_present(df, f"{field}_unparsed_original"))
    invalid = ~unparseable & (blanked | broken(value))
    missing = text.isna() & ~blanked & ~unparseable
    valid = ~unparseable & ~invalid & ~missing
    population = closed & ~duplicate & valid

    t = iqr_thresholds(value[population])
    has_bounds = "lower_bound" in t
    lower, upper = t.get("lower_bound", np.nan), t.get("upper_bound", np.nan)
    below = closed & valid & (value < lower)  # comparisons with NaN bounds are False
    above = closed & valid & (value > upper)
    evaluable = closed & valid & has_bounds
    status = pd.Series(np.select(
        [~closed, unparseable, invalid, missing, np.full(len(df), not has_bounds), below, above],
        [STATUS_NOT_CLOSED, STATUS_UNPARSEABLE, STATUS_INVALID, STATUS_MISSING, STATUS_NO_THRESHOLDS,
         STATUS_BELOW, STATUS_ABOVE], STATUS_WITHIN), index=df.index, dtype="string")
    # The ClosePrice rule is for Closed records (a sale price isn't expected otherwise);
    # the LivingArea and DaysOnMarket rules hold for every record.
    business_invalid = invalid & closed if field == "ClosePrice" else invalid

    t.update(dataset=None, field=field, business_rule=rule,
             population=f"Closed, not an exact later duplicate, valid {field}",
             closed_records=int(closed.sum()),
             closed_duplicates_not_used=int((closed & duplicate).sum()),
             closed_missing=int((closed & missing).sum()),
             closed_business_invalid=int((closed & invalid).sum()),
             closed_unparseable=int((closed & unparseable).sum()),
             all_records_business_invalid=int(business_invalid.sum()),
             population_below_lower=int((population & below).sum()),
             population_above_upper=int((population & above).sum()),
             flagged_below_lower=int(below.sum()),
             flagged_above_upper=int(above.sum()))
    if t["population_n"]:
        t["population_share_outside"] = (t["population_below_lower"] + t["population_above_upper"]) / t["population_n"]
        t["lower_bound_percentile_rank"] = float((value[population] < lower).mean())
        t["upper_bound_percentile_rank"] = float((value[population] <= upper).mean())
    columns = {f"{field}_business_invalid_flag": business_invalid,
               f"{field}_iqr_evaluable": evaluable,
               f"{field}_iqr_outlier_flag": evaluable & (below | above),
               f"{field}_iqr_status": status}
    masks = {"value": value, "valid": valid, "missing": missing, "invalid": invalid,
             "unparseable": unparseable, "below": below, "above": above, "has_bounds": has_bounds}
    return columns, t, masks


def join_reasons(conditions, index):
    """All reasons that apply to each row, '; '-separated, or <NA> when none does."""
    parts = [np.where(np.asarray(mask, dtype=bool), label, "") for label, mask in conditions]
    joined = ["; ".join(p for p in row if p) for row in zip(*parts)]
    reasons = pd.Series(joined, index=index, dtype="string")
    return reasons.mask(reasons == "")


def flag(df):
    """The Week 7 columns for df (same index), the threshold rows and the working masks."""
    closed = is_closed(df)
    duplicate = as_bool(df["duplicate_record_flag"])
    new, thresholds, work = {}, [], {}
    for field in FIELDS:
        columns, t, masks = evaluate_field(df, field, closed, duplicate)
        new.update(columns)
        thresholds.append(t)
        work[field] = masks

    outliers = pd.DataFrame({f: new[f"{f}_iqr_outlier_flag"] for f in FIELDS})
    new["iqr_outlier_flag"] = outliers.any(axis=1)
    new["iqr_outlier_fields"] = join_reasons([(f, outliers[f]) for f in FIELDS], df.index)
    new["iqr_fields_evaluated"] = pd.DataFrame({f: new[f"{f}_iqr_evaluable"] for f in FIELDS}).sum(axis=1).astype("Int64")

    # Every reason that applies, so reasons overlap; only "not Closed" is given for
    # records that aren't Closed, because their fields are not evaluated.
    conditions = [("not Closed", ~closed), ("exact later duplicate", closed & duplicate)]
    for field in FIELDS:
        m = work[field]
        conditions += [(f"{field} missing", closed & m["missing"]),
                       (f"{field} business invalid ({BUSINESS_RULES[field][0]})", closed & m["invalid"]),
                       (f"{field} unparseable", closed & m["unparseable"]),
                       (f"{field} no IQR thresholds", closed & m["valid"] & (not m["has_bounds"])),
                       (f"{field} below IQR lower bound", m["below"]),
                       (f"{field} above IQR upper bound", m["above"])]
    within = pd.concat([new[f"{f}_iqr_status"].eq(STATUS_WITHIN) for f in FIELDS], axis=1).all(axis=1)
    include = (closed & ~duplicate & within.astype(bool)).astype(bool)
    new["analysis_include"] = include
    new["analysis_exclusion_reasons"] = join_reasons(conditions, df.index)
    work.update(closed=closed, duplicate=duplicate, include=include, conditions=conditions,
                all_valid=pd.concat([work[f]["valid"] for f in FIELDS], axis=1).all(axis=1))
    return pd.DataFrame(new, index=df.index), thresholds, work


# ---- Checks and saving --------------------------------------------------------------

def validate(df, new, work, thresholds, name):
    """Independent rechecks in memory, before anything is saved."""
    problems = []
    closed, duplicate, include = work["closed"], work["duplicate"], work["include"]
    for t in thresholds:
        f = t["field"]
        m = work[f]
        population = closed & ~duplicate & m["valid"]
        values = m["value"][population].to_numpy()
        if len(values):
            q1, q3 = np.percentile(values, [25, 75], method="linear")
            if not np.allclose([q1, q3], [t["q1"], t["q3"]], rtol=1e-12, atol=0):
                problems.append(f"{f}: quartiles differ from numpy's")
        elif "lower_bound" in t:
            problems.append(f"{f}: bounds without observations")
    # every included row meets the documented rules, checked from the values themselves
    for f in FIELDS:
        rule = BUSINESS_RULES[f][1]
        t = next(t for t in thresholds if t["field"] == f)
        v = work[f]["value"][include]
        if v.isna().any() or rule(v).any() or not np.isfinite(v).all():
            problems.append(f"{f}: an included row has a missing or invalid value")
        if len(v) and "lower_bound" not in t:
            problems.append(f"{f}: rows included although the field has no thresholds")
        elif len(v) and ((v < t["lower_bound"]) | (v > t["upper_bound"])).any():
            problems.append(f"{f}: an included row is outside the bounds")
        if (new.loc[~closed, f"{f}_iqr_evaluable"]).any():
            problems.append(f"{f}: a record that isn't Closed was evaluated")
        if (new[f"{f}_iqr_outlier_flag"] & ~new[f"{f}_iqr_evaluable"]).any():
            problems.append(f"{f}: an outlier flag on a value that wasn't evaluated")
    if (include & (~closed | duplicate)).any():
        problems.append("an included row is not Closed or is an exact later duplicate")
    if not (new["analysis_exclusion_reasons"].isna() == include).all():
        problems.append("exclusion reasons do not match analysis_include")
    if len(new) != len(df) or not new.index.equals(df.index):
        problems.append("row count or order changed")
    clash = [c for c in new.columns if c in df.columns]
    if clash:
        problems.append(f"new columns already exist in the input: {clash}")
    if problems:
        raise ValueError(f"{name}: " + "; ".join(problems))


def reloads_same(back, new):
    """Columns of new that do not reload to the same values."""
    bad = []
    for col in new.columns:
        if new[col].dtype == bool:
            ok = back[col].isin(["True", "False"]).all() and (back[col].eq("True").to_numpy() == new[col].to_numpy()).all()
        elif pd.api.types.is_numeric_dtype(new[col]):
            ok = same_strings(back[col], new[col].astype("string"))
        else:
            ok = same_strings(back[col], new[col])
        if not ok:
            bad.append(col)
    return bad


def save_and_check(df, new, flagged_path, filtered_path):
    """
    Write both files, reload them as text and check before replacing earlier files:
      - flagged: the same rows in the same order; every input column identical to the
        input text; the new columns reload to the same values;
      - filtered: exactly the flagged rows with analysis_include = True, same columns,
        same order, same text.
    """
    out = pd.concat([df, new], axis=1)
    tmp_flagged = flagged_path.with_name(flagged_path.name + ".tmp")
    tmp_filtered = filtered_path.with_name(filtered_path.name + ".tmp")
    try:
        out.to_csv(tmp_flagged, index=False)
        back = load(tmp_flagged)
        problems = []
        if len(back) != len(df) or list(back.columns) != list(out.columns):
            problems.append("flagged: shape or column order changed on reload")
        changed = [c for c in df.columns if not same_text(back[c], df[c])]
        if changed:
            problems.append(f"flagged: input columns changed: {changed}")
        bad = reloads_same(back, new)
        if bad:
            problems.append(f"flagged: new columns did not reload: {bad}")
        out[new["analysis_include"].to_numpy()].to_csv(tmp_filtered, index=False)
        sub = load(tmp_filtered)
        expected = back[back["analysis_include"].eq("True")].reset_index(drop=True)
        if len(sub) != len(expected) or list(sub.columns) != list(back.columns):
            problems.append("filtered: not the same rows or columns as the included flagged rows")
        elif [c for c in back.columns if not same_text(sub[c], expected[c])]:
            problems.append("filtered: text differs from the included flagged rows")
        if problems:
            raise ValueError("; ".join(problems))
    except BaseException:
        tmp_flagged.unlink(missing_ok=True)
        tmp_filtered.unlink(missing_ok=True)
        raise
    os.replace(tmp_flagged, flagged_path)
    os.replace(tmp_filtered, filtered_path)
    return len(back), back.shape[1], len(sub)


# ---- Summaries --------------------------------------------------------------------

def stage_masks(work):
    closed, duplicate = work["closed"], work["duplicate"]
    eligible = closed & ~duplicate & work["all_valid"]
    return [pd.Series(True, index=closed.index), closed, closed & ~duplicate, eligible, work["include"]]


def compare(name, label, before, after):
    """Median and mean before and after, on the given before/after values."""
    b, a = before.dropna(), after.dropna()
    row = {"dataset": name, "item": label, "n_before": len(b), "n_after": len(a),
           "median_before": b.median() if len(b) else np.nan, "median_after": a.median() if len(a) else np.nan,
           "mean_before": b.mean() if len(b) else np.nan, "mean_after": a.mean() if len(a) else np.nan}
    for stat in ("median", "mean"):
        before_v, after_v = row[f"{stat}_before"], row[f"{stat}_after"]
        row[f"{stat}_change"] = after_v - before_v
        row[f"{stat}_pct_change"] = (after_v - before_v) / before_v * 100 if before_v else np.nan
    return row


def before_after(df, work, name):
    """Population flow, overall sizes, medians by stage, IQR-step comparison, reasons."""
    rows = []
    masks = stage_masks(work)
    previous = None
    for label, mask in zip(STAGE_LABELS, masks):
        n = int(mask.sum())
        rows.append({"dataset": name, "section": "population flow", "item": label, "records": n,
                     "removed_at_this_step": None if previous is None else previous - n})
        previous = n
    total, closed_n, kept = int(len(df)), int(work["closed"].sum()), int(work["include"].sum())
    rows += [{"dataset": name, "section": "dataset size", "item": "full flagged dataset (all input rows)", "records": total},
             {"dataset": name, "section": "dataset size", "item": "filtered analysis dataset (Closed only)", "records": kept,
              "share_of_all": kept / total if total else np.nan,
              "share_of_closed": kept / closed_n if closed_n else np.nan}]
    for field in FIELDS:  # medians at each Closed stage, over the field's valid values
        m = work[field]
        for label, mask in list(zip(STAGE_LABELS, masks))[1:]:
            v = m["value"][mask & m["valid"]]
            rows.append({"dataset": name, "section": "median by stage", "item": f"{field} | {label}",
                         "n": len(v), "median": v.median() if len(v) else np.nan,
                         "mean": v.mean() if len(v) else np.nan})
    eligible, include = masks[3], masks[4]
    for field in FIELDS:  # the IQR step itself, on the same eligible population
        v = work[field]["value"]
        rows.append({"section": "IQR step: eligible vs filtered", **compare(name, field, v[eligible], v[include])})
    for metric in [m for m in SUPPLEMENTARY if m in df]:  # diagnostics only; never exclusion criteria
        v = df[metric].map(to_float, na_action="ignore").astype("float64")
        row = compare(name, metric, v[eligible], v[include])
        for stat, q in (("p1", 0.01), ("p99", 0.99)):
            row[f"{stat}_before"], row[f"{stat}_after"] = v[eligible].quantile(q), v[include].quantile(q)
        row["max_before"], row["max_after"] = v[eligible].max(), v[include].max()
        rows.append({"section": "supplementary diagnostic (not an exclusion criterion)", **row})
    reasons = work["conditions"]
    for label, mask in reasons:
        rows.append({"dataset": name, "section": "exclusion reasons (overlapping)", "item": label,
                     "records": int(np.asarray(mask, dtype=bool).sum())})
    reason_count = np.sum([np.asarray(mask, dtype=bool) for _, mask in reasons], axis=0)
    excluded = ~work["include"]
    rows += [{"dataset": name, "section": "unique excluded", "item": "records excluded (unique)", "records": int(excluded.sum())},
             {"dataset": name, "section": "unique excluded", "item": "records excluded for two or more reasons",
              "records": int((reason_count >= 2).sum())}]
    closed_unique = work["closed"] & ~work["duplicate"]
    validity = np.zeros(len(df), dtype=bool)
    iqr = np.zeros(len(df), dtype=bool)
    for field in FIELDS:
        m = work[field]
        validity |= (m["missing"] | m["invalid"] | m["unparseable"]).to_numpy()
        iqr |= (m["below"] | m["above"]).to_numpy()
    for label, mask in [("Closed, not duplicate: validity/missingness only", closed_unique & validity & ~iqr),
                        ("Closed, not duplicate: IQR only", closed_unique & ~validity & iqr),
                        ("Closed, not duplicate: both validity/missingness and IQR", closed_unique & validity & iqr)]:
        rows.append({"dataset": name, "section": "unique excluded", "item": label, "records": int(mask.sum())})
    return rows


def pooled_evidence(df, work):
    """Share of ClosePrice values above the dataset-wide upper bound, by county."""
    if "CountyOrParish" not in df:
        return pd.DataFrame()
    m = work["ClosePrice"]
    population = work["closed"] & ~work["duplicate"] & m["valid"]
    frame = pd.DataFrame({"county": df["CountyOrParish"].fillna("(missing)"), "above": m["above"]})[population]
    g = frame.groupby("county")["above"].agg(["size", "sum"])
    g = g[g["size"] >= 1000].assign(share=lambda x: x["sum"] / x["size"])
    return g.sort_values("share", ascending=False).rename(
        columns={"size": "eligible ClosePrice values", "sum": "above upper bound", "share": "share above"})


def percentile_guidance(work, thresholds):
    """Filtered values beyond the population's P1 or P99: extremes the IQR bounds keep."""
    rows = []
    include = work["include"]
    for t in thresholds:
        if "p1" not in t:
            continue
        v = work[t["field"]]["value"][include]
        rows.append({"field": t["field"], "P1": t["p1"], "P99": t["p99"], "lower bound": t["lower_bound"],
                     "upper bound": t["upper_bound"], "filtered rows below P1": int((v < t["p1"]).sum()),
                     "filtered rows above P99": int((v > t["p99"]).sum()),
                     "filtered minimum": v.min() if len(v) else np.nan})
    return pd.DataFrame(rows)


# ---- One dataset ----------------------------------------------------------------------

def process(name, in_path, flagged_path, filtered_path):
    """Flag, check, save and summarize one dataset. Returns what the report needs."""
    print(f"\n=== {name}")
    df = load(in_path)
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df]
    if missing_cols:
        raise ValueError(f"{in_path.name}: required columns missing: {missing_cols}")
    print(f"  input: {len(df):,} rows x {df.shape[1]} columns")
    new, thresholds, work = flag(df)
    for t in thresholds:
        t["dataset"] = name
    validate(df, new, work, thresholds, name)
    rows_out, cols_out, filtered_rows = save_and_check(df, new, flagged_path, filtered_path)
    print(f"  flagged: {rows_out:,} rows x {cols_out} columns (all input rows and text kept)")
    print(f"  filtered: {filtered_rows:,} rows (analysis_include = True)")
    for t in thresholds:
        if "lower_bound" in t:
            print(f"  {t['field']:<13} n {t['population_n']:>8,}  Q1 {t['q1']:>12,.2f}  Q3 {t['q3']:>12,.2f}  "
                  f"bounds [{t['lower_bound']:,.2f}, {t['upper_bound']:,.2f}]  below {t['flagged_below_lower']:,}  "
                  f"above {t['flagged_above_upper']:,}  {t['threshold_status']}")
        else:
            print(f"  {t['field']:<13} {t['threshold_status']}")
    return {"thresholds": thresholds, "summary": before_after(df, work, name),
            "pooled": pooled_evidence(df, work), "guidance": percentile_guidance(work, thresholds),
            "rows": len(df), "columns_in": df.shape[1], "columns_out": cols_out, "filtered_rows": filtered_rows,
            "new_columns": list(new.columns)}


# ---- Report ---------------------------------------------------------------------------

FLAG_SEMANTICS = [
    ("`<field>_business_invalid_flag`", "True when the value breaks the business rule now, or was set to null in "
     "cleaning for breaking it. The ClosePrice rule applies to Closed records only; the LivingArea and "
     "DaysOnMarket rules apply to every record."),
    ("`<field>_iqr_status`", "`within bounds`, `below lower bound`, `above upper bound`, or why the value was "
     "not compared: `not Closed`, `missing`, `business invalid`, `unparseable`, `no thresholds`."),
    ("`<field>_iqr_evaluable`", "True only when the value was compared with the bounds (Closed record, valid "
     "value, thresholds available)."),
    ("`<field>_iqr_outlier_flag`", "True when an evaluated value is outside the bounds. False also when the value "
     "was not evaluated, so read it together with `_iqr_evaluable`."),
    ("`iqr_outlier_flag`", "True when any of the three fields is an IQR outlier."),
    ("`iqr_outlier_fields`", "Which fields are outliers (blank when none)."),
    ("`iqr_fields_evaluated`", "How many of the three fields (0 to 3) were compared with their bounds."),
    ("`analysis_include`", "True for the rows in the filtered dataset."),
    ("`analysis_exclusion_reasons`", "Every reason a row is excluded, `; `-separated (blank when included). "
     "Reasons overlap. Records that aren't Closed get only `not Closed`."),
]


def fmt_table(rows, columns):
    df = pd.DataFrame(rows)
    return md_table(df[[c for c in columns if c in df]], index=False)


def write_report(path, results, input_meta):
    started = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Week 7 – Outlier Detection validation report", "",
        f"Generated by `week7_outlier_detection.py` on {started}.", "",
        "## Inputs", "",
        *[f"- `{m['file']}`: {m['rows']:,} rows × {m['columns']} columns; SHA-256 {m['sha256']} "
          f"(unchanged after the run: {m['unchanged']})" for m in input_meta], "",
        "## Policy", "",
        "- **Business rules first, separate from IQR:** ClosePrice <= 0 is invalid for Closed records; "
        "LivingArea <= 0 and DaysOnMarket < 0 are invalid; 0 days is valid. Values the cleaning set to "
        "null for breaking a rule (originals in `<field>_invalid_original`) count as invalid, not missing.",
        "- **Thresholds per dataset and field:** Q1 and Q3 (pandas' linear interpolation) of Closed records "
        "that are not exact later duplicates and have a valid value for that field; lower = Q1 − 1.5 × IQR, "
        "upper = Q3 + 1.5 × IQR; values equal to a bound are within it.",
        "- **Only Closed records are evaluated.** Others are kept in the flagged files with status `not "
        "Closed`: a missing sale price is expected and their DaysOnMarket is days so far.",
        "- **Filtered dataset (Closed only):** Closed, not an exact later duplicate, all three fields valid and "
        "within all three bounds. Repeated ListingKeys that aren't exact duplicates are kept.",
        "- **IQR = 0** is applied as written (both bounds equal Q1 = Q3) and reported; **no eligible values** "
        "means no thresholds, and no record can pass that field. No fallback threshold is invented.",
        "- **Dataset-wide (pooled) thresholds** are the baseline. Pooling across counties and property types "
        "flags legitimately expensive or unusual properties (see the county table), so an IQR outlier is an "
        "unusual value, not a proven data error.",
        "- Price per square foot and the close-to-list ratios are diagnostics only; they never exclude a row.", "",
        "## Flag columns", "", "| Column | Meaning |", "|---|---|",
        *[f"| {c} | {d} |" for c, d in FLAG_SEMANTICS], ""]
    threshold_cols = ["field", "population_n", "q1", "q3", "iqr", "lower_bound", "upper_bound",
                      "p1", "p5", "p50", "p95", "p99", "threshold_status"]
    count_cols = ["field", "closed_records", "closed_duplicates_not_used", "closed_missing",
                  "closed_business_invalid", "closed_unparseable", "all_records_business_invalid",
                  "population_below_lower", "population_above_upper", "flagged_below_lower",
                  "flagged_above_upper", "upper_bound_percentile_rank"]
    for name, res in results.items():
        summary = pd.DataFrame(res["summary"])
        section = lambda s: summary[summary["section"] == s]
        flow = section("population flow")
        iqr_step = section("IQR step: eligible vs filtered")
        lines += [f"## {name}", "",
                  f"Flagged: {res['rows']:,} rows × {res['columns_out']} columns ({res['columns_in']} input + "
                  f"{len(res['new_columns'])} new). Filtered: {res['filtered_rows']:,} rows.", "",
                  "### Thresholds", "", fmt_table(res["thresholds"], threshold_cols), "",
                  "### Counts", "",
                  "`closed_*` counts include exact later duplicates; `population_*` counts are the threshold "
                  "population; `flagged_*` counts are every evaluated Closed row. `upper_bound_percentile_rank` is "
                  "the share of the population at or below the upper bound.", "",
                  fmt_table(res["thresholds"], count_cols), "",
                  "### Population flow", "",
                  "Each step removes rows from the step before, so these removals don't overlap.", "",
                  md_table(flow[["item", "records", "removed_at_this_step"]].fillna(""), index=False), "",
                  "### Exclusion reasons (overlapping; a row can have several)", "",
                  md_table(section("exclusion reasons (overlapping)")[["item", "records"]], index=False), "",
                  md_table(section("unique excluded")[["item", "records"]], index=False), "",
                  "### Medians immediately before and after the IQR step", "",
                  "Same population definition before and after: eligible Closed records (not duplicates, all "
                  "three fields valid) versus those within all three bounds.", "",
                  md_table(iqr_step[["item", "n_before", "n_after", "median_before", "median_after",
                                     "median_pct_change", "mean_before", "mean_after", "mean_pct_change"]],
                           index=False), "",
                  "### Supplementary diagnostics (not exclusion criteria)", "",
                  md_table(section("supplementary diagnostic (not an exclusion criterion)")[
                      ["item", "n_before", "n_after", "median_before", "median_after", "p99_before",
                       "p99_after", "max_before", "max_after"]], index=False), "",
                  "### Percentiles alongside the bounds", "",
                  "The lower bounds can fall below zero for these right-skewed fields, in which case the IQR rule "
                  "cannot flag low values; P1 shows how many very low values the filtered data still holds.", "",
                  md_table(res["guidance"], index=False), ""]
        if len(res["pooled"]):
            pooled = res["pooled"].head(8).reset_index().rename(columns={"county": "CountyOrParish"})
            lines += ["### Pooled thresholds by county (ClosePrice, counties with ≥ 1,000 values)", "",
                      "Highest shares above the dataset-wide upper bound. These are high-priced markets, so many "
                      "of their flagged values are likely genuine sales rather than errors (not checked row by "
                      "row).", "", md_table(pooled, index=False), ""]
        filtered_share = res["filtered_rows"] / res["rows"] * 100 if res["rows"] else 0
        closed_n = int(flow["records"].iloc[1])
        closed_share = f"; {res['filtered_rows'] / closed_n * 100:.1f}% of the {closed_n:,} Closed records" \
            if closed_n else ""
        lines += ["### Written comparison", "",
                  f"The full flagged dataset keeps all {res['rows']:,} rows; the filtered analysis dataset keeps "
                  f"{res['filtered_rows']:,} ({filtered_share:.1f}% of all rows{closed_share}).",
                  *[f"- {r['item']}: median {r['median_before']:,.2f} → {r['median_after']:,.2f} "
                    f"({r['median_pct_change']:+.1f}%), mean {r['mean_before']:,.2f} → {r['mean_after']:,.2f} "
                    f"({r['mean_pct_change']:+.1f}%), on {int(r['n_before']):,} → {int(r['n_after']):,} records."
                    for r in iqr_step.to_dict("records") if r["n_before"]], ""]
    negative = ", ".join(f"{name} {t['field']} ({t['lower_bound']:,.1f})" for name, res in results.items()
                         for t in res["thresholds"] if t.get("lower_bound", 0) < 0) or "none"
    lines += [
        "## Checks", "",
        "- Quartiles recomputed with numpy (`method=\"linear\"`) match pandas'.",
        "- Every included row is Closed, not an exact later duplicate, has valid finite values for all three "
        "fields and is within all three bounds (checked from the values, not from the flags).",
        "- No record that isn't Closed is evaluated; no outlier flag is set on a value that wasn't evaluated; "
        "exclusion reasons are blank exactly for included rows.",
        "- Flagged files reload with the same rows, order and input text; new columns reload to the same "
        "values; filtered files are exactly the included flagged rows.", "",
        "## Limitations", "",
        "- IQR flags unusual values, not errors. Pooled thresholds flag legitimate luxury homes, large "
        "properties and slow sales; filtering does not by itself make the data more accurate.",
        f"- Lower bounds below the business-rule floor in this run: {negative}. For these fields the IQR step "
        "cannot flag low values, so implausibly low ones (see the filtered minimums) stay in the filtered data; "
        "the business rules only catch values <= 0 (< 0 for days).",
        "- Thresholds are per dataset; listings' Closed records overlap with sold, so the two sets of "
        "thresholds are close but not identical.",
        "- Medians move less than means when extremes are removed; both are reported.",
        "- Repeated ListingKeys that aren't exact duplicates are kept; why they repeat is unverified.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---- Main ---------------------------------------------------------------------------

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    for in_file, _, _ in DATASETS.values():
        if not (IN_DIR / in_file).exists():
            raise FileNotFoundError(f"{IN_DIR / in_file} not found. Run week6_feature_engineering.py first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    before = {f: sha256(IN_DIR / f) for f, _, _ in DATASETS.values()}

    results = {}
    for name, (in_file, flagged, filtered) in DATASETS.items():
        results[name] = process(name, IN_DIR / in_file, OUT_DIR / flagged, OUT_DIR / filtered)

    thresholds = pd.DataFrame([t for r in results.values() for t in r["thresholds"]])
    thresholds.reindex(columns=THRESHOLD_COLUMNS).to_csv(OUT_DIR / "iqr_thresholds.csv", index=False)
    summary = pd.DataFrame([row for r in results.values() for row in r["summary"]])
    summary.to_csv(OUT_DIR / "before_after_summary.csv", index=False)
    input_meta = []
    for name, (in_file, _, _) in DATASETS.items():
        after = sha256(IN_DIR / in_file)
        input_meta.append({"file": f"output/week6/{in_file}", "rows": results[name]["rows"],
                           "columns": results[name]["columns_in"], "sha256": after, "unchanged": after == before[in_file]})
        if after != before[in_file]:
            raise ValueError(f"{in_file} changed during the run")
    write_report(OUT_DIR / "validation_report.md", results, input_meta)

    print("\nIQR step (eligible Closed records vs filtered):")
    step = summary[summary["section"] == "IQR step: eligible vs filtered"]
    print(step[["dataset", "item", "n_before", "n_after", "median_before", "median_after", "median_pct_change",
                "mean_pct_change"]].to_string(index=False))
    print(f"\nSaved to {OUT_DIR}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as err:
        sys.exit(f"ERROR: {err}")
