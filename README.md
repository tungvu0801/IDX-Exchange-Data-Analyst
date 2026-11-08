# IDX-Exchange-Data-Analyst

Work for the IDX Exchange Data Analyst Internship, using California Regional MLS
(CRMLS) data pulled from the Trestle API through IDX Exchange.

## Week 1 – Monthly Dataset Aggregation

**Goal:** combine the monthly MLS files from January 2024 through the most
recently completed calendar month into two datasets, one for listings and one
for sold transactions. Both are filtered to `PropertyType == 'Residential'` and
saved as new CSVs, ready for analysis over time.

**Deliverable:** [`week1_aggregate.py`](week1_aggregate.py)

---

## Repository contents

| File | What it does |
|---|---|
| `week1_aggregate.py` | **Week 1 deliverable.** Combines the monthly files, filters to Residential, saves the outputs, and records row counts. |
| `week2_3_eda.py` | **Weeks 2–3 deliverable.** Inspects and validates the sold data: property types, Residential filter, missing values, numeric distributions with charts, EDA questions. Saves the filtered dataset. |
| `week2_3_mortgage_rates.py` | **Weeks 2–3 (continued) deliverable.** Fetches the FRED 30-year mortgage rate, averages it by month and merges it onto the combined sold and listings datasets. |
| `week4_5_cleaning.py` | **Weeks 4–5 deliverable.** Cleans both enriched datasets: types, impossible values, date-order and geographic flags, duplicates. Saves the cleaned files and a cleaning summary. |
| `test_week4_5_cleaning.py` | Regression tests for `week4_5_cleaning.py` on a small synthetic file (no real data needed). |
| `week6_feature_engineering.py` | **Week 6 deliverable.** Adds the market metrics and school districts to both cleaned datasets, and saves segmented summaries, a sample and a validation report. |
| `test_week6_feature_engineering.py` | Regression tests for `week6_feature_engineering.py` on synthetic data and synthetic district polygons. |
| `week7_outlier_detection.py` | **Week 7 deliverable.** Flags business-rule failures and IQR outliers in ClosePrice, LivingArea and DaysOnMarket, and saves full flagged and Closed-only filtered datasets, thresholds, a before/after summary and a validation report. |
| `test_week7_outlier_detection.py` | Regression tests for `week7_outlier_detection.py` on synthetic data. |
| `weeks8_10_tableau_prep.py` | **Weeks 8–10 preparation.** Builds the Tableau sales and listings data sources, reference calculations, a ZIP geography check and a validation report. |
| `test_weeks8_10_tableau_prep.py` | Regression tests for `weeks8_10_tableau_prep.py` on synthetic data. |
| `weeks8_10_tableau_build_guide.md` | Step-by-step guide to building `market_analysis.twbx` and `competitive_analysis.twbx` in Tableau. |
| `download_missing_months.py` | Downloads any month that is missing or damaged, checks it, and saves it to `csv/`. |
| `crmls_listed.py` | Original single-month script for listings (filtered by `ListingContractDate`). |
| `crmls_sold.py` | Original single-month script for closed sales (filtered by `CloseDate` and `MlsStatus = 'Closed'`). |
| `idx_auth.py` | Gets an API access token. Reads the key from a local `.env` file, so no credentials are stored in the code. |

The data itself is **not** in this repository: the files are too large for
GitHub (over 100 MB) and the MLS data is for internal use. Git ignores the
following local folders:

```
csv/            raw monthly files (CRMLSListingYYYYMM.csv, CRMLSSoldYYYYMM.csv)
output/         combined datasets and run_report.txt (Week 1); week2_3/ and mortgage_rates/
                (Weeks 2–3); cleaned/ (Weeks 4–5); week6/ (Week 6, including the downloaded
                school district boundaries); week7/ (Week 7); weeks8_10/ (Tableau data,
                references and workbooks)
*.twbx *.twb    Tableau workbooks and extracts (they embed MLS data)
*.hyper *.tde
backup/         copies of raw files that were replaced
downloads_tmp/  in-progress downloads and the download log
.env            API key (local only)
```

---

## Process

### 1. Collect the monthly files

The monthly files in `csv/` come from two sources, both provided by IDX:

- **FileZilla exports from IDX** – the original monthly files.
- **Direct API downloads** by `download_missing_months.py`, used to fill gaps.

Each month is two files:

- **Listings:** listings whose contract started that month (`ListingContractDate`).
- **Sold:** sales that closed that month (`CloseDate`, `MlsStatus = 'Closed'`).

`download_missing_months.py` uses the same endpoint, fields, date filters,
monthly boundaries, page size and stop condition as the current IDX fetch
scripts (`crmls_listed.py`, `crmls_sold.py`). Whether the historical FileZilla
exports were produced with identical queries is not confirmed. The downloader
fetches any month that is missing from `csv/` or structurally damaged. For each
month it:

1. Downloads all pages of results into a temporary file, saved as UTF-8.
2. Checks the file:
   - the row count equals the total the API reports;
   - no `ListingKey` appears twice;
   - every row has every field;
   - every date falls inside the month.
3. Moves the file into `csv/` only if every check passes. A file being replaced
   is backed up first. A month that fails is never treated as complete.

Timeouts and rate limits are retried a limited number of times. If
authentication fails, the run stops with a message that doesn't show the key.

**One FileZilla file was replaced.** The local copy of `CRMLSListing202601.csv`
had 2,606 rows, a final row with 78 of 82 fields and no trailing newline, so it
was treated as truncated and replaced by an API download (25,931 rows). The
original local copy is kept in `backup/`. This describes the file as observed
locally; it has not been checked whether the copy on the IDX FileZilla server
has the same problem.

**Where both `CRMLSSold{YYYYMM}.csv` and `CRMLSSold{YYYYMM}_filled.csv` exist,
the script uses the `_filled` file.** This is the script's current behaviour,
not a confirmed IDX requirement. What `_filled` means (it adds `latfilled` and
`lonfilled` columns) has not been confirmed with IDX.

### 2. Combine and filter (`week1_aggregate.py`)

1. **Check coverage:** list every month from January 2024 to the last completed
   month and report any that are missing.
2. **Check each file:** confirm that every row has the right number of fields,
   that the text is UTF-8, and that a `PropertyType` column exists. Problems are
   reported, never silently fixed.
3. **Remove duplicate columns:** the original listings script wrote some fields
   twice, which pandas loads as `Name.1`. A copy is dropped only if it matches
   the original in every row.
4. **Combine** the files with `pd.concat` and confirm the row count is unchanged.
   Columns that only some months have are left blank for the other months.
5. **Filter** to `PropertyType == 'Residential'`.
6. **Save** to a temporary file, read it back to check the row count and the
   filter, then replace the previous output. If any month is missing, the file
   name ends in `_INCOMPLETE`.

---

## How to run

**Requirements:** Python 3.12, `pandas` (with `numpy`), `requests`, `matplotlib`.
No GIS library is needed. Week 6 uses matplotlib's point-in-polygon test for
the school districts.

```bash
pip install pandas requests matplotlib
```

**Credentials (only needed for downloading):** create a file named `.env` in the
project folder containing:

```
IDX_TOKEN_KEY=<your IDX Exchange key>
```

Never commit this file. `.gitignore` already excludes it.

**Commands:**

```bash
python download_missing_months.py --plan              # list missing/damaged months (no download)
python download_missing_months.py                     # download them
python download_missing_months.py --compare-existing  # compare local row counts with the API today
python week1_aggregate.py                             # build the Week 1 datasets
python week2_3_eda.py                                 # Weeks 2-3 validation and EDA (sold)
python week2_3_mortgage_rates.py                      # add the FRED mortgage rate (needs internet)
python week4_5_cleaning.py                            # Weeks 4-5 cleaning and quality flags
python week6_feature_engineering.py                   # Week 6 metrics, school districts, summaries
python week7_outlier_detection.py                     # Week 7 IQR outlier flags and filtered datasets
python weeks8_10_tableau_prep.py                      # Weeks 8-10 Tableau data sources and references
python test_week4_5_cleaning.py                       # tests (synthetic data, no real files needed)
python test_week6_feature_engineering.py
python test_week7_outlier_detection.py
python test_weeks8_10_tableau_prep.py
```

---

## Week 1 results

Run on 2026-10-03, covering 2024-01 through 2026-09:

| | Listings | Sold |
|---|---:|---:|
| Monthly files found | 33 of 33 | 33 of 33 |
| Rows before concat (sum of monthly files) | 1,046,606 | 736,168 |
| Rows after concat | 1,046,606 | 736,168 |
| Rows after Residential filter | **665,579** | **495,070** |

Outputs:
- `output/combined_listings_residential.csv`
- `output/combined_sold_residential.csv`
- `output/run_report.txt` (full per-file log)

I checked both outputs by reading them back. The row counts match, every row
has `PropertyType == 'Residential'`, and all 33 months appear in the date
columns.

---

## Known limitations

Having a file for every month does **not** prove the source data is complete or
consistent.

### Mixed sources

`csv/` holds **69 monthly files** (33 listing, 36 sold). The script selects
**66** (33 + 33). Origin was judged from the download manifest and each file's
header layout, not from row counts or modification dates.

| Origin | Physical | Selected | Which |
|---|---:|---:|---|
| API download (`download_missing_months.py`, recorded in `csv/download_manifest.csv`) | 14 | 11 | Listings 2026-01, 2026-05 to 2026-09; Sold 2026-05 to 2026-09. Sold 2024-04/06/07 plain files are present but not selected. |
| Consistent with the IDX FileZilla exports (header layout differs from the downloader's; no manifest record) | 52 | 52 | All other listing files; all `_filled` and 78-column sold files. |
| Unknown (header identical to the current `crmls_sold.py`, no manifest record) | 3 | 3 | Sold 2026-02, 2026-03, 2026-04. |

Consequences:

- **The files are snapshots from different dates.** FileZilla export dates are
  unknown; API downloads were taken on 2026-10-02 and 2026-10-03. Compared with
  the API on 2026-10-03, FileZilla listing files hold 1,153 to 13,575 *more*
  rows per month, and most FileZilla sold files hold up to 1,296 *fewer*. API
  downloads taken one day apart also differed by tens to hundreds of rows.
  **A count difference between sources is expected and does not by itself show
  that a file is incomplete or incorrect.** The causes have not been confirmed
  with IDX; possibilities include snapshot timing, listings leaving the feed
  after expiring or being withdrawn (no file from either source contains
  Expired, Withdrawn or Canceled statuses), late-reported closings, and
  differences in how the FileZilla exports were produced.
- **Month-to-month trends may step** where a FileZilla month sits next to an
  API month (for example listings 2026-04 to 2026-05) for reasons unrelated to
  the market.
- **Column coverage varies by source:** `ListAgentEmail` and
  `BuyerAgencyCompensation` appear only in some FileZilla listing files;
  `latfilled`/`lonfilled` only in `_filled` sold files; `OriginatingSystemName`
  only in files with the current sold header.

### Open questions

- **January 2024 listings.** The file has 27,454 rows; the API returned about
  23,400 on 2026-10-03. Its `Closed` count is exactly 20,000, the only
  round-thousand status count in any monthly file. One hypothesis is a cap in
  that export; this is unconfirmed. The file is used unchanged.
- **Same listing in two months.** 203 listing rows and 379 sold rows share a
  `ListingKey` with a row in another month. A plausible cause is a date that
  changed between snapshots. They were not removed; this is left for cleaning.
- **Recent months will change** as late closings and status updates arrive.

Points to confirm with IDX: whether the feed drops expired or withdrawn
listings; whether the January 2024 export was capped; what `_filled` means and
which version to prefer; whether the FileZilla set or a single-date API snapshot
should be treated as canonical for trend analysis.

---

## Weeks 2–3 – Dataset Structuring and Validation

**Goal:** inspect the sold dataset before analysis, keep only Residential
records, and run the first exploratory checks that later weeks build on.

**Deliverable:** [`week2_3_eda.py`](week2_3_eda.py). It reads the same 33
monthly sold files as Week 1, using Week 1's file-selection code.

### What the script does

1. **Dataset understanding:** rows, columns and data types. Each column is
   labelled as a market analysis field (price, timing, property, location) or
   a metadata field (identifiers, agents and offices, system).
2. **Property types and filter:** lists every `PropertyType` value with its
   count and share before filtering, then keeps `PropertyType == 'Residential'`
   (exact, case-sensitive). It also checks for case or spacing variants and
   blanks.
3. **Missing values:** null count and percentage for every column, a flag for
   columns with strictly more than 90% missing, and a keep/drop decision with
   its reason. Core analysis fields are always kept. It also counts values that
   may stand in for missing data (zeros, "Other", Y/N fields that only ever
   record True) without changing them.
4. **Numeric distributions:** for nine fields, a raw summary (min, max, mean,
   median, 1st to 99th percentiles), skewness, a histogram and a boxplot.
5. **EDA questions:** the handbook's six questions. Each answer states which
   rows it uses and which it leaves out.
6. **Save:** the filtered dataset, reloaded after saving to check its shape and
   that every row is Residential.

**What is removed:** only non-Residential rows and the columns more than 90%
missing. Every flagged row stays in the saved dataset.

How values are flagged in `review_flags.csv`:

- **Impossible values** break a field's definition: a close, list or original
  list price of $0 or less, a living area of 0 or less, negative days on
  market, or coordinates of 0, 0.
- **Review thresholds** are cut-offs chosen for this project. Values beyond
  them are unusual and worth checking, not proven errors:
  - More than 3 × IQR beyond the 25th or 75th percentile. For right-skewed
    fields this is measured on a log scale, which works out to
    low = Q1 ÷ (Q3/Q1)³ and high = Q3 × (Q3/Q1)³. For ClosePrice that is
    $49,756 to $15,023,457.
  - Days on market over 3,650 (10 years).
  - A close price more than 3 times, or less than a third of, the list price.
  - A year built after the sale year (possibly a pre-construction sale).
- **Other checks:** date order, repeated ListingKeys, non-dwelling subtypes
  and sales outside California.

The saved dataset has a `RowNumber` column (1 = first data row), and every flag
points at a RowNumber. A ListingKey can appear in more than one row, so it
can't identify a row on its own.

### Outputs (in `output/week2_3/`, not committed)

| File | Contents |
|---|---|
| `sold_residential_filtered.csv` | Filtered dataset: 495,070 rows × 71 columns (70 kept columns + `RowNumber`) |
| `column_summary.csv` | Null-count table for all 85 columns: count, %, over-90% flag, core field, decision and reason |
| `possible_hidden_missing.csv` | Values that may stand in for missing data |
| `numeric_summary.csv` | Raw distribution summary, skewness and review thresholds for the nine fields |
| `county_median_prices.csv` | Median close price and sale count per county |
| `review_flags.csv` | One row per flag: RowNumber, ListingKey, category, field, value and detail |
| `figures/*.png` | Histogram + boxplot for each of the nine fields |
| `eda_report.md` | Everything above as one readable report |

### Results (run on 2026-10-09)

- **Property types:** 8 values in 736,168 closed sales. Residential is 495,070
  (67.25%); ResidentialLease is next at 169,403 (23.01%). The filter keeps
  495,070 rows, the same as the Week 1 output.
- **Missing values:** 15 of 85 columns are more than 90% missing (8 of them
  completely empty) and are dropped. No core field is near the threshold; the
  least complete is LotSizeAcres at 7.67%.
- **Raw summary of the deliverable fields** (every non-missing value,
  including impossible and unusual ones; 1st to 99th percentiles are in
  `numeric_summary.csv`):

  | | ClosePrice | LivingArea (sq ft) | DaysOnMarket |
  |---|---:|---:|---:|
  | count | 495,068 | 494,796 | 495,070 |
  | min | $0 | 0 | −288 |
  | 25th percentile | $575,000 | 1,250 | 8 |
  | median | $825,000 | 1,648 | 19 |
  | mean | $1,189,912 | 1,902.7 | 37.6 |
  | 75th percentile | $1,300,000 | 2,227 | 49 |
  | max | $989,500,000 | 17,021,321 | 12,430 |

- **Shape** (skewness within the 1st to 99th percentiles): prices, living
  area, lot size and days on market are strongly right-skewed and bathrooms
  moderately; bedrooms and year built are roughly symmetric.
- **EDA questions:**
  - *Residential share:* 67.25% of all 736,168 closed sales.
  - *Close price* (495,067 sales above $0; 2 missing and 1 at $0 left out):
    median $825,000, mean $1,189,915. The raw mean of $1,189,912 differs only
    because it includes the $0 sale. Leaving out the 811 prices beyond the
    review thresholds gives a mean of $1,120,959.
  - *Days on market* (495,014 sales; 56 negative values left out): median 19
    days. 62.6% went under contract within 30 days and 0.21% took more than a
    year.
  - *Price vs list price* (495,067 sales with both prices above $0): 39.63%
    sold above, 17.44% at and 42.93% below. Against the original list price
    (494,166 sales): 36.94% above, 11.59% at, 51.47% below.
  - *Date consistency:* the three date-order rules are broken 632 times by 557
    rows; 75 rows break two or more.
  - *Highest median prices* (counties with 100+ sales): San Mateo $1,700,000,
    Santa Clara $1,590,000 and San Francisco $1,200,000.
- **Flags for the cleaning step:** 26,619 flags on 24,282 rows (23,903
  ListingKeys). They include 282 impossible values, 128 non-dwelling records,
  32 sales outside California and 375 repeated ListingKeys, 48 of which are
  exact copies within one monthly file.

These results pool monthly files from different sources and snapshot dates
(see *Known limitations*), so month-to-month comparisons should allow for that.

---

## Weeks 2–3 (continued) – Mortgage Rate Enrichment

**Goal:** add the national 30-year fixed mortgage rate to every sale and
listing, so later analysis can relate the market to borrowing costs.

**Deliverable:** [`week2_3_mortgage_rates.py`](week2_3_mortgage_rates.py)

**Requires:**
- `pandas` and `requests`
- `week1_aggregate.py` in the same folder, because the script imports
  `OUTPUT_DIR` from it
- both Week 1 combined CSVs, `output/combined_sold_residential.csv` and
  `output/combined_listings_residential.csv` (run `week1_aggregate.py` first)
- an internet connection, to fetch the series from FRED

### What the script does

1. **Fetch:** downloads FRED series `MORTGAGE30US` (Freddie Mac, weekly, in
   percent) directly as a CSV. No API key is needed, but it needs internet.
2. **Resample:** averages the weekly readings in each calendar month.
3. **Key:** builds `year_month` from `CloseDate` for sold rows and from
   `ListingContractDate` for listings.
4. **Merge:** left-merges the monthly rate onto both Week 1 combined datasets
   (`combined_sold_residential.csv` and `combined_listings_residential.csv`).
   The merge is checked to be many-to-one, so no row can be duplicated.
5. **Validate:** stops with an error, and saves nothing for that dataset, if any
   row has a null `rate_30yr_fixed` or the row count changed.
6. **Save:** both enriched datasets, reloaded after saving to confirm the row
   count and that no rate is null.

### Outputs (in `output/mortgage_rates/`, not committed)

All outputs are saved locally under `output/mortgage_rates/`, which is
git-ignored. The enriched CSVs are therefore not in this repository; submit
them separately if they are required.

| File | Contents |
|---|---|
| `sold_with_rates.csv` | Sold dataset + `year_month` + `rate_30yr_fixed` |
| `listings_with_rates.csv` | Listings dataset + `year_month` + `rate_30yr_fixed` |
| `mortgage30us_weekly.csv` | Weekly observations used to calculate monthly averages |
| `mortgage30us_monthly.csv` | Monthly average rate and number of weekly readings |

### Results (run on 2026-10-17)

| | Sold | Listings |
|---|---:|---:|
| Rows before and after merge | 495,070 | 665,579 |
| Columns after merge | 86 (84 + 2) | 75 (73 + 2) |
| Months covered | 2024-01 to 2026-09 (33) | 2024-01 to 2026-09 (33) |
| Null `rate_30yr_fixed` | 0 | 0 |

- FRED returned 2,899 weekly readings, from 1971-04-02 to 2026-10-15, with no
  blanks. Each of the 33 months used has 4 or 5 weekly readings.
- The monthly average ranged from 6.048% (February 2026) to 7.060% (May 2024).
- Checked independently: every original column is unchanged from Week 1,
  `year_month` matches the date column's year and month, and every rate equals
  a separately computed monthly mean.

FRED can revise past readings, so a later run may give slightly different
rates. `mortgage30us_weekly.csv` keeps the weekly observations this run used
to calculate the monthly averages.

---

## Weeks 4–5 – Data Cleaning and Preparation

**Goal:** prepare both mortgage-enriched datasets for analysis, with explicit
quality flags. Impossible values are blanked (with the original kept), nothing
is imputed, and no row is removed, so each analysis can choose which flags to
filter on.

**Deliverable:** [`week4_5_cleaning.py`](week4_5_cleaning.py)

**Requires:**
- `pandas`
- `week1_aggregate.py`, for `OUTPUT_DIR`
- the two enriched inputs (run `week2_3_mortgage_rates.py` first)

No internet is needed.

**Inputs (read only, never modified):**
- `output/mortgage_rates/sold_with_rates.csv` (495,070 rows × 86 columns)
- `output/mortgage_rates/listings_with_rates.csv` (665,579 rows × 75 columns)

**Run:** `python week4_5_cleaning.py`

**Tests:** `python test_week4_5_cleaning.py` (standard-library `unittest`). The
tests run the cleaning on an 8-row synthetic file and check:
- an invalid date is exported blank and its original text is kept;
- a missing coordinate next to an invalid one;
- repeated keys versus missing keys;
- date checks that pass, fail or can't be evaluated;
- leading-zero identifiers, row counts, `year_month` and mortgage rates are
  preserved;
- no pandas warnings are raised.

### Transformations and why

| Step | What it does | Why |
|---|---|---|
| Read | Every column is read as text; only empty cells count as missing | Nothing is guessed, and identifiers keep leading zeros (40 `BuyerAgentMlsId` values in sold start with 0) |
| Drop columns | Drops 8 columns with no values at all (`FireplacesTotal`, `AboveGradeFinishedArea`, `TaxAnnualAmount`, `TaxYear`, `ElementarySchoolDistrict`, `BusinessType`, `CoveredSpaces`, `MiddleOrJuniorSchoolDistrict`) and `ListingKeyNumeric` | The empty columns carry no information, and `ListingKeyNumeric` is an exact copy of `ListingKey` in every row. Columns that are only partly empty are kept, however much is missing |
| Identifiers | `ListingKey`, `ListingId`, `PostalCode`, `BuyerAgentMlsId` and `UnparsedAddress` are kept as text, unchanged | They are labels, not numbers |
| Street number | Removes the trailing `.0` from `StreetNumberNumeric` (`2811.0` → `2811`) and keeps it as text | An earlier conversion to decimals added the `.0` |
| Dates | Parses `CloseDate`, `PurchaseContractDate`, `ListingContractDate` and `ContractStatusChangeDate` with the exact format `YYYY-MM-DD` | That is the only format in the inputs. There are no time parts or time zones, so no date can shift. Missing dates stay missing |
| Numbers | Converts 22 columns (prices, areas, lot sizes, days on market, bedrooms, bathrooms, year built, stories, garage and parking, coordinates, mortgage rate) with Python's `float()`. Whole-number fields become nullable integers | The inputs contain no `$`, commas or spaces. `float()` returns the binary floating-point value nearest to the text. The inputs were written in shortest round-trip form, so each value reads back as the same float and is written out as the same text. pandas' faster parser isn't always correctly rounded: it read `6.1899999999999995` as a neighbouring float that prints as `6.19`. Neither approach is exact decimal arithmetic |
| True/False | The `*YN` fields, `latfilled` and `lonfilled` become nullable booleans; blanks stay missing | What a blank means is not documented |
| Values that fail to convert | A date, number or True/False value that can't be converted (for example the date `2024-02-30`) is exported blank. Its original text goes into `<column>_unparsed_original` and `parse_failure_flag` is set. That column is only created when something fails, so the current run has none | Dates and coordinates are never repaired or guessed |
| Impossible values | Flags the row, copies the original into `<column>_invalid_original`, and sets the analytical value to null | Keeps an audit trail while stopping impossible values from distorting statistics |
| No imputation | No missing price, area, bedroom count, bathroom count, date or coordinate is filled in | |

### Flag definitions and counts

| Flag | Definition | Sold | Listings |
|---|---|---:|---:|
| `invalid_close_price_flag` | ClosePrice ≤ 0 | 1 | 0 |
| `invalid_living_area_flag` | LivingArea ≤ 0 | 177 | 429 |
| `negative_days_on_market_flag` | DaysOnMarket < 0 | 56 | 34 |
| `negative_bedrooms_flag` | BedroomsTotal < 0 (0 is allowed) | 0 | 0 |
| `negative_bathrooms_flag` | BathroomsTotalInteger < 0 (0 is allowed) | 0 | 0 |
| `listing_after_close_flag` | ListingContractDate > CloseDate | 75 | 91 |
| `purchase_after_close_flag` | PurchaseContractDate > CloseDate | 242 | 266 |
| `negative_timeline_flag` | PurchaseContractDate < ListingContractDate | 315 | 325 |
| `missing_coordinates_flag` | Latitude or Longitude missing | 4,795 | 81,451 |
| `zero_coordinate_flag` | Latitude = 0 or Longitude = 0 | 46 | 92 |
| `positive_longitude_flag` | Longitude > 0 | 35 | 100 |
| `invalid_coordinate_range_flag` | Latitude outside [−90, 90] or Longitude outside [−180, 180] | 2 | 6 |
| `outside_ca_bbox_flag` | Potential geographic issue: outside latitude 32.5 to 42.1 or longitude −124.5 to −114.1 | 117 | 405 |
| `duplicate_record_flag` | Identical, as raw text, to an earlier row in every input column (86 in sold, 75 in listings). Only the later copies are flagged, so the count is excess rows | 48 | 0 |
| `missing_listing_key_flag` | ListingKey is missing | 0 | 0 |
| `repeated_listing_key_flag` | A non-missing ListingKey appears in more than one row; every such row is flagged. Missing keys never count as repeated | 754 (375 keys) | 404 (201 keys) |
| `parse_failure_flag` | A non-missing date, number or True/False value failed to convert | 0 | 0 |
| `any_quality_issue_flag` | Any of the `_flag` columns above. The `*_evaluable` columns are not included | 6,422 | 83,103 |

- **Date flags:** equal dates are allowed. Each rule also has a
  `<rule>_evaluable` column (`listing_after_close_evaluable`,
  `purchase_after_close_evaluable`, `negative_timeline_evaluable`). It is True
  when both of the rule's dates are present and valid. Together the two columns
  give three states:

  | `_evaluable` | `_flag` | Meaning |
  |---|---|---|
  | True | False | Checked and passed |
  | True | True | Checked and failed |
  | False | False | Not checked: a date is missing or unparseable. The flag is always False here, so False alone doesn't mean "passed" |

  An evaluable column only records whether a check could run; it is not a
  quality issue. Rows not evaluated, for the three rules in table order:
  - sold: 1, 197 and 198;
  - listings: 446,765, 446,796 and 332,462, mostly unsold listings with no
    CloseDate.
- **Close-date flags on listings that aren't Closed are diagnostic only.**
  23,256 such listings (mostly Pending) have a CloseDate, and what it means is
  unverified; it may be a scheduled date. Of the flagged rows:
  - `purchase_after_close_flag` includes 18 Pending listings;
  - `listing_after_close_flag` flags only Closed listings;
  - `negative_timeline_flag` doesn't use CloseDate. It also flags 42 Pending
    and 17 ActiveUnderContract listings.
- **Geographic flags:** each check uses whatever coordinates it can:
  - `missing_coordinates_flag` is evaluated on every row.
  - `zero_coordinate_flag` and `invalid_coordinate_range_flag` check each
    coordinate that is present. A row with only a Longitude of `329.0` is still
    flagged as out of range.
  - `positive_longitude_flag` needs Longitude.
  - `outside_ca_bbox_flag` needs both coordinates.

  When a check can't run, its flag is False. `cleaning_summary.csv` reports
  each skipped check as `<flag>: not evaluable`, along with the number of rows
  with only one coordinate. In the current data no row has just one
  coordinate, so every geographic check skipped the same rows: 4,795 in sold
  and 81,451 in listings. There are no geographic `_evaluable` columns,
  because whether a check could run follows directly from which coordinates
  are present.
- **Bounding box:** a screening method, not proof of location. The box also
  covers parts of Nevada, Arizona, Oregon, Mexico and the ocean, so a point
  inside it is not proven to be in California. Coordinates are never changed,
  swapped or geocoded.

### Which flags to filter on

| Analysis | Exclude rows where | Note |
|---|---|---|
| Prices, price per square foot | Apply the duplicate policy below. Don't exclude rows for missing or flagged coordinates | Impossible ClosePrice and LivingArea values are already null, so they drop out of averages automatically. A price is valid without a location |
| Completed-sale timing (days on market, contract to close) | Records that aren't Closed (use sold, which is all Closed, or listings with `MlsStatus == 'Closed'`); rows where the measure's `*_evaluable` column is False; rows where its date flag is True; then apply the duplicate policy | Negative DaysOnMarket values are already null. Close-date flags on non-Closed listings are diagnostic only |
| Maps and location analysis | `missing_coordinates_flag`, `zero_coordinate_flag`, `positive_longitude_flag`, `invalid_coordinate_range_flag`; review `outside_ca_bbox_flag` | Some rows outside the box are genuine out-of-state properties |
| Monthly counts and volumes | Apply the duplicate policy; consider `repeated_listing_key_flag` and `missing_listing_key_flag` | A repeated key may be the same home counted twice |

- **Choose the flags for each analysis.** Don't filter on
  `any_quality_issue_flag` everywhere. It includes missing coordinates (12% of
  listings), which don't invalidate a price, date or count analysis.
- **Duplicates need an explicit policy downstream.** The 48 exact duplicate
  rows in sold are kept, and the script does not deduplicate. Each analysis
  should state its choice:
  - exclude rows with `duplicate_record_flag`, which keeps the first copy and
    counts each record once;
  - or keep every row, and say so.

  Repeated ListingKeys that aren't exact duplicates are a separate question,
  and the cleaning doesn't resolve them.
- **No outliers are removed.** Only impossible values (such as a price ≤ 0) are
  blanked. Choosing outlier thresholds is left to each analysis.

### Results (run on 2026-10-24)

| | Sold | Listings |
|---|---:|---:|
| Rows before → after | 495,070 → 495,070 | 665,579 → 665,579 |
| Columns before → after | 86 → 103 | 75 → 92 |
| Dates that failed to parse | 0 | 0 |
| Numbers that failed to convert | 0 | 0 |
| Rows with any date flag | 557 (75 with two or more) | 590 (91 with two or more) |
| Rows with any geographic flag | 4,912 | 81,856 |
| Rows with any quality flag | 6,422 | 83,103 |

- **Columns after:** 9 columns are dropped, and three groups are added at the
  end in this order:
  - 5 audit columns (`<column>_invalid_original`);
  - 3 `*_evaluable` columns;
  - 18 flag columns (17 `_flag` columns plus `any_quality_issue_flag`).
- **Changes since the 2026-10-17 run:** this run adds `missing_listing_key_flag`
  and the three `*_evaluable` columns. All 99 (sold) and 88 (listings) earlier
  columns are byte-identical to the earlier output. Because no ListingKey is
  missing, the repeated-key counts and every other count are unchanged.
- **Missing dates, sold:** PurchaseContractDate 197, ListingContractDate 1,
  ContractStatusChangeDate 594.
- **Missing dates, listings:** CloseDate is missing in 446,765 rows. All of them
  are Active, Pending, ActiveUnderContract or ComingSoon, so a missing CloseDate
  is expected and is not treated as invalid. PurchaseContractDate is missing in
  332,462 rows.
- **Per-column missing counts,** before and after cleaning, are in
  `cleaning_summary.csv`.
- **Validated in the script and again independently:**
  - `year_month` matches the CloseDate (sold) or ListingContractDate
    (listings) month in every row.
  - `rate_30yr_fixed` is unchanged and never null.
  - Every flag matches an independent recomputation from the input text.
  - Each `*_evaluable` column is True exactly when both dates are present.
    No date flag is True on a row that couldn't be evaluated.
- **How the output text compares with the input:** checked column by column
  after reloading. The script's own reload check (the `saved file` rows in
  `cleaning_summary.csv`) confirms:
  - Every identifier (ListingKey, ListingId, PostalCode, BuyerAgentMlsId,
    UnparsedAddress), `year_month` and `rate_30yr_fixed` is text-identical to
    the input.
  - Each exported date equals its parsed value.
  - The original text of any unparseable date is in its
    `<column>_unparsed_original` column.
  - The flag and `*_evaluable` columns hold only True/False, with the same
    counts as in memory.

  The independent check covered every kept column.

  | | Sold (77 kept columns) | Listings (66 kept columns) |
  |---|---|---|
  | Verbatim: identical text in every row | 68 columns, including all identifiers, the four dates, Latitude, Longitude, `year_month`, `rate_30yr_fixed` and the True/False fields | 58 columns, the same groups |
  | Same value, different text | YearBuilt, BedroomsTotal, BathroomsTotalInteger, Stories and MainLevelBedrooms are written as whole numbers (`2.0` → `2`); StreetNumberNumeric loses its `.0` | The same 6 columns |
  | Impossible values blanked, original text kept in `<column>_invalid_original` | ClosePrice 1, LivingArea 177, DaysOnMarket 56; every other value in these columns is verbatim | LivingArea 429, DaysOnMarket 34; ClosePrice is verbatim |

### Outputs (in `output/cleaned/`, git-ignored, not committed)

| File | Contents |
|---|---|
| `sold_cleaned.csv` | Cleaned sold data, audit columns, evaluable columns and flags |
| `listings_cleaned.csv` | Cleaned listings data, audit columns, evaluable columns and flags |
| `cleaning_summary.csv` | One row per reported count for both datasets (`dataset`, `section`, `item`, `count`, `detail`): shapes, dropped columns and reasons, missing values before and after, parse failures, invalid values, flag counts, rows not evaluated per check, missing and repeated ListingKeys, in-memory dtypes, validation results and the saved-file check |

The cleaned CSVs are not in this repository; submit them separately if they are
required.

### Reloading the cleaned files

A CSV stores text only, so pandas dtypes (dates, nullable integers, booleans,
periods) are not saved. Parse them again when reloading:

```python
import pandas as pd

DATES = ["CloseDate", "PurchaseContractDate", "ListingContractDate", "ContractStatusChangeDate"]
TEXT = ["ListingKey", "ListingId", "PostalCode", "BuyerAgentMlsId", "StreetNumberNumeric", "year_month"]
WHOLE = ["DaysOnMarket", "BedroomsTotal", "BathroomsTotalInteger", "MainLevelBedrooms", "YearBuilt", "Stories"]
YES_NO = ["ViewYN", "WaterfrontYN", "BasementYN", "PoolPrivateYN", "AttachedGarageYN", "FireplaceYN",
          "NewConstructionYN", "latfilled", "lonfilled"]
sold = pd.read_csv("output/cleaned/sold_cleaned.csv",
                   dtype={**{c: "string" for c in TEXT}, **{c: "Int64" for c in WHOLE},
                          **{c: "boolean" for c in YES_NO}},
                   parse_dates=DATES, date_format="%Y-%m-%d",
                   float_precision="round_trip", low_memory=False)
sold["year_month"] = pd.PeriodIndex(sold["year_month"], freq="M")  # optional
```

Tested on the 2026-10-24 sold output. It returns 495,070 rows and keeps the 40
leading-zero `BuyerAgentMlsId` values. What each group comes back as:

| Columns | Type after reloading | Without the snippet |
|---|---|---|
| Flags and `*_evaluable` | `bool` (never blank) | Same: `bool` automatically |
| Identifiers, `StreetNumberNumeric` | `string`, leading zeros kept | `ListingKey` becomes `int64`. The others stay text only because some of their values aren't numeric, which a future file may not guarantee |
| The four dates | `datetime64`; unparseable and missing dates are `NaT` | Text |
| Whole-number fields | `Int64` (nullable) | `float64` |
| `*YN`, `latfilled`, `lonfilled` | `boolean`; blanks stay `<NA>` | `object`, because of the blanks |
| `year_month` | `period[M]` after the last line | Text such as `2024-02` |
| `rate_30yr_fixed` and other decimals | `float64`, read exactly | `float64`, but pandas' default parser can change the last digit (`6.1899999999999995` → `6.19`) |
| `<column>_invalid_original` | `float64`; add `"string"` to `dtype` to keep the exact original text | `float64` |
| `<column>_unparsed_original` | Only present if a value failed to convert (none in this run); add `"string"` to `dtype` | — |

The listings file loads the same way from `listings_cleaned.csv`. First remove
the columns it doesn't have (`ViewYN`, `WaterfrontYN`, `BasementYN`,
`PoolPrivateYN`, `latfilled`, `lonfilled`) from `YES_NO`.

### Limitations and open decisions

- **Duplicates:** sold has 48 pairs of identical rows (96 rows). The 48 later
  copies carry `duplicate_record_flag` and are kept. Each analysis must
  explicitly choose whether to exclude them (see *Which flags to filter on*).
- **Repeated ListingKeys:** sold has 754 rows across 375 keys (379 rows beyond
  the first per key), and listings 404 rows across 201 keys (203 beyond the
  first). Why they repeat has not been verified. No ListingKey is missing in
  either dataset.
- **CloseDate on unsold listings:** 23,256 listings that aren't Closed (mostly
  Pending) have a CloseDate whose meaning is unverified; it may be a scheduled
  date. Close-date flags on these rows are diagnostic only. Restrict
  completed-sale timeline analysis to Closed records with valid required dates.
- **Out-of-state rows:** of the rows outside the bounding box, 18 of 117 (sold)
  and 186 of 405 (listings) are recorded with a state other than CA.
- **Coordinates are not corrected:** swapped or sign-flipped coordinates are
  flagged only.
- **Outliers stay in:** statistical outliers are not removed. The Weeks 2–3
  review thresholds in `output/week2_3/review_flags.csv` are separate.
- **Values left as they are:** zeros in lot size, bedrooms and bathrooms;
  "Other" and "Unknown" placeholder text; and blank WaterfrontYN or BasementYN
  values. What they mean is not documented.
- **Mixed sources:** the inputs come from monthly files from different sources
  and dates (see *Known limitations*).

---

## Week 6 – Feature Engineering and Market Metrics

**Goal:** add the market metrics that will feed the Tableau dashboards, add
California school districts from each property's coordinates, and summarize the
metrics by segment. No row is added, removed or deduplicated, and every input
column is kept exactly as it was.

**Deliverable:** [`week6_feature_engineering.py`](week6_feature_engineering.py)

**Requires:**
- `pandas`, `numpy`, `matplotlib`, and `requests` (for the one-time boundary
  download)
- `week1_aggregate.py` and `week4_5_cleaning.py`, whose helpers it reuses
- the two cleaned inputs (run `week4_5_cleaning.py` first)

Internet is needed only on the first run, to download the boundaries. The script
stops with an error if a cleaned input is missing; it never reruns earlier
stages.

**Inputs (read only, never modified; their SHA-256 hashes were identical before
and after the run):**
- `output/cleaned/sold_cleaned.csv` (495,070 rows × 103 columns)
- `output/cleaned/listings_cleaned.csv` (665,579 rows × 92 columns)

Both files are from the cleaning run of 2026-10-25, and the counts above were
checked against them on 2026-10-31.

**Run:** `python week6_feature_engineering.py` (about 3 minutes)

**Tests:** `python test_week6_feature_engineering.py` runs 11 tests on a
synthetic 15-row file and synthetic district polygons. They cover:
- division by zero and missing or invalid inputs;
- the two handbook ratios being identical (values, null mask and reasons), and
  the extra ratio dividing by ListPrice;
- `YrMo` against `year_month` on each dataset's date basis, including a
  deliberately wrong sold `year_month` that must raise an error;
- dates out of order, and equal dates;
- records that aren't Closed;
- preservation of identifiers and every input column;
- excluding duplicates from the summaries only;
- that the spatial join preserves rows (shared locations, overlapping
  Elementary and High districts, an ambiguous overlap, a hole, a
  MultiPolygon, and missing, invalid and out-of-state coordinates);
- that no pandas warnings are raised.

The tests were also run against five deliberately broken versions of the
script, and each one was caught:
- the denominator check removed;
- every record treated as Closed;
- the date-order flags ignored;
- a repeated key in the spatial lookup;
- `price_ratio` switched back to ListPrice.

### Requirements: verified versus interpreted

**Verified** against the Week 6 section of the intern handbook
(`IDX_Exchange_Intern_Handbook_Final-version5.docx`):
- the metric table: names, formulas and purposes;
- adding school districts from latitude and longitude using the linked
  data.ca.gov resource;
- segment analysis by:
  - PropertyType and PropertySubType;
  - CountyOrParish and MLSAreaMajor;
  - ListOfficeName and BuyerOfficeName;
- the deliverable: a `.py` script, a sample output table showing the new
  columns, and at least one summary grouped by PropertyType or CountyOrParish.

**The two ratios follow the handbook literally.** The handbook gives
ClosePrice / OriginalListPrice for both Price Ratio ("negotiation strength") and
Close to Original List Ratio ("full price reduction history"), and the script
uses exactly that (`PRICE_RATIO_DENOMINATOR = "OriginalListPrice"`). So
`price_ratio` and `close_to_original_list_ratio` are identical: the same
formula, eligibility rules, values, nulls and null reasons. Every run checks
this.

**Added beyond the handbook:** `close_to_current_list_ratio` = ClosePrice /
ListPrice, with its own null-reason column. It is an extra analytical metric
(sale price against the list price at the time of sale). It is **not** a
handbook requirement and does not replace either required ratio.

**Choices** (the handbook doesn't state these):
- Completed-sale metrics are filled only for Closed records.
- Every metric has a `*_null_reason` column.
- Exact duplicates are excluded from the summaries.
- The summary statistics are my choice.
- Column names other than `Year`, `Month` and `YrMo` are my own, and `YrMo` is
  written as `YYYY-MM`.

### Metrics

| Column | Formula | Filled for | Null when (first failing check, in this order) |
|---|---|---|---|
| `price_ratio` (handbook) | ClosePrice / OriginalListPrice | Closed | not Closed; ClosePrice missing, invalid or ≤ 0; OriginalListPrice missing or ≤ 0 |
| `close_to_original_list_ratio` (handbook) | ClosePrice / OriginalListPrice (identical to `price_ratio`) | Closed | the same as `price_ratio` |
| `close_to_current_list_ratio` (extra, not in the handbook) | ClosePrice / ListPrice | Closed | not Closed; ClosePrice as above; ListPrice missing or ≤ 0 |
| `price_per_sqft` | ClosePrice / LivingArea | Closed | not Closed; ClosePrice as above; LivingArea missing, invalid or ≤ 0 |
| `DaysOnMarket` | The MLS field itself, as cleaned. Not a new column, and not recomputed from dates | (existing) | Negative values were set to null in cleaning; the originals are in `DaysOnMarket_invalid_original` |
| `Year`, `Month`, `YrMo` | CloseDate's year, month and `YYYY-MM` | Closed | not Closed; CloseDate missing |
| `listing_to_contract_days` | PurchaseContractDate − ListingContractDate, in days | Any status (it uses no close field) | a date missing; `negative_timeline_evaluable` False; `negative_timeline_flag` True |
| `contract_to_close_days` | CloseDate − PurchaseContractDate, in days | Closed | not Closed; a date missing; `purchase_after_close_evaluable` False; `purchase_after_close_flag` True |

- **Nulls and reasons:**
  - A denominator must be greater than 0, so there is never a division by zero
    or an infinite value.
  - A metric is null exactly when its `*_null_reason` is filled. `Year`,
    `Month` and `YrMo` share `YrMo_null_reason`.
  - Reasons look like `OriginalListPrice <= 0`, `LivingArea missing`,
    `not Closed (MlsStatus Pending)`, or
    `PurchaseContractDate after CloseDate (purchase_after_close_flag)`.
- **Why only Closed records:** on listings that aren't Closed, CloseDate may be
  a future or scheduled date (it runs to 2030-04-16), and 5 such listings have
  a ClosePrice. Their completed-sale metrics are left null.
- **Date flags are respected:**
  - an interval is computed only where the cleaning's `*_evaluable` column is
    True and its flag is False;
  - equal dates give 0 days;
  - `Year`, `Month` and `YrMo` don't depend on the date-order flags, just as
    `year_month` doesn't.
- **Days on market:** the script reports Closed records with a value, zeros,
  and values set to null in cleaning. In the summaries, DaysOnMarket counts
  only Closed records. On other listings it is days so far, not time to sell.
- **Precision:** numbers are read with Python's `float()`, as in Weeks 4–5, and
  written in shortest round-trip form. After saving, every metric is reloaded
  and compared exactly. It is also checked against an independent
  recomputation that uses pandas' own parser.

### School districts

- **Source:** *California School District Areas 2024-25* from the California
  Department of Education. This is the dataset the handbook links to; CDE
  calls the layer "the authoritative geographic data source for all school
  district area boundaries in California".
  - Vintage: the 2024-25 academic year. The layer data was last edited on
    2026-03-10.
  - Contents: 937 districts (516 Elementary, 76 High, 345 Unified).
- **File and coordinate system:**
  - The handbook's link is a shapefile in Web Mercator (EPSG:3857). The script
    downloads the same layer as GeoJSON, which is longitude/latitude in WGS 84
    (CRS84), so no reprojection library is needed.
  - The two exports have identical sets of CDS codes, types and names.
  - The file is saved to `output/week6/school_districts/`. The URL, download
    time and SHA-256 hash are recorded in `source.json`, and the hash is
    checked on every run.
- **Coordinate systems: one documented, one assumed.**
  - **Boundary file (documented, checked):** the handbook's shapefile declares
    WGS 84 Web Mercator (EPSG:3857) in its `.prj`, and the map service reports
    the same. The GeoJSON used here declares `urn:ogc:def:crs:OGC:1.3:CRS84`
    (WGS 84 longitude/latitude), and its coordinates fall within California's
    longitude/latitude range.
  - **MLS `Latitude`/`Longitude` (assumed, not verified):** the matching
    assumes WGS 84 decimal degrees and applies no transformation. The values
    are in decimal-degree ranges, so they are geographic coordinates. But
    nothing in the MLS export states their datum or CRS, and I haven't checked
    the Trestle metadata, so the source CRS is unverified.
  - If the MLS coordinates were NAD 83 instead, the two datums differ by
    roughly 1–2 m in California. That's a general geodesy figure, not
    measured here, and it would only matter for points very close to a
    district boundary.
- **Method:** each distinct coordinate pair (614,184 across both datasets) is
  tested once against every district polygon, holes included. Each row then
  looks up its pair. A lookup can't add or drop rows, and the script raises an
  error if the lookup table has a repeated key.
- **Which rows are matched:**
  - Rows the cleaning flagged as missing, zero, out of range or with a
    positive longitude are not matched. Coordinates are never repaired.
  - Rows outside the bounding box are still tested. In this run none of them
    fell inside a district.
- **District types:** Elementary and High districts overlap by design, so each
  type has its own columns: `elementary_district_name` / `_cds`,
  `high_district_name` / `_cds` and `unified_district_name` / `_cds`. CDS
  codes are text, so leading zeros are kept.
- **Status columns:**
  - `school_district_match_status`: `matched`, `ambiguous` (more than one
    district of the same type; that type is left blank), `unmatched`,
    `invalid coordinates` or `missing coordinates`;
  - `school_district_match_count`: how many districts contain the point;
  - `school_district_match_note`: the types matched, the competing CDS codes,
    or the flag that blocked the match.
- **Existing fields are unchanged:** `HighSchoolDistrict`, `ElementarySchool`,
  `MiddleOrJuniorSchool` and `HighSchool` are kept as they were.
- **Checked against the CDE's own map service:** 60 randomly generated points
  were compared, and all 60 agreed (48 matched, 12 outside every district).
  Random points were used so that no MLS coordinates were sent anywhere.

| | Sold | Listings |
|---|---:|---:|
| Matched | 490,019 | 583,533 |
| Ambiguous | 0 | 0 |
| Unmatched | 174 (35 outside the CA box) | 401 (211 outside the box) |
| Invalid coordinates (not matched) | 82 | 194 |
| Missing coordinates (not matched) | 4,795 | 81,451 |
| Matched, as a share of rows with usable coordinates | 99.96% | 99.93% |
| Types matched: Unified / Elementary + High / Elementary + Unified / Elementary only | 368,765 / 118,803 / 2,000 / 451 | 446,614 / 133,668 / 2,776 / 475 |
| MLS `HighSchoolDistrict` has exactly the same name as the match | 219,306 of 320,307 | 254,860 of 373,204 |

- **Elementary + Unified:** some elementary districts sit inside a unified
  district that serves their upper grades (for example Garvey Elementary and
  Alhambra Unified). These rows count as matched.
- **Elementary only:** almost all of these are Hermosa Beach City Elementary,
  which no High or Unified polygon covers.
- **Agreement with the MLS field:** most of the name differences are spelling
  variants (`William S. Hart Union` → `William S. Hart Union High`,
  `Newport Mesa Unified` → `Newport-Mesa Unified`). So the exact-name
  agreement is only a sanity check, not an error rate.

### Segmented summaries

| File | Grouped by | Groups (sold / listings) |
|---|---|---:|
| `summary_by_property_type.csv` | PropertyType | 1 / 1 (all Residential) |
| `summary_by_property_subtype.csv` | PropertyType + PropertySubType | 21 / 22 |
| `summary_by_county.csv` | CountyOrParish | 63 / 63 |
| `summary_by_county_mls_area.csv` | CountyOrParish + MLSAreaMajor | 1,317 / 1,402 |
| `summary_by_list_office.csv` | ListOfficeName | 19,800 / 22,135 |
| `summary_by_buyer_office.csv` | BuyerOfficeName | 22,710 / 15,648 |

- **Columns:**
  - each file has a `dataset` column (sold or listings), and a blank segment
    value is shown as `(missing)`;
  - counts: `records`, `duplicate_rows_excluded`, `records_used` and
    `closed_records_used`;
  - for each metric: `<metric>_n` (valid observations), `_median`, `_mean`,
    `_p25` and `_p75`.
- **Metrics summarized:** ClosePrice, price_ratio,
  close_to_original_list_ratio, close_to_current_list_ratio (extra),
  price_per_sqft, DaysOnMarket, listing_to_contract_days and
  contract_to_close_days. The `price_ratio_*` and
  `close_to_original_list_ratio_*` statistics are identical by design.
- **Exclusions:**
  - The 48 exact later duplicates in sold (`duplicate_record_flag`) are
    excluded. Listings has none.
  - Repeated ListingKeys that aren't exact duplicates (754 rows in sold, 404 in
    listings) are kept.
  - Each metric uses only the rows where it has a value. Rows are not dropped
    for `any_quality_issue_flag`, so missing coordinates don't remove a sale
    from the price statistics.
- **Use sold for completed-sale statistics.** The listings summaries count only
  Closed listings for those metrics. Their `listing_to_contract_days` also
  includes Pending and ActiveUnderContract listings.
- CoListOfficeName is in the data but is not summarized.

The first five rows of `summary_by_county.csv` for sold (medians; exact
duplicates excluded):

| County | Sales | Close price | Price ratio = close / original list | Close / current list (extra) | $ per sq ft | Days on market | Listing to contract | Contract to close |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Los Angeles | 123,039 | 905,000 | 0.9988 | 1.0000 | 608.65 | 19 | 26 | 30 |
| Riverside | 68,285 | 600,000 | 0.9854 | 1.0000 | 320.70 | 30 | 38 | 30 |
| San Diego | 61,607 | 900,000 | 0.9918 | 1.0000 | 589.90 | 15 | 22 | 26 |
| Orange | 55,759 | 1,185,000 | 0.9929 | 1.0000 | 675.00 | 15 | 26 | 29 |
| San Bernardino | 46,057 | 535,000 | 0.9920 | 1.0000 | 332.03 | 25 | 32 | 32 |

### Results (run on 2026-10-31)

| | Sold | Listings |
|---|---:|---:|
| Rows in → out | 495,070 → 495,070 | 665,579 → 665,579 |
| Columns in → out | 103 → 128 | 92 → 117 |
| Closed records | 495,070 | 195,558 |
| `price_ratio` filled | 494,166 | 194,604 |
| `close_to_original_list_ratio` filled (identical to `price_ratio`) | 494,166 | 194,604 |
| `close_to_current_list_ratio` filled (extra) | 495,067 | 195,558 |
| Rows where the two list ratios both have values but differ (ListPrice ≠ OriginalListPrice) | 154,415 | 43,575 |
| `price_per_sqft` filled | 494,616 | 195,382 |
| `Year` / `Month` / `YrMo` filled | 495,070 | 195,558 |
| `listing_to_contract_days` filled | 494,557 | 332,792 |
| `contract_to_close_days` filled | 494,631 | 195,279 |
| DaysOnMarket valid on Closed records (zeros included) | 495,014 (19,995 zeros) | 195,535 (13,831 zeros) |

- **New columns:** each dataset gets 25:
  - 9 metrics: the three ratios, `price_per_sqft`, `Year`, `Month`, `YrMo` and
    the two day counts;
  - 7 null-reason columns;
  - 9 district columns.
- **Main null reasons, sold:**
  - `price_ratio` and `close_to_original_list_ratio`: OriginalListPrice
    missing (899) or 0 (2), plus 3 without a valid ClosePrice.
  - `close_to_current_list_ratio`: only the 3 without a valid ClosePrice.
  - `price_per_sqft`: LivingArea missing (274) or set to null in cleaning (177).
  - `listing_to_contract_days`: `negative_timeline_flag` (315) or
    PurchaseContractDate missing (197).
  - `contract_to_close_days`: `purchase_after_close_flag` (242) or
    PurchaseContractDate missing (197).
- **Main null reasons, listings:** 470,021 records aren't Closed. For
  `listing_to_contract_days`, PurchaseContractDate is missing in 332,462 rows.
- **Validated in the script:**
  - `price_ratio` and `close_to_original_list_ratio` are identical in every row
    of both datasets: values, nulls and null reasons.
  - **`YrMo` against `year_month`, each on its own date basis:**
    - In both datasets, `year_month` equals the month of the date it was built
      from (CloseDate for sold, ListingContractDate for listings), with 0
      mismatches.
    - `YrMo` equals the CloseDate month on every Closed record.
    - Sold: `YrMo` equals `year_month` in all 495,070 rows, since both come
      from CloseDate.
    - Listings: they agree in 20,448 of 195,558 Closed records. The rest closed
      in a different month from their listing month, which is expected, not an
      error.
  - After saving and reloading, all input columns are text-identical to the
    input. This covers identifiers with leading zeros, `year_month`,
    `rate_30yr_fixed`, coordinates, audit values and flags.
  - The new columns reload to exactly the values computed.
- **Validated independently** (separate code that doesn't import the script):
  - the schema: input columns first, then the 25 new columns;
  - every input column is text-identical to the cleaned file;
  - every metric is recomputed from the cleaned text, with its pattern of
    nulls;
  - the two required ratios are identical, and the extra ratio uses ListPrice;
  - every null has a reason, and there are no infinite values;
  - the `year_month` and `YrMo` checks above;
  - in all six summary files, the `price_ratio_*` and
    `close_to_original_list_ratio_*` statistics are identical;
  - the sold county summary matches a recomputation exactly;
  - the sample has 8 fully filled rows per dataset.
- **Ratios and price per square foot are not outlier-filtered.** The extremes
  are large:
  - `price_ratio` reaches 9,118,000, where OriginalListPrice is $1;
  - `close_to_current_list_ratio` reaches 200,200, where ListPrice is $1;
  - `price_per_sqft` reaches 1,164,067, where ClosePrice is $835,800,000 on a
    $835,800 list price.

  Outlier handling is Week 7.

### Outputs (in `output/week6/`, git-ignored, not committed)

| File | Contents |
|---|---|
| `sold_engineered.csv`, `listings_engineered.csv` | Every input column unchanged, followed by the 25 new columns |
| `sample_engineered.csv` | Rows with every new column filled (8 per dataset), plus one example of each common null reason |
| `summary_by_<segment>.csv` | The six segmented summaries above |
| `validation_report.md` | Requirements, formulas, coverage, null reasons, distributions, exclusions, district coverage, checks and limitations |
| `validation_summary.csv` | Every count in the report, one per row |
| `school_districts/` | The boundary GeoJSON and `source.json` |

### Reloading the engineered files

Use the Weeks 4–5 snippet (see *Reloading the cleaned files*), with these
additions:

```python
TEXT += ["YrMo", "elementary_district_cds", "high_district_cds", "unified_district_cds"]
WHOLE += ["Year", "Month", "listing_to_contract_days", "contract_to_close_days",
          "school_district_match_count"]
sold = pd.read_csv("output/week6/sold_engineered.csv", ...)  # same arguments as before
```

Without `"string"`, the CDS codes would lose their leading zeros. The ratio
columns load as `float64`. Keep `float_precision="round_trip"` to read them
exactly.

### Limitations and open questions

- **The ratio columns overlap by design:** `price_ratio` duplicates
  `close_to_original_list_ratio`, because the handbook gives both the same
  formula. `close_to_current_list_ratio` is the extra metric that differs.
- **Outliers are not removed:** Week 7 will handle them. The summaries report
  medians and quartiles, which extreme values affect less.
- **Boundaries are from one year:** the 2024-25 boundaries are used for sales
  from 2024 to 2026. Boundary changes in other years are not reflected.
- **The MLS coordinate system is assumed:** the matching treats MLS
  `Latitude`/`Longitude` as WGS 84, but their source CRS is undocumented and
  unverified. Only the boundary file's CRS is documented (see *School
  districts*).
- **Points on a boundary** may match both neighbours (they would be reported
  as ambiguous; none were in this run) or neither.
- **Unmatched within the California bounding box; cause not verified:** 139
  sold and 190 listing rows. They are not snapped to the nearest district.
- **Repeated ListingKeys** are kept in the summaries, and why they repeat is
  still unverified.
- **CloseDate on listings that aren't Closed** has an unverified meaning, so
  those listings have no completed-sale metrics.

---

## Week 7 – Outlier Detection and Data Quality

**Goal:**
- flag statistically unusual ClosePrice, LivingArea and DaysOnMarket values with
  the IQR method, keeping business-rule failures separate;
- save a full flagged dataset and a filtered analysis dataset for sold and for
  listings.

No record is deleted from the flagged files, and no input value is changed.

**Deliverable:** [`week7_outlier_detection.py`](week7_outlier_detection.py)

**Requires:**
- `pandas` and `numpy`
- `week1_aggregate.py`, `week4_5_cleaning.py` and
  `week6_feature_engineering.py`, whose helpers it reuses
- the Week 6 outputs (run `week6_feature_engineering.py` first)

No internet is needed. The script stops with an error if an input is missing;
it never reruns earlier stages.

**Inputs (read only; their SHA-256 hashes are checked before and after the run,
and were unchanged):**
- `output/week6/sold_engineered.csv` (495,070 rows × 128 columns)
- `output/week6/listings_engineered.csv` (665,579 rows × 117 columns)

A raw line count of these files is 1–2 higher than the row count, because one
office name in each file contains a line break inside quotes. pandas reads
them correctly.

**Run:** `python week7_outlier_detection.py` (about 3 minutes)

**Tests:** `python test_week7_outlier_detection.py` runs 13 tests on small
synthetic datasets. They cover:
- the threshold calculation, checked against hand-computed quartiles and numpy;
- inclusive bounds;
- missing values, values that are invalid now or were set to null in cleaning,
  and unparseable values;
- zero DaysOnMarket;
- records that aren't Closed;
- exact duplicates versus repeated ListingKeys;
- overlapping exclusion reasons and the medians before and after the IQR step;
- supplementary metrics never excluding a row;
- IQR = 0, and fields with no eligible values;
- that the flagged file preserves the input and the filtered file is exactly
  the included rows;
- that no pandas warnings are raised.

The tests were also run against five deliberately broken versions of the
script, and each one was caught:
- exclusive bounds;
- duplicates used for the thresholds;
- values set to null in cleaning treated as missing;
- records that aren't Closed evaluated;
- IQR = 0 silently skipped.

### Requirements: verified versus chosen

**Verified** against the Week 7 section of the intern handbook:
- apply the IQR method to ClosePrice, LivingArea and DaysOnMarket, using
  lower = Q1 − 1.5 × IQR and upper = Q3 + 1.5 × IQR;
- add outlier flag columns rather than deleting records;
- apply business rules (e.g. ClosePrice <= 0 is always invalid);
- use percentiles alongside IQR;
- save both a full flagged dataset and a clean filtered dataset;
- write a comparison of dataset size and median values before and after
  filtering.

**My choices** (the handbook doesn't specify these):
- thresholds per dataset, estimated on Closed records that aren't exact later
  duplicates;
- quartiles with pandas' default linear interpolation, the method in the
  handbook's example code;
- bounds are inclusive;
- the filtered datasets are Closed-only;
- how IQR = 0 and empty populations are handled;
- the column names.

### Filtering policy

| Step | Rule |
|---|---|
| Business rules (first, separate from IQR) | ClosePrice <= 0 is invalid for Closed records. LivingArea <= 0 and DaysOnMarket < 0 are invalid for every record; 0 days is valid. A value the cleaning set to null for breaking a rule (original kept in `<field>_invalid_original`) counts as **business invalid**, not missing. |
| Threshold population | Per dataset and per field: Closed records that are not exact later duplicates (`duplicate_record_flag`) and have a non-null, finite, valid value for that field |
| Bounds | Q1 and Q3 by linear interpolation; lower = Q1 − 1.5 × IQR, upper = Q3 + 1.5 × IQR; a value equal to a bound is within it |
| Evaluation | Only Closed records. Others keep status `not Closed`: a missing sale price is expected there, and their DaysOnMarket is days so far, not time to sell |
| Filtered analysis dataset | **Closed only.** Not an exact later duplicate, all three fields valid, and within all three bounds. Repeated ListingKeys that aren't exact duplicates are kept |
| IQR = 0 | The formula is applied as written (both bounds equal Q1 = Q3) and the field is reported in `threshold_status`. None occurred in this run |
| No eligible values | No thresholds are computed or invented; values get status `no thresholds`, and no record can pass that field. None occurred in this run |

- **Pooled thresholds:** the dataset-wide thresholds are the baseline. Pooling
  every county and property type into one distribution flags expensive markets
  and large or unusual homes. In San Mateo, 30% of sales are above the sold
  upper bound for ClosePrice; in Santa Clara, 24%. So an IQR outlier is an
  *unusual* value, not a proven data error.
- **Diagnostics only:** price per square foot and the close-to-list ratios are
  reported, but they never exclude a row.

### Flag columns (17 per dataset, appended after the input columns)

| Column | Meaning |
|---|---|
| `<field>_business_invalid_flag` | The value breaks the business rule now, or was set to null in cleaning for breaking it |
| `<field>_iqr_status` | `within bounds`, `below lower bound` or `above upper bound`; or why the value wasn't compared: `not Closed`, `missing`, `business invalid`, `unparseable` or `no thresholds` |
| `<field>_iqr_evaluable` | True only when the value was actually compared with the bounds |
| `<field>_iqr_outlier_flag` | True when an evaluated value is outside the bounds. It is also False for unevaluated values, so read it with `_iqr_evaluable` or `_iqr_status` |
| `iqr_outlier_flag`, `iqr_outlier_fields`, `iqr_fields_evaluated` | Any field an outlier; which fields; how many of the three were evaluated (0–3) |
| `analysis_include` | True for exactly the rows in the filtered file |
| `analysis_exclusion_reasons` | Every applicable reason, separated by `; ` (blank when included). Records that aren't Closed get only `not Closed` |

`<field>` is `ClosePrice`, `LivingArea` or `DaysOnMarket`. A blank or
ineligible value never shows `within bounds`, so it can't look as if it passed.

### Results (run on 2026-11-07)

**Thresholds** (the threshold population):

| | Field | n | Q1 | Q3 | IQR | Lower | Upper | P1 | P5 | P50 | P95 | P99 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Sold | ClosePrice | 495,019 | 575,000 | 1,300,000 | 725,000 | −512,500 | 2,387,500 | 200,000 | 339,000 | 825,000 | 2,860,000 | 5,600,000 |
| Sold | LivingArea | 494,571 | 1,250 | 2,227 | 977 | −215.5 | 3,692.5 | 610 | 841 | 1,648 | 3,569 | 5,300 |
| Sold | DaysOnMarket | 494,966 | 8 | 49 | 41 | −53.5 | 110.5 | 0 | 1 | 19 | 132 | 235 |
| Listings | ClosePrice | 195,558 | 599,000 | 1,350,000 | 751,000 | −527,500 | 2,476,500 | 215,000 | 350,000 | 850,000 | 2,900,000 | 5,550,000 |
| Listings | LivingArea | 195,382 | 1,248 | 2,190 | 942 | −165 | 3,603 | 616 | 850 | 1,632 | 3,477 | 5,056 |
| Listings | DaysOnMarket | 195,535 | 6 | 32 | 26 | −33 | 71 | 0 | 0 | 13 | 84 | 135 |

**Flags among Closed records:**

| | Field | Below lower | Above upper | Upper bound at | Business invalid | Missing |
|---|---|---:|---:|---:|---:|---:|
| Sold | ClosePrice | 0 | 37,060 | P92.5 | 1 | 2 |
| Sold | LivingArea | 0 | 21,662 | P95.6 | 177 | 274 |
| Sold | DaysOnMarket | 0 | 36,753 | P92.6 | 56 | 0 |
| Listings | ClosePrice | 0 | 14,130 | P92.8 | 0 | 0 |
| Listings | LivingArea | 0 | 8,455 | P95.7 | 77 | 99 |
| Listings | DaysOnMarket | 0 | 14,256 | P92.7 | 23 | 0 |

- **Duplicates:** the sold "above upper" counts include a few exact
  duplicates (7, 5 and 5). Within the threshold population they are 37,053,
  21,657 and 36,748.
- **Records that aren't Closed** also carry the LivingArea and DaysOnMarket
  rules: for all listings, 429 LivingArea and 34 DaysOnMarket values are
  business invalid.
- **Upper bound at:** the share of the threshold population at or below the
  upper bound.

**Population flow** (each step's removals are counted only at that step, so
they don't overlap):

| Stage | Sold | Listings |
|---|---:|---:|
| All input records (full flagged dataset) | 495,070 | 665,579 |
| Closed | 495,070 | 195,558 |
| Not an exact later duplicate | 495,022 | 195,558 |
| All three fields valid (eligible; before IQR) | 494,512 | 195,359 |
| Within all three IQR bounds (**filtered dataset**) | **417,886** | **165,236** |

- **Removed at the IQR step:** 76,626 sold (15.5% of eligible) and 30,123
  listings (15.4%).
- **Share kept:** the sold filtered set is 84.4% of all sold rows. The listings
  filtered set is 24.8% of all listings and 84.5% of Closed listings.

**Exclusion reasons overlap.** Unique excluded rows are 77,184 for sold and
500,343 for listings. Of these, 16,668 sold and 6,178 listing rows have two or
more reasons. Among Closed records that aren't duplicates:

| | Sold | Listings |
|---|---:|---:|
| Validity or missingness only | 272 | 105 |
| IQR only | 76,626 | 30,123 |
| Both | 238 | 94 |

**Medians and means immediately before and after the IQR step** (eligible
Closed records versus the filtered dataset):

| | Field | Median before → after | Change | Mean before → after | Change |
|---|---|---:|---:|---:|---:|
| Sold | ClosePrice | 825,000 → 785,000 | −4.8% | 1,186,706 → 899,305 | −24.2% |
| Sold | LivingArea | 1,648 → 1,574 | −4.5% | 1,903 → 1,681 | −11.7% |
| Sold | DaysOnMarket | 19 → 16 | −15.8% | 37.6 → 26.7 | −29.1% |
| Listings | ClosePrice | 850,000 → 815,000 | −4.1% | 1,193,943 → 933,100 | −21.8% |
| Listings | LivingArea | 1,632 → 1,563 | −4.2% | 1,840 → 1,666 | −9.5% |
| Listings | DaysOnMarket | 13 → 12 | −7.7% | 23.9 → 17.9 | −25.3% |

### Discussion

- **The filter is one-sided.** Every lower bound is negative, so the IQR step
  removes only high values. That is why every median and mean falls.
  - Medians move 4–5% for price and area. Means move 9–24%, because the means
    were pulled up by the long upper tail.
  - DaysOnMarket shifts most in relative terms (sold median 19 → 16 days).
    In sold, 7.4% of the DaysOnMarket threshold population is above 110.5
    days.
- **Filtered statistics describe a narrower market.** They are not more
  accurate, and they understate prices relative to all Closed sales. They
  remove most luxury sales in the highest-priced counties, for example 30% of
  San Mateo's. For county-level, luxury or large-home analysis, use the
  flagged dataset with segment-appropriate thresholds rather than the pooled
  filter.
- **Implausibly low values pass.** Because the lower bounds are negative, the
  filtered sold data still contains a ClosePrice of $1.15 and a LivingArea of
  1 sq ft. It also has 3,670 sales below the population's P1 ($200,000), which
  are not necessarily errors. Only the business rules (≤ 0) catch low values.
- **Supplementary diagnostics** (reported, not used to exclude):
  - price per square foot: its median moves 536 → 525 in sold, and its maximum
    falls from 1,164,067 to 735,000;
  - `close_to_current_list_ratio` still reaches 200,200 in the filtered data
    (a $1 ListPrice), because ratio extremes aren't IQR outliers in any of the
    three fields.

### Outputs (in `output/week7/`, git-ignored, not committed)

| File | Contents |
|---|---|
| `sold_flagged.csv`, `listings_flagged.csv` | Every input row and column unchanged, in the same order, followed by the 17 flag columns (sold 145 columns, listings 134) |
| `sold_filtered.csv`, `listings_filtered.csv` | Exactly the flagged rows with `analysis_include = True`, with the same columns and order (417,886 and 165,236 rows) |
| `iqr_thresholds.csv` | One row per dataset and field, with these column groups: population, Q1/Q3/IQR/bounds, `threshold_status`, P1/P5/P50/P95/P99, min/max, counts below and above, the bounds' percentile ranks, and Closed missing/invalid/unparseable counts |
| `before_after_summary.csv` | Long format with a `section` column: `population flow`, `dataset size`, `median by stage`, `IQR step: eligible vs filtered`, `supplementary diagnostic (not an exclusion criterion)`, `exclusion reasons (overlapping)` and `unique excluded` |
| `validation_report.md` | Policy, flag semantics, thresholds, counts, population flow, exclusion reasons, median comparison, percentiles, pooled-threshold evidence by county, the written comparison, checks and limitations |

To reload a flagged or filtered file, use the Week 6 snippet (see *Reloading
the engineered files*). Add `"Int64"` for `iqr_fields_evaluated`; the
`*_flag`, `*_evaluable` and `analysis_include` columns load as `bool`.

### Validation

- **In the script, before saving:**
  - quartiles match numpy's linear method;
  - every included row is checked against the rules from its values: Closed,
    not a duplicate, valid finite values, within all bounds;
  - no record that isn't Closed is evaluated;
  - no outlier flag is set on a value that wasn't evaluated;
  - exclusion reasons are blank exactly for included rows.
- **After saving:**
  - the flagged files reload with the same rows, order and input text;
  - the new columns reload to the same values;
  - the filtered files are exactly the included flagged rows.
- **Independently** (separate code that doesn't import the script):
  - every input column of the flagged files is identical to the Week 6 text;
  - the filtered files are exactly the `analysis_include = True` subset;
  - thresholds, percentiles and counts, recomputed from the Week 6 text with
    numpy, match `iqr_thresholds.csv`;
  - the flags and `analysis_include` match a recomputation;
  - the population flow, medians, means and exclusion counts match
    `before_after_summary.csv`;
  - the report shows the same medians.

### Limitations

- **IQR flags unusual values, not errors.** Valid market extremes (luxury
  homes, very large properties, slow sales) are flagged too, and filtering
  doesn't by itself make the data more accurate.
- **One set of thresholds per dataset:** they are pooled across counties and
  property types, which over-flags high-priced markets. Segment-specific
  thresholds would be a separate, documented choice.
- **Low values aren't screened by IQR here:** the lower bounds are negative.
- **Sold and listings overlap:** listings' Closed records overlap with sold, so
  the two sets of thresholds are close but not identical.
- **Repeated ListingKeys** that aren't exact duplicates are kept; why they
  repeat is still unverified.

---

## Weeks 8–10 – Tableau Dashboard Development

**Goal:** the handbook's two workbooks.
- `market_analysis.twbx`: five required monthly dashboards plus one of my own
  design, filterable by city, county, ZIP code and PropertySubType.
- `competitive_analysis.twbx`: Top 100 agents and offices, two ZIP heat maps,
  plus one of my own design.

**Status:**
- **Done here (and validated):** the data preparation, the reference numbers
  and the build guide.
- **Still manual:** building the workbooks in Tableau, following
  [`weeks8_10_tableau_build_guide.md`](weeks8_10_tableau_build_guide.md). They
  are not built yet.

**Deliverable (preparation):**
[`weeks8_10_tableau_prep.py`](weeks8_10_tableau_prep.py)

**Requires:**
- `pandas`, `numpy` and `requests`
- the Week 7 outputs; it reuses Week 1, 4–5, 6 and 7 helpers

It downloads the Census ZCTA list (about 1 MB) once. No MLS data is sent
anywhere.

**Run:** `python weeks8_10_tableau_prep.py` (about 2 minutes)

**Tests:** `python test_weeks8_10_tableau_prep.py` runs 10 tests on synthetic
sales and listings. They cover:
- the counting grain and exact duplicates;
- the metric-specific valid mode and the IQR mode;
- new listings across all statuses, independent of the sales mode;
- office normalization and placeholders;
- agent keys and ranking ties;
- ZIP derivation with leading zeros;
- labels that match across the two sources;
- no warnings.

### Inputs (read only; SHA-256 unchanged after the run)

- `output/week7/sold_flagged.csv` (495,070 × 145) and
  `output/week7/listings_flagged.csv` (665,579 × 134). These are the Week 6
  engineered data plus the Week 7 flags; the Week 6 files are unchanged too.
- Every row is `Residential`. Sold rows are all `Closed`; listings are Active
  323,323, Closed 195,558, Pending 97,029, ActiveUnderContract 47,364 and
  ComingSoon 2,305.

### Counting grain: evidence and policy

| | Sales | Listings |
|---|---:|---:|
| Input rows | 495,070 | 665,579 |
| Exact later duplicates dropped (`duplicate_record_flag`) | 48 | 0 |
| Rows in the Tableau file | 495,022 | 665,579 |
| Repeated-key rows (after removing duplicates) | 658 in 327 keys | 404 in 201 keys |
| Counted rows (`transaction_row = 1`, one per ListingKey) | 494,691 | 665,376 |

**Evidence:** after exact duplicates are removed, every repeated ListingKey has:
- the same ListingId;
- its rows in different monthly files.

The sold rows also differ in CloseDate (1–440 days apart, median 25). The
listing rows differ in ListingContractDate, often with a status change such as
ComingSoon → Active or Active → Closed. They are snapshots of one listing whose
dates moved between pulls.

**Policy:**
- A ListingKey counts once.
- The counted row is the most recently updated snapshot: the latest
  `ContractStatusChangeDate`, then the later date, then the later file row. The
  other snapshots stay in the files with `transaction_row = 0`.

**Unresolved:** in 86 sold keys the ClosePrice also differs. A price correction
can't be told apart from a closing that fell through and closed again; these
still count once.

### The two Tableau sources

**`tableau_sales.csv`** (sold; sale month = CloseDate)
- **Original columns, text-identical to the input:** identifiers, geography
  originals, prices, dates and the Week 7 flags.
- **Filter labels:** `county_label`, `city_label`, `zip_code`, `state_label` and
  `property_subtype_label`.
- **Agent and office keys and labels.**
- **Eligibility for each mode,** as 0/1 columns.

**`tableau_listings.csv`** (all statuses; listing month = ListingContractDate)
- the same filter labels, and `new_listing_event`.

The two sources are never appended or joined. Filters pass between them only
through blend links on the four label fields.

**Labels** are conservative:
- Values that differ only in case or spacing share the most frequent spelling.
  This merges 1,249 → 1,244 city spellings; county, state and subtype have no
  variants.
- The same mapping is used in both files.
- The originals are kept.

**ZIP code:** the 5-digit text taken from `PostalCode`.

| | Sales | Listings |
|---|---:|---:|
| 5-digit | 492,087 | 661,854 |
| ZIP+4 trimmed | 2,567 | 3,422 |
| Malformed suffix trimmed | 31 | 47 |
| Not usable | 6 | 53 |

These are counted rows. 434 counted sales and 716 counted listings have a ZIP
that isn't in the Census ZCTA list, so Tableau may not map them; they are listed
in `zip_geography_check.csv`.

### Sales modes and metric definitions

| Mode | Population | Default in |
|---|---|---|
| Week 7 IQR-filtered | Week 7 `analysis_include` (417,597 counted sales) | `market_analysis`, continuing the prior assignment |
| Valid before IQR | Metric-specific validity (494,691 counted sales). Closed sales need only a CloseDate; volume and median price a valid ClosePrice (494,689); average DOM a valid DaysOnMarket (494,635; 0 is valid); the ratio a valid ratio (493,788). A missing LivingArea or DaysOnMarket never removes a sale from counts or volume | `competitive_analysis`: the IQR filter removes every sale above about $2.39M and would drop the high-end brokerages from the rankings |

**Metric definitions** (copyable Tableau formulas are in the guide):
- **Median close price:** median of the eligible ClosePrice.
- **Average days on market:** mean of the eligible DaysOnMarket.
- **Average close-to-original-list ratio:** mean of the row-level
  `close_to_original_list_ratio`, shown as a percentage. It is never computed
  from price sums and never uses the current-list ratio.
- **New listings:** sum of `new_listing_event` by `listing_month`. It never uses
  the sales mode.
- **Closed sales:** sum of the counted rows by `sale_month`.
- **Sales volume:** sum of the eligible ClosePrice.

### Agents and offices

- **No listing-agent or listing-office ID exists in the data.**
- **Offices** are keyed by name, normalized for case and spacing (19,142
  offices with sales).
- **Agents** are keyed by name + listing office (98,286), and shown as
  "Name · Office".
- **Why not email:**
  - `ListAgentEmail` is missing for every listing from 2026-06 on;
  - some team emails are shared by several agents;
  - of the 3,487 name + office keys with more than one email, 3,053 used them
    one after another, so email would split one person.
- **Unresolved:** in 434 keys the emails overlap in time; these may be two
  people with the same name in one office.
- **Sensitivity:** the Top 100 by volume shares 93–94 names with rankings keyed
  by email + name, by name only, or by email only.
- **Unattributed, never ranked:** placeholder names ("Non-Member",
  "PWNONMEMBER", "Unknown Office" and similar) and missing names. In the valid
  mode, 117 counted sales have no identifiable listing agent and 9 have no
  identifiable listing office. They stay in market totals.

### Coverage

- Both sources run from **2024-01 to 2026-09** (33 months). Months without data
  are absent, never zero.
- Some months come from dated API snapshots (2026-10-02/03): listings 2026-01
  and 2026-05 to 2026-09; sales 2026-05 to 2026-09. The rest come from
  FileZilla exports, so trends can step at the boundaries
  (`month_coverage.csv`).
- Recent months may still be revised by late reporting.

### Outputs (in `output/weeks8_10/`, git-ignored)

`tableau_sales.csv`, `tableau_listings.csv`, `reference_monthly.csv`,
`reference_agents_top100.csv`, `reference_offices_top100.csv`,
`reference_zip.csv`, `reference_segments.csv`, `zip_geography_check.csv`,
`month_coverage.csv`, `validation_report.md` and
`reference/2024_Gaz_zcta_national.zip`. Save the workbooks in
`output/weeks8_10/workbooks/`; `*.twbx`, `*.twb`, `*.hyper` and `*.tde` are also
git-ignored everywhere.

### Validation

- **In the script:**
  - one counted row per ListingKey;
  - the IQR mode never counts a row the valid mode doesn't;
  - the saved files reload with identical identifier, geography, price, date
    and flag text;
  - `zip_code` is always 5 digits;
  - 0/1 columns hold only 0 or 1;
  - `zcta_latitude` and `zcta_longitude` are plain numbers, blank only where a
    ZIP has no Census point. The Census file pads its longitude column, and
    that padding is trimmed (fixed 2026-11-07; 0 values failed conversion);
  - no cell contains a line break;
  - monthly totals add up.
- **Independently** (separate code from the Week 7 files):
  - the counting grain;
  - monthly closed sales, volume, median price, average DOM and average ratio
    in both modes;
  - totals taken from the Tableau files the way the guide's formulas compute
    them;
  - monthly new listings;
  - the agent and office Top 100s (sizes, ranks, totals);
  - ZIP homes sold and medians;
  - the Los Angeles County segment;
  - the input hashes.

  All of them match.

### Limitations and open questions

- **The average close-to-original-list ratio is dominated by a few records**
  with a tiny OriginalListPrice (e.g. $1), in both modes. For example, the
  February 2025 valid-mode average is 877 (87,700%) against a median of 1.00. No
  ratio cutoff is applied, because none is documented. The guide shows the
  median next to the average. **A supervisor decision is needed.**
- **Valid-mode volume rankings are driven by a few implausible ClosePrices:**
  - the #1 agent has $810M of $1.44B in one sale;
  - the #4 and #5 agents have 98–99.9% of their volume in one sale
    ($970M–$989.5M).

  The largest-sale columns and tooltips expose this; units and the IQR mode
  aren't affected. No price cutoff is invented.
- **Volume credit:** listing-side only, with no split for co-listing offices
  (`CoListOfficeName` is present for about 24% of sales).
- **Names, not IDs:** office branches of one brand share a name, and agent
  identity is name-based.
- **Repeated keys:** 86 sold keys whose ClosePrice differs are counted once,
  which may be wrong.
- **Mapping:** Tableau's own geocoding decides what maps; the ZCTA list only
  predicts it.
- **Publishing:** Weeks 11–12 ask for Tableau Public, but the MLS data is
  confidential. How to publish (for example aggregated data only) must be agreed
  before anything is uploaded.
