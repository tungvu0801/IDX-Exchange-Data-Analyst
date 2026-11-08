# Weeks 8–10 – Tableau build guide

Step-by-step instructions for building `market_analysis.twbx` and
`competitive_analysis.twbx` in Tableau Desktop from the prepared files.

**Status:**
- The data preparation and the reference numbers are done and validated
  (`python weeks8_10_tableau_prep.py`; see `output/weeks8_10/validation_report.md`).
- **The workbooks are not built yet; you build them by hand in Tableau.** These
  steps were written without access to Tableau. Check every sheet against the
  reference numbers in [Part 6](#part-6--check-your-numbers).
- Menu names follow recent Tableau Desktop versions and may differ slightly in
  yours.

**Confidentiality:** the files and any `.twbx` built from them contain MLS data.
- Save workbooks only in `output/weeks8_10/workbooks/`, which is git-ignored.
- **Do not publish them to Tableau Public** or upload them anywhere.
- Weeks 11–12 ask for publishing. How to do that without exposing MLS data (for
  example with aggregated data only) needs to be agreed with the supervisor
  first.

---

## Part 0 – The files

All files are in `output/weeks8_10/`.

| File | Use | Rows |
|---|---|---:|
| `tableau_sales.csv` | **Sales data source.** One row per sold record (all Closed, all Residential), minus the 48 exact later duplicates | 495,022 |
| `tableau_listings.csv` | **Listings data source.** One row per listing record, every status (Active, Pending, ActiveUnderContract, ComingSoon, Closed) | 665,579 |
| `reference_monthly.csv` | What the monthly charts should show, in both sales modes | 33 months |
| `reference_agents_top100.csv`, `reference_offices_top100.csv` | Top 100 by volume and by units, both modes | |
| `reference_zip.csv` | Homes sold and median close price per ZIP, both modes | |
| `reference_segments.csv` | Totals for sample filter selections (county, city, ZIP, subtype) | |
| `zip_geography_check.csv` | ZIP values Tableau may not place on a map | |
| `month_coverage.csv` | Months in each source and where each month's file came from | |

Don't use `output/week7/listings_filtered.csv` for new listings: it holds only
Closed records.

### Key columns

| Column | In | Meaning |
|---|---|---|
| `ListingKey`, `ListingId` | both | Identifiers. **Text**, never numbers |
| `transaction_row` | both | 1 = this row counts. A ListingKey that appears more than once is several snapshots of one listing; only the most recently updated snapshot has 1 |
| `sale_month` | sales | First day of the CloseDate month (e.g. `2024-01-01`). Use it for sale months |
| `listing_month` | listings | First day of the ListingContractDate month. Use it for new-listing months |
| `new_listing_event` | listings | 1 = count as one new listing |
| `county_label`, `city_label`, `zip_code`, `property_subtype_label` | both | Filter fields. They have **the same name and the same values in both files**, so one filter can drive both sources. Blank values are `(missing)`. The originals are kept in `CountyOrParish`, `City`, `PostalCode` and `PropertySubType` |
| `zip_code` | both | 5-digit ZIP as **text**, from `PostalCode` (ZIP+4 trimmed). Blank where `PostalCode` isn't a ZIP; `zip_status` says why |
| `ClosePrice`, `DaysOnMarket`, `close_to_original_list_ratio` | sales | The metric inputs |
| `valid_sale_count`, `valid_price`, `valid_dom`, `valid_ratio` | sales | 0/1: does the row count in the **"Valid before IQR"** mode for that metric? |
| `iqr_sale_count`, `iqr_price`, `iqr_dom`, `iqr_ratio` | sales | 0/1: the same for the **"Week 7 IQR-filtered"** mode |
| `listing_agent_label`, `listing_office_label` | sales | Display names for rankings. The agent label is "Name · Office". `(unattributed)` means no usable name |
| `listing_agent_identified`, `listing_office_identified` | sales | 1 = a real competitor; 0 = missing or a placeholder like "Non-Member" |
| `zcta_latitude`, `zcta_longitude` | sales | Census point for the ZIP, used for the fallback map |

### Why two sales modes

| Mode | Population | Use it for |
|---|---|---|
| **Week 7 IQR-filtered** | The Week 7 filtered dataset: Closed, not a duplicate, and ClosePrice, LivingArea and DaysOnMarket all valid and within their IQR bounds (417,597 sales) | **Default for `market_analysis`**, continuing the Week 7 assignment |
| **Valid before IQR** | Every closed sale, with **metric-specific** validity: a sale counts in closed sales; volume and median price need a valid ClosePrice; average DOM needs a valid DaysOnMarket; the ratio needs a valid ratio (494,691 sales) | **Default for `competitive_analysis`**: the IQR filter removes every sale above about $2.39M, which would cut the high-end brokerages out of the rankings |

- In the valid mode, a missing LivingArea or DaysOnMarket never removes a sale
  from the counts or the volume.
- New listings never change with the mode, because the listings source doesn't
  use it.

---

## Part 1 – Connect the data (do this in both workbooks)

### 1.1 Connect the sales file

1. Open Tableau Desktop. On the start page, under **Connect › To a File**,
   click **Text file**.
2. Select `C:\Users\tung0\Downloads\DATA\output\weeks8_10\tableau_sales.csv`.
3. On the Data Source page, double-click the data source name at the top left
   and rename it **Sales**.
4. **Set the data types.** Click the small type icon above each column in the
   grid:

   | Set to | Columns |
   |---|---|
   | **String** (Abc) | `ListingKey`, `ListingId`, `zip_code`, `PostalCode`, `listing_agent_key`, `listing_office_key`, `sale_yrmo` |
   | **Date** | `CloseDate`, `sale_month` |
   | **Number (decimal)** | `ClosePrice`, `ListPrice`, `OriginalListPrice`, `LivingArea`, `DaysOnMarket`, `close_to_original_list_ratio`, `Latitude`, `Longitude`, `zcta_latitude`, `zcta_longitude` |
   | **Number (whole)** | `transaction_row`, `valid_sale_count`, `valid_price`, `valid_dom`, `valid_ratio`, `iqr_sale_count`, `iqr_price`, `iqr_dom`, `iqr_ratio`, `listing_agent_identified`, `listing_office_identified`, `zip_in_census_zcta`, `zip_in_california_range` |

   Tableau often guesses `zip_code` and `ListingKey` as numbers. Change them to
   String, or ZIP codes with leading zeros (e.g. `01234`) are corrupted.
5. At the top right, select **Extract** instead of Live. Extracts are faster,
   and MEDIAN is reliable on them. When you first open a sheet, Tableau asks
   where to save the extract: choose `output\weeks8_10\workbooks\`. Create the
   folder if needed.

### 1.2 Connect the listings file

1. **Data › New Data Source › Text file**, and select
   `output\weeks8_10\tableau_listings.csv`.
2. Rename it **Listings**.
3. **Set the data types:**
   - String: `ListingKey`, `ListingId`, `zip_code`, `PostalCode`,
     `listing_yrmo`, `MlsStatus`;
   - Date: `ListingContractDate`, `listing_month`;
   - Number (whole): `transaction_row`, `new_listing_event`,
     `zip_in_census_zcta`, `zip_in_california_range`;
   - Number (decimal): `ListPrice`, `OriginalListPrice`.
4. Select **Extract**.

(`competitive_analysis` uses only the Sales source, so you can skip 1.2 there.)

### 1.3 Geographic roles (Data pane, in each source)

Right-click the field, then **Geographic Role**:

| Field | Role |
|---|---|
| `zip_code` | **ZIP Code/Postcode** |
| `county_label` | **County** |
| `city_label` | **City** |
| `state_label` | **State/Province** |
| `zcta_latitude` / `zcta_longitude` (Sales) | **Latitude** / **Longitude** |

### 1.4 Check the row counts

On a new sheet, from the Sales source, drag `transaction_row` to the Text mark
and set the aggregation to **Sum**: it should read **494,691** (counted sales).
**Count** of the source shows **495,022** rows. From Listings, **SUM** of
`new_listing_event` = **665,376**.

### 1.5 Let one filter drive both sources (market_analysis only)

1. **Data › Edit Blend Relationships…**
2. Primary data source: **Sales**. Select **Listings** on the right and choose
   **Custom**.
3. Remove every automatic link. **In particular, don't link `ListingKey` or
   `ListingId`**: that would restrict listings to homes that sold.
4. Click **Add…** four times and link:
   - `county_label` ↔ `county_label`
   - `city_label` ↔ `city_label`
   - `zip_code` ↔ `zip_code`
   - `property_subtype_label` ↔ `property_subtype_label`

The sales and listings data are never appended or joined; these links only let
filters pass from one source to the other.

---

## Part 2 – Parameter and calculated fields

### 2.1 Sales Mode parameter

In the Data pane, open the drop-down at the top (or right-click empty space) and
choose **Create Parameter…**:
- Name: `Sales Mode`
- Data type: **String**
- Allowable values: **List**, with two values typed exactly:
  - `Week 7 IQR-filtered`
  - `Valid before IQR`
- Current value: `Week 7 IQR-filtered` in **market_analysis**; `Valid before
  IQR` in **competitive_analysis**.

Then right-click the parameter and choose **Show Parameter**.

### 2.2 Sales calculated fields

Create each with **Analysis › Create Calculated Field…**, with the **Sales**
source selected. Copy the formulas exactly; field names in brackets must match.

**Sale Counted** (0 or 1 for each row)
```
IF [Sales Mode] = "Week 7 IQR-filtered" THEN [iqr_sale_count] ELSE [valid_sale_count] END
```

**Eligible Close Price**
```
IF [Sales Mode] = "Week 7 IQR-filtered" AND [iqr_price] = 1 THEN [ClosePrice]
ELSEIF [Sales Mode] = "Valid before IQR" AND [valid_price] = 1 THEN [ClosePrice]
END
```

**Eligible Days on Market**
```
IF [Sales Mode] = "Week 7 IQR-filtered" AND [iqr_dom] = 1 THEN [DaysOnMarket]
ELSEIF [Sales Mode] = "Valid before IQR" AND [valid_dom] = 1 THEN [DaysOnMarket]
END
```

**Eligible Close to Original List Ratio**
```
IF [Sales Mode] = "Week 7 IQR-filtered" AND [iqr_ratio] = 1 THEN [close_to_original_list_ratio]
ELSEIF [Sales Mode] = "Valid before IQR" AND [valid_ratio] = 1 THEN [close_to_original_list_ratio]
END
```

**Closed Sales**
```
SUM([Sale Counted])
```

**Sales Volume**
```
SUM([Eligible Close Price])
```

**Median Close Price**
```
MEDIAN([Eligible Close Price])
```

**Avg Days on Market** (0 days is a valid value and is included)
```
AVG([Eligible Days on Market])
```

**Avg Close to Original List Ratio** (the mean of the row-level ratios; required
by the handbook)
```
AVG([Eligible Close to Original List Ratio])
```

**Median Close to Original List Ratio** (companion; see the warning in 3.3)
```
MEDIAN([Eligible Close to Original List Ratio])
```

**Largest Sale** (for tooltips; shows when one sale drives a total)
```
MAX([Eligible Close Price])
```

Notes:
- Every eligibility column already includes `transaction_row`, so each sale
  counts once.
- **Don't** compute the ratio as `SUM([ClosePrice]) / SUM([OriginalListPrice])`,
  and don't use `close_to_current_list_ratio`. The required metric is the
  average of the row-level ratios.
- Tableau calculates medians from the rows under your filters. Never average
  monthly medians.

### 2.3 Listings calculated field

With the **Listings** source selected:

**New Listings**
```
SUM([new_listing_event])
```

It doesn't reference `Sales Mode`, so switching the mode can't change it.

### 2.4 Shared filters

In **market_analysis**, add these four filters from the **Sales** source, then
switch each one to apply across both sources:
1. Drag `county_label`, `city_label`, `zip_code` and `property_subtype_label`
   to the Filters shelf of any sales sheet. Choose **Use all**, then OK.
2. For each filter pill, open its drop-down: **Apply to Worksheets › All Using
   Related Data Sources**. It then also filters the Listings sheets, through the
   links from 1.5.
3. Right-click each pill and choose **Show Filter**. In the filter card's menu,
   choose **Multiple Values (dropdown)**, and for city and ZIP also **Only
   Relevant Values**, so a county selection narrows the city and ZIP lists.

Set the four filters up the same way in **competitive_analysis**. It only needs
the Sales source, so use **All Using This Data Source**.

---

## Part 3 – market_analysis.twbx

Use the default **Sales Mode = Week 7 IQR-filtered**. Every chart covers January
2024 to **September 2026**, the latest month in both sources.

### Date axis (same for every monthly chart)

- Drag `sale_month` (or `listing_month`) to **Columns**. Right-click the pill
  and choose the **second "Month"** (continuous, shown like "May 2015"). The
  pill turns green.
- Don't turn on "Show Missing Values". A month with no data must stay empty,
  not become zero.
- Both sources cover 2024-01 to 2026-09 (33 months).
- **Trend caveats:**
  - The most recent months may still change as late closings are reported.
  - Some months come from API downloads (listings: 2026-01 and 2026-05 to
    2026-09; sales: 2026-05 to 2026-09). The rest come from FileZilla exports,
    so trends can step at those boundaries for reasons unrelated to the market
    (see `month_coverage.csv`).

### 3.1 Sheet "Median Close Price" (Sales)

1. **Columns:** MONTH(`sale_month`), continuous.
2. **Rows:** `Median Close Price`.
3. **Marks:** Line.
4. **Tooltip:** drag in `Closed Sales` and `Median Close Price`; include the
   mode in the text (Tooltip › Insert › Parameters.Sales Mode).
5. **Format the axis:** right-click the Rows pill › Format › Numbers ›
   **Currency (Custom)**, 0 decimals.
6. **Title:** "Monthly median close price – <Parameters.Sales Mode>". Insert the
   parameter with Title › Insert.

### 3.2 Sheet "Average Days on Market" (Sales)

Build it like 3.1, with `Avg Days on Market` on Rows and the number format set
to **Number (Custom)**, 1 decimal.

### 3.3 Sheet "Close to Original List Ratio" (Sales)

1. **Rows:** `Avg Close to Original List Ratio`.
2. **Number format:** **Percentage**, 1 decimal (0.985 shows as 98.5%).
3. **Tooltip:** `Median Close to Original List Ratio`, `Closed Sales`, and
   `MAX([Eligible Close to Original List Ratio])`.
4. **Caption:** add one under the title, because the average is distorted (see
   the warning below).

> ⚠️ **Known data issue.** A few records have a tiny OriginalListPrice (e.g. $1),
> which gives ratios in the thousands or millions. One such record can lift a
> month's average to hundreds of percent, in both modes. In February 2025 the
> valid-mode average is 877 (87,700%) while the median is 1.00. No ratio cutoff
> is applied, because none is documented. Show the median next to the average,
> say so in the caption, and raise it with your supervisor.

### 3.4 Sheet "New Listings" (Listings)

1. Select the **Listings** source.
2. **Columns:** MONTH(`listing_month`), continuous.
3. **Rows:** `New Listings`.
4. **Marks:** Bar.
5. **Tooltip:** `New Listings`.
6. **Title:** "New listings (all statuses; not affected by Sales Mode)".

### 3.5 Sheet "Closed Sales" (Sales)

1. **Columns:** MONTH(`sale_month`), continuous.
2. **Rows:** `Closed Sales`.
3. **Marks:** Bar.
4. **Tooltip:** `Closed Sales`, `Sales Volume`.

### 3.6 The five required dashboards

For each sheet 3.1–3.5:
1. **Dashboard › New Dashboard.** Name it after the sheet.
2. **Size:** Fixed, 1200 × 800 (Automatic also works).
3. Drag the sheet into the canvas.
4. From the sheet's drop-down (top right of the sheet on the dashboard), use
   **Filters ›** to add the `county_label`, `city_label`, `zip_code` and
   `property_subtype_label` filter cards, and **Parameters › Sales Mode**. Put
   them in a column on the right.
5. Add a **Text** object at the bottom with a definition and the data notes.
   For example: "Median of eligible ClosePrice by CloseDate month. Mode shown in
   title. Recent months may be revised."

On the New Listings dashboard, add the text "Sales Mode does not change new
listings."

### 3.7 Additional dashboard: "Market Momentum"

**Goal:** show supply (new listings), completed demand (closed sales) and speed
(average days on market) on one timeline.

1. **Duplicate** the sheets "New Listings", "Closed Sales" and "Average Days on
   Market" (right-click the sheet tab › Duplicate).
2. Make the date axes match: on each sheet, right-click the date axis › Edit
   Axis › **Fixed**, start 2024-01-01, end 2026-09-01.
3. Create a new dashboard named "Market Momentum" and stack the three sheets
   vertically: new listings at the top, closed sales in the middle, days on
   market at the bottom.
4. Add the four filters and the Sales Mode parameter.
5. **Caption, mandatory:**

   > New listings are counted by the month a listing contract started; closed
   > sales by the month a sale closed. They are different groups of homes, so
   > their ratio is **not** a conversion rate or months of inventory. Sales Mode
   > affects the closed-sales and days-on-market charts only.

### 3.8 Save

**File › Save As…**, choose type **Tableau Packaged Workbook (*.twbx)**, and
save as `output\weeks8_10\workbooks\market_analysis.twbx`. A packaged workbook
contains the extract (MLS data): keep it local.

---

## Part 4 – competitive_analysis.twbx

Repeat **Part 1** (Sales only) and **Part 2** (parameter default **Valid before
IQR**) in a new workbook. Then add a month filter:
1. Drag `sale_month` to Filters and choose **Month / Year**.
2. Choose **Use all**, then **Show Filter**, and set the card to **Multiple
   Values (dropdown)**.

### How the Top 100 is calculated (read first)

- The rankings use the **RANK table calculation**, which runs **after** every
  ordinary filter. So the month, county, city, ZIP and subtype filters, and
  Sales Mode, all shape the population **before** the Top 100 is chosen.
- Filtering on the rank is a table-calculation filter, applied last, so it
  hides rows without changing anyone's totals.
- **If you use the built-in Top N filter instead**, add the other filters to
  context first (right-click each › **Add to Context**). Otherwise Tableau picks
  the Top 100 before those filters apply.
- **Ties:** `RANK` gives tied values the same rank (1, 2, 2, 4). If several
  competitors tie at 100th, all of them are shown, so a list can have more than
  100 rows. In the valid mode, the agent Top 100 by units has 101 rows. Sort tied
  rows by name.
- **Unattributed:** `(unattributed)` rows (missing names and placeholders such as
  "Non-Member") are not ranked. In agent rankings they are filtered out; in the
  market-share dashboard they stay in the total but get no rank.

Calculated fields (Sales source):

**Agent Volume (identified)**
```
IF [listing_agent_identified] = 1 THEN [Eligible Close Price] END
```
**Agent Units (identified)**
```
IF [listing_agent_identified] = 1 THEN [Sale Counted] END
```
**Office Volume (identified)**
```
IF [listing_office_identified] = 1 THEN [Eligible Close Price] END
```
**Office Units (identified)**
```
IF [listing_office_identified] = 1 THEN [Sale Counted] END
```
**Rank by Agent Volume**: `RANK(SUM([Agent Volume (identified)]), 'desc')`

**Rank by Agent Units**: `RANK(SUM([Agent Units (identified)]), 'desc')`

**Rank by Office Volume**: `RANK(SUM([Office Volume (identified)]), 'desc')`

**Rank by Office Units**: `RANK(SUM([Office Units (identified)]), 'desc')`

### 4.1 Sheet "Top 100 Agents – Volume"

1. **Rows:** `listing_agent_label`.
2. **Columns:** `Sales Volume`.
3. **Marks:** Bar.
4. **Filters:** `listing_agent_identified`, keeping only 1.
5. **Rank:**
   - Drag `Rank by Agent Volume` to Rows, to the left of the label.
   - Right-click it, choose **Discrete**, then **Edit Table Calculation**.
   - Set **Compute Using › Specific Dimensions** and tick only
     `listing_agent_label`.
6. **Rank filter:**
   - Ctrl-drag the `Rank by Agent Volume` pill to **Filters**.
   - Choose **At most** 100 (or Range 1 to 100) and leave null values excluded.
7. **Sort:** click the `listing_agent_label` pill › Sort › By Field ›
   `Sales Volume` › Descending.
8. **Tooltip:** `Closed Sales`, `Sales Volume`, `Largest Sale`.
9. **Number format:** Currency (Custom), 0 decimals, units in Millions (M).

> ⚠️ **Read the tooltips.** In the valid mode, a few volume leaders are driven by
> one implausible sale. Examples: an agent at #1 with $1.44B in 10 sales, $810M
> of it in one sale; agents at #4 and #5 whose volume is 98–99.9% one sale of
> $970M–$989.5M. No price cutoff is applied, because none is documented. The
> `Largest Sale` tooltip makes this visible. The units ranking and the IQR mode
> aren't affected by these sales. Raise this with your supervisor before
> presenting the volume ranking.

### 4.2 Sheet "Top 100 Agents – Units"

Duplicate 4.1. Replace `Sales Volume` with `Closed Sales` on Columns, and the
rank pill and rank filter with `Rank by Agent Units`. Sort by `Closed Sales`.

*Optional single sheet with a selector:*
1. Create a parameter **Rank By** (String; list `Sales volume`, `Units`).
2. Create **Ranking Value**:
   `IF [Rank By] = "Sales volume" THEN SUM([Agent Volume (identified)]) ELSE SUM([Agent Units (identified)]) END`
3. Create **Rank (selected)**: `RANK([Ranking Value], 'desc')`.
4. Use these in place of the separate fields, and show the parameter.

### 4.3 Sheets "Top 100 Offices – Volume" and "Top 100 Offices – Units"

Build them as 4.1 and 4.2, with `listing_office_label`,
`listing_office_identified` and the office rank fields. Show the `county_label`,
`city_label`, `zip_code`, `property_subtype_label` and `sale_month` filters
(required).

### 4.4 Sheet "ZIP Map – Median Close Price"

1. In the Data pane, double-click `zip_code`. It must have the ZIP Code/Postcode
   role. Tableau builds a map with generated Latitude/Longitude.
2. Change **Marks** to **Map** (filled).
3. **Color:** `Median Close Price`. Edit Colors: sequential, Stepped Color 7
   steps if you like. Format the legend as currency.
4. **Tooltip:** `zip_code`, `Median Close Price`, `Closed Sales`.
5. **Filters, all shown:** `sale_month` (Month / Year), `county_label`,
   `city_label`, `zip_code`, `property_subtype_label`, plus the Sales Mode
   parameter.
6. **Check for unknown locations:**
   - Look at the indicator at the bottom right of the map, e.g. "12 unknown",
     and click it › **Edit Locations…** to see which ZIP codes Tableau couldn't
     place.
   - Compare them with `zip_geography_check.csv`, which lists the ZIP codes not
     in the Census ZCTA list and those with no usable ZIP. For example, `92878`
     (243 listings) and `99999` are not ZCTAs. 434 counted sales and 716
     counted listings have such a ZIP; 6 sales have no usable ZIP.
   - **Don't** hide the indicator without recording the number. Put it in a
     caption: "N sales in ZIP codes Tableau could not map are not shown."
7. **Fallback, if filled ZIP shapes don't resolve:** some ZIP codes, such as PO
   box or new ZIP codes, have no area shape in Tableau.
   - Build a symbol map instead: **Columns** AVG(`zcta_longitude`), **Rows**
     AVG(`zcta_latitude`), **Detail** `zip_code`, **Marks** Circle,
     **Color/Size** `Median Close Price`.
   - The points are the Census internal points of each ZIP area.
   - ZIP codes not in the Census list have no point either; report their count
     the same way.

### 4.5 Sheet "ZIP Map – Homes Sold"

Duplicate 4.4 and put `Closed Sales` on Color instead.

### 4.6 Additional dashboard: "Office Market Share"

**Goal:** each office's share of sales volume and of units within the selected
market. The denominator is the **whole eligible market under your filters**,
including unattributed sales and offices outside the Top 100.

1. **Rows:** `listing_office_label`. **Don't** filter
   `listing_office_identified` here: unattributed sales must stay in the total.
2. **Columns:** `Sales Volume`.
3. Right-click it › **Quick Table Calculation › Percent of Total**. Then Edit
   Table Calculation › Compute Using › Specific Dimensions ›
   `listing_office_label`. This is SUM(volume) ÷ the total of all offices in the
   view.
4. Add `Rank by Office Volume` (Discrete, computed using `listing_office_label`)
   to Rows. Ctrl-drag it to Filters and choose **At most** 20 (or 100).
   - `(unattributed)` has no rank, so it disappears from the list, but it
     remains in the Percent of Total denominator.
   - Table-calculation filters are applied after the percentages are
     calculated.
5. Format the measure as **Percentage**, 1 decimal.
6. Duplicate the sheet for units: `Closed Sales` and `Rank by Office Units`.
7. **KPI sheet "Unattributed share":** create
   `SUM(IF [listing_office_identified] = 0 THEN [Eligible Close Price] END) / [Sales Volume]`.
   Show it as Text, formatted as a percentage. With all data in the valid mode
   it's about 0.002%: 9 sales, $10.7M.
8. Make a dashboard with the volume-share bars, the units-share bars and the
   KPI, plus the filters and the parameter.
9. **Caption:** "Share of sales volume / units of all eligible sales under the
   current filters. Listing office only; co-listing offices are not credited.
   Office names are grouped by spelling (case and spaces); branches of one
   brand share a name."

### 4.7 Required dashboards and save

1. Create one dashboard each for:
   - Top 100 Agents (put the volume and units sheets side by side, or use the
     selector);
   - Top 100 Offices (volume and units);
   - ZIP Map – Median Close Price;
   - ZIP Map – Homes Sold;
   - Office Market Share.
2. Add the filters and the Sales Mode parameter to each.
3. **File › Save As › Tableau Packaged Workbook** to
   `output\weeks8_10\workbooks\competitive_analysis.twbx`.

---

## Part 5 – How filters and the mode behave

| Control | Affects | Doesn't affect |
|---|---|---|
| `county_label`, `city_label`, `zip_code`, `property_subtype_label` (All Using Related Data Sources) | Every sheet in both sources | — |
| `sale_month` filter | Sales sheets | New listings (a different month field) |
| **Sales Mode** | Closed sales, volume, median price, average DOM, average ratio, rankings, maps | **New listings**: the listings source never references the parameter |
| Rank filters (≤ 100) | Which rows are shown | Totals, percentages and other competitors' ranks |

---

## Part 6 – Check your numbers

Compare each sheet with these values before you save. They come from
`reference_*.csv`, and an independent recomputation confirmed them.

| Selection | Check | Week 7 IQR-filtered | Valid before IQR |
|---|---|---:|---:|
| All data, all months | Closed sales | 417,597 | 494,691 |
| All data, all months | Median close price | $786,000 | $825,000 |
| All data, all months | New listings (any mode) | 665,376 | 665,376 |
| All data, 2026-09 | Closed sales / median price | 12,115 / $784,000 | 14,584 / $823,500 |
| All data, 2026-09 | New listings | 22,211 | 22,211 |
| All data, 2026-09 | Avg days on market | 29.98 | 42.00 |
| County = Los Angeles | Closed sales / median price | 102,789 / $860,000 | 122,925 / $905,000 |
| City = San Diego | Closed sales / median price | 20,392 / $895,000 | 22,454 / $928,000 |
| PropertySubType = Condominium | Closed sales / median price | 72,730 / $625,000 | 81,070 / $625,000 |
| Top office by volume, all data | | Compass, $33.23B, 28,034 units | Compass, $67.99B, 37,319 units |

- Per-month values are in `reference_monthly.csv` (columns `_iqr` and `_valid`).
- Rankings are in `reference_agents_top100.csv` and
  `reference_offices_top100.csv` (columns `mode`, `ranked_by`, `rank`, `label`,
  `units`, `volume`).
- Per-ZIP values are in `reference_zip.csv`.
- **If a number differs:**
  - check the data types (Part 1);
  - check that the filter is set to "All Using Related Data Sources";
  - check that the rank's Compute Using is the label field;
  - check that Show Missing Values is off.

---

## Part 7 – Troubleshooting

- **ZIP codes look like 92,101 or lose leading zeros:** `zip_code` is a number.
  Change it to String, then reassign the ZIP role.
- **MEDIAN is greyed out:** use the Extract connection (Part 1, step 5).
- **The new-listings sheet doesn't react to a filter:** check the blend links
  (1.5), and that the filter applies to "All Using Related Data Sources".
- **The Top 100 changes when you add a filter that should come first:** you're
  using a Top N dimension filter. Use the rank table calculation, or add the
  other filters to context.
- **A row shows "(unattributed)":** the name is missing or a placeholder; it is
  never ranked.
- **To refresh after rerunning the preparation script:** Data › (source) ›
  Extract › Refresh.
