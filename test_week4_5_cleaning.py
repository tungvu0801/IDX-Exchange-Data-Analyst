"""
Regression tests for week4_5_cleaning.py on a small synthetic sold file.
No real data is needed. Run: python test_week4_5_cleaning.py
"""

import contextlib
import hashlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path

import pandas as pd

import week4_5_cleaning as w

COLUMNS = ["ListingKey", "ListingId", "PostalCode", "BuyerAgentMlsId", "UnparsedAddress",
           "MlsStatus", "ListingContractDate", "PurchaseContractDate", "CloseDate",
           "ContractStatusChangeDate", "ClosePrice", "LivingArea", "DaysOnMarket",
           "BedroomsTotal", "BathroomsTotalInteger", "Latitude", "Longitude", "ViewYN",
           "year_month", "rate_30yr_fixed"]
# One row per case; dates are Listing, Purchase, Close
ROWS = [
    # 0: leading-zero identifiers, all three date rules evaluable and passing
    ["0001", "0042AB", "01234", "0099", "1 A St", "Closed", "2024-01-05", "2024-01-20",
     "2024-02-10", "2024-02-10", "500000.0", "1200.0", "15", "0.0", "1.0", "34.05", "-118.24",
     "True", "2024-02", "6.1899999999999995"],
    # 1: invalid PurchaseContractDate; Latitude missing while Longitude is invalid
    ["0002", "B2", "90210", "X1", "2 B St", "Closed", "2024-01-05", "2024-02-30",
     "2024-02-10", "2024-02-10", "600000.0", "1300.0", "36", "3.0", "2.0", "", "329.0",
     "False", "2024-02", "6.1899999999999995"],
    # 2: repeated key; listing after close and purchase before listing (failing checks)
    ["0003", "C3", "90001", "X2", "3 C St", "Closed", "2024-03-01", "2024-02-01",
     "2024-02-15", "2024-02-15", "700000.0", "1400.0", "5", "3.0", "2.0", "34.10", "-118.30",
     "", "2024-02", "6.1899999999999995"],
    # 3: same key as row 2, different content
    ["0003", "C3", "90001", "X2", "3 C St", "Closed", "2024-01-10", "2024-01-20",
     "2024-01-30", "2024-01-30", "710000.0", "1400.0", "10", "3.0", "2.0", "34.10", "-118.30",
     "", "2024-01", "6.6425"],
    # 4 and 5: missing ListingKey (two of them; they must not count as "repeated")
    ["", "D4", "90002", "X3", "4 D St", "Closed", "2024-01-05", "2024-01-20", "2024-01-25",
     "2024-01-25", "400000.0", "900.0", "7", "2.0", "1.0", "34.00", "-118.00", "True",
     "2024-01", "6.6425"],
    ["", "E5", "90003", "X4", "5 E St", "Closed", "2024-01-06", "2024-01-21", "2024-01-26",
     "2024-01-26", "410000.0", "950.0", "8", "2.0", "1.0", "34.01", "-118.01", "True",
     "2024-01", "6.6425"],
    # 6: PurchaseContractDate missing, nothing else wrong -> unevaluable, but no quality issue
    ["0006", "F6", "90004", "X5", "6 F St", "Closed", "2024-01-05", "", "2024-01-25",
     "2024-01-25", "420000.0", "1000.0", "20", "2.0", "1.0", "34.02", "-118.02", "False",
     "2024-01", "6.6425"],
    # 7: equal dates are allowed (passing)
    ["0007", "G7", "90005", "X6", "7 G St", "Closed", "2024-01-15", "2024-01-15",
     "2024-01-15", "2024-01-15", "430000.0", "1050.0", "0", "2.0", "1.0", "34.03", "-118.03",
     "True", "2024-01", "6.6425"],
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CleaningRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        cls.in_path, cls.out_path = folder / "sold_with_rates.csv", folder / "sold_cleaned.csv"
        pd.DataFrame(ROWS, columns=COLUMNS).to_csv(cls.in_path, index=False)
        cls.input_hash = sha256(cls.in_path)
        w.summary_rows.clear()
        with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter("always")
            w.clean("sold", cls.in_path, cls.out_path, "CloseDate")
        cls.warnings = [str(x.message) for x in caught]
        cls.summary = pd.DataFrame(w.summary_rows)
        cls.raw = w.load(cls.in_path)
        cls.out = w.load(cls.out_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def count(self, item):
        return int(self.summary.loc[self.summary["item"] == item, "count"].iloc[0])

    def test_invalid_date_exports_missing_with_original_text_kept(self):
        self.assertTrue(pd.isna(self.out.loc[1, "PurchaseContractDate"]))
        self.assertEqual(self.out.loc[1, "PurchaseContractDate_unparsed_original"], "2024-02-30")
        self.assertTrue(self.out["PurchaseContractDate_unparsed_original"].drop(index=1).isna().all())
        self.assertEqual(self.out.loc[1, "parse_failure_flag"], "True")
        self.assertEqual(self.count("PurchaseContractDate: failed to parse"), 1)
        self.assertEqual(self.count("PurchaseContractDate: originally missing"), 1)  # row 6

    def test_missing_coordinate_with_invalid_available_coordinate(self):
        row = self.out.loc[1]
        self.assertTrue(pd.isna(row["Latitude"]))
        self.assertEqual(row["Longitude"], "329.0")  # kept as it was, not repaired
        self.assertEqual(row["missing_coordinates_flag"], "True")
        self.assertEqual(row["invalid_coordinate_range_flag"], "True")
        self.assertEqual(row["positive_longitude_flag"], "True")
        self.assertEqual(row["outside_ca_bbox_flag"], "False")  # needs both coordinates
        self.assertEqual(self.count("outside_ca_bbox_flag: not evaluable"), 1)
        self.assertEqual(self.count("invalid_coordinate_range_flag: not evaluable"), 0)
        self.assertEqual(self.count("rows with only one coordinate"), 1)

    def test_repeated_valid_keys_versus_missing_keys(self):
        self.assertEqual(self.out["repeated_listing_key_flag"].tolist(),
                         ["False", "False", "True", "True", "False", "False", "False", "False"])
        self.assertEqual(self.out["missing_listing_key_flag"].tolist(),
                         ["False", "False", "False", "False", "True", "True", "False", "False"])
        self.assertEqual(self.count("repeated_listing_key_flag"), 2)
        detail = self.summary.loc[self.summary["item"] == "repeated_listing_key_flag", "detail"].iloc[0]
        self.assertIn("1 distinct keys, 1 rows beyond the first per key", detail)

    def test_unevaluable_versus_passing_versus_failing_date_checks(self):
        o = self.out
        # passing: evaluable and not flagged (row 0, and equal dates in row 7)
        for r in (0, 7):
            for rule in ("listing_after_close", "purchase_after_close", "negative_timeline"):
                self.assertEqual((o.loc[r, f"{rule}_evaluable"], o.loc[r, f"{rule}_flag"]), ("True", "False"))
        # failing: evaluable and flagged (row 2)
        self.assertEqual((o.loc[2, "listing_after_close_evaluable"], o.loc[2, "listing_after_close_flag"]), ("True", "True"))
        self.assertEqual((o.loc[2, "negative_timeline_evaluable"], o.loc[2, "negative_timeline_flag"]), ("True", "True"))
        self.assertEqual(o.loc[2, "purchase_after_close_flag"], "False")
        # unevaluable: flag stays False, evaluable says it was not checked (rows 1 and 6)
        for r in (1, 6):
            for rule in ("purchase_after_close", "negative_timeline"):
                self.assertEqual((o.loc[r, f"{rule}_evaluable"], o.loc[r, f"{rule}_flag"]), ("False", "False"))
        # eligibility columns are not quality issues: row 6 is unevaluable but clean
        self.assertEqual(o.loc[6, "any_quality_issue_flag"], "False")
        self.assertEqual(self.count("purchase_after_close_flag: not evaluable"), 2)

    def test_identifiers_rows_month_key_and_rates_preserved(self):
        self.assertEqual(sha256(self.in_path), self.input_hash)  # input not modified
        self.assertEqual(len(self.out), len(self.raw))
        for col in ["ListingKey", "ListingId", "PostalCode", "BuyerAgentMlsId", "year_month", "rate_30yr_fixed"]:
            self.assertTrue(w.same_text(self.out[col], self.raw[col]), col)
        self.assertEqual(self.out.loc[0, ["ListingKey", "PostalCode", "BuyerAgentMlsId"]].tolist(),
                         ["0001", "01234", "0099"])
        self.assertEqual(self.out.loc[0, "rate_30yr_fixed"], "6.1899999999999995")

    def test_zero_counts_are_allowed_and_no_pandas_warnings(self):
        self.assertEqual(self.out.loc[0, "negative_bedrooms_flag"], "False")  # 0 bedrooms is allowed
        self.assertEqual(self.warnings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
