# Weeks 8–10 – Workbook acceptance checklist

Work through every item in Tableau before calling a workbook complete.

- **Where the expected values come from:** `output/weeks8_10/reference_*.csv`,
  which an independent recomputation confirmed (see
  `output/weeks8_10/validation_report.md`).
- **Number formats:** ratios are shown as Tableau percentages (1.0 = 100%).
  Medians and volumes are in dollars.
- **Build steps:** `weeks8_10_tableau_build_guide.md`.

---

## A. market_analysis.twbx

### A1. Required dashboards

- [ ] Monthly median close price
- [ ] Average days on market
- [ ] Average close-to-original-list price ratio
- [ ] New listings
- [ ] Closed sales
- [ ] Additional: Market Momentum (new listings, closed sales and days on
      market on one timeline, with the "different cohorts, not a conversion
      rate or months of inventory" caption)
- [ ] Every dashboard shows the County, City, ZIP code and PropertySubType
      filters and the Sales Mode parameter
- [ ] The New Listings dashboard says Sales Mode doesn't apply to it

### A2. Data sources and counting grain

- [ ] Two separate data sources, **Sales** (`tableau_sales.csv`) and
      **Listings** (`tableau_listings.csv`)
- [ ] Each source contains one table only: no joins, unions or relationships
      inside a data source
- [ ] Blend links (Data › Edit Blend Relationships) are **only** these four:
      `county_label`, `city_label`, `zip_code`, `property_subtype_label`.
      There is no link on `ListingKey`, `ListingId` or any date
- [ ] Data types:
  - `ListingKey`, `ListingId`, `zip_code` and `PostalCode` are **String**
    in both sources;
  - `CloseDate`, `sale_month`, `ListingContractDate` and `listing_month` are
    **Date**
- [ ] Both sources use Extract connections

| Check (no filters) | Expected |
|---|---:|
| Sales: row count (`tableau_sales.csv (Count)`) | 495,022 |
| Sales: SUM(`transaction_row`) | 494,691 |
| Sales: SUM(`valid_sale_count`) | 494,691 |
| Sales: SUM(`iqr_sale_count`) | 417,597 |
| Listings: row count | 665,579 |
| Listings: SUM(`new_listing_event`) | 665,376 |

### A3. Monthly coverage

- [ ] Every monthly chart runs from **January 2024 to September 2026** (33
      months) in both sources
- [ ] No month after September 2026 appears; MAX(`sale_month`) and
      MAX(`listing_month`) are both 2026-09-01
- [ ] "Show Missing Values" is off, so no month is invented as zero
- [ ] Captions say:
  - recent months may be revised;
  - listings 2026-01 and 2026-05 to 2026-09, and sales 2026-05 to 2026-09,
    come from API snapshots, so trends can step at those boundaries

### A4. Metric reconciliation (no filters)

| Month | Mode | New listings | Closed sales | Median close price | Avg DOM | Avg ratio (as %) | Median ratio |
|---|---|---:|---:|---:|---:|---:|---:|
| Jan 2024 | IQR-filtered | 17,005 | 9,793 | $720,000 | 30.00 | 120.8% | 99.7% |
| Jan 2024 | Valid | 17,005 | 11,194 | $749,000 | 39.01 | 117.3% | |
| Feb 2025 | IQR-filtered | 21,928 | 9,873 | $787,500 | 28.14 | 170.3% | 100.0% |
| Feb 2025 | Valid | 21,928 | 12,093 | $835,000 | 41.36 | 87,705.5% | |
| Jun 2025 | IQR-filtered | 17,056 | 13,063 | $799,000 | 26.88 | 137.2% | 99.6% |
| Jun 2025 | Valid | 17,056 | 15,318 | $840,000 | 36.29 | 137.8% | |
| Sep 2026 | IQR-filtered | 22,211 | 12,115 | $784,000 | 29.98 | 8,380.9% | 99.0% |
| Sep 2026 | Valid | 22,211 | 14,584 | $823,500 | 42.00 | 6,987.0% | |
| All months | IQR-filtered | 665,376 | 417,597 | $786,000 | | | |
| All months | Valid | 665,376 | 494,691 | $825,000 | | | |

- [ ] Every row above matches; all 33 months are in `reference_monthly.csv`
- [ ] Sales volume matches, e.g. Sep 2026: $10,828,045,890 (IQR) and
      $17,520,382,157 (valid)

### A5. Sales Mode behaviour

- [ ] Switching the mode changes closed sales, volume, median price, average DOM
      and the average ratio. For example, Sep 2026 closed sales go between
      12,115 and 14,584
- [ ] Switching the mode does **not** change new listings (Sep 2026: 22,211 in
      both modes)
- [ ] Each title or caption shows the current mode
- [ ] The default when the workbook opens is **Week 7 IQR-filtered**

### A6. Filters

Apply each selection on its own, compare it with `reference_segments.csv` (all
months), then clear it.

| Selection | New listings | Closed sales (IQR / valid) | Median close price (IQR / valid) |
|---|---:|---:|---:|
| County = Los Angeles | 169,486 | 102,789 / 122,925 | $860,000 / $905,000 |
| City = San Diego | 31,427 | 20,392 / 22,454 | $895,000 / $928,000 |
| ZIP = 92253 | 4,556 | 2,193 / 3,075 | $727,000 / $798,253 |
| PropertySubType = Condominium | 119,399 | 72,730 / 81,070 | $625,000 / $625,000 |
| County = Orange **and** PropertySubType = SingleFamilyResidence | 39,515 | 27,470 / 34,933 | $1,280,000 / $1,400,000 |

- [ ] Every row matches. **The new-listings numbers prove the filters reach the
      Listings source**: if new listings don't change, the filter isn't set to
      "All Using Related Data Sources" or a blend link is missing
- [ ] The latest month for the same selections matches the
      `latest month 2026-09` rows of `reference_segments.csv`

### A7. Known anomalies shown, not hidden

- [ ] The ratio dashboard shows the median next to the average, with a caption:
  - the average is dominated by a few records with a tiny OriginalListPrice;
  - in the IQR mode, monthly averages range from 115.9% (Aug 2025) to 16,903.9%
    (Nov 2024), while monthly medians range from 98.7% to 100.5%;
  - no cutoff is applied
- [ ] No extra filter has been added to hide extreme values. That would be an
      undocumented cutoff

### A8. Packaging and reopening

- [ ] Saved as **Tableau Packaged Workbook** to
      `output/weeks8_10/workbooks/market_analysis.twbx`
- [ ] Tableau closed completely, then the `.twbx` reopened by double-clicking
      it. The data loads without asking for the CSV files, and A2 and A4 still
      match
- [ ] `git status` doesn't list the `.twbx` (it's ignored)
- [ ] **Not** published to Tableau Public, Tableau Server or any other site

---

## B. competitive_analysis.twbx

### B1. Required dashboards

- [ ] Top 100 listing agents by **sales volume** and by **units**: two sheets,
      or one sheet with a Rank By selector
- [ ] Top 100 listing offices by volume and units, filterable by City, County,
      ZIP code and PropertySubType
- [ ] ZIP heat map of median close price, filterable by month, City, County, ZIP
      code and PropertySubType
- [ ] ZIP heat map of homes sold, with the same filters
- [ ] Additional: Office Market Share (volume and units share of the whole
      selected market)
- [ ] The default Sales Mode when the workbook opens is **Valid before IQR**,
      and the IQR-filtered option still works

### B2. Ranking rules

- [ ] Ranks use `RANK(…, 'desc')` table calculations, computed using the
      agent or office label. They are filtered with **At most 100**, applied
      after all other filters
- [ ] Adding a filter (e.g. County = Los Angeles) re-ranks within the filtered
      market
- [ ] Ties share a rank, and every row tied at 100 is shown. Valid mode, no
      filters: the agent Top 100 by units has **101** rows
- [ ] `(unattributed)` never appears in a ranking
- [ ] The agent label is "Name · Office". The caption says identity is
      name-based (no agent or office ID exists); an agent who changed office
      appears once per office; office branches of one brand share a name

### B3. Ranking reconciliation (compare with `reference_*_top100.csv`)

| Check | Week 7 IQR-filtered | Valid before IQR |
|---|---|---|
| #1 office by volume, no filters | Compass – $33,229,881,855, 28,034 units | Compass – $67,986,570,822, 37,319 units |
| Office Top 100 rows by volume / by units | 100 / 100 | 100 / 100 |
| Agent Top 100 rows by volume / by units | 100 / 100 | 100 / 101 |
| Top office by volume, County = Los Angeles | see `reference_segments.csv` | Compass |
| Top office by volume, City = San Diego | see `reference_segments.csv` | Coldwell Banker West |
| Top office by volume, Orange + SingleFamilyResidence | see `reference_segments.csv` | Coldwell Banker Realty |

- [ ] The first 10 rows of each ranking match the reference file: rank, label,
      units, volume
- [ ] A `Largest Sale` tooltip is on every volume ranking

### B4. ZIP maps

- [ ] `zip_code` is String, with the **ZIP Code/Postcode** role; Marks = Map
      (filled)
- [ ] The unknown-locations indicator count is recorded in a caption, and the
      unknown ZIP codes are compared with `zip_geography_check.csv`
- [ ] ZIP 92253, all months: homes sold 2,193 (IQR) / 3,075 (valid); median
      $727,000 / $798,253
- [ ] The month filter works: one month shows only that month's sales
- [ ] **If the fallback symbol map is used:** `zcta_latitude` and
      `zcta_longitude` load as **Number (decimal)**, with the Latitude and
      Longitude roles. Since the 2026-11-07 fix they are plain numbers in the
      file. If either shows as text (Abc), the workbook is connected to an old
      copy of `tableau_sales.csv`: refresh the extract

### B5. Office Market Share

- [ ] Shares are a Percent of Total computed over **all** offices in the view,
      including `(unattributed)`. With no rank filter, the shares add up to 100%
- [ ] Applying the Top 20/100 rank filter doesn't change any office's share
- [ ] The unattributed volume share is about 0.002% (valid, no filters: 9 sales,
      $10.7M)
- [ ] The caption says it is listing office only, with co-listing offices not
      credited

### B6. Packaging and reopening

- [ ] Saved as **Tableau Packaged Workbook** to
      `output/weeks8_10/workbooks/competitive_analysis.twbx`
- [ ] Reopened from disk; data loads; B3 still matches
- [ ] Not listed by `git status`; not published anywhere

---

## C. Known data anomalies to carry into captions

| Anomaly | Effect | Where to say it |
|---|---|---|
| A few records with a tiny OriginalListPrice (e.g. $1) | The average close-to-original-list ratio is far above 100% in every month, in both modes | Ratio dashboard |
| A few implausible ClosePrices ($810M–$989.5M) | They lead the valid-mode **volume** rankings; for some agents one sale is over 97% of their volume | Agent and office volume rankings |
| 86 sold ListingKeys whose ClosePrice differs between snapshots | Counted once; it may be a separate closing (unresolved) | Data notes |
| Agent identity is name + office | Namesakes in one office may merge (434 keys whose emails overlap in time); an agent who moved office is split | Agent rankings |
| Listing office credited with the full price | Co-listing offices (about 24% of sales) get no share | Office rankings and market share |
| ZIP codes not in the Census ZCTA list (434 counted sales, 716 counted listings); 6 sales without a usable ZIP | They may be unknown on the maps | ZIP maps |
| ZIP codes with no Census point (missing, invalid or not a ZCTA) | Blank `zcta_latitude`/`zcta_longitude`; not shown on the fallback map. The padded Census longitude was fixed on 2026-11-07 | Fallback map only |
| Months from API snapshots versus FileZilla exports | Possible steps in trends; recent months may be revised | All monthly charts |
| MLS data is confidential | No Tableau Public or other publishing without an agreed approach | Workbook notes |
