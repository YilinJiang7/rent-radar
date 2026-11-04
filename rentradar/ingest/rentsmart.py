"""RentSmart Boston (Analyze Boston): 311 + Inspectional Services records per property.

https://data.boston.gov/dataset/rentsmart
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from .. import address, signals
from . import read_csv, resolve, to_float

ALIASES = {
    "date": ["open_dt", "status_date", "violation_date", "dt"],
    "violation_type": ["type", "record_type", "violation_category"],
    "description": ["descript", "violation_description", "case_title", "description_"],
    "address": ["full_address", "location", "property_address", "addr"],
    "zip_code": ["zip", "zipcode", "location_zipcode", "postal_code"],
    "parcel": ["parcel_id", "pid", "sam_id"],
    "owner": ["owner_name", "property_owner"],
    "latitude": ["lat", "y"],
    "longitude": ["long", "lon", "lng", "x"],
    "id": ["case_enquiry_id", "record_id", "case_id", "_id"],
}


def load(paths: Iterable[Path], zips: Optional[Set[str]] = None) -> List[Dict]:
    out: Dict[str, Dict] = {}
    for p in paths:
        rows = read_csv(p)
        first = next(rows, None)
        if first is None:
            continue
        cols = resolve(list(first.keys()), ALIASES, ["date", "violation_type", "description", "address"], f"RentSmart {Path(p).name}")

        def handle(r):
            g = lambda k: (r.get(cols[k]) if cols.get(k) else None)  # noqa: E731
            addr = (g("address") or "").strip()
            key = address.parse(addr, g("zip_code"))
            z = key.zip if key else address.norm_zip(g("zip_code"))
            if zips and z not in zips:
                return
            desc = (g("description") or "").strip()
            vt = (g("violation_type") or "").strip()
            date = (g("date") or "").strip()[:10]
            rid = g("id")
            if not rid:
                rid = "rs_" + hashlib.sha1(f"{date}|{vt}|{desc}|{addr}".encode()).hexdigest()[:12]
            sig = signals.classify_rule(desc, vt)
            out[str(rid)] = {
                "record_id": str(rid),
                "date": date,
                "year": int(date[:4]) if date[:4].isdigit() else None,
                "violation_type": vt,
                "description": desc,
                "signal": sig,
                "signal_source": "rule",
                "building_level": int(signals.building_level(vt, sig)),
                "address": addr,
                "street_key": key.street_zip if key else None,
                "num_lo": key.lo if key else None,
                "num_hi": key.hi if key else None,
                "zip": z,
                "parcel": address.norm_pid(g("parcel")) or None,
                "owner": (g("owner") or "").strip().upper() or None,
                "lat": to_float(g("latitude")),
                "lon": to_float(g("longitude")),
            }

        handle(first)
        for r in rows:
            handle(r)
    return list(out.values())
