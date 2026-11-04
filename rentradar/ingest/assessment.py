"""Boston Property Assessment (owner of record, owner-occupied flag, mailing address).

https://data.boston.gov/dataset/property-assessment
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from .. import address
from . import read_csv, resolve, to_int

ALIASES = {
    "pid": ["parcel_id", "parcel"],
    "st_num": ["street_number", "st_num1"],
    "st_num2": ["st_num_2"],
    "st_name": ["street_name", "st_name_full"],
    "st_name_suf": ["st_name_suffix", "suffix"],
    "unit_num": ["unit", "unit_number"],
    "zip_code": ["zipcode", "zip", "mail_zipcode_property"],
    "owner": ["owner_name", "owner1"],
    "own_occ": ["owner_occupied", "own_occupied"],
    "mail_city": ["mail_cs", "mailing_city"],
    "mail_state": ["mailing_state"],
    "lu_desc": ["lu", "land_use", "luc_desc"],
    "yr_built": ["year_built"],
    "res_units": ["units", "num_units", "living_units"],
}


def load(paths: Iterable[Path], zips: Optional[Set[str]] = None) -> List[Dict]:
    out: List[Dict] = []
    for p in paths:
        rows = read_csv(p)
        first = next(rows, None)
        if first is None:
            continue
        cols = resolve(list(first.keys()), ALIASES, ["st_num", "st_name", "zip_code", "owner"], f"Assessment {Path(p).name}")

        def handle(r):
            g = lambda k: (r.get(cols[k]) if cols.get(k) else None)  # noqa: E731
            name = (g("st_name") or "").strip()
            suf = (g("st_name_suf") or "").strip()
            if suf and not name.upper().endswith(" " + suf.upper()):
                name = f"{name} {suf}"
            key = address.from_parts(g("st_num"), name, g("zip_code"), g("st_num2"))
            if key is None or (zips and key.zip not in zips):
                return
            mail_city = (g("mail_city") or "").strip().upper()
            mail_state = (g("mail_state") or "").strip().upper()
            if not mail_state and "," in mail_city:  # "BOSTON, MA" style
                mail_city, mail_state = [s.strip() for s in mail_city.rsplit(",", 1)]
            out.append({
                "pid": (g("pid") or "").strip(),
                "street_key": key.street_zip, "num_lo": key.lo, "num_hi": key.hi,
                "unit": (g("unit_num") or "").strip() or None,
                "zip": key.zip,
                "owner": (g("owner") or "").strip().upper() or None,
                "owner_occupied": 1 if (g("own_occ") or "").strip().upper() in ("Y", "YES", "1", "TRUE") else 0,
                "mail_city": mail_city or None,
                "mail_state": mail_state or None,
                "land_use": (g("lu_desc") or "").strip() or None,
                "year_built": to_int(g("yr_built")),
                "units": to_int(g("res_units")),
            })

        handle(first)
        for r in rows:
            handle(r)
    return out
