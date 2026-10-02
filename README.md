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
| `download_missing_months.py` | Downloads any month that is missing or damaged, checks it, and saves it to `csv/`. |
| `crmls_listed.py` | Original single-month script for listings (filtered by `ListingContractDate`). |
| `crmls_sold.py` | Original single-month script for closed sales (filtered by `CloseDate` and `MlsStatus = 'Closed'`). |
| `idx_auth.py` | Gets an API access token. Reads the key from a local `.env` file, so no credentials are stored in the code. |

The data itself is **not** in this repository: the files are too large for
GitHub (over 100 MB) and the MLS data is for internal use. Git ignores the
following local folders:

```
csv/            raw monthly files (CRMLSListingYYYYMM.csv, CRMLSSoldYYYYMM.csv)
output/         combined datasets and run_report.txt
backup/         copies of raw files that were replaced
downloads_tmp/  in-progress downloads and the download log
.env            API key (local only)
```

---

## Process

### 1. Collect the monthly files

Each month comes from the Trestle API as two files:

- **Listings:** listings whose contract started that month (`ListingContractDate`).
- **Sold:** sales that closed that month (`CloseDate`, `MlsStatus = 'Closed'`).

When this project started, 17 listing months and 17 sold months were missing,
and January 2026 listings was an incomplete download. `download_missing_months.py`
filled the gaps. For each month it:

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

**Requirements:** Python 3.12, `pandas`, `requests`

```bash
pip install pandas requests
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
```

---

## Week 1 results

Run on 2026-10-02, covering 2024-01 through 2026-09:

| | Listings | Sold |
|---|---:|---:|
| Monthly files found | 33 of 33 | 33 of 33 |
| Rows before concat (sum of monthly files) | 925,452 | 742,127 |
| Rows after concat | 925,452 | 742,127 |
| Rows after Residential filter | **596,911** | **497,570** |

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

- **Files come from different points in time.** 35 files were downloaded on
  2026-10-02, and each matched the API's own count at that moment. The other 31
  were saved earlier, at different and unknown dates, so they can't be checked
  the same way.
  - Older listing files have 1,500 to 13,544 more rows than the API returns today.
  - Older sold files from August 2024 onward are missing roughly 600 to 1,200
    closings per month that were reported later.
  - Month-to-month trends may jump where an older file sits next to a newer one.
- **January 2024 listings: unresolved discrepancy.** The local file has 27,454
  rows; the API returns 23,403 today.
  - Most of the records found only in the local file were `Active` when it was
    saved. None of 400 sampled still exist in the API under any date.
  - Likely cause: listings that later expired or were withdrawn are no longer
    served by the feed. This is not proven.
  - The file also has exactly 20,000 `Closed` rows, which may point to a limit
    in the tool that produced it.
  - The file was left unchanged.
- **Same listing in two months.** 93 listings and 287 sold rows share a
  `ListingKey` with a row in another month, because a date changed between
  downloads. They were not removed; this is left for data cleaning.
- **Recent months are still changing.** Late-reported closings will keep
  adding to the latest sold months.
- **Some columns don't cover every month:**
  - `ListAgentEmail` is blank for listings downloaded with the current script.
  - `BuyerAgencyCompensation` exists only in early-2024 files.
  - `latfilled` and `lonfilled` exist only in the `_filled` sold files.

**Possible next step:** download all 33 months again in one session, so every
month comes from the same point in time. Keep the current files in `backup/`.
