"""MassDOT crash records 2021-2025 (re-used from PSet1, `data/vendor/crashes/`)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

from . import read_csv, resolve, to_float, to_int

ALIASES = {
    "crash_numb": ["crash_number", "id"],
    "crash_datetime_iso": ["crash_date", "date"],
    "year": [],
    "lat": ["latitude"],
    "lon": ["longitude"],
    "crash_severity_descr": ["severity"],
    "numb_fatal_injr": ["fatal"],
    "numb_nonfatal_injr": ["injuries"],
    "non_mtrst_type_cl": ["non_motorist_type"],
    "ambnt_light_descr": ["light"],
    "aadt": [],
    "streetname": ["rdwy", "street"],
}


def load(paths: Iterable[Path]) -> List[Dict]:
    out: Dict[str, Dict] = {}
    for p in paths:
        rows = read_csv(p)
        first = next(rows, None)
        if first is None:
            continue
        cols = resolve(list(first.keys()), ALIASES, ["crash_numb", "lat", "lon"], f"Crashes {Path(p).name}")

        def handle(r):
            g = lambda k: (r.get(cols[k]) if cols.get(k) else None)  # noqa: E731
            lat, lon = to_float(g("lat")), to_float(g("lon"))
            if lat is None or lon is None:
                return
            non_m = (g("non_mtrst_type_cl") or "").lower()
            sev = g("crash_severity_descr") or ""
            fatal = to_int(g("numb_fatal_injr")) or 0
            inj = to_int(g("numb_nonfatal_injr")) or 0
            out[str(g("crash_numb"))] = {
                "crash_id": str(g("crash_numb")),
                "date": (g("crash_datetime_iso") or "")[:10],
                "year": to_int(g("year")),
                "lat": lat, "lon": lon,
                "severity": sev,
                "fatal": fatal,
                "injuries": inj,
                # "Non-fatal injury" / "Fatal injury" (vs "Property damage only")
                "injury": int(fatal > 0 or inj > 0 or sev.lower().endswith("injury")),
                "ped": int("pedestrian" in non_m),
                "bike": int("cycl" in non_m or "bicycl" in non_m),
                "dark": int((g("ambnt_light_descr") or "").lower().startswith("dark")),
                "aadt": to_int(g("aadt")),
                "street": g("streetname"),
            }

        handle(first)
        for r in rows:
            handle(r)
    return list(out.values())
