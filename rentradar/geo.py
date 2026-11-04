"""Small geometry helpers and a grid spatial index (no external GIS deps)."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple, TypeVar

EARTH_R = 6_371_000.0
T = TypeVar("T")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def _to_xy(lat: float, lon: float, lat0: float) -> Tuple[float, float]:
    """Equirectangular projection in metres; accurate enough at city scale."""
    x = math.radians(lon) * EARTH_R * math.cos(math.radians(lat0))
    y = math.radians(lat) * EARTH_R
    return x, y


def point_segment_distance_m(plat, plon, alat, alon, blat, blon) -> float:
    lat0 = (alat + blat) / 2
    px, py = _to_xy(plat, plon, lat0)
    ax, ay = _to_xy(alat, alon, lat0)
    bx, by = _to_xy(blat, blon, lat0)
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class GridIndex:
    """Bucket points into ~cell_m squares so radius queries stay fast."""

    def __init__(self, items: Iterable[Tuple[float, float, T]], cell_m: float = 200.0):
        self.cell_deg = cell_m / 111_000.0
        self.cells: Dict[Tuple[int, int], List[Tuple[float, float, T]]] = defaultdict(list)
        self.n = 0
        for lat, lon, obj in items:
            if lat is None or lon is None:
                continue
            self.cells[self._key(lat, lon)].append((lat, lon, obj))
            self.n += 1

    def _key(self, lat: float, lon: float) -> Tuple[int, int]:
        return int(math.floor(lat / self.cell_deg)), int(math.floor(lon / self.cell_deg))

    def _candidates(self, lat: float, lon: float, radius_m: float) -> Iterator[Tuple[float, float, T]]:
        r_lat = radius_m / 111_000.0
        r_lon = radius_m / (111_000.0 * max(0.1, math.cos(math.radians(lat))))
        i0, j0 = self._key(lat - r_lat, lon - r_lon)
        i1, j1 = self._key(lat + r_lat, lon + r_lon)
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                yield from self.cells.get((i, j), ())

    def within(self, lat: float, lon: float, radius_m: float) -> List[Tuple[float, T]]:
        out = []
        for plat, plon, obj in self._candidates(lat, lon, radius_m):
            d = haversine_m(lat, lon, plat, plon)
            if d <= radius_m:
                out.append((d, obj))
        out.sort(key=lambda t: t[0])
        return out

    def nearest(self, lat: float, lon: float, max_m: float):
        hits = self.within(lat, lon, max_m)
        return hits[0] if hits else None

    def along_segment(self, alat, alon, blat, blon, width_m: float) -> List[Tuple[float, T]]:
        """Points within width_m of the straight segment A->B."""
        length = haversine_m(alat, alon, blat, blon)
        steps = max(1, int(length // (width_m * 1.5)) + 1)
        seen = {}
        for k in range(steps + 1):
            t = k / steps
            lat = alat + (blat - alat) * t
            lon = alon + (blon - alon) * t
            for plat, plon, obj in self._candidates(lat, lon, width_m * 1.5):
                oid = id(obj)
                if oid in seen:
                    continue
                d = point_segment_distance_m(plat, plon, alat, alon, blat, blon)
                if d <= width_m:
                    seen[oid] = (d, obj)
        return sorted(seen.values(), key=lambda t: t[0])


def nearest_area(lat: float, lon: float, areas: Dict[str, Sequence]) -> str:
    best, best_d = None, float("inf")
    for z, (_label, _city, clat, clon) in areas.items():
        d = haversine_m(lat, lon, clat, clon)
        if d < best_d:
            best, best_d = z, d
    return best
