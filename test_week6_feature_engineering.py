"""
Regression tests for week6_feature_engineering.py on a small synthetic listings
file and synthetic district polygons. No real data or internet is needed.
Run: python test_week6_feature_engineering.py
"""

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import warnings
from pathlib import Path

import pandas as pd

import week6_feature_engineering as w

# ListingKey, MlsStatus, ClosePrice, ListPrice, OriginalListPrice, LivingArea, DaysOnMarket,
# ListingContractDate, PurchaseContractDate, CloseDate, Latitude, Longitude
ROWS = [
    # 0: Closed, every input valid; inside Alpha Unified; leading-zero identifiers
    ["0001", "Closed", "500000.0", "520000.0", "550000.0", "1000.0", "10",
     "2024-01-01", "2024-01-11", "2024-02-10", "34.25", "-118.25"],
    # 1: zero denominators; inside Bravo Elementary and Charlie Union High
    ["0002", "Closed", "400000.0", "0.0", "0.0", "0.0", "5",
     "2024-01-01", "2024-01-11", "2024-02-10", "34.25", "-117.75"],
    # 2: ClosePrice blanked in cleaning (original -5.0), LivingArea missing, DOM blanked; in a hole
    ["0003", "Closed", "", "300000.0", "300000.0", "", "",
     "2024-01-01", "2024-01-11", "2024-02-10", "36.25", "-120.25"],
    # 3: purchase before listing (negative_timeline_flag); inside Foxtrot Unified
    ["0004", "Closed", "450000.0", "450000.0", "460000.0", "900.0", "14",
     "2024-03-01", "2024-02-01", "2024-03-15", "36.1", "-120.1"],
    # 4: purchase after close (purchase_after_close_flag); in Golf Unified's second part
    ["0005", "Closed", "350000.0", "360000.0", "370000.0", "700.0", "40",
     "2024-03-01", "2024-04-10", "2024-04-01", "37.05", "-121.15"],
    # 5: PurchaseContractDate missing; same location as row 0
    ["0006", "Closed", "510000.0", "500000.0", "500000.0", "1100.0", "20",
     "2024-01-05", "", "2024-01-25", "34.25", "-118.25"],
    # 6: Pending with a ClosePrice and a future CloseDate
    ["0007", "Pending", "600000.0", "610000.0", "620000.0", "1200.0", "19",
     "2024-05-01", "2024-05-20", "2030-04-16", "34.25", "-118.25"],
    # 7: Active, no contract yet
    ["0008", "Active", "", "700000.0", "700000.0", "1300.0", "30",
     "2024-06-01", "", "", "34.25", "-117.75"],
    # 8: exact later duplicate of row 0
    ["0001", "Closed", "500000.0", "520000.0", "550000.0", "1000.0", "10",
     "2024-01-01", "2024-01-11", "2024-02-10", "34.25", "-118.25"],
    # 9: equal dates (0-day intervals); OriginalListPrice missing; same location as row 0
    ["0009", "Closed", "550000.0", "550000.0", "", "1000.0", "0",
     "2024-07-15", "2024-07-15", "2024-07-15", "34.25", "-118.25"],
    # 10: inside two overlapping Unified districts (ambiguous); key repeated in row 11
    ["0010", "Closed", "800000.0", "790000.0", "800000.0", "2000.0", "8",
     "2024-02-01", "2024-02-10", "2024-03-01", "35.25", "-119.1"],
    # 11: same key as row 10, different content; Latitude missing
    ["0010", "Closed", "810000.0", "790000.0", "800000.0", "2000.0", "9",
     "2024-02-01", "2024-02-11", "2024-03-02", "", "-119.1"],
    # 12: positive longitude
    ["0012", "Closed", "300000.0", "310000.0", "320000.0", "800.0", "12",
     "2024-02-01", "2024-02-10", "2024-03-01", "34.25", "118.25"],
    # 13: out of state (no district); LivingArea missing
    ["0013", "Closed", "250000.0", "260000.0", "270000.0", "", "6",
     "2024-02-01", "2024-02-10", "2024-03-01", "40.0", "-100.0"],
    # 14: zero latitude
    ["0014", "Closed", "260000.0", "260000.0", "260000.0", "850.0", "7",
     "2024-02-01", "2024-02-10", "2024-03-01", "0.0", "-118.25"],
]
COLUMNS = ["ListingKey", "MlsStatus", "ClosePrice", "ListPrice", "OriginalListPrice", "LivingArea",
           "DaysOnMarket", "ListingContractDate", "PurchaseContractDate", "CloseDate",
           "Latitude", "Longitude"]


def square(x0, x1, y0, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


DISTRICTS = [  # name, type, CDS code, geometry
    ("Alpha Unified", "Unified", "01000000000001", {"type": "Polygon", "coordinates": [square(-118.5, -118.0, 34.0, 34.5)]}),
    ("Bravo Elementary", "Elementary", "02000000000002", {"type": "Polygon", "coordinates": [square(-118.0, -117.5, 34.0, 34.5)]}),
    ("Charlie Union High", "High", "03000000000003", {"type": "Polygon", "coordinates": [square(-118.0, -117.0, 34.0, 34.5)]}),
    ("Delta Unified", "Unified", "04000000000004", {"type": "Polygon", "coordinates": [square(-119.5, -119.0, 35.0, 35.5)]}),
    ("Echo Unified", "Unified", "05000000000005", {"type": "Polygon", "coordinates": [square(-119.25, -118.75, 35.0, 35.5)]}),
    ("Foxtrot Unified", "Unified", "06000000000006", {"type": "Polygon", "coordinates": [
        square(-120.5, -120.0, 36.0, 36.5), square(-120.3, -120.2, 36.2, 36.3)]}),
    ("Golf Unified", "Unified", "07000000000007", {"type": "MultiPolygon", "coordinates": [
        [square(-121.5, -121.4, 37.0, 37.1)], [square(-121.2, -121.1, 37.0, 37.1)]]}),
]


def cleaned_frame():
    """The synthetic rows with every column the cleaning would have added, as text."""
    df = pd.DataFrame(ROWS, columns=COLUMNS)
    n = len(df)
    df.insert(1, "ListingId", [f"ID{i:03d}" for i in range(n)])
    df["PostalCode"] = ["01234"] * n
    df["BuyerAgentMlsId"] = ["0099"] * n
    df["PropertyType"] = "Residential"
    df["PropertySubType"] = ["SingleFamilyResidence", "Condominium"] * 7 + ["Townhouse"]
    df["CountyOrParish"] = ["Los Angeles"] * 8 + ["Los Angeles"] + ["Kern"] * 6
    df["MLSAreaMajor"] = ["A1", ""] * 7 + ["A1"]
    df["ListOfficeName"] = "Office 1"
    df["BuyerOfficeName"] = ["Office 2", ""] * 7 + ["Office 2"]
    df["HighSchoolDistrict"] = ["Alpha Unified"] + ["Other"] * (n - 1)
    df["year_month"] = df["ListingContractDate"].str[:7]
    df["rate_30yr_fixed"] = "6.1899999999999995"
    df["ClosePrice_invalid_original"] = ["", "", "-5.0"] + [""] * (n - 3)
    df["LivingArea_invalid_original"] = ""
    df["DaysOnMarket_invalid_original"] = ["", "", "-3"] + [""] * (n - 3)
    dates = {c: pd.to_datetime(df[c], format="%Y-%m-%d", errors="coerce") for c in
             ["ListingContractDate", "PurchaseContractDate", "CloseDate"]}
    for rule, first, second in [("listing_after_close", "ListingContractDate", "CloseDate"),
                                ("purchase_after_close", "PurchaseContractDate", "CloseDate"),
                                ("negative_timeline", "ListingContractDate", "PurchaseContractDate")]:
        evaluable = dates[first].notna() & dates[second].notna()
        df[f"{rule}_evaluable"] = evaluable
        df[f"{rule}_flag"] = evaluable & (dates[first] > dates[second])
    lat = pd.to_numeric(df["Latitude"], errors="coerce")
    lon = pd.to_numeric(df["Longitude"], errors="coerce")
    df["missing_coordinates_flag"] = lat.isna() | lon.isna()
    df["zero_coordinate_flag"] = lat.eq(0) | lon.eq(0)
    df["positive_longitude_flag"] = lon > 0
    df["invalid_coordinate_range_flag"] = (lat.abs() > 90) | (lon.abs() > 180)
    df["outside_ca_bbox_flag"] = lat.notna() & lon.notna() & ~(lat.between(32.5, 42.1) & lon.between(-124.5, -114.1))
    df["duplicate_record_flag"] = [False] * 8 + [True] + [False] * (n - 9)
    df["repeated_listing_key_flag"] = df["ListingKey"].duplicated(keep=False)
    return df


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FeatureEngineeringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        cls.in_path, cls.out_path = folder / "listings_cleaned.csv", folder / "listings_engineered.csv"
        cleaned_frame().to_csv(cls.in_path, index=False)
        geo = folder / "districts.geojson"
        geo.write_text(json.dumps({
            "type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "features": [{"type": "Feature", "geometry": g, "properties": {
                "DistrictName": name, "DistrictType": kind, "CDSCode": cds, "Year": "2024-25"}}
                for name, kind, cds, g in DISTRICTS]}), encoding="utf-8")
        cls.input_hash = sha256(cls.in_path)
        w.summary_rows.clear()
        with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter("always")
            cls.matches = w.district_lookup([cls.in_path], w.load_districts(geo))
            cls.result = w.process("listings", cls.in_path, cls.out_path, "ListingContractDate", cls.matches)
        cls.warnings = [str(x.message) for x in caught]
        cls.summary = pd.DataFrame(w.summary_rows)
        cls.raw = w.load(cls.in_path)
        cls.out = w.load(cls.out_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cell(self, row, col):
        return self.out.loc[row, col]

    def validation(self, item):
        return self.summary.loc[self.summary["item"] == item].iloc[0]

    def test_division_by_zero_gives_null_with_reason_not_infinity(self):
        self.assertTrue(pd.isna(self.cell(1, "price_ratio")))
        self.assertEqual(self.cell(1, "price_ratio_null_reason"), "OriginalListPrice <= 0")
        self.assertEqual(self.cell(1, "close_to_original_list_ratio_null_reason"), "OriginalListPrice <= 0")
        self.assertEqual(self.cell(1, "close_to_current_list_ratio_null_reason"), "ListPrice <= 0")
        self.assertEqual(self.cell(1, "price_per_sqft_null_reason"), "LivingArea <= 0")
        numeric = ["price_ratio", "close_to_original_list_ratio", "close_to_current_list_ratio",
                   "price_per_sqft", "listing_to_contract_days", "contract_to_close_days"]
        written = self.out[numeric].stack().str.lower()  # the text as saved, missing cells skipped
        self.assertFalse(written.str.contains("inf|nan").any())

    def test_missing_and_invalid_inputs_give_null_with_reason(self):
        reason = "ClosePrice set to null in cleaning as invalid (original in ClosePrice_invalid_original)"
        for metric in ("price_ratio", "close_to_original_list_ratio", "close_to_current_list_ratio",
                       "price_per_sqft"):
            self.assertTrue(pd.isna(self.cell(2, metric)))
            self.assertEqual(self.cell(2, f"{metric}_null_reason"), reason)
        self.assertEqual(self.cell(13, "price_per_sqft_null_reason"), "LivingArea missing")
        self.assertEqual(float(self.cell(13, "price_ratio")), 250000.0 / 270000.0)  # other metrics unaffected
        for metric in ("listing_to_contract_days", "contract_to_close_days"):
            self.assertEqual(self.cell(5, f"{metric}_null_reason"), "PurchaseContractDate missing")
        # DaysOnMarket is the cleaned MLS field, untouched; its invalid original stays in the audit column
        self.assertTrue(pd.isna(self.cell(2, "DaysOnMarket")))
        self.assertEqual(self.cell(2, "DaysOnMarket_invalid_original"), "-3")

    def test_formulas_on_a_valid_closed_record(self):
        self.assertEqual(float(self.cell(0, "price_ratio")), 500000.0 / 550000.0)  # handbook: OriginalListPrice
        self.assertEqual(float(self.cell(0, "close_to_original_list_ratio")), 500000.0 / 550000.0)
        self.assertEqual(float(self.cell(0, "close_to_current_list_ratio")), 500000.0 / 520000.0)
        self.assertEqual(float(self.cell(0, "price_per_sqft")), 500.0)
        self.assertEqual(self.out.loc[0, ["Year", "Month", "YrMo"]].tolist(), ["2024", "2", "2024-02"])
        self.assertEqual(self.out.loc[0, ["listing_to_contract_days", "contract_to_close_days"]].tolist(), ["10", "30"])
        self.assertTrue(pd.isna(self.cell(0, "price_ratio_null_reason")))

    def test_required_ratios_identical_and_current_list_ratio_uses_list_price(self):
        o = self.out
        self.assertEqual(w.PRICE_RATIO_DENOMINATOR, "OriginalListPrice")
        # the two handbook ratios: same values, same null mask, same reasons, in every row
        self.assertTrue((o["price_ratio"].isna() == o["close_to_original_list_ratio"].isna()).all())
        self.assertTrue(w.same_text(o["price_ratio"], o["close_to_original_list_ratio"]))
        self.assertTrue(w.same_text(o["price_ratio_null_reason"], o["close_to_original_list_ratio_null_reason"]))
        self.assertEqual(self.validation("price_ratio identical to close_to_original_list_ratio")["count"], 15)
        # the extra ratio divides by ListPrice wherever it has a value
        filled = o["close_to_current_list_ratio"].notna()
        expected = self.raw.loc[filled, "ClosePrice"].map(float) / self.raw.loc[filled, "ListPrice"].map(float)
        self.assertEqual(o.loc[filled, "close_to_current_list_ratio"].map(float).tolist(), expected.tolist())
        # row 9: OriginalListPrice missing, so only the current-list ratio has a value
        self.assertEqual(self.cell(9, "price_ratio_null_reason"), "OriginalListPrice missing")
        self.assertEqual(self.cell(9, "close_to_current_list_ratio"), "1.0")
        self.assertTrue(pd.isna(self.cell(9, "close_to_current_list_ratio_null_reason")))

    def test_yrmo_checked_against_year_month_on_each_date_basis(self):
        # listings: year_month comes from ListingContractDate, so differences from YrMo are expected
        basis = self.validation("year_month equals the ListingContractDate month")
        self.assertEqual((basis["count"], basis["detail"].split(";")[0]), (15, "mismatches: 0"))
        compare = self.validation("YrMo equals year_month (year_month is from ListingContractDate)")
        self.assertEqual(compare["count"], 3)  # rows 3, 5 and 9 closed in their listing month
        self.assertIn("of 13 rows with a YrMo", compare["detail"])
        # sold: year_month comes from CloseDate, so YrMo must equal it, and a mismatch is an error
        sold_path = Path(self.tmp.name) / "sold_like.csv"
        frame = cleaned_frame()
        frame["year_month"] = frame["CloseDate"].str[:7].where(frame["CloseDate"] != "", "2024-06")
        frame.to_csv(sold_path, index=False)
        sold = w.load(sold_path)
        with contextlib.redirect_stdout(io.StringIO()):
            w.validate(sold, w.engineer(sold), "sold", "CloseDate")  # passes
            sold.loc[0, "year_month"] = "2024-01"  # CloseDate is 2024-02-10
            with self.assertRaisesRegex(ValueError, "year_month differs from the CloseDate month"):
                w.validate(sold, w.engineer(sold), "sold", "CloseDate")

    def test_invalid_date_order_gives_null_and_equal_dates_give_zero(self):
        self.assertTrue(pd.isna(self.cell(3, "listing_to_contract_days")))
        self.assertEqual(self.cell(3, "listing_to_contract_days_null_reason"),
                         "PurchaseContractDate before ListingContractDate (negative_timeline_flag)")
        self.assertEqual(self.cell(3, "contract_to_close_days"), "43")  # 2024-02-01 -> 2024-03-15
        self.assertTrue(pd.isna(self.cell(4, "contract_to_close_days")))
        self.assertEqual(self.cell(4, "contract_to_close_days_null_reason"),
                         "PurchaseContractDate after CloseDate (purchase_after_close_flag)")
        self.assertEqual(self.cell(4, "listing_to_contract_days"), "40")
        self.assertEqual(self.out.loc[9, ["listing_to_contract_days", "contract_to_close_days"]].tolist(), ["0", "0"])

    def test_non_closed_records_get_no_completed_sale_metrics(self):
        for metric in w.COMPLETED_SALE_METRICS:
            self.assertTrue(pd.isna(self.cell(6, metric)), metric)  # Pending, ClosePrice and 2030 CloseDate
            self.assertTrue(pd.isna(self.cell(7, metric)), metric)
        self.assertEqual(self.cell(6, "price_ratio_null_reason"), "not Closed (MlsStatus Pending)")
        self.assertEqual(self.cell(6, "YrMo_null_reason"), "not Closed (MlsStatus Pending)")
        self.assertEqual(self.cell(7, "contract_to_close_days_null_reason"), "not Closed (MlsStatus Active)")
        self.assertEqual(self.cell(6, "listing_to_contract_days"), "19")  # uses no close field
        self.assertEqual(self.cell(7, "listing_to_contract_days_null_reason"), "PurchaseContractDate missing")

    def test_identifiers_and_every_input_column_preserved(self):
        self.assertEqual(sha256(self.in_path), self.input_hash)  # input not modified
        self.assertEqual(len(self.out), len(self.raw))
        self.assertEqual(list(self.out.columns[:self.raw.shape[1]]), list(self.raw.columns))
        for col in self.raw.columns:
            self.assertTrue(w.same_text(self.out[col], self.raw[col]), col)
        self.assertEqual(self.out.loc[0, ["ListingKey", "PostalCode", "BuyerAgentMlsId", "rate_30yr_fixed"]].tolist(),
                         ["0001", "01234", "0099", "6.1899999999999995"])

    def test_duplicates_excluded_from_summaries_only(self):
        self.assertEqual(len(self.out), 15)  # the engineered data keeps the duplicate
        table = self.result["summaries"]["property_type"].iloc[0]
        self.assertEqual((table["records"], table["duplicate_rows_excluded"], table["records_used"]), (15, 1, 14))
        self.assertEqual(table["closed_records_used"], 12)  # repeated key 0010 counted twice; Pending/Active not Closed
        self.assertEqual(table["ClosePrice_n"], 11)  # row 2's ClosePrice was invalid
        self.assertEqual(table["close_to_current_list_ratio_n"], 10)  # and row 1's ListPrice is 0
        self.assertEqual(table["price_ratio_n"], 9)  # and row 9's OriginalListPrice is missing
        self.assertEqual(table["close_to_original_list_ratio_n"], 9)
        self.assertEqual(table["price_ratio_median"], table["close_to_original_list_ratio_median"])
        # each metric excludes only its own invalid rows (not every flagged row)
        self.assertEqual(table["listing_to_contract_days_n"], 11)
        subtype = self.result["summaries"]["county_mls_area"]
        self.assertIn("(missing)", set(subtype["MLSAreaMajor"]))

    def test_spatial_join_preserves_rows_and_reports_problems(self):
        o = self.out
        self.assertEqual(o["ListingKey"].tolist(), self.raw["ListingKey"].tolist())  # same rows, same order
        self.assertLess(len(self.matches), int((~self.raw["missing_coordinates_flag"].eq("True")).sum()))
        for r in (0, 5, 6, 8, 9):  # several rows share one location; each still appears once
            self.assertEqual((o.loc[r, "school_district_match_status"], o.loc[r, "unified_district_name"],
                              o.loc[r, "unified_district_cds"]), ("matched", "Alpha Unified", "01000000000001"))
        self.assertEqual(o.loc[1, ["elementary_district_name", "high_district_name", "school_district_match_note",
                                   "school_district_match_count"]].tolist(),
                         ["Bravo Elementary", "Charlie Union High", "Elementary + High", "2"])
        self.assertTrue(pd.isna(o.loc[1, "unified_district_name"]))
        self.assertEqual(o.loc[2, "school_district_match_status"], "unmatched")  # inside the hole
        self.assertEqual(o.loc[3, "unified_district_name"], "Foxtrot Unified")
        self.assertEqual(o.loc[4, "unified_district_name"], "Golf Unified")  # second polygon of a MultiPolygon
        self.assertEqual(o.loc[10, "school_district_match_status"], "ambiguous")
        self.assertIn("2 Unified districts (04000000000004|05000000000005)", o.loc[10, "school_district_match_note"])
        self.assertTrue(pd.isna(o.loc[10, "unified_district_name"]))
        self.assertEqual(o.loc[11, "school_district_match_status"], "missing coordinates")
        self.assertEqual(o.loc[12, ["school_district_match_status", "school_district_match_note"]].tolist(),
                         ["invalid coordinates", "positive_longitude_flag"])
        self.assertIn("outside the CA bounding box", o.loc[13, "school_district_match_note"])
        self.assertEqual(o.loc[14, "school_district_match_note"], "zero_coordinate_flag")
        self.assertEqual(o.loc[0, ["Latitude", "Longitude"]].tolist(), ["34.25", "-118.25"])  # not altered

    def test_no_pandas_warnings(self):
        self.assertEqual(self.warnings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
