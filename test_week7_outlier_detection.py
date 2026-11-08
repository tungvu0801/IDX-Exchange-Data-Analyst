"""
Regression tests for week7_outlier_detection.py on small synthetic datasets.
No real data is needed. Run: python test_week7_outlier_detection.py
"""

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import week7_outlier_detection as w

COLUMNS = ["ListingKey", "PostalCode", "MlsStatus", "ClosePrice", "LivingArea", "DaysOnMarket",
           "ClosePrice_invalid_original", "LivingArea_invalid_original", "DaysOnMarket_invalid_original",
           "duplicate_record_flag", "CountyOrParish", "price_per_sqft", "year_month"]


def row(key, status, price, area, days, price_audit="", area_audit="", days_audit="", duplicate="False",
        ppsf="500.0"):
    return [key, "01234", status, price, area, days, price_audit, area_audit, days_audit, duplicate,
            "Test County", ppsf, "2024-01"]


# T: quartiles fall exactly on data values. Closed, non-duplicate population (rows 0-8):
#   ClosePrice   5000 10000 20000 25000 30000 35000 40000 70000 71000 -> Q1 20000, Q3 40000, bounds [-10000, 70000]
#   LivingArea   9 10 40 45 50 55 60 90 91                          -> Q1 40, Q3 60, bounds [10, 90]
#   DaysOnMarket 0 20 40 45 50 55 60 70 200                         -> Q1 40, Q3 60, bounds [10, 90]
T_ROWS = [
    row("0001", "Closed", "5000.0", "40.0", "40"),
    row("0001", "Closed", "10000.0", "45.0", "45"),           # same key, different record: kept
    row("0003", "Closed", "20000.0", "50.0", "50", ppsf="999999.0"),  # extreme diagnostic only
    row("0004", "Closed", "25000.0", "55.0", "55"),
    row("0005", "Closed", "30000.0", "60.0", "60"),
    row("0006", "Closed", "35000.0", "10.0", "20"),           # LivingArea exactly at the lower bound
    row("0007", "Closed", "40000.0", "90.0", "70"),           # LivingArea exactly at the upper bound
    row("0008", "Closed", "70000.0", "9.0", "0"),             # ClosePrice at upper bound; area and 0 days below
    row("0009", "Closed", "71000.0", "91.0", "200"),          # all three above
    row("0005", "Closed", "30000.0", "60.0", "60", duplicate="True"),  # exact later duplicate of row 4
    row("0010", "Pending", "9999999.0", "50.0", "500"),       # not Closed
    row("0011", "Active", "", "", "5", area_audit="-1.0"),    # not Closed; area invalid in cleaning
]
# M: missing, invalid (now and in cleaning) and unparseable values
M_ROWS = [
    row("m0", "Closed", "", "1000.0", "10"),                          # ClosePrice missing
    row("m1", "Closed", "", "1100.0", "12", price_audit="-5.0"),      # ClosePrice set to null in cleaning
    row("m2", "Closed", "300000.0", "0.0", "14"),                     # LivingArea 0 (invalid now)
    row("m3", "Closed", "310000.0", "1200.0", "", days_audit="-3"),   # DaysOnMarket set to null in cleaning
    row("m4", "Closed", "n/a", "1300.0", "16"),                       # ClosePrice not a number
    row("m5", "Closed", "320000.0", "1400.0", ""),                    # DaysOnMarket missing
    row("m6", "Closed", "300000.0", "1000.0", "0"),                   # zero days: valid
    row("m7", "Closed", "310000.0", "1100.0", "10"),
    row("m8", "Closed", "320000.0", "1200.0", "20"),
    row("m9", "Closed", "330000.0", "1300.0", "30"),
    row("m10", "Closed", "340000.0", "1400.0", "40"),
]
# Z: DaysOnMarket has IQR = 0 (Q1 = Q3 = 7)
Z_ROWS = [row(f"z{i}", "Closed", f"{100000 + 10000 * i}.0", f"{1000 + 100 * i}.0", d)
          for i, d in enumerate(["7", "7", "7", "7", "7", "7", "7", "0", "30"])]
# E: no eligible LivingArea (the only valid one is on an exact later duplicate)
E_ROWS = [
    row("e0", "Closed", "100000.0", "1000.0", "10", duplicate="True"),
    row("e1", "Closed", "100000.0", "", "10"),
    row("e2", "Active", "", "1000.0", "5"),
]
# N: no Closed records at all
N_ROWS = [row("n0", "Active", "", "1000.0", "5"), row("n1", "Pending", "", "1200.0", "9")]


def run(folder, name, rows):
    path = folder / f"{name}_engineered.csv"
    pd.DataFrame(rows, columns=COLUMNS).to_csv(path, index=False)
    flagged, filtered = folder / f"{name}_flagged.csv", folder / f"{name}_filtered.csv"
    result = w.process(name, path, flagged, filtered)
    thresholds = {t["field"]: t for t in result["thresholds"]}
    summary = pd.DataFrame(result["summary"])
    return w.load(path), w.load(flagged), w.load(filtered), thresholds, summary


class OutlierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter("always")
            cls.T = run(folder, "t", T_ROWS)
            cls.M = run(folder, "m", M_ROWS)
            cls.Z = run(folder, "z", Z_ROWS)
            cls.E = run(folder, "e", E_ROWS)
            cls.N = run(folder, "n", N_ROWS)
        cls.warnings = [str(x.message) for x in caught]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_thresholds_follow_the_handbook_formula(self):
        _, _, _, t, _ = self.T
        expected = {"ClosePrice": (20000, 40000, -10000, 70000), "LivingArea": (40, 60, 10, 90),
                    "DaysOnMarket": (40, 60, 10, 90)}
        for field, (q1, q3, lower, upper) in expected.items():
            self.assertEqual((t[field]["q1"], t[field]["q3"], t[field]["lower_bound"], t[field]["upper_bound"]),
                             (q1, q3, lower, upper), field)
            self.assertEqual(t[field]["iqr"], q3 - q1)
            self.assertEqual(t[field]["population_n"], 9)  # duplicate and non-Closed rows not used
        # the same quartiles as numpy's linear method, and the percentiles are reported
        values = [5000, 10000, 20000, 25000, 30000, 35000, 40000, 70000, 71000]
        self.assertEqual(t["ClosePrice"]["p50"], np.percentile(values, 50))
        self.assertAlmostEqual(t["ClosePrice"]["p95"], np.percentile(values, 95))
        self.assertEqual(t["ClosePrice"]["closed_duplicates_not_used"], 1)

    def test_bounds_are_inclusive(self):
        _, flagged, _, _, _ = self.T
        self.assertEqual(flagged.loc[5, "LivingArea_iqr_status"], "within bounds")  # 10 = lower bound
        self.assertEqual(flagged.loc[6, "LivingArea_iqr_status"], "within bounds")  # 90 = upper bound
        self.assertEqual(flagged.loc[7, "ClosePrice_iqr_status"], "within bounds")  # 70000 = upper bound
        self.assertEqual(flagged.loc[7, "LivingArea_iqr_status"], "below lower bound")  # 9
        self.assertEqual(flagged.loc[8, "LivingArea_iqr_status"], "above upper bound")  # 91
        self.assertEqual(flagged.loc[8, "ClosePrice_iqr_outlier_flag"], "True")      # 71000
        self.assertEqual(flagged.loc[8, "iqr_outlier_fields"], "ClosePrice; LivingArea; DaysOnMarket")

    def test_zero_days_on_market_is_valid_but_can_be_an_iqr_outlier(self):
        _, flagged, _, _, _ = self.T
        self.assertEqual(flagged.loc[7, "DaysOnMarket_business_invalid_flag"], "False")
        self.assertEqual(flagged.loc[7, "DaysOnMarket_iqr_status"], "below lower bound")  # 0 < 10
        _, flagged_m, _, _, _ = self.M
        self.assertEqual(flagged_m.loc[6, "DaysOnMarket_business_invalid_flag"], "False")
        self.assertEqual(flagged_m.loc[6, "DaysOnMarket_iqr_status"], "within bounds")  # bounds [-5, 35] here

    def test_missing_invalid_and_unparseable_values_never_look_evaluated(self):
        _, f, _, t, _ = self.M
        cases = [(0, "ClosePrice", "missing", "False", "ClosePrice missing"),
                 (1, "ClosePrice", "business invalid", "True", "ClosePrice business invalid (ClosePrice <= 0)"),
                 (2, "LivingArea", "business invalid", "True", "LivingArea business invalid (LivingArea <= 0)"),
                 (3, "DaysOnMarket", "business invalid", "True", "DaysOnMarket business invalid (DaysOnMarket < 0)"),
                 (4, "ClosePrice", "unparseable", "False", "ClosePrice unparseable"),
                 (5, "DaysOnMarket", "missing", "False", "DaysOnMarket missing")]
        for r, field, status, invalid_flag, reason in cases:
            self.assertEqual(f.loc[r, f"{field}_iqr_status"], status, (r, field))
            self.assertEqual(f.loc[r, f"{field}_business_invalid_flag"], invalid_flag, (r, field))
            self.assertEqual((f.loc[r, f"{field}_iqr_evaluable"], f.loc[r, f"{field}_iqr_outlier_flag"]),
                             ("False", "False"), (r, field))
            self.assertEqual(f.loc[r, "analysis_include"], "False")
            self.assertIn(reason, f.loc[r, "analysis_exclusion_reasons"])
        self.assertEqual(f.loc[0, "iqr_fields_evaluated"], "2")  # LivingArea and DaysOnMarket only
        # a value set to null in cleaning is told apart from an ordinary missing one
        self.assertEqual((t["ClosePrice"]["closed_missing"], t["ClosePrice"]["closed_business_invalid"],
                          t["ClosePrice"]["closed_unparseable"]), (1, 1, 1))

    def test_records_that_are_not_closed_are_kept_but_not_evaluated(self):
        raw, f, filtered, _, _ = self.T
        for r in (10, 11):
            for field in w.FIELDS:
                self.assertEqual(f.loc[r, f"{field}_iqr_status"], "not Closed")
                self.assertEqual(f.loc[r, f"{field}_iqr_evaluable"], "False")
            self.assertEqual(f.loc[r, "analysis_exclusion_reasons"], "not Closed")
        self.assertEqual(f.loc[10, "ClosePrice_iqr_outlier_flag"], "False")  # 9,999,999 not evaluated
        self.assertEqual(f.loc[11, "ClosePrice_business_invalid_flag"], "False")  # missing price is expected
        self.assertEqual(f.loc[11, "LivingArea_business_invalid_flag"], "True")   # rule holds for all records
        self.assertNotIn("0010", set(filtered["ListingKey"]))
        self.assertEqual(len(f), len(raw))

    def test_exact_duplicates_excluded_but_repeated_keys_kept(self):
        _, f, filtered, _, summary = self.T
        self.assertEqual(f.loc[9, "ClosePrice_iqr_status"], "within bounds")  # evaluated...
        self.assertEqual(f.loc[9, "analysis_exclusion_reasons"], "exact later duplicate")  # ...but excluded
        self.assertEqual(filtered["ListingKey"].tolist(), ["0001", "0001", "0003", "0004", "0005", "0006", "0007"])
        flow = summary[summary["section"] == "population flow"]["records"].tolist()
        self.assertEqual(flow, [12, 10, 9, 9, 7])

    def test_reasons_overlap_and_unique_total_is_reported(self):
        _, _, _, _, s = self.T
        reasons = s[s["section"] == "exclusion reasons (overlapping)"].set_index("item")["records"]
        self.assertEqual(reasons["LivingArea below IQR lower bound"], 1)
        self.assertEqual(reasons["DaysOnMarket below IQR lower bound"], 1)
        self.assertEqual(reasons["ClosePrice above IQR upper bound"], 1)
        unique = s[s["section"] == "unique excluded"].set_index("item")["records"]
        self.assertEqual(unique["records excluded (unique)"], 5)  # rows 7, 8, 9, 10 and 11
        self.assertEqual(unique["records excluded for two or more reasons"], 2)  # rows 7 and 8
        self.assertLess(unique["records excluded (unique)"], reasons.sum())

    def test_medians_before_and_after_the_iqr_step(self):
        _, _, _, _, s = self.T
        step = s[s["section"] == "IQR step: eligible vs filtered"].set_index("item")
        self.assertEqual((step.loc["ClosePrice", "n_before"], step.loc["ClosePrice", "n_after"]), (9, 7))
        self.assertEqual(step.loc["ClosePrice", "median_before"], 30000)
        self.assertEqual(step.loc["ClosePrice", "median_after"], 25000)

    def test_supplementary_metrics_never_exclude(self):
        _, f, filtered, _, _ = self.T
        self.assertEqual(f.loc[2, "analysis_include"], "True")  # price_per_sqft 999,999
        self.assertIn("0003", set(filtered["ListingKey"]))
        self.assertFalse(f["analysis_exclusion_reasons"].fillna("").str.contains("price_per_sqft").any())

    def test_zero_iqr_applies_the_formula_and_reports_it(self):
        _, f, filtered, t, _ = self.Z
        d = t["DaysOnMarket"]
        self.assertTrue(d["iqr_is_zero"])
        self.assertEqual((d["q1"], d["q3"], d["lower_bound"], d["upper_bound"]), (7, 7, 7, 7))
        self.assertIn("IQR = 0", d["threshold_status"])
        self.assertEqual(f["DaysOnMarket_iqr_status"].tolist()[-2:], ["below lower bound", "above upper bound"])
        self.assertEqual(len(filtered), 7)  # only the rows with exactly 7 days

    def test_no_eligible_values_means_no_thresholds_and_nothing_passes(self):
        _, f, filtered, t, s = self.E
        self.assertEqual(t["LivingArea"]["population_n"], 0)
        self.assertNotIn("lower_bound", t["LivingArea"])
        self.assertIn("no thresholds", t["LivingArea"]["threshold_status"])
        self.assertEqual(f.loc[0, "LivingArea_iqr_status"], "no thresholds")  # valid, but nothing to compare with
        self.assertEqual(f.loc[1, "LivingArea_iqr_status"], "missing")
        self.assertIn("LivingArea no IQR thresholds", f.loc[0, "analysis_exclusion_reasons"])
        self.assertEqual(len(filtered), 0)
        self.assertEqual(list(filtered.columns), list(f.columns))  # an empty file, but with its header
        _, f_n, filtered_n, t_n, _ = self.N
        self.assertEqual(len(filtered_n), 0)
        self.assertTrue(all(t_n[field]["population_n"] == 0 for field in w.FIELDS))
        self.assertEqual(set(f_n["analysis_exclusion_reasons"]), {"not Closed"})

    def test_flagged_preserves_input_and_filtered_is_the_included_subset(self):
        raw, f, filtered, _, _ = self.T
        self.assertEqual(list(f.columns[:raw.shape[1]]), list(raw.columns))
        for col in raw.columns:
            self.assertTrue(w.same_text(f[col], raw[col]), col)
        self.assertEqual(f.loc[0, ["ListingKey", "PostalCode"]].tolist(), ["0001", "01234"])
        expected = f[f["analysis_include"] == "True"].reset_index(drop=True)
        for col in f.columns:
            self.assertTrue(w.same_text(filtered[col], expected[col]), col)

    def test_no_pandas_warnings(self):
        self.assertEqual(self.warnings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
