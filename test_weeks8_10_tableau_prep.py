"""
Regression tests for weeks8_10_tableau_prep.py on small synthetic sold and listings
tables. No real data or internet is needed. Run: python test_weeks8_10_tableau_prep.py
"""

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path

import pandas as pd

import weeks8_10_tableau_prep as p

SOLD_COLUMNS = ["ListingKey", "ListingId", "MlsStatus", "PropertyType", "PropertySubType", "CloseDate",
                "ContractStatusChangeDate", "ClosePrice", "ListPrice", "OriginalListPrice", "LivingArea",
                "DaysOnMarket", "close_to_original_list_ratio", "City", "CountyOrParish", "StateOrProvince",
                "PostalCode", "Latitude", "Longitude", "ListAgentFullName", "ListAgentEmail", "ListOfficeName",
                "ClosePrice_iqr_status", "LivingArea_iqr_status", "DaysOnMarket_iqr_status", "iqr_outlier_flag",
                "analysis_include", "analysis_exclusion_reasons", "duplicate_record_flag"]
W, A, M = "within bounds", "above upper bound", "missing"


def sale(key, close, price, agent, email, office, city="Los Angeles", postal="90210", status=(W, W, W),
         include="True", ratio="0.98", olp="500000.0", la="1500.0", dom="20", change=None, dup="False"):
    reasons = "" if include == "True" else "something"
    return [key, f"ID{key}", "Closed", "Residential", "SingleFamilyResidence", close, change or close, price,
            "500000.0", olp, la, dom, ratio, city, "Los Angeles", "CA", postal, "34.1", "-118.4", agent, email,
            office, *status, "False" if include == "True" else "True", include, reasons, dup]


SOLD = [
    sale("0001", "2024-01-10", "500000.0", "Ann Lee", "ann@x.com", "Compass"),                       # 0
    sale("0002", "2024-01-15", "3000000.0", "Bob Ray", "bob@x.com", "COMPASS", city="LOS ANGELES",
         postal="90210-1234", status=(A, W, W), include="False"),                                     # 1 IQR outlier
    sale("0003", "2024-02-01", "400000.0", "Cy Doe", "cy@x.com", "Unknown Office", postal="0",
         status=(W, M, W), la="", include="False"),                                                    # 2 LivingArea missing
    sale("0004", "2024-02-03", "450000.0", "Non Member", "", "Redfin", status=(W, W, M), dom="",
         include="False"),                                                                             # 3 DOM missing
    sale("0005", "2024-02-10", "600000.0", "Di Fox", "di@x.com", "Redfin"),                          # 4 snapshot A
    sale("0005", "2024-03-05", "600000.0", "Di Fox", "di@x.com", "Redfin"),                          # 5 snapshot B (counted)
    sale("0001", "2024-01-10", "500000.0", "Ann Lee", "ann@x.com", "Compass", dup="True"),            # 6 exact later duplicate
    sale("0007", "2024-03-07", "700000.0", "Ann Lee", "ann@x.com", "Compass", ratio="", olp=""),     # 7 ratio missing
    sale("0008", "2024-03-09", "", "Ed Kim", "ed@x.com", "Zillow Offices", status=(M, W, W),
         include="False", ratio=""),                                                                   # 8 ClosePrice missing
    sale("0009", "2024-03-11", "1200000.0", "Ann Lee", "ann2@y.com", "Zillow Offices"),              # 9 namesake, other office
    sale("0010", "2024-04-02", "550000.0", "Ann  Lee", "ann.new@x.com", "Compass"),                  # 10 same agent, new email
]
LISTING_COLUMNS = ["ListingKey", "ListingId", "MlsStatus", "PropertyType", "PropertySubType", "ListingContractDate",
                   "ContractStatusChangeDate", "ClosePrice", "ListPrice", "OriginalListPrice", "City",
                   "CountyOrParish", "StateOrProvince", "PostalCode", "analysis_include", "duplicate_record_flag"]
LISTINGS = [
    ["0001", "ID0001", "Closed", "Residential", "SingleFamilyResidence", "2024-01-05", "2024-01-10", "500000.0",
     "500000.0", "500000.0", "los angeles", "Los Angeles", "CA", "90210", "True", "False"],
    ["1001", "ID1001", "Active", "Residential", "Condominium", "2024-01-20", "2024-01-20", "", "400000.0",
     "400000.0", "Pasadena", "Los Angeles", "CA", "01234", "False", "False"],
    ["1002", "ID1002", "ComingSoon", "Residential", "Condominium", "2024-01-25", "2024-01-25", "", "450000.0",
     "450000.0", "Pasadena", "Los Angeles", "CA", "91101", "False", "False"],                     # snapshot A
    ["1002", "ID1002", "Active", "Residential", "Condominium", "2024-02-03", "2024-02-03", "", "450000.0",
     "450000.0", "Pasadena", "Los Angeles", "CA", "91101", "False", "False"],                     # snapshot B
    ["1003", "ID1003", "Pending", "Residential", "", "2024-02-10", "2024-02-12", "", "350000.0", "350000.0",
     "Pasadena", "Los Angeles", "CA", "91101", "False", "False"],
]
# As the Census file arrives: the last column's name and values are padded with spaces
RAW_ZCTA = pd.DataFrame({
    "GEOID": ["90210", "91101", "90001", "90002", "90003"],
    "INTPTLAT": ["34.10", "34.15", "abc", "95.0", None],
    "INTPTLONG                 ": ["-118.41          ", "-118.13    ", "-118.0  ", "-118.2 ", "-118.3"]})
ZCTA, ZCTA_FAILURES = p.parse_zcta(RAW_ZCTA)


def text_frame(rows, columns, folder, name):
    """Write and reload as the project reads files: every column text, blank = missing."""
    path = folder / f"{name}.csv"
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
    return p.load(path)


class TableauPrepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter("always")
            cls.sold = text_frame(SOLD, SOLD_COLUMNS, folder, "sold")
            cls.listings_in = text_frame(LISTINGS, LISTING_COLUMNS, folder, "listings")
            labels = {c: p.label_map(cls.sold[c], cls.listings_in[c])
                      for c in ["CountyOrParish", "City", "StateOrProvince", "PropertySubType"]}
            cls.sales, cls.info = p.build_sales(cls.sold, labels, ZCTA)
            cls.listings, _ = p.build_listings(cls.listings_in, labels, ZCTA)
            p.validate(cls.sales, cls.listings, cls.sold, cls.listings_in)
            cls.monthly = p.monthly_reference(cls.sales, cls.listings).set_index("month")
            cls.offices, cls.office_summary = p.ranking(cls.sales, p.MODE_VALID, "office")
            cls.agents, _ = p.ranking(cls.sales, p.MODE_VALID, "agent")
            kept = cls.listings_in[cls.listings_in["duplicate_record_flag"] != "True"].reset_index(drop=True)
            cls.saved = p.save_checked(cls.listings.reset_index(drop=True), folder / "tableau_listings.csv", kept)
            sold_kept = cls.sold[cls.sold["duplicate_record_flag"] != "True"].reset_index(drop=True)
            cls.saved_sales = p.save_checked(cls.sales.reset_index(drop=True), folder / "tableau_sales.csv", sold_kept)
        cls.warnings = [str(x.message) for x in caught]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def row(self, i):
        return self.sales.loc[i]

    def test_exact_duplicates_dropped_and_one_counted_row_per_key(self):
        self.assertEqual(len(self.sales), len(self.sold) - 1)
        self.assertNotIn(6, self.sales.index)
        self.assertEqual(self.sales.groupby("ListingKey")["transaction_row"].sum().tolist(), [1] * 9)
        # the most recently updated snapshot counts; the other stays in the file with 0
        self.assertEqual((self.row(4)["transaction_row"], self.row(5)["transaction_row"]), (0, 1))
        self.assertIn("snapshot", self.row(5)["listing_key_repeat_class"])
        self.assertEqual(self.row(4)["valid_sale_count"], 0)  # a non-counted snapshot never counts

    def test_valid_mode_keeps_sales_with_missing_area_or_days(self):
        self.assertEqual((self.row(2)["valid_sale_count"], self.row(2)["valid_price"]), (1, 1))  # LivingArea missing
        self.assertEqual((self.row(3)["valid_sale_count"], self.row(3)["valid_price"], self.row(3)["valid_dom"]),
                         (1, 1, 0))  # DaysOnMarket missing: counted and in volume, but not in average DOM
        self.assertEqual((self.row(8)["valid_sale_count"], self.row(8)["valid_price"]), (1, 0))  # no price
        self.assertEqual((self.row(7)["valid_price"], self.row(7)["valid_ratio"]), (1, 0))  # no ratio

    def test_iqr_mode_is_the_week7_filtered_population(self):
        self.assertEqual((self.row(1)["valid_sale_count"], self.row(1)["iqr_sale_count"]), (1, 0))  # above bound
        self.assertEqual(self.row(2)["iqr_sale_count"], 0)
        self.assertEqual((self.row(0)["iqr_sale_count"], self.row(0)["iqr_ratio"]), (1, 1))
        self.assertTrue((self.sales["iqr_sale_count"] <= self.sales["valid_sale_count"]).all())

    def test_monthly_reference_uses_counted_rows_and_each_mode(self):
        jan = self.monthly.loc["2024-01-01"]
        self.assertEqual((jan["closed_sales_valid"], jan["closed_sales_iqr"]), (2, 1))
        self.assertEqual(jan["median_close_price_valid"], (500000 + 3000000) / 2)
        self.assertEqual(jan["median_close_price_iqr"], 500000)
        self.assertEqual(self.monthly.loc["2024-03-01", "closed_sales_valid"], 4)  # snapshot B, 7, 8, 9
        self.assertEqual(self.monthly.loc["2024-02-01", "closed_sales_valid"], 2)  # snapshot A not counted

    def test_new_listings_use_all_statuses_and_ignore_sales_modes(self):
        self.assertEqual(self.monthly.loc["2024-01-01", "new_listings"], 2)  # 0001 and 1001; 1002 counts in Feb
        self.assertEqual(self.monthly.loc["2024-02-01", "new_listings"], 2)  # 1002 (Active snapshot) and 1003
        changed = self.listings_in.assign(analysis_include="True")  # IQR flags have no effect on listings
        labels = {c: p.label_map(self.sold[c], changed[c]) for c in ["CountyOrParish", "City", "StateOrProvince",
                                                                     "PropertySubType"]}
        again, _ = p.build_listings(changed, labels, ZCTA)
        self.assertEqual(again["new_listing_event"].tolist(), self.listings["new_listing_event"].tolist())
        self.assertNotIn("analysis_include", self.listings.columns)

    def test_offices_normalized_placeholders_unattributed_and_ties_share_a_rank(self):
        self.assertEqual(self.row(0)["listing_office_key"], self.row(1)["listing_office_key"])  # Compass = COMPASS
        self.assertEqual(self.row(1)["listing_office_label"], "Compass")
        self.assertEqual(self.row(1)["ListOfficeName"], "COMPASS")  # the original is kept
        self.assertEqual((self.row(2)["listing_office_label"], self.row(2)["listing_office_identified"]),
                         ("(unattributed)", 0))
        volume = self.offices[self.offices["ranked_by"] == "volume"].set_index("label")
        self.assertNotIn("(unattributed)", volume.index)
        units = self.offices[self.offices["ranked_by"] == "units"].set_index("label")["rank"]
        self.assertEqual(units["Compass"], 1)                    # 4 units
        self.assertEqual(units["Redfin"], units["Zillow Offices"])  # 2 units each: tied
        self.assertEqual(units["Redfin"], 2)
        # market totals include the unattributed sale, so shares use the full market
        self.assertEqual(self.office_summary["unattributed_units"], 1)
        self.assertEqual(self.office_summary["market_units"], 9)

    def test_agents_keyed_by_name_and_office_not_email(self):
        self.assertNotEqual(self.row(0)["listing_agent_key"], self.row(9)["listing_agent_key"])  # other office
        self.assertEqual(self.row(0)["listing_agent_key"], self.row(10)["listing_agent_key"])  # new email, same agent
        self.assertEqual(self.row(0)["listing_agent_label"], "Ann Lee · Compass")
        self.assertEqual(self.row(10)["listing_agent_label"], "Ann Lee · Compass")  # spacing variant merged
        self.assertEqual(self.row(9)["listing_agent_label"], "Ann Lee · Zillow Offices")
        agents = self.agents[self.agents["ranked_by"] == "units"].set_index("label")
        self.assertEqual(agents.loc["Ann Lee · Compass", "units"], 3)  # rows 0, 7 and 10
        self.assertEqual(self.row(3)["listing_agent_identified"], 0)  # "Non Member"
        self.assertNotIn("ann@x.com", " ".join(self.sales.fillna("").astype(str).stack()))  # no email in Tableau

    def test_zip_codes_text_with_status_and_geocoding_check(self):
        self.assertEqual(self.row(1)["zip_code"], "90210")  # ZIP+4 trimmed
        self.assertEqual(self.row(1)["PostalCode"], "90210-1234")
        self.assertTrue(pd.isna(self.row(2)["zip_code"]))
        self.assertEqual(self.row(2)["zip_status"], "invalid format (not mapped)")
        self.assertEqual(self.row(0)["zip_in_census_zcta"], 1)
        self.assertEqual(self.saved.loc[1, "zip_code"], "01234")  # leading zero survives saving
        self.assertEqual(self.saved.loc[1, "zip_in_california_range"], "0")

    def test_zcta_coordinates_trimmed_numeric_and_failures_reported(self):
        self.assertEqual((ZCTA.loc["90210", "latitude"], ZCTA.loc["90210", "longitude"]), (34.10, -118.41))
        self.assertTrue(pd.isna(ZCTA.loc["90001", "latitude"]))  # "abc"
        self.assertTrue(pd.isna(ZCTA.loc["90002", "latitude"]))  # 95 is not a latitude
        self.assertEqual(ZCTA.loc["90002", "longitude"], -118.2)  # the other coordinate is kept
        self.assertEqual(ZCTA_FAILURES["latitude: not a number after trimming (set to missing)"], 1)
        self.assertEqual(ZCTA_FAILURES["latitude: outside ±90 (set to missing)"], 1)
        self.assertEqual(ZCTA_FAILURES["latitude: blank"], 1)
        self.assertEqual(ZCTA_FAILURES["longitude: not a number after trimming (set to missing)"], 0)
        # in the saved sales file: plain numbers, and blank only where there is no Census point
        self.assertEqual((self.saved_sales.loc[0, "zcta_latitude"], self.saved_sales.loc[0, "zcta_longitude"]),
                         ("34.1", "-118.41"))
        self.assertTrue(pd.isna(self.saved_sales.loc[2, "zcta_longitude"]))  # PostalCode "0": no ZIP, no point
        self.assertTrue(self.saved_sales["zcta_longitude"].dropna().str.fullmatch(r"-?\d+(\.\d+)?").all())

    def test_labels_match_across_sources(self):
        self.assertEqual(self.listings.loc[0, "city_label"], "Los Angeles")  # "los angeles" in listings
        self.assertEqual(self.listings.loc[0, "City"], "los angeles")
        self.assertEqual(self.listings.loc[4, "property_subtype_label"], "(missing)")
        self.assertEqual(set(self.sales["city_label"]), {"Los Angeles"})

    def test_no_pandas_warnings(self):
        self.assertEqual(self.warnings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
