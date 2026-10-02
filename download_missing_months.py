"""
Week 1 - Batch downloader for missing CRMLS monthly files.

Finds every month from January 2024 through the most recently completed
calendar month that has no valid file in csv/, downloads it from the Trestle
API, and saves it as csv/CRMLSListing{YYYYMM}.csv or csv/CRMLSSold{YYYYMM}.csv.

It uses the same fields ($select) and date filters as crmls_listed.py and
crmls_sold.py. Each month is:
  1. downloaded page by page into downloads_tmp/ as UTF-8,
  2. checked: every page fetched, row count == the API's own count, no duplicate
     ListingKeys, every row has all fields, every date falls inside the month,
  3. only then moved into csv/. A file being replaced is first copied to backup/.
A month that fails any check is never moved into csv/.

Usage:
    python download_missing_months.py                     # download what's missing
    python download_missing_months.py --plan              # list what's missing; no network
    python download_missing_months.py --compare-existing  # compare local row counts with the API

Credentials: IDX_TOKEN_KEY in .env (git-ignored) or an environment variable.
"""

import argparse
import csv
import filecmp
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from idx_auth import AuthError, get_token
from week1_aggregate import (BASE_DIR, DATA_DIR, END, START, check_file_structure,
                             find_monthly_file, months_in_range)

API_URL = "https://api-trestle.corelogic.com/trestle/odata/Property"
TMP_DIR = BASE_DIR / "downloads_tmp"
BACKUP_DIR = BASE_DIR / "backup"
MANIFEST = DATA_DIR / "download_manifest.csv"

PAGE_SIZE = 1000              # same $top as the fetch scripts
REQUEST_TIMEOUT = (15, 120)   # seconds to connect, seconds to wait for a page
MAX_REQUEST_ATTEMPTS = 5      # per page, for timeouts / rate limits / server errors
MAX_MONTH_ATTEMPTS = 2        # re-download a month whose result fails validation
MAX_WAIT = 120                # longest pause between attempts, in seconds

# Fields from the $select in crmls_listed.py and crmls_sold.py. crmls_listed.py
# lists some fields twice (that caused the 'Name.1' columns); duplicates removed here.
LISTING_FIELDS = [
    "OriginalListPrice", "ListingKey", "CloseDate", "ClosePrice", "ListAgentFirstName",
    "ListAgentLastName", "Latitude", "Longitude", "UnparsedAddress", "PropertyType",
    "LivingArea", "ListPrice", "DaysOnMarket", "ListOfficeName", "BuyerOfficeName",
    "CoListOfficeName", "ListAgentFullName", "CoListAgentFirstName",
    "CoListAgentLastName", "BuyerAgentMlsId", "BuyerAgentFirstName",
    "BuyerAgentLastName", "FireplacesTotal", "AssociationFeeFrequency",
    "AboveGradeFinishedArea", "ListingKeyNumeric", "MLSAreaMajor", "TaxAnnualAmount",
    "CountyOrParish", "MlsStatus", "ElementarySchool", "AttachedGarageYN",
    "ParkingTotal", "BuilderName", "PropertySubType", "LotSizeAcres", "SubdivisionName",
    "BuyerOfficeAOR", "YearBuilt", "StreetNumberNumeric", "ListingId",
    "BathroomsTotalInteger", "City", "TaxYear", "BuildingAreaTotal", "BedroomsTotal",
    "ContractStatusChangeDate", "ElementarySchoolDistrict", "CoBuyerAgentFirstName",
    "PurchaseContractDate", "ListingContractDate", "BelowGradeFinishedArea",
    "BusinessType", "StateOrProvince", "CoveredSpaces", "MiddleOrJuniorSchool",
    "FireplaceYN", "Stories", "HighSchool", "Levels", "LotSizeDimensions",
    "LotSizeArea", "MainLevelBedrooms", "NewConstructionYN", "GarageSpaces",
    "HighSchoolDistrict", "PostalCode", "AssociationFee", "LotSizeSquareFeet",
    "MiddleOrJuniorSchoolDistrict",
]
SOLD_FIELDS = [
    "BuyerAgentAOR", "ListAgentAOR", "Flooring", "ViewYN", "WaterfrontYN", "BasementYN",
    "PoolPrivateYN", "OriginalListPrice", "ListingKey", "ListAgentEmail", "CloseDate",
    "ClosePrice", "ListAgentFirstName", "ListAgentLastName", "Latitude", "Longitude",
    "UnparsedAddress", "PropertyType", "LivingArea", "ListPrice", "DaysOnMarket",
    "ListOfficeName", "BuyerOfficeName", "CoListOfficeName", "ListAgentFullName",
    "CoListAgentFirstName", "CoListAgentLastName", "BuyerAgentMlsId",
    "BuyerAgentFirstName", "BuyerAgentLastName", "FireplacesTotal",
    "AssociationFeeFrequency", "AboveGradeFinishedArea", "ListingKeyNumeric",
    "MLSAreaMajor", "TaxAnnualAmount", "CountyOrParish", "MlsStatus",
    "ElementarySchool", "AttachedGarageYN", "ParkingTotal", "BuilderName",
    "PropertySubType", "LotSizeAcres", "SubdivisionName", "BuyerOfficeAOR", "YearBuilt",
    "StreetNumberNumeric", "ListingId", "BathroomsTotalInteger", "City", "TaxYear",
    "BuildingAreaTotal", "BedroomsTotal", "ContractStatusChangeDate",
    "ElementarySchoolDistrict", "CoBuyerAgentFirstName", "PurchaseContractDate",
    "ListingContractDate", "BelowGradeFinishedArea", "BusinessType", "StateOrProvince",
    "CoveredSpaces", "MiddleOrJuniorSchool", "FireplaceYN", "Stories", "HighSchool",
    "Levels", "LotSizeDimensions", "LotSizeArea", "MainLevelBedrooms",
    "NewConstructionYN", "GarageSpaces", "HighSchoolDistrict", "PostalCode",
    "AssociationFee", "LotSizeSquareFeet", "MiddleOrJuniorSchoolDistrict",
    "OriginatingSystemName", "OriginatingSystemSubName",
]

DATASETS = {
    "listings": {
        "prefix": "CRMLSListing",
        "fields": LISTING_FIELDS,
        "date_field": "ListingContractDate",
        # Same filter as crmls_listed.py: listings by the date the listing contract started
        "filter": "ListingContractDate ge {start} and ListingContractDate lt {end}",
    },
    "sold": {
        "prefix": "CRMLSSold",
        "fields": SOLD_FIELDS,
        "date_field": "CloseDate",
        # Same filter as crmls_sold.py: closed sales by the date they closed
        "filter": "MlsStatus eq 'Closed' and CloseDate ge {start} and CloseDate lt {end}",
    },
}


class DownloadError(Exception):
    """A month couldn't be downloaded, or the download failed validation."""


def month_bounds(ym):
    """'202403' -> ('2024-03-01T00:00:00.000Z', '2024-04-01T00:00:00.000Z'), as in the fetch scripts."""
    year, month = int(ym[:4]), int(ym[4:])
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start.isoformat(timespec="milliseconds") + "Z", end.isoformat(timespec="milliseconds") + "Z"


def month_query(dataset, ym, fields, top):
    cfg = DATASETS[dataset]
    start, end = month_bounds(ym)
    return {
        "$select": ",".join(fields),
        "$filter": cfg["filter"].format(start=start, end=end),
        "$top": top,
        "$count": "true",  # ask the API how many records match, to prove nothing was missed
    }


class TrestleClient:
    """Sends API requests with an access token, retrying temporary failures a limited number of times."""

    def __init__(self):
        self.session = requests.Session()
        self.token = get_token()

    def get_json(self, url, params=None):
        token_refreshed = False
        problem = ""
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            wait = min(5 * 2 ** (attempt - 1), MAX_WAIT)  # 5, 10, 20, 40 seconds
            try:
                resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT,
                                        headers={"Authorization": f"Bearer {self.token}"})
            except requests.RequestException as err:
                problem = f"network problem ({type(err).__name__})"
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        problem = "page arrived incomplete (invalid JSON)"
                elif resp.status_code == 401 and not token_refreshed:
                    # Tokens expire; during a long run, get a fresh one once and retry right away
                    self.token = get_token()
                    token_refreshed = True
                    problem, wait = "access token expired, got a new one", 0
                elif resp.status_code in (401, 403):
                    raise AuthError(
                        f"The Trestle API refused access (HTTP {resp.status_code}) even with a fresh token. "
                        f"Your IDX Exchange access may not cover this data - ask your IDX Exchange contact."
                    )
                elif resp.status_code == 429 or resp.status_code >= 500:
                    problem = "rate limited (HTTP 429)" if resp.status_code == 429 else f"server error (HTTP {resp.status_code})"
                    retry_after = resp.headers.get("Retry-After", "")
                    if retry_after.isdigit():
                        wait = min(int(retry_after), MAX_WAIT)
                else:
                    # e.g. 400: the request itself is wrong, so retrying won't help
                    raise DownloadError(f"API answered HTTP {resp.status_code}: {resp.text[:300]}")
            if attempt < MAX_REQUEST_ATTEMPTS:
                print(f"      {problem}; retrying in {wait}s (retry {attempt} of {MAX_REQUEST_ATTEMPTS - 1})")
                time.sleep(wait)
        raise DownloadError(f"a page failed {MAX_REQUEST_ATTEMPTS} times ({problem})")


def download_month(client, dataset, ym, tmp_path):
    """Download every page for one month into tmp_path. Returns (rows_written, api_count)."""
    fields = DATASETS[dataset]["fields"]
    url, params = API_URL, month_query(dataset, ym, fields, PAGE_SIZE)
    rows, pages, api_count = 0, 0, None

    with open(tmp_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        while url:
            data = client.get_json(url, params)
            if pages == 0:
                api_count = data.get("@odata.count")
            for record in data.get("value", []):
                writer.writerow({field: record.get(field, "") for field in fields})
                rows += 1
            pages += 1
            if pages % 10 == 0:
                print(f"      {pages} pages, {rows:,} rows so far")
            # Keep going until the API stops sending a link to the next page
            url = data.get("@odata.nextLink")
            params = None  # the next link already contains the query
    return rows, api_count


def validate_month(path, dataset, ym, rows_written, api_count):
    """Return a list of reasons this download can't be trusted (empty list = valid)."""
    cfg = DATASETS[dataset]
    problems = []
    if api_count is None:
        problems.append("the API didn't report a total count, so completeness can't be proven")
    elif rows_written != api_count:
        problems.append(f"downloaded {rows_written:,} rows but the API reports {api_count:,}")
    if rows_written == 0:
        problems.append("no records came back for this month")

    try:
        structure_problems, _ = check_file_structure(path)
        problems += structure_problems
    except ValueError as err:
        problems.append(str(err))
        return problems

    # Re-read the file from disk and check its contents
    month_prefix = f"{ym[:4]}-{ym[4:]}"
    keys, rows_on_disk, outside_month, not_closed = set(), 0, 0, 0
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows_on_disk += 1
            keys.add(row.get("ListingKey"))
            if not (row.get(cfg["date_field"]) or "").startswith(month_prefix):
                outside_month += 1
            if dataset == "sold" and row.get("MlsStatus") != "Closed":
                not_closed += 1
    if rows_on_disk != rows_written:
        problems.append(f"file holds {rows_on_disk:,} rows but {rows_written:,} were written")
    if len(keys) != rows_on_disk:
        problems.append(f"{rows_on_disk - len(keys):,} duplicate ListingKeys (pages overlapped)")
    if outside_month:
        problems.append(f"{outside_month:,} rows have {cfg['date_field']} outside {month_prefix}")
    if not_closed:
        problems.append(f"{not_closed:,} rows don't have MlsStatus 'Closed'")
    return problems


def install(tmp_path, final_path):
    """Move a validated download into place, backing up any file it replaces."""
    if final_path.exists():
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = BACKUP_DIR / f"{final_path.stem}_replaced_{stamp}{final_path.suffix}"
        shutil.copy2(final_path, backup)
        if not filecmp.cmp(final_path, backup, shallow=False):
            raise DownloadError(f"backup of {final_path.name} doesn't match the original; not replacing it")
        print(f"    Backed up the old {final_path.name} to backup/{backup.name}")
    os.replace(tmp_path, final_path)


def record_in_manifest(dataset, ym, final_path, rows, api_count):
    """Log each verified download with the API's count at that moment."""
    new_file = not MANIFEST.exists()
    with open(MANIFEST, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["dataset", "month", "file", "rows", "api_count", "downloaded_at"])
        writer.writerow([dataset, ym, final_path.name, rows, api_count, datetime.now().isoformat(timespec="seconds")])


def find_work():
    """Return [(dataset, ym, reason)] for every month without a valid file."""
    todo = []
    for dataset, cfg in DATASETS.items():
        for ym in months_in_range(START, END):
            existing = find_monthly_file(cfg["prefix"], ym)
            if existing is None:
                todo.append((dataset, ym, "missing"))
                continue
            try:
                problems, _ = check_file_structure(existing)
            except ValueError as err:
                problems = [str(err)]
            if not problems:
                continue
            if existing.name != f"{cfg['prefix']}{ym}.csv":
                print(f"  {existing.name} looks damaged ({problems[0]}); review it by hand - not replaced automatically")
                continue
            todo.append((dataset, ym, f"replace damaged file ({problems[0]})"))
    return todo


def compare_existing(client):
    """For information: compare each local file's row count with what the API returns today."""
    print(f"\n{'file':32} {'local rows':>10} {'API today':>10} {'difference':>10}")
    for dataset, cfg in DATASETS.items():
        for ym in months_in_range(START, END):
            path = find_monthly_file(cfg["prefix"], ym)
            if path is None:
                continue
            with open(path, encoding="utf-8", newline="") as f:
                local = sum(1 for _ in csv.reader(f)) - 1
            data = client.get_json(API_URL, month_query(dataset, ym, ["ListingKey"], 1))
            api = data.get("@odata.count")
            api_text = "n/a" if api is None else f"{api:,}"
            diff = "" if api is None else f"{local - api:+,}"
            print(f"{path.name:32} {local:>10,} {api_text:>10} {diff:>10}")


def main():
    parser = argparse.ArgumentParser(description="Download missing CRMLS monthly files.")
    parser.add_argument("--plan", action="store_true", help="only list what would be downloaded (no network)")
    parser.add_argument("--compare-existing", action="store_true",
                        help="compare local row counts with the API's current counts (no downloads)")
    args = parser.parse_args()

    print(f"Required coverage: {START:%Y-%m} through {END:%Y-%m}")
    if args.compare_existing:
        compare_existing(TrestleClient())
        return 0

    todo = find_work()
    for dataset in DATASETS:
        months = [(ym, reason) for d, ym, reason in todo if d == dataset]
        print(f"\n{dataset}: {len(months)} month(s) to download")
        for ym, reason in months:
            print(f"  {ym}  {reason}")
    if args.plan or not todo:
        return 0

    TMP_DIR.mkdir(exist_ok=True)
    client = TrestleClient()
    print("\nAuthenticated with IDX Exchange.")

    succeeded, failed = [], []
    for i, (dataset, ym, _) in enumerate(todo, 1):
        final = DATA_DIR / f"{DATASETS[dataset]['prefix']}{ym}.csv"
        tmp = TMP_DIR / f"{final.name}.part"
        print(f"\n[{i}/{len(todo)}] {dataset} {ym}")
        started, last_error = time.time(), ""
        for attempt in range(1, MAX_MONTH_ATTEMPTS + 1):
            try:
                rows, api_count = download_month(client, dataset, ym, tmp)
                problems = validate_month(tmp, dataset, ym, rows, api_count)
                if problems:
                    raise DownloadError("; ".join(problems))
                install(tmp, final)
                record_in_manifest(dataset, ym, final, rows, api_count)
                print(f"    OK: {rows:,} rows, matches API count {api_count:,} -> csv/{final.name} "
                      f"({time.time() - started:.0f}s)")
                succeeded.append((dataset, ym))
                break
            except DownloadError as err:
                last_error = str(err)
                print(f"    Attempt {attempt} of {MAX_MONTH_ATTEMPTS} failed: {last_error}")
            finally:
                tmp.unlink(missing_ok=True)  # never leave a partial download behind
        else:
            failed.append((dataset, ym, last_error))

    print(f"\nDone: {len(succeeded)} downloaded, {len(failed)} failed.")
    for dataset, ym, error in failed:
        print(f"  FAILED {dataset} {ym}: {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AuthError as err:
        sys.exit(f"\nSTOPPED - authentication problem: {err}")
