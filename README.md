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
