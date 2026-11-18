#!/usr/bin/env python3
"""Download the public city datasets into data/raw/ (run on your own Mac).

    python scripts/fetch_data.py            # everything
    python scripts/fetch_data.py rentsmart  # one source: rentsmart | assessment | mbta

Sources (all public, no key needed):
  * RentSmart Boston            https://data.boston.gov/dataset/rentsmart
  * Property Assessment (latest) https://data.boston.gov/dataset/property-assessment
  * MBTA GTFS (stops.txt only)  https://cdn.mbta.com/MBTA_GTFS.zip

Uses `curl` (built into macOS) for the transfers, so Python SSL certificate
setup does not matter. If Analyze Boston answers 403 (bot protection), the
script prints the page to download from by hand and where to put the file.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CKAN = "https://data.boston.gov/api/3/action/package_show?id={slug}"
RENTSMART_DUMP = "https://data.boston.gov/datastore/dump/dc615ff7-2ff3-416a-922b-f0f334f085d0"
UA = "rent-radar/0.2 (MIT 1.125 student project)"


def curl(url: str, out: Path = None) -> bytes:
    cmd = ["curl", "-fsSL", "--retry", "3", "-A", UA, url]
    if out:
        cmd[1] = "-fL"  # show progress bar for big files
        cmd += ["-o", str(out)]
    r = subprocess.run(cmd, capture_output=out is None)
    if r.returncode != 0:
        raise RuntimeError(f"curl failed ({r.returncode}) for {url}")
    return r.stdout if out is None else b""


def manual(slug: str, dest: Path, hint: str) -> None:
    print(f"\n  Could not download automatically. Please open\n    https://data.boston.gov/dataset/{slug}\n"
          f"  download {hint} (CSV) and save it as\n    {dest}\n  then run `python -m rentradar.build` again.\n")


def ckan_resources(slug: str):
    meta = json.loads(curl(CKAN.format(slug=slug)))
    res = meta["result"]["resources"]
    # keep a copy so a wrong pick can be diagnosed without another request
    out = RAW / slug / "_resources.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([{k: r.get(k) for k in ("id", "name", "format", "url", "last_modified", "created", "size")}
                               for r in res], indent=1))
    return res


def header(path: Path) -> list:
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return [c.strip() for c in fh.readline().strip().split(",")]


def fetch_rentsmart() -> None:
    """Record-level RentSmart (one row per complaint/violation, 2016-present).

    The package also lists property-level files (rs_prop_* + JSON columns,
    split by year built, last updated ~2020); those are NOT what we want, so
    we download the record-level table by its resource id and check the header.
    """
    dest = RAW / "rentsmart" / "rentsmart.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print("RentSmart (record level) ->", dest)
    try:
        curl(RENTSMART_DUMP, dest)
        cols = [c.lower() for c in header(dest)]
        print("  saved", dest.stat().st_size // 1_000_000, "MB; columns:", cols)
        if "violation_type" not in cols and "description" not in cols:
            raise RuntimeError("downloaded file is not the record-level table")
    except Exception as e:  # noqa: BLE001
        print("  error:", e)
        try:
            ckan_resources("rentsmart")
            print("  resource list saved to data/raw/rentsmart/_resources.json -- pick the record-level CSV from it and download it by hand")
        except Exception:  # noqa: BLE001
            pass
        manual("rentsmart", dest, "the record-level 'RENTSMART 2016 - PRESENT' CSV")


def _fy(r) -> int:
    # only the file name: resource ids are hex and can contain "20xx" (b3862082 -> "2082")
    text = f"{r.get('name') or ''} {(r.get('url') or '').rsplit('/', 1)[-1]}".lower()
    years = [int(y) for y in re.findall(r"20(\d{2})(?!\d)", text)] + [int(y) for y in re.findall(r"fy(\d{2})(?!\d)", text)]
    return max(years) if years else 0


def fetch_assessment() -> None:
    dest = RAW / "assessment" / "assessment.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print("Property Assessment (newest fiscal year) ->", dest)
    try:
        res = [r for r in ckan_resources("property-assessment")
               if (r.get("format") or "").upper() == "CSV" and r.get("url")]
        res.sort(key=lambda r: (_fy(r), r.get("last_modified") or r.get("created") or ""), reverse=True)
        print("  candidates (newest first):")
        for r in res[:5]:
            print(f"    FY{_fy(r):02d}  {r.get('name')}  {r['url']}")
        r = res[0]
        curl(r["url"], dest)
        cols = header(dest)
        print("  saved", dest.stat().st_size // 1_000_000, "MB; columns:", cols[:25], "...")
        if _fy(r) < 24:
            print("  WARNING: newest file found is FY", _fy(r), "-- check data/raw/property-assessment/_resources.json")
    except Exception as e:  # noqa: BLE001
        print("  error:", e)
        manual("property-assessment", dest, "the newest 'FY20xx Property Assessment Data' file")


def fetch_mbta() -> None:
    dest = RAW / "mbta" / "stops.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print("MBTA GTFS stops ->", dest)
    with tempfile.TemporaryDirectory() as td:
        z = Path(td) / "gtfs.zip"
        curl("https://cdn.mbta.com/MBTA_GTFS.zip", z)
        with zipfile.ZipFile(z) as zf, zf.open("stops.txt") as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
    print("  saved", dest.stat().st_size // 1000, "KB")


STEPS = {"rentsmart": fetch_rentsmart, "assessment": fetch_assessment, "mbta": fetch_mbta}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(STEPS)
    for w in wanted:
        if w not in STEPS:
            sys.exit(f"unknown source {w}; choose from {list(STEPS)}")
        STEPS[w]()
    print("\nDone. Next: python -m rentradar.build")
