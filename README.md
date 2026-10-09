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
| `download_missing_months.py` | Downloads any month that is missing or damaged, checks it, and saves it to `csv/`. |
| `crmls_listed.py` | Original single-month script for listings (filtered by `ListingContractDate`). |
| `crmls_sold.py` | Original single-month script for closed sales (filtered by `CloseDate` and `MlsStatus = 'Closed'`). |
| `idx_auth.py` | Gets an API access token. Reads the key from a local `.env` file, so no credentials are stored in the code. |

The data itself is **not** in this repository: the files are too large for
GitHub (over 100 MB) and the MLS data is for internal use. Git ignores the
following local folders:

```
csv/            raw monthly files (CRMLSListingYYYYMM.csv, CRMLSSoldYYYYMM.csv)
output/         combined datasets and run_report.txt (Week 1); week2_3/ (Weeks 2–3)
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

**Requirements:** Python 3.12, `pandas`, `requests`, `matplotlib`

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
