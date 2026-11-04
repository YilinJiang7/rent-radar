#!/usr/bin/env python3
"""Refresh active rental listings from RentCast, one request per zip page.

    python scripts/fetch_rentcast.py                 # all v1 zips (about 8-12 requests)
    python scripts/fetch_rentcast.py --zips 02134    # just one zip
    python scripts/fetch_rentcast.py --import-snapshot ~/path/to/_rentcast_test

The free Developer plan allows 50 requests/month, so the script counts
requests and stops at --max-requests (default 15). The API key is read from
RENTCAST_API_KEY in .env / the environment, or asked for (input hidden).
It is never written to disk by this script.

Endpoint: GET https://api.rentcast.io/v1/listings/rental/long-term
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "raw" / "rentcast"
URL = "https://api.rentcast.io/v1/listings/rental/long-term"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get(params: dict, key: str):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    with tempfile.TemporaryDirectory() as td:
        hdr = Path(td) / "h.txt"
        cfg = Path(td) / "c.txt"
        cfg.write_text(f'header = "X-Api-Key: {key}"\n')  # keeps the key out of `ps` output
        r = subprocess.run(["curl", "-sS", "-K", str(cfg), "-D", str(hdr), "-H", "Accept: application/json",
                            f"{URL}?{q}"], capture_output=True)
        headers = hdr.read_text() if hdr.exists() else ""
    status = headers.split("\n", 1)[0] if headers else "?"
    total = next((l.split(":", 1)[1].strip() for l in headers.splitlines() if l.lower().startswith("x-total-count")), None)
    if " 200" not in status:
        raise RuntimeError(f"{status.strip()} {r.stdout[:300].decode(errors='replace')}")
    return json.loads(r.stdout), total


def main():
    from rentradar import config
    ap = argparse.ArgumentParser()
    ap.add_argument("--zips", nargs="*", default=list(config.AREAS))
    ap.add_argument("--max-requests", type=int, default=15)
    ap.add_argument("--import-snapshot", type=Path, help="copy existing listings_*.json files instead of calling the API")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if a.import_snapshot:
        n = 0
        for p in sorted(Path(a.import_snapshot).expanduser().glob("listings_*.json")):
            shutil.copy(p, OUT / p.name)
            n += 1
        print(f"copied {n} snapshot file(s) into {OUT}")
        return

    load_env()
    key = os.getenv("RENTCAST_API_KEY") or getpass.getpass("RentCast API key (hidden): ").strip()
    used = 0
    today = date.today().isoformat()
    for z in a.zips:
        offset, rows = 0, []
        while True:
            if used >= a.max_requests:
                print(f"stopping: reached --max-requests {a.max_requests}")
                break
            data, total = get({"zipCode": z, "state": "MA", "status": "Active", "limit": 500,
                               "offset": offset, "includeTotalCount": "true"}, key)
            used += 1
            rows.extend(data)
            print(f"  {z}: got {len(data)} (offset {offset}, total {total}) - requests used {used}")
            if len(data) < 500:
                break
            offset += 500
        (OUT / f"{today}_{z}.json").write_text(json.dumps(rows))
        if used >= a.max_requests:
            break
    print(f"done: {used} request(s) used this run; files in {OUT}")
    print("Tip: remove older snapshot files from data/raw/rentcast/ if you only want the newest listings.")


if __name__ == "__main__":
    main()
