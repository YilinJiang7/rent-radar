"""Read-side data access: loads listings + precomputed evidence into memory.

The dataset is small (hundreds of listings), so the API and agent work on
in-memory dicts and only hit SQLite for record details.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional

from . import config, db
from .scoring import Scorer


class Store:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or config.DB_PATH)
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.path} not found. Run `python -m rentradar.build` (or `--fixtures`) first."
            )
        self.conn: sqlite3.Connection = db.connect(self.path)
        self.listings: Dict[str, dict] = {r["id"]: dict(r) for r in self.conn.execute("SELECT * FROM listings")}
        self.features: Dict[str, dict] = {
            r["listing_id"]: json.loads(r["json"]) for r in self.conn.execute("SELECT * FROM features")
        }
        self.meta = db.get_meta(self.conn, "build", {})
        self.scorer = Scorer(list(self.listings.values()), self.features)

    def close(self) -> None:
        self.conn.close()

    # -- queries -------------------------------------------------------------
    def filter(self, max_price=None, min_price=None, min_beds=None, max_beds=None, areas=None,
               cities=None, campus=None, max_bike_min=None, include_stale=True, property_types=None) -> List[dict]:
        out = []
        areas_l = {a.lower() for a in areas} if areas else None
        for l in self.listings.values():
            if max_price is not None and l["price"] > max_price:
                continue
            if min_price is not None and l["price"] < min_price:
                continue
            beds = l.get("bedrooms") or 0
            if min_beds is not None and beds < min_beds:
                continue
            if max_beds is not None and beds > max_beds:
                continue
            if areas_l and not ({l["area"].lower(), l["area_zip"]} & areas_l):
                continue
            if cities and (l.get("city") or "").lower() not in {c.lower() for c in cities}:
                continue
            if not include_stale and l["stale"]:
                continue
            if property_types and l.get("property_type") not in property_types:
                continue
            if max_bike_min is not None:
                c = self.features[l["id"]]["commute"].get(campus or config.DEFAULT_CAMPUS)
                if c and c["bike_min"] > max_bike_min:
                    continue
            out.append(l)
        return out

    def scored(self, rows: List[dict], campus: str, weights=None, budget=None, owner_occ_pref: str = "plus") -> List[dict]:
        res = []
        for l in rows:
            s = self.scorer.score(l, self.features[l["id"]], campus, weights, budget, owner_occ_pref)
            res.append({"listing": l, "score": s})
        res.sort(key=lambda x: (x["score"]["total"] is None, -(x["score"]["total"] or 0), x["listing"]["price"]))
        return res

    def records_for(self, listing_id: str, limit: int = 50) -> List[dict]:
        q = """SELECT c.*, lr.match_type FROM listing_records lr JOIN city_records c USING(record_id)
               WHERE lr.listing_id = ? ORDER BY c.date DESC LIMIT ?"""
        return [dict(r) for r in self.conn.execute(q, (listing_id, limit))]

    def record(self, record_id: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM city_records WHERE record_id = ?", (record_id,)).fetchone()
        return dict(r) if r else None

    def area_stats(self) -> List[dict]:
        by: Dict[str, List[dict]] = {}
        for l in self.listings.values():
            by.setdefault(l["area_zip"], []).append(l)
        out = []
        for z, rows in sorted(by.items()):
            prices = [r["price"] for r in rows]
            out.append({
                "zip": z, "area": config.AREAS[z][0], "city": config.AREAS[z][1],
                "listings": len(rows), "median_price": int(median(prices)),
                "stale_listings": sum(r["stale"] for r in rows),
            })
        return out
