"""MBTA GTFS stops.txt -> rapid-transit stations and bus stops.

https://cdn.mbta.com/MBTA_GTFS.zip (only stops.txt is kept by fetch_data.py).
MBTA's GTFS adds a `vehicle_type` column on platforms: 0 light rail (Green
Line, Mattapan), 1 subway (Red/Orange/Blue), 2 commuter rail, 3 bus.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from . import read_csv, resolve, to_float

ALIASES = {
    "stop_id": [], "stop_name": [], "stop_desc": [], "stop_lat": [], "stop_lon": [],
    "location_type": [], "parent_station": [], "vehicle_type": [],
}
# e.g. "Harvard - Red Line - Alewife", "Harvard Avenue - Green Line - (B) Boston College"
LINE_RE = re.compile(r"(Red|Orange|Blue|Green|Mattapan)\s+Line(?:\s*-\s*\(?([BCDE])\)?(?=[\s)]|$))?|\b(Green Line [BCDE])\b", re.I)


def _lines(desc: str) -> List[str]:
    found = []
    for m in LINE_RE.finditer(desc or ""):
        if m.group(3):
            found.append(m.group(3).title().replace("Line", "Line"))
        else:
            name = m.group(1).title() + " Line"
            if m.group(2) and name.startswith("Green"):
                name += " " + m.group(2).upper()
            found.append(name)
    return found


def load(path: Path) -> List[Dict]:
    rows = list(read_csv(path))
    if not rows:
        return []
    cols = resolve(list(rows[0].keys()), ALIASES, ["stop_id", "stop_name", "stop_lat", "stop_lon"], "MBTA stops.txt")
    g = lambda r, k: (r.get(cols[k]) if cols.get(k) else None)  # noqa: E731
    by_id = {g(r, "stop_id"): r for r in rows}

    stations: Dict[str, Dict] = {}
    lines = defaultdict(set)
    out: List[Dict] = []
    for r in rows:
        vt = (g(r, "vehicle_type") or "").strip()
        lat, lon = to_float(g(r, "stop_lat")), to_float(g(r, "stop_lon"))
        if lat is None:
            continue
        if vt in ("0", "1"):
            parent_id = g(r, "parent_station") or g(r, "stop_id")
            parent = by_id.get(parent_id, r)
            stations.setdefault(parent_id, {
                "stop_id": parent_id,
                "name": g(parent, "stop_name"),
                "lat": to_float(g(parent, "stop_lat")) or lat,
                "lon": to_float(g(parent, "stop_lon")) or lon,
                "kind": "rapid_transit",
            })
            for ln in _lines(g(r, "stop_desc") or ""):
                lines[parent_id].add(ln)
        elif vt == "3" and (g(r, "location_type") or "0") in ("0", ""):
            out.append({"stop_id": g(r, "stop_id"), "name": g(r, "stop_name"), "lat": lat, "lon": lon, "kind": "bus", "lines": ""})
    for sid, s in stations.items():
        ls = lines[sid]
        if any(l.startswith("Green Line ") for l in ls):
            ls.discard("Green Line")  # keep the branch names only
        s["lines"] = ", ".join(sorted(ls))
        out.append(s)
    return out
