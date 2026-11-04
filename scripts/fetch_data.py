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
    return meta["result"]["resources"]


def fetch_rentsmart() -> None:
    dest = RAW / "rentsmart" / "rentsmart.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print("RentSmart ->", dest)
    try:
        res = [r for r in ckan_resources("rentsmart") if (r.get("format") or "").upper() == "CSV"]
        if not res:
            raise RuntimeError("no CSV resource listed")
        r = max(res, key=lambda r: r.get("size") or 0)
        print("  resource:", r.get("name"), r["url"])
        curl(r["url"], dest)
        print("  saved", dest.stat().st_size // 1_000_000, "MB")
    except Exception as e:  # noqa: BLE001
        print("  error:", e)
        try:  # CKAN datastore dump of the known RentSmart resource (2016-present)
            print("  trying datastore dump", RENTSMART_DUMP)
            curl(RENTSMART_DUMP, dest)
            print("  saved", dest.stat().st_size // 1_000_000, "MB")
        except Exception as e2:  # noqa: BLE001
            print("  error:", e2)
            manual("rentsmart", dest, "the RentSmart CSV")


def fetch_assessment() -> None:
    dest = RAW / "assessment" / "assessment.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print("Property Assessment ->", dest)
    try:
        res = [r for r in ckan_resources("property-assessment") if (r.get("format") or "").upper() == "CSV"]

        def fy(r):
            m = re.search(r"(?:FY|20)(\d{2,4})", (r.get("name") or "") + " " + r.get("url", ""))
            return int(m.group(1)[-2:]) if m else 0
        r = max(res, key=fy)
        print("  resource:", r.get("name"), r["url"])
        curl(r["url"], dest)
        print("  saved", dest.stat().st_size // 1_000_000, "MB")
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
